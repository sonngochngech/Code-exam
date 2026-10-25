"""Hệ thống 2, phần giám sát và phán đoán của giáo viên.

Điểm cần nhớ khi trình bày trước hội đồng: toàn bộ việc nhận diện khuôn mặt
và ước lượng hướng nhìn chạy trên máy của học sinh, trong trình duyệt. Máy chủ
chỉ nhận mốc thời gian kèm một ảnh chụp nhỏ tại đúng thời điểm có dấu hiệu.
Video không bao giờ rời khỏi máy của học sinh.

Hệ thống không kết luận học sinh gian lận. Nó chỉ đánh dấu để giáo viên xem lại.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import access, config, db
from ..limits import Seconds, ShortText
from ..auth import chi_giao_vien, nguoi_dung_hien_tai
from ..services import (attempt_clock, audit, evidence, images, judgments,
                        monitoring_config, session_lifecycle)

# Mọi endpoint cần đăng nhập; phần tổng hợp, ảnh bằng chứng và phán đoán của
# giáo viên thêm quyền giáo viên.
router = APIRouter(prefix="/api/proctor", tags=["giam sat"],
                   dependencies=[Depends(nguoi_dung_hien_tai)])

TEN_LOAI = {
    "roi_khung_hinh": "Rời khỏi khung hình",
    "nguoi_thu_hai": "Xuất hiện người thứ hai",
    "nhin_ra_ngoai": "Hướng nhìn ra ngoài màn hình",
    "chuyen_cua_so": "Chuyển sang cửa sổ khác",
}
TEN_LOAI["roi_toan_man_hinh"] = "Rời chế độ toàn màn hình"

class MocMoi(BaseModel):
    ca_thi: int
    hoc_sinh: ShortText
    loai: ShortText
    giay: Seconds
    keo_dai: Seconds | None = None
    anh: str | None = None           # ảnh bằng chứng, dạng chuỗi base64
    # M6: mã do trình duyệt sinh cho mỗi mốc, để gửi lại không tạo bản trùng.
    client_moc_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{8,64}$")


@router.post("/moc")
def ghi_moc(m: MocMoi, nd: dict = Depends(nguoi_dung_hien_tai)):
    """Trình duyệt gửi lên khi phát hiện một dấu hiệu vượt ngưỡng."""
    hoc_sinh = access.student_code(nd, m.hoc_sinh)
    access.require_session_assignment(m.ca_thi, nd, "hoc_sinh")
    if m.loai not in TEN_LOAI:
        raise HTTPException(400, f"Loại dấu hiệu không hợp lệ: {m.loai}")
    anh = images.require_safe(m.anh)
    with db.ket_noi() as conn:
        session_lifecycle.require_open(conn, m.ca_thi)
        attempt_clock.require_working(conn, m.ca_thi, hoc_sinh)
        cfg = monitoring_config.latest(conn, m.ca_thi)
        threshold_key = monitoring_config.EVENT_THRESHOLD[m.loai]
        cur = conn.execute(
            "INSERT OR IGNORE INTO moc_bat_thuong (ca_thi,hoc_sinh,loai,giay,keo_dai,anh,"
            " nguong_ap_dung,phien_ban_cau_hinh,client_moc_id,tao_luc)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (m.ca_thi, hoc_sinh, m.loai, m.giay, m.keo_dai, anh,
             cfg[threshold_key], cfg["phien_ban"], m.client_moc_id, db.bay_gio()),
        )
        if cur.rowcount:
            return {"da_ghi": True, "moc_id": cur.lastrowid}
        # M6: mốc này đã được lưu từ lần gửi trước; trả lại đúng mốc đó.
        existing = conn.execute(
            "SELECT id FROM moc_bat_thuong WHERE ca_thi=? AND hoc_sinh=? AND client_moc_id=?",
            (m.ca_thi, hoc_sinh, m.client_moc_id)).fetchone()
    if not existing:                      # bị bỏ qua vì lý do khác, không phải do gửi trùng
        raise HTTPException(400, "Không ghi được mốc này")
    return {"da_ghi": True, "moc_id": existing["id"], "trung": True}


@router.get("/nguong")
def lay_nguong():
    """Ngưỡng cảnh báo gửi xuống trình duyệt. Học sinh chỉnh trong buổi học
    thứ ba để thấy đánh đổi giữa báo nhầm và bỏ sót."""
    return {
        "giay_roi_khung_hinh": config.GIAY_ROI_KHUNG_HINH,
        "giay_nhin_ra_ngoai": config.GIAY_NHIN_RA_NGOAI,
        "giay_chuyen_cua_so": config.GIAY_CHUYEN_CUA_SO,
        "nguong_goc_nhin": config.NGUONG_GOC_NHIN,
    }


@router.get("/ca/{ca_id}/tong-hop")
def tong_hop_ca(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    """Danh sách học sinh kèm số mốc theo từng loại. Đây là màn hình giáo viên
    nhìn vào ở vòng phán đoán thứ hai."""
    evidence.require_evidence_unlocked(ca_id, _u)
    with db.ket_noi() as conn:
        moc = conn.execute(
            "SELECT hoc_sinh, loai, giay, keo_dai, id FROM moc_bat_thuong"
            " WHERE ca_thi = ? ORDER BY hoc_sinh, giay", (ca_id,)
        ).fetchall()
        hs = conn.execute(
            "SELECT DISTINCT hoc_sinh FROM bai_lam WHERE ca_thi = ?", (ca_id,)
        ).fetchall()

    theo_hs: dict[str, dict] = {}
    for d in hs:
        theo_hs[d["hoc_sinh"]] = {"hoc_sinh": d["hoc_sinh"], "tong": 0,
                                  "theo_loai": Counter(), "moc": []}
    for m in moc:
        o = theo_hs.setdefault(m["hoc_sinh"], {"hoc_sinh": m["hoc_sinh"], "tong": 0,
                                               "theo_loai": Counter(), "moc": []})
        o["tong"] += 1
        o["theo_loai"][m["loai"]] += 1
        o["moc"].append({"id": m["id"], "loai": m["loai"], "ten_loai": TEN_LOAI[m["loai"]],
                         "giay": m["giay"], "keo_dai": m["keo_dai"]})

    ds = sorted(theo_hs.values(), key=lambda x: -x["tong"])
    for o in ds:
        o["theo_loai"] = {TEN_LOAI[k]: v for k, v in o["theo_loai"].items()}
    return ds


@router.get("/moc/{moc_id}/anh")
def lay_anh(moc_id: int, _u: dict = Depends(chi_giao_vien)):
    """Ảnh bằng chứng của một mốc. Tách riêng để màn hình tổng hợp tải nhanh."""
    with db.ket_noi() as conn:
        d = conn.execute("SELECT ca_thi, anh FROM moc_bat_thuong WHERE id = ?",
                         (moc_id,)).fetchone()
    if not d:
        raise HTTPException(404, "Không tìm thấy mốc")
    evidence.require_evidence_unlocked(d["ca_thi"], _u)
    with db.ket_noi() as conn:
        audit.log(conn, _u["ma"], "xem_bang_chung", "moc_bat_thuong",
                  moc_id, d["ca_thi"])
    return {"anh": images.safe_data_url(d["anh"])}


@router.get("/ca/{ca_id}/danh-sach-hoc-sinh")
def danh_sach_hoc_sinh(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    evidence.require_teacher_access(ca_id, _u)
    with db.ket_noi() as conn:
        rows = conn.execute(
            "SELECT DISTINCT hoc_sinh FROM bai_lam WHERE ca_thi=? ORDER BY hoc_sinh",
            (ca_id,),
        ).fetchall()
    return [row["hoc_sinh"] for row in rows]


# ---------------------------------------------------------------------------
# Phán đoán của giáo viên, hai vòng
# ---------------------------------------------------------------------------
class PhanDoanMoi(BaseModel):
    ca_thi: int
    giao_vien: str
    vong: int                        # 1 chưa xem dữ liệu, 2 đã xem
    muc: dict[str, int]              # {"ma_hoc_sinh": muc_nghi_ngo_0_den_3}
    ghi_chu: dict[str, str] = {}


@router.post("/phan-doan")
def ghi_phan_doan(p: PhanDoanMoi, _u: dict = Depends(chi_giao_vien)):
    """Ghi phán đoán của giáo viên. Vòng 1 phải nộp trước khi xem dữ liệu.

    Thiết kế đo lặp trên cùng một giáo viên: nhờ vậy chênh lệch giữa hai vòng
    phản ánh tác động của dữ liệu, không lẫn với chênh lệch năng lực giữa các
    giáo viên khác nhau.
    """
    access.teacher_code(_u, p.giao_vien)
    return {"da_ghi": judgments.submit(
        p.ca_thi, _u, p.vong, p.muc, p.ghi_chu
    )}


@router.get("/ca/{ca_id}/da-nop-vong1")
def da_nop_vong1(ca_id: int, giao_vien: str | None = None,
                 _u: dict = Depends(chi_giao_vien)):
    """Màn hình giáo viên gọi hàm này để biết đã được phép xem dữ liệu chưa."""
    giao_vien = access.teacher_code(_u, giao_vien)
    with db.ket_noi() as conn:
        c = conn.execute(
            "SELECT COUNT(*) c FROM phan_doan WHERE ca_thi = ? AND giao_vien = ?"
            " AND vong = 1", (ca_id, giao_vien)
        ).fetchone()["c"]
        ca = conn.execute("SELECT muc_giam_sat FROM ca_thi WHERE id = ?",
                          (ca_id,)).fetchone()
        own = conn.execute(
            "SELECT hoc_sinh,vong,muc_nghi_ngo,ghi_chu FROM phan_doan"
            " WHERE ca_thi = ? AND giao_vien = ?", (ca_id, giao_vien)).fetchall()
        submitted = [r["hoc_sinh"] for r in conn.execute(
            "SELECT DISTINCT hoc_sinh FROM bai_lam WHERE ca_thi=? ORDER BY hoc_sinh", (ca_id,))]
    muc = ca["muc_giam_sat"] if ca else "day_du"
    # The teacher's own submitted judgments, so the page can show what is locked.
    vong = {1: {}, 2: {}}
    for r in own:
        vong.setdefault(r["vong"], {})[r["hoc_sinh"]] = {
            "muc": r["muc_nghi_ngo"], "ghi_chu": r["ghi_chu"]}
    thieu = [h for h in submitted if h not in vong[1]]
    return {"da_nop": c > 0, "so_hoc_sinh": c, "muc_giam_sat": muc,
            "vong_1_day_du": c > 0 and not thieu, "thieu_vong_1": thieu if c > 0 else [],
            "da_nop_vong_2": bool(vong[2]), "vong_1": vong[1], "vong_2": vong[2]}
