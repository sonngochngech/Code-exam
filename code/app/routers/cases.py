"""BL-12: combined case record and versioned human-only final decisions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..auth import chi_giao_vien
from ..services import audit, evidence, monitoring_config

router = APIRouter(prefix="/api/cases", tags=["case decisions"])
STATUSES = {"khong_vi_pham", "can_lam_ro", "vi_pham"}


def _rows(conn, sql: str, params: tuple) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


@router.get("/ca/{session_id}/hoc-sinh/{student}")
def get_case(session_id: int, student: str, user: dict = Depends(chi_giao_vien)):
    evidence.require_evidence_unlocked(session_id, user)
    with db.ket_noi() as conn:
        assigned = conn.execute(
            "SELECT 1 FROM ca_thi_nguoi_dung WHERE ca_thi=? AND nguoi_dung=?"
            " AND vai_tro_trong_ca='hoc_sinh'", (session_id, student),
        ).fetchone()
        if not assigned:
            raise HTTPException(404, "Học sinh không thuộc ca thi")
        return {
            "ca_thi": session_id, "hoc_sinh": student,
            "cau_hinh": monitoring_config.latest(conn, session_id),
            "su_kien_he_thong": _rows(conn,
                "SELECT id,loai,giay,keo_dai,nguong_ap_dung,phien_ban_cau_hinh"
                " FROM moc_bat_thuong WHERE ca_thi=? AND hoc_sinh=? ORDER BY giay",
                (session_id, student)),
            "su_co_ky_thuat": _rows(conn,
                "SELECT camera,mo_hinh,ket_noi,toan_man_hinh,chi_tiet,cap_nhat_luc"
                " FROM trang_thai_ky_thuat WHERE ca_thi=? AND hoc_sinh=?",
                (session_id, student)),
            "ho_tro": [{**row, "moc_lien_ket": [r["moc_id"] for r in conn.execute(
                "SELECT moc_id FROM yeu_cau_ho_tro_moc WHERE yeu_cau=? ORDER BY moc_id",
                (row["id"],))]} for row in _rows(conn,
                "SELECT id,loai,noi_dung,moc_id,giay_trong_bai,trang_thai,phan_hoi_gv,"
                " giay_gian_doan,giao_vien,tao_luc,xu_ly_luc FROM yeu_cau_ho_tro"
                " WHERE ca_thi=? AND hoc_sinh=? ORDER BY id", (session_id, student))],
            "phan_hoi_hoc_sinh": _rows(conn,
                "SELECT moc_id,lua_chon,giai_thich,tao_luc FROM phan_hoi_sau_thi"
                " WHERE ca_thi=? AND hoc_sinh=? ORDER BY id", (session_id, student)),
            "phan_doan_giao_vien": _rows(conn,
                "SELECT giao_vien,vong,muc_nghi_ngo,ghi_chu,loai_thay_doi,tao_luc"
                " FROM phan_doan WHERE ca_thi=? AND hoc_sinh=? ORDER BY giao_vien,vong",
                (session_id, student)),
            "ket_luan_con_nguoi": _rows(conn,
                "SELECT phien_ban,trang_thai,can_cu,nguoi_xu_ly,tao_luc"
                " FROM ket_luan_ho_so WHERE ca_thi=? AND hoc_sinh=? ORDER BY phien_ban",
                (session_id, student)),
        }


class Decision(BaseModel):
    trang_thai: str
    can_cu: str


@router.post("/ca/{session_id}/hoc-sinh/{student}/ket-luan")
def decide(session_id: int, student: str, body: Decision,
           user: dict = Depends(chi_giao_vien)):
    evidence.require_evidence_unlocked(session_id, user)
    reason = body.can_cu.strip()
    if body.trang_thai not in STATUSES:
        raise HTTPException(400, "Trạng thái kết luận không hợp lệ")
    if not reason:
        raise HTTPException(400, "Kết luận phải có căn cứ")
    with db.ket_noi() as conn:
        assigned = conn.execute(
            "SELECT 1 FROM ca_thi_nguoi_dung WHERE ca_thi=? AND nguoi_dung=?"
            " AND vai_tro_trong_ca='hoc_sinh'", (session_id, student),
        ).fetchone()
        if not assigned:
            raise HTTPException(404, "Học sinh không thuộc ca thi")
        round_two = conn.execute(
            "SELECT 1 FROM phan_doan WHERE ca_thi=? AND hoc_sinh=? AND vong=2"
            " AND giao_vien=? LIMIT 1",
            (session_id, student, user["ma"]),
        ).fetchone()
        if not round_two:                                               # M9b
            raise HTTPException(
                409, "Phải hoàn tất phán đoán vòng hai của chính thầy cô trước khi kết luận")
        previous = conn.execute(
            "SELECT phien_ban,trang_thai,can_cu,nguoi_xu_ly,tao_luc"
            " FROM ket_luan_ho_so WHERE ca_thi=? AND hoc_sinh=?"
            " ORDER BY phien_ban DESC LIMIT 1", (session_id, student),
        ).fetchone()
        version = conn.execute(
            "SELECT COALESCE(MAX(phien_ban),0)+1 FROM ket_luan_ho_so"
            " WHERE ca_thi=? AND hoc_sinh=?", (session_id, student),
        ).fetchone()[0]
        created = db.bay_gio()
        conn.execute(
            "INSERT INTO ket_luan_ho_so"
            " (ca_thi,hoc_sinh,phien_ban,trang_thai,can_cu,nguoi_xu_ly,tao_luc)"
            " VALUES (?,?,?,?,?,?,?)", (session_id, student, version,
             body.trang_thai, reason[:1000], user["ma"], created),
        )
        after = {"phien_ban": version, "trang_thai": body.trang_thai,
                 "can_cu": reason[:1000], "nguoi_xu_ly": user["ma"],
                 "tao_luc": created}
        audit.log(conn, user["ma"], "mo_lai_ho_so" if previous else "ket_luan_ho_so",
                  "ho_so", student, session_id,
                  before=dict(previous) if previous else None, after=after)
    return {"phien_ban": version, "trang_thai": body.trang_thai,
            "can_cu": reason[:1000], "nguoi_xu_ly": user["ma"], "tao_luc": created}
