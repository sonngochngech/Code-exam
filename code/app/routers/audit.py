from fastapi import APIRouter, Depends, Query

from .. import access, db
from ..auth import chi_giao_vien

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def audit_log(ca: int | None = None, hanh_dong: str | None = Query(None, max_length=60),
              an_dang_nhap: bool = False,
              trang: int = Query(1, ge=1, le=100_000), moi_trang: int = Query(20, ge=1, le=100),
              user: dict = Depends(chi_giao_vien)):
    """Read-only audit viewer (Phiếu 3). A teacher sees the sessions they are assigned to and
    their own actions that belong to no session (student accounts, learning material)."""
    if ca is not None:
        access.require_session_assignment(ca, user, "giao_vien")
        scope, params = "ca_thi = ?", [ca]
    else:
        scope = ("(ca_thi IN (SELECT ca_thi FROM ca_thi_nguoi_dung WHERE nguoi_dung = ?"
                 " AND vai_tro_trong_ca = 'giao_vien') OR (ca_thi IS NULL AND chu_the = ?))")
        params = [user["ma"], user["ma"]]
    if hanh_dong:
        scope += " AND hanh_dong = ?"
        params.append(hanh_dong)
    if an_dang_nhap:                       # đăng nhập là phần lớn nhật ký, che đi cho dễ đọc
        scope += " AND hanh_dong != 'dang_nhap'"
    with db.ket_noi() as connection:
        tong = connection.execute(
            f"SELECT COUNT(*) c FROM nhat_ky_kiem_toan WHERE {scope}", params).fetchone()["c"]
        rows = connection.execute(
            "SELECT id,ca_thi,chu_the,hanh_dong,loai_doi_tuong,ma_doi_tuong,du_lieu_truoc,"
            f"du_lieu_sau,tao_luc FROM nhat_ky_kiem_toan WHERE {scope} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [moi_trang, (trang - 1) * moi_trang]).fetchall()
    return {"tong": tong, "trang": trang, "moi_trang": moi_trang, "danh_sach": [dict(r) for r in rows]}


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
