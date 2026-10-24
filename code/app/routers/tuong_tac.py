"""Hệ thống 2, quy trình liên kết TRƯỚC – TRONG – SAU buổi thi.

Ba phần này là một phần của giải pháp, nối hướng dẫn, hỗ trợ, cảnh báo và
phản hồi trên cùng một website:

  * Trước thi: học sinh xem video hướng dẫn, trả lời câu hỏi tình huống rồi
    xác nhận "đã hiểu và đồng ý". Giáo viên xem được số em đã chuẩn bị.
  * Trong thi: học sinh bấm nút hỗ trợ; hệ thống tự ghi mã, phòng, thời điểm,
    nội dung. Giáo viên tiếp nhận, ghi cách xử lí và thời gian gián đoạn.
  * Sau thi: trong vòng một giờ, học sinh xem lại sự kiện của mình và chọn
    đồng ý / không đồng ý / cần làm rõ kèm giải thích.

Nguyên tắc bảo mật: học sinh chỉ thao tác trên chính dữ liệu của mình. Mọi
endpoint phía học sinh ép mã học sinh bằng tài khoản đang đăng nhập, không
tin mã gửi lên từ trình duyệt. Các endpoint tổng hợp thêm quyền giáo viên.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import access, db
from ..auth import chi_giao_vien, nguoi_dung_hien_tai
from ..services import audit, feedback_deadlines

router = APIRouter(prefix="/api/tuong-tac", tags=["truoc trong sau buoi thi"],
                   dependencies=[Depends(nguoi_dung_hien_tai)])

LOAI_HO_TRO = {"mat_mang", "thiet_bi", "loi_thoi_gian", "xin_ra_ngoai",
                "can_ca_nhan", "khac"}
LUA_CHON = {"dong_y", "khong_dong_y", "can_lam_ro"}

TEN_LOAI_MOC = {
    "roi_khung_hinh": "Rời khỏi khung hình",
    "nguoi_thu_hai": "Xuất hiện người thứ hai",
    "nhin_ra_ngoai": "Hướng nhìn ra ngoài màn hình",
    "chuyen_cua_so": "Chuyển sang cửa sổ khác",
    "roi_toan_man_hinh": "Rời chế độ toàn màn hình",
}


def _la_hoc_sinh_cua_minh(nd: dict, ma_gui: str) -> str:
    """Học sinh chỉ thao tác trên mã của chính mình; giáo viên thì tuỳ."""
    if nd.get("vai_tro") == "hoc_sinh":
        return nd["ma"]
    return ma_gui or nd["ma"]


# ===========================================================================
# TRƯỚC BUỔI THI
# ===========================================================================
@router.get("/truoc-thi/ca/{ca_id}/huong-dan")
def lay_huong_dan(ca_id: int, nd: dict = Depends(nguoi_dung_hien_tai)):
    access.student_code(nd, None)
    access.require_session_assignment(ca_id, nd, "hoc_sinh")
    with db.ket_noi() as conn:
        row = conn.execute(
            "SELECT h.* FROM ca_thi c JOIN noi_dung_huong_dan h"
            " ON h.phien_ban=c.phien_ban_huong_dan WHERE c.id=?", (ca_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy nội dung hướng dẫn")
    return dict(row)


class XacNhanTruoc(BaseModel):
    ca_thi: int
    hoc_sinh: str | None = None
    da_xem_video: bool = False
    da_doc_ban_chu: bool = False
    tra_loi_tinh_huong: dict[str, str] = {}
    dong_y: bool = False
    phien_ban_huong_dan: int


@router.post("/truoc-thi/xac-nhan")
def xac_nhan_truoc_thi(x: XacNhanTruoc, nd: dict = Depends(nguoi_dung_hien_tai)):
    hs = access.student_code(nd, x.hoc_sinh)
    access.require_session_assignment(x.ca_thi, nd, "hoc_sinh")
    with db.ket_noi() as conn:
        session = conn.execute(
            "SELECT phien_ban_huong_dan FROM ca_thi WHERE id=?", (x.ca_thi,),
        ).fetchone()
        if not session or x.phien_ban_huong_dan != session["phien_ban_huong_dan"]:
            raise HTTPException(409, "Phiên bản hướng dẫn không còn hiệu lực")
        if not (x.da_xem_video or x.da_doc_ban_chu):
            raise HTTPException(400, "Chưa hoàn thành video hoặc bản chữ hướng dẫn")
        if x.tra_loi_tinh_huong.get("q1") != "b" or not x.dong_y:
            raise HTTPException(400, "Chưa hoàn thành kiểm tra hiểu biết và xác nhận")
        conn.execute(
            "INSERT INTO xac_nhan_truoc_thi (ca_thi, hoc_sinh, da_xem_video,"
            " tra_loi_tinh_huong,dong_y,phien_ban_huong_dan,tao_luc) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(ca_thi, hoc_sinh) DO UPDATE SET"
            " da_xem_video=excluded.da_xem_video,"
            " tra_loi_tinh_huong=excluded.tra_loi_tinh_huong,"
            " dong_y=excluded.dong_y,phien_ban_huong_dan=excluded.phien_ban_huong_dan,"
            " tao_luc=excluded.tao_luc",
            (x.ca_thi, hs, 1 if x.da_xem_video else 0,
             json.dumps(x.tra_loi_tinh_huong, ensure_ascii=False),
             1 if x.dong_y else 0, x.phien_ban_huong_dan, db.bay_gio()),
        )
    return {"da_ghi": True, "hoc_sinh": hs}


@router.get("/truoc-thi/{ca_id}/thong-ke")
def thong_ke_truoc_thi(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    """Giáo viên xem số em đã xác nhận hiểu và đồng ý trước khi thi."""
    access.require_session_assignment(ca_id, _u, "giao_vien")
    with db.ket_noi() as conn:
        ds = conn.execute(
            "SELECT hoc_sinh, da_xem_video, dong_y, tao_luc"
            " FROM xac_nhan_truoc_thi WHERE ca_thi = ? ORDER BY hoc_sinh", (ca_id,)
        ).fetchall()
    rows = [dict(d) for d in ds]
    return {
        "so_xac_nhan": sum(1 for r in rows if r["dong_y"]),
        "so_xem_video": sum(1 for r in rows if r["da_xem_video"]),
        "danh_sach": rows,
    }


# ===========================================================================
# TRONG BUỔI THI – hỗ trợ
# ===========================================================================
class YeuCauHoTro(BaseModel):
    ca_thi: int
    hoc_sinh: str | None = None
    lop: str | None = None
    loai: str = "khac"
    noi_dung: str = ""
    moc_id: int | None = None
    giay_trong_bai: float | None = None


@router.post("/ho-tro")
def tao_ho_tro(y: YeuCauHoTro, nd: dict = Depends(nguoi_dung_hien_tai)):
    hs = access.student_code(nd, y.hoc_sinh)
    access.require_session_assignment(y.ca_thi, nd, "hoc_sinh")
    loai = y.loai if y.loai in LOAI_HO_TRO else "khac"
    lop = y.lop or nd.get("lop")
    noi_dung = (y.noi_dung or "").strip()[:500]
    with db.ket_noi() as conn:
        if y.moc_id is not None:
            event = conn.execute(
                "SELECT 1 FROM moc_bat_thuong WHERE id=? AND ca_thi=? AND hoc_sinh=?",
                (y.moc_id, y.ca_thi, hs),
            ).fetchone()
            if not event:
                raise HTTPException(400, "Mốc liên kết không thuộc bài làm của học sinh")
        cur = conn.execute(
            "INSERT INTO yeu_cau_ho_tro (ca_thi, hoc_sinh, lop, loai, noi_dung,"
            " moc_id,giay_trong_bai,trang_thai,tao_luc) VALUES (?,?,?,?,?,?,?,'moi',?)",
            (y.ca_thi, hs, lop, loai, noi_dung, y.moc_id, y.giay_trong_bai,
             db.bay_gio()),
        )
    return {"id": cur.lastrowid, "trang_thai": "moi"}


@router.get("/ho-tro/ca/{ca_id}")
def danh_sach_ho_tro(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, _u, "giao_vien")
    with db.ket_noi() as conn:
        ds = conn.execute(
            "SELECT * FROM yeu_cau_ho_tro WHERE ca_thi = ?"
            " ORDER BY CASE trang_thai WHEN 'moi' THEN 0 WHEN 'dang_xu_ly'"
            " THEN 1 ELSE 2 END, id DESC", (ca_id,)
        ).fetchall()
    return [dict(d) for d in ds]


@router.get("/ho-tro/ca/{ca_id}/so-moi")
def so_ho_tro_moi(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    """Dùng cho huy hiệu nhấp nháy trên màn hình coi thi."""
    access.require_session_assignment(ca_id, _u, "giao_vien")
    with db.ket_noi() as conn:
        c = conn.execute(
            "SELECT COUNT(*) c FROM yeu_cau_ho_tro WHERE ca_thi = ?"
            " AND trang_thai = 'moi'", (ca_id,)).fetchone()["c"]
    return {"so_moi": c}


class XuLyHoTro(BaseModel):
    trang_thai: str = "xong"             # dang_xu_ly | xong
    phan_hoi_gv: str = ""
    giay_gian_doan: float | None = None


@router.post("/ho-tro/{yc_id}/xu-ly")
def xu_ly_ho_tro(yc_id: int, x: XuLyHoTro, nd: dict = Depends(chi_giao_vien)):
    tt = x.trang_thai if x.trang_thai in ("dang_xu_ly", "xong") else "xong"
    with db.ket_noi() as conn:
        co = conn.execute("SELECT id,ca_thi FROM yeu_cau_ho_tro WHERE id = ?",
                          (yc_id,)).fetchone()
        if not co:
            raise HTTPException(404, "Không tìm thấy yêu cầu hỗ trợ")
        access.require_session_assignment(co["ca_thi"], nd, "giao_vien")
        conn.execute(
            "UPDATE yeu_cau_ho_tro SET trang_thai=?, phan_hoi_gv=?,"
            " giay_gian_doan=?, giao_vien=?, xu_ly_luc=? WHERE id=?",
            (tt, x.phan_hoi_gv.strip()[:500], x.giay_gian_doan, nd["ma"],
             db.bay_gio(), yc_id),
        )
    return {"da_ghi": True, "trang_thai": tt}


class LienKetMoc(BaseModel):
    moc_ids: list[int]


@router.post("/ho-tro/{yc_id}/lien-ket")
def lien_ket_ho_tro(yc_id: int, body: LienKetMoc, nd: dict = Depends(chi_giao_vien)):
    """FR-043: teacher links a support request to one or more events of that student."""
    with db.ket_noi() as conn:
        yc = conn.execute("SELECT ca_thi,hoc_sinh FROM yeu_cau_ho_tro WHERE id=?",
                          (yc_id,)).fetchone()
        if not yc:
            raise HTTPException(404, "Không tìm thấy yêu cầu hỗ trợ")
        access.require_session_assignment(yc["ca_thi"], nd, "giao_vien")
        ids = set(body.moc_ids)
        if not ids:
            raise HTTPException(400, "Chưa chọn sự kiện nào")
        marks = ",".join("?" for _ in ids)
        owned = conn.execute(
            f"SELECT COUNT(*) FROM moc_bat_thuong WHERE ca_thi=? AND hoc_sinh=?"
            f" AND id IN ({marks})", (yc["ca_thi"], yc["hoc_sinh"], *ids)).fetchone()[0]
        if owned != len(ids):
            raise HTTPException(400, "Sự kiện không thuộc học sinh của yêu cầu này")
        conn.executemany(
            "INSERT OR IGNORE INTO yeu_cau_ho_tro_moc (yeu_cau,moc_id,giao_vien,tao_luc)"
            " VALUES (?,?,?,?)", [(yc_id, i, nd["ma"], db.bay_gio()) for i in ids])
        audit.log(conn, nd["ma"], "lien_ket_ho_tro", "yeu_cau_ho_tro", yc_id,
                  yc["ca_thi"], after={"moc_ids": sorted(ids)})
        return {"yeu_cau": yc_id, "moc_ids": [r["moc_id"] for r in conn.execute(
            "SELECT moc_id FROM yeu_cau_ho_tro_moc WHERE yeu_cau=? ORDER BY moc_id",
            (yc_id,))]}


# ===========================================================================
# SAU BUỔI THI – xem lại và phản hồi
# ===========================================================================
@router.get("/sau-thi/moc/{moc_id}/anh")
def anh_cua_toi(moc_id: int, nd: dict = Depends(nguoi_dung_hien_tai)):
    """Return only evidence belonging to the authenticated student."""
    hs = access.student_code(nd, None)
    with db.ket_noi() as conn:
        row = conn.execute(
            "SELECT m.ca_thi,m.anh FROM moc_bat_thuong m"
            " JOIN ca_thi_nguoi_dung p ON p.ca_thi=m.ca_thi"
            "  AND p.nguoi_dung=m.hoc_sinh AND p.vai_tro_trong_ca='hoc_sinh'"
            " WHERE m.id=? AND m.hoc_sinh=?", (moc_id, hs),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy bằng chứng được phép")
    with db.ket_noi() as conn:
        audit.log(conn, hs, "xem_bang_chung", "moc_bat_thuong",
                  moc_id, row["ca_thi"])
    return {"moc_id": moc_id, "anh": row["anh"]}


@router.get("/sau-thi/ca/{ca_id}/su-kien")
def su_kien_cua_toi(ca_id: int, hoc_sinh: str | None = None,
                    nd: dict = Depends(nguoi_dung_hien_tai)):
    """Danh sách sự kiện của chính học sinh để xem lại và phản hồi.

    Chỉ trả mốc thời gian, loại và ảnh bằng chứng của riêng em; không trả dữ
    liệu của bạn khác. Kèm thời gian còn lại của cửa sổ phản hồi một giờ.
    """
    hs = access.student_code(nd, hoc_sinh)
    access.require_session_assignment(ca_id, nd, "hoc_sinh")
    with db.ket_noi() as conn:
        moc = conn.execute(
            "SELECT id, loai, giay, keo_dai FROM moc_bat_thuong"
            " WHERE ca_thi = ? AND hoc_sinh = ? ORDER BY giay", (ca_id, hs)
        ).fetchall()
        da_ph = conn.execute(
            "SELECT moc_id, lua_chon, giai_thich FROM phan_hoi_sau_thi"
            " WHERE ca_thi = ? AND hoc_sinh = ?", (ca_id, hs)
        ).fetchall()
        deadline = feedback_deadlines.status(conn, ca_id, hs)
        ho_tro = conn.execute(
            "SELECT id,loai,noi_dung,moc_id,giay_trong_bai,trang_thai,tao_luc"
            " FROM yeu_cau_ho_tro WHERE ca_thi=? AND hoc_sinh=? ORDER BY id",
            (ca_id, hs),
        ).fetchall()
    da = {r["moc_id"]: dict(r) for r in da_ph}
    with db.ket_noi() as conn:
        linked: dict[int, set] = {}
        for r in conn.execute(
                "SELECT l.moc_id,l.yeu_cau FROM yeu_cau_ho_tro_moc l"
                " JOIN yeu_cau_ho_tro y ON y.id=l.yeu_cau WHERE y.ca_thi=? AND y.hoc_sinh=?",
                (ca_id, hs)):
            linked.setdefault(r["moc_id"], set()).add(r["yeu_cau"])
    ds = []
    for m in moc:
        pr = da.get(m["id"], {})
        nearby = [dict(h) for h in ho_tro if h["moc_id"] == m["id"] or h["id"] in linked.get(m["id"], ()) or (
            h["moc_id"] is None and h["giay_trong_bai"] is not None
            and abs(h["giay_trong_bai"] - m["giay"]) <= 120)]
        ds.append({"moc_id": m["id"], "loai": m["loai"],
                   "ten_loai": TEN_LOAI_MOC.get(m["loai"], m["loai"]),
                   "giay": m["giay"], "keo_dai": m["keo_dai"],
                   "ho_tro_gan": nearby,
                   "lua_chon": pr.get("lua_chon"),
                   "giai_thich": pr.get("giai_thich")})
    return {"hoc_sinh": hs, "su_kien": ds, "ho_tro": [dict(h) for h in ho_tro],
            **deadline}


class MotPhanHoi(BaseModel):
    moc_id: int | None = None
    lua_chon: str
    giai_thich: str = ""


class PhanHoiSauThi(BaseModel):
    ca_thi: int
    hoc_sinh: str | None = None
    phan_hoi: list[MotPhanHoi] = []


class GiaHanPhanHoi(BaseModel):
    them_phut: int
    ly_do: str


@router.post("/sau-thi/ca/{ca_id}/gia-han/{hoc_sinh}")
def gia_han_phan_hoi(ca_id: int, hoc_sinh: str, body: GiaHanPhanHoi,
                     nd: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, nd, "giao_vien")
    reason = body.ly_do.strip()
    if body.them_phut <= 0 or not reason:
        raise HTTPException(400, "Gia hạn phải có số phút dương và lý do")
    with db.ket_noi() as conn:
        session = conn.execute(
            "SELECT cho_phep_gia_han FROM ca_thi WHERE id=?", (ca_id,),
        ).fetchone()
        assigned = conn.execute(
            "SELECT 1 FROM ca_thi_nguoi_dung WHERE ca_thi=? AND nguoi_dung=?"
            " AND vai_tro_trong_ca='hoc_sinh'", (ca_id, hoc_sinh),
        ).fetchone()
        if not session or not assigned:
            raise HTTPException(404, "Không tìm thấy học sinh trong ca thi")
        if not session["cho_phep_gia_han"]:
            raise HTTPException(409, "Ca thi không cho phép gia hạn phản hồi")
        conn.execute(
            "INSERT INTO gia_han_phan_hoi"
            " (ca_thi,hoc_sinh,them_phut,ly_do,giao_vien,tao_luc) VALUES (?,?,?,?,?,?)",
            (ca_id, hoc_sinh, body.them_phut, reason[:500], nd["ma"], db.bay_gio()),
        )
        audit.log(conn, nd["ma"], "gia_han_phan_hoi", "hoc_sinh", hoc_sinh,
                  ca_id, after={"them_phut": body.them_phut, "ly_do": reason[:500]})
        return feedback_deadlines.status(conn, ca_id, hoc_sinh)


@router.post("/sau-thi/phan-hoi")
def gui_phan_hoi(p: PhanHoiSauThi, nd: dict = Depends(nguoi_dung_hien_tai)):
    """Ghi phản hồi của học sinh. Quá hạn một giờ vẫn nhận (gia hạn) nhưng
    đánh dấu để giáo viên biết."""
    hs = access.student_code(nd, p.hoc_sinh)
    access.require_session_assignment(p.ca_thi, nd, "hoc_sinh")
    hop_le = [r for r in p.phan_hoi if r.lua_chon in LUA_CHON]
    if not hop_le:
        raise HTTPException(400, "Chưa có phản hồi hợp lệ nào")
    with db.ket_noi() as conn:
        event_ids = {r.moc_id for r in hop_le if r.moc_id is not None}
        if event_ids:
            placeholders = ",".join("?" for _ in event_ids)
            owned = conn.execute(
                f"SELECT COUNT(*) FROM moc_bat_thuong WHERE ca_thi=? AND hoc_sinh=?"
                f" AND id IN ({placeholders})", (p.ca_thi, hs, *event_ids),
            ).fetchone()[0]
            if owned != len(event_ids):
                raise HTTPException(400, "Phản hồi chứa sự kiện không thuộc học sinh")
        deadline = feedback_deadlines.status(conn, p.ca_thi, hs)
        if deadline["het_han"]:
            raise HTTPException(409, "Đã hết hạn phản hồi; cần giáo viên gia hạn")
        # Ghi mới: xoá phản hồi cũ của em cho ca này rồi ghi lại, tránh trùng.
        conn.execute("DELETE FROM phan_hoi_sau_thi WHERE ca_thi = ? AND hoc_sinh = ?",
                     (p.ca_thi, hs))
        conn.executemany(
            "INSERT INTO phan_hoi_sau_thi (ca_thi, hoc_sinh, moc_id, lua_chon,"
            " giai_thich, tao_luc) VALUES (?,?,?,?,?,?)",
            [(p.ca_thi, hs, r.moc_id, r.lua_chon, r.giai_thich.strip()[:500],
              db.bay_gio()) for r in hop_le],
        )
    return {"da_ghi": len(hop_le), "het_han": False}


@router.get("/sau-thi/ca/{ca_id}/phan-hoi")
def tong_hop_phan_hoi(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    """Giáo viên xem phản hồi của học sinh để đối chiếu trước khi kết luận."""
    access.require_session_assignment(ca_id, _u, "giao_vien")
    with db.ket_noi() as conn:
        ds = conn.execute(
            "SELECT p.hoc_sinh, p.moc_id, p.lua_chon, p.giai_thich, p.tao_luc,"
            " m.loai, m.giay FROM phan_hoi_sau_thi p"
            " LEFT JOIN moc_bat_thuong m ON m.id = p.moc_id"
            " WHERE p.ca_thi = ? ORDER BY p.hoc_sinh, m.giay", (ca_id,)
        ).fetchall()
        students = conn.execute(
            "SELECT DISTINCT hoc_sinh FROM bai_lam WHERE ca_thi=? ORDER BY hoc_sinh",
            (ca_id,),
        ).fetchall()
        theo_hs: dict[str, list] = {r["hoc_sinh"]: [] for r in students}
        for d in ds:
            theo_hs.setdefault(d["hoc_sinh"], []).append({
                "moc_id": d["moc_id"], "lua_chon": d["lua_chon"],
                "giai_thich": d["giai_thich"],
                "ten_loai": TEN_LOAI_MOC.get(d["loai"], "Phản hồi chung"),
                "giay": d["giay"]})
        result = []
        for student, responses in theo_hs.items():
            deadline = feedback_deadlines.status(conn, ca_id, student)
            state = "da_phan_hoi" if responses else (
                "khong_phan_hoi" if deadline["het_han"] else "chua_phan_hoi")
            result.append({"hoc_sinh": student, "phan_hoi": responses,
                           "trang_thai_phan_hoi": state, **deadline})
        return result
