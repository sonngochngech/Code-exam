"""Điểm khởi động của cả hai hệ thống.

Chạy:  python -m uvicorn app.main:app --reload
Mở:    http://127.0.0.1:8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, limits, llm
from .routers import admin, attempt_control, audit, cases, exam, proctor, readiness, stats, tutor, tuong_tac
from .services import audit as audit_service, exam_access_codes

app = FastAPI(
    title="Hệ thống AI trợ giảng và giám sát kỳ thi",
    description="Hai hệ thống dùng chung một nền tảng, phục vụ hai đề tài dự thi.",
    version="1.0",
)


class _QuaLon(BaseException):
    """Thân yêu cầu vượt trần. Kế thừa BaseException để FastAPI không đổi nó thành lỗi 400 "đọc thân"."""


class GioiHanThan:
    """ASGI thuần: đếm byte thật của thân yêu cầu.

    Kiểm tra Content-Length khai báo (bên dưới) không chặn được yêu cầu truyền từng phần vì loại
    này không có tiêu đề đó; đếm ở đây thì chặn được cả hai.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        tran = limits.MAX_UPLOAD_BYTES if scope["path"] in limits.UPLOAD_PATHS else limits.MAX_BODY_BYTES
        da_nhan, da_tra_loi = 0, False

        async def nhan():
            nonlocal da_nhan
            tin = await receive()
            if tin["type"] == "http.request":
                da_nhan += len(tin.get("body", b""))
                if da_nhan > tran:
                    raise _QuaLon()
            return tin

        async def gui(tin):
            nonlocal da_tra_loi
            if tin["type"] == "http.response.start":
                da_tra_loi = True
            await send(tin)

        try:
            await self.app(scope, nhan, gui)
        except _QuaLon:
            if not da_tra_loi:
                await JSONResponse(status_code=413, content={
                    "detail": "Yêu cầu quá lớn, vui lòng gửi dữ liệu nhỏ hơn."})(scope, receive, send)


app.add_middleware(GioiHanThan)          # thêm trước để nằm sát ứng dụng nhất


@app.middleware("http")
async def bao_ve_duong_truyen(request: Request, call_next):
    """BL-19: reject clear-text non-local deployment traffic when enabled."""
    local_hosts = {"127.0.0.1", "localhost", "testserver"}
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    secure = request.url.scheme == "https" or forwarded == "https"
    if config.BAT_BUOC_HTTPS and request.url.hostname not in local_hosts and not secure:
        return JSONResponse(status_code=400, content={"detail": "Triển khai yêu cầu HTTPS"})
    cap = limits.MAX_UPLOAD_BYTES if request.url.path in limits.UPLOAD_PATHS else limits.MAX_BODY_BYTES
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:                      # M5
        return JSONResponse(status_code=413, content={
            "detail": "Yêu cầu quá lớn, vui lòng gửi dữ liệu nhỏ hơn."})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self)"
    if secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.exception_handler(Exception)
async def loi_khong_luong_truoc(request: Request, exc: Exception):
    """L2: lỗi bất ngờ chỉ ghi vào nhật ký máy chủ, người dùng không thấy nội dung lỗi."""
    logging.getLogger("app").error(
        "Lỗi không xử lý ở %s %s", request.method, request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={
        "detail": "Máy chủ gặp lỗi. Em thử lại sau ít phút, nếu vẫn lỗi thì báo thầy cô."})


# Tên ô nhập bằng tiếng Việt cho thông báo lỗi dữ liệu; ô nào chưa có tên thì chỉ nói "có một ô".
TEN_O_NHAP = {
    "ten": "Tên", "mon": "Môn", "ma": "Mã", "ho_ten": "Họ tên", "lop": "Lớp", "so_phut": "Số phút",
    "cau_hoi": "Danh sách câu hỏi", "noi_dung": "Nội dung", "phuong_an": "Phương án", "dap_an": "Đáp án",
    "de_thi": "Đề thi", "ly_do": "Lý do", "can_cu": "Căn cứ", "them_phut": "Số phút thêm", "giay": "Thời điểm",
    "quy_dinh": "Quy định", "phut_phan_hoi": "Số phút phản hồi", "phut_xu_ly_gv": "Số phút xử lý của giáo viên",
    "so_ngay_luu_anh": "Số ngày lưu ảnh", "tra_loi": "Câu trả lời", "ghi": "Lựa chọn nhập", "tep": "Tệp",
    "trang_thai": "Trạng thái", "muc_giam_sat": "Mức giám sát", "lua_chon": "Lựa chọn", "giai_thich": "Giải thích",
}
LOI_NHAP = {
    "missing": "còn thiếu", "string_too_long": "quá dài", "too_long": "có quá nhiều mục",
    "string_too_short": "đang để trống", "too_short": "đang để trống", "greater_than": "nhỏ hơn mức cho phép",
    "greater_than_equal": "nhỏ hơn mức cho phép", "less_than": "lớn hơn mức cho phép",
    "less_than_equal": "lớn hơn mức cho phép", "int_parsing": "phải là một số", "float_parsing": "phải là một số",
    "int_from_float": "phải là số nguyên", "finite_number": "phải là một số hợp lệ", "value_error": "chưa hợp lệ",
    "string_pattern_mismatch": "chưa đúng định dạng", "json_invalid": "chưa hợp lệ",
}


@app.exception_handler(RequestValidationError)
async def loi_du_lieu_gui_len(request: Request, exc: RequestValidationError):
    """Báo trường nào sai bằng tiếng Việt, và không in lại giá trị gửi lên.

    Bộ xử lý mặc định nhét cả giá trị đầu vào vào phản hồi; với Infinity hoặc NaN
    việc mã hóa JSON thất bại và người dùng nhận lỗi 500 (M5).
    """
    van_de = []
    for loi in exc.errors():
        cuoi = [str(p) for p in loi.get("loc", ()) if p != "body" and not str(p).isdigit()]
        ten = TEN_O_NHAP.get(cuoi[-1], "") if cuoi else ""
        mo_ta = LOI_NHAP.get(loi.get("type", ""), "chưa hợp lệ")
        van_de.append(f"{ten} {mo_ta}".strip() if ten else f"có một ô {mo_ta}")
    return JSONResponse(status_code=422, content={
        "detail": "Chưa lưu được vì " + "; ".join(dict.fromkeys(van_de))[:300] +
                  ". Kiểm tra lại các ô đã nhập rồi thử lại."})


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
    # L1: mã không tồn tại và mã học sinh đoán được khi đã có mã dự thi trả lời giống hệt
    # nhau, để không dò ra được tài khoản nào tồn tại.
    if not nd or (nd["vai_tro"] == "hoc_sinh" and not exam_login
                  and exam_access_codes.student_has_active_open_code(nd["ma"])):
        raise HTTPException(401, "Mã không đúng hoặc đã hết hiệu lực. "
                                 "Em kiểm tra lại, hoặc hỏi thầy cô để lấy mã dự thi.")
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
