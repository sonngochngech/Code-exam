"""Điểm khởi động của cả hai hệ thống.

Chạy:  python -m uvicorn app.main:app --reload
Mở:    http://127.0.0.1:8000
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, llm
from .routers import admin, attempt_control, audit, cases, exam, proctor, readiness, stats, tutor, tuong_tac
from .services import audit as audit_service, exam_access_codes

app = FastAPI(
    title="Hệ thống AI trợ giảng và giám sát kỳ thi",
    description="Hai hệ thống dùng chung một nền tảng, phục vụ hai đề tài dự thi.",
    version="1.0",
)


@app.middleware("http")
async def bao_ve_duong_truyen(request: Request, call_next):
    """BL-19: reject clear-text non-local deployment traffic when enabled."""
    local_hosts = {"127.0.0.1", "localhost", "testserver"}
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    secure = request.url.scheme == "https" or forwarded == "https"
    if config.BAT_BUOC_HTTPS and request.url.hostname not in local_hosts and not secure:
        return JSONResponse(status_code=400, content={"detail": "Triển khai yêu cầu HTTPS"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self)"
    if secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.on_event("startup")
def khoi_dong():
    db.khoi_tao()


# ---------------------------------------------------------------------------
# Đăng nhập
# ---------------------------------------------------------------------------
class YeuCauDangNhap(BaseModel):
    ma: str


@app.post("/api/dang-nhap", tags=["chung"])
def dang_nhap(yc: YeuCauDangNhap):
    """Giáo viên dùng mã mẫu; học sinh dùng mã dự thi theo ca.

    Lưu ý khi triển khai thật: giáo viên chưa có mật khẩu, phù hợp cho phạm vi
    thử nghiệm trong lớp có giám sát. Nếu mở rộng ra toàn trường thì phải bổ
    sung cơ chế xác thực giáo viên phù hợp.
    """
    entered = yc.ma.strip()
    exam_login = exam_access_codes.resolve(entered)
    nd = db.lay_nguoi_dung(exam_login["hoc_sinh"]) if exam_login else db.lay_nguoi_dung(entered)
    if not nd:
        raise HTTPException(404, "Không tìm thấy mã này. Em kiểm tra lại nhé.")
    if nd["vai_tro"] == "hoc_sinh" and not exam_login \
            and exam_access_codes.student_has_active_open_code(nd["ma"]):
        raise HTTPException(401, "Em hãy dùng mã dự thi riêng do giáo viên cấp.")
    # Cấp token phiên. Trình duyệt gửi kèm token này ở mọi lời gọi API sau đó.
    session_id = exam_login["ca_thi"] if exam_login else None
    token = auth.tao_phien(nd, session_id)
    with db.ket_noi() as conn:
        audit_service.log(conn, nd["ma"], "dang_nhap", "nguoi_dung", nd["ma"])
    return {"ma": nd["ma"], "ho_ten": nd["ho_ten"],
            "vai_tro": nd["vai_tro"], "lop": nd["lop"], "token": token,
            "ca_thi": session_id}


@app.get("/api/trang-thai", tags=["chung"])
def trang_thai():
    """Trang kiểm tra nhanh, cũng dùng khi trình bày để chứng minh hệ thống sống."""
    with db.ket_noi() as conn:
        dem = {
            b: conn.execute(f"SELECT COUNT(*) c FROM {b}").fetchone()["c"]
            for b in ("nguoi_dung", "hoc_lieu", "cau_hoi",
                      "de_thi", "ca_thi", "bai_lam", "moc_bat_thuong", "phan_doan")
        }
    return {"che_do_ai": llm.mo_ta_che_do(), "so_ban_ghi": dem}


# ---------------------------------------------------------------------------
# Gắn các nhóm đường dẫn
# ---------------------------------------------------------------------------
app.include_router(tutor.router)
app.include_router(admin.router)
app.include_router(exam.router)
app.include_router(proctor.router)
app.include_router(readiness.router)
app.include_router(attempt_control.router)
app.include_router(cases.router)
app.include_router(audit.router)
app.include_router(stats.router)
app.include_router(tuong_tac.router)


# ---------------------------------------------------------------------------
# Giao diện web
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=config.THU_MUC_WEB / "static"), name="static")


def _trang(ten: str):
    duong_dan = config.THU_MUC_WEB / ten
    if not duong_dan.exists():
        raise HTTPException(404, f"Chưa có trang {ten}")
    return FileResponse(duong_dan)


@app.get("/", include_in_schema=False)
def trang_chu(request: Request, da: str | None = None):
    """Trang giới thiệu, chọn theo tên miền. coithi.cloud ra Dự án 2, còn lại
    ra Dự án 1. Tham số ?da=1|2 dùng để xem thử trên máy."""
    host = (request.headers.get("host") or "").lower()
    la_da2 = da == "2" or (da != "1" and "coithi" in host)
    return _trang("landing-da2.html" if la_da2 else "landing-da1.html")


@app.get("/vao", include_in_schema=False)
def trang_vao():
    """Trang đăng nhập và chọn phần (ứng dụng chính)."""
    return _trang("index.html")


@app.get("/tro-giang", include_in_schema=False)
def trang_tro_giang():
    return _trang("tutor.html")


@app.get("/bang-dieu-khien", include_in_schema=False)
def trang_bang_dieu_khien():
    return _trang("teacher.html")


@app.get("/thong-tin", include_in_schema=False)
def trang_thong_tin():
    return _trang("info.html")


@app.get("/lam-bai", include_in_schema=False)
def trang_lam_bai():
    return _trang("exam.html")


@app.get("/coi-thi", include_in_schema=False)
def trang_coi_thi():
    return _trang("proctor.html")


@app.get("/quan-tri", include_in_schema=False)
def trang_quan_tri():
    return _trang("admin.html")
