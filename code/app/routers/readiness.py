"""Readiness and technical conditions, deliberately separate from behavior events."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import access, db
from ..limits import LongText
from ..auth import chi_giao_vien, nguoi_dung_hien_tai

router = APIRouter(prefix="/api/readiness", tags=["technical readiness"])


class Readiness(BaseModel):
    ca_thi: int
    camera: bool
    mo_hinh: bool
    ket_noi: bool
    toan_man_hinh: bool
    chi_tiet: LongText | None = None


@router.put("")
def save(body: Readiness, user: dict = Depends(nguoi_dung_hien_tai)):
    student = access.student_code(user, None)
    access.require_session_assignment(body.ca_thi, user, "hoc_sinh")
    with db.ket_noi() as conn:
        conn.execute(
            "INSERT INTO trang_thai_ky_thuat"
            " (ca_thi,hoc_sinh,camera,mo_hinh,ket_noi,toan_man_hinh,chi_tiet,cap_nhat_luc)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(ca_thi,hoc_sinh) DO UPDATE SET"
            " camera=excluded.camera,mo_hinh=excluded.mo_hinh,ket_noi=excluded.ket_noi,"
            " toan_man_hinh=excluded.toan_man_hinh,chi_tiet=excluded.chi_tiet,"
            " cap_nhat_luc=excluded.cap_nhat_luc",
            (body.ca_thi, student, body.camera, body.mo_hinh, body.ket_noi,
             body.toan_man_hinh, body.chi_tiet, db.bay_gio()),
        )
    return {"da_ghi": True, **body.model_dump(), "hoc_sinh": student}


@router.get("/ca/{ca_id}/cua-toi")
def mine(ca_id: int, user: dict = Depends(nguoi_dung_hien_tai)):
    student = access.student_code(user, None)
    access.require_session_assignment(ca_id, user, "hoc_sinh")
    with db.ket_noi() as conn:
        row = conn.execute(
            "SELECT camera,mo_hinh,ket_noi,toan_man_hinh,chi_tiet,cap_nhat_luc"
            " FROM trang_thai_ky_thuat WHERE ca_thi=? AND hoc_sinh=?",
            (ca_id, student),
        ).fetchone()
    return dict(row) if row else None


@router.get("/ca/{ca_id}")
def session_status(ca_id: int, user: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, user, "giao_vien")
    with db.ket_noi() as conn:
        rows = conn.execute(
            "SELECT hoc_sinh,camera,mo_hinh,ket_noi,toan_man_hinh,chi_tiet,cap_nhat_luc"
            " FROM trang_thai_ky_thuat WHERE ca_thi=? ORDER BY hoc_sinh", (ca_id,)
        ).fetchall()
    return [dict(row) for row in rows]
