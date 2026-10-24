from fastapi import APIRouter, Depends

from .. import access, db
from ..auth import chi_giao_vien

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/ca/{session_id}")
def session_log(session_id: int, user: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(session_id, user, "giao_vien")
    with db.ket_noi() as connection:
        rows = connection.execute(
            "SELECT id,chu_the,hanh_dong,loai_doi_tuong,ma_doi_tuong,"
            " du_lieu_truoc,du_lieu_sau,tao_luc FROM nhat_ky_kiem_toan"
            " WHERE ca_thi=? ORDER BY id", (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]
