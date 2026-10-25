"""BL-11: simple per-student pause and extra-time controls."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import access, db
from ..limits import MAX_EXTRA_SECONDS, LongText, ShortText
from ..auth import chi_giao_vien, nguoi_dung_hien_tai
from ..services import attempt_clock, audit

router = APIRouter(prefix="/api/attempt-control", tags=["attempt control"])
ACTIONS = {"tam_dung", "tiep_tuc", "them_gio"}


def _state(conn, session_id: int, student: str) -> dict:
    rows = conn.execute(
        "SELECT hanh_dong,so_giay,ly_do,giao_vien,tao_luc FROM dieu_chinh_bai_thi"
        " WHERE ca_thi=? AND hoc_sinh=? ORDER BY id", (session_id, student),
    ).fetchall()
    paused = False
    for row in rows:
        if row["hanh_dong"] == "tam_dung": paused = True
        elif row["hanh_dong"] == "tiep_tuc": paused = False
    return {**attempt_clock.snapshot(conn, session_id, student),
            "ca_thi": session_id, "hoc_sinh": student, "tam_dung": paused,
            "them_giay": sum(r["so_giay"] for r in rows if r["hanh_dong"] == "them_gio"),
            "lich_su": [dict(r) for r in rows]}


class Control(BaseModel):
    hanh_dong: ShortText
    so_giay: int = Field(default=0, ge=0, le=MAX_EXTRA_SECONDS)
    ly_do: LongText


@router.post("/ca/{session_id}/hoc-sinh/{student}")
def control(session_id: int, student: str, body: Control,
            user: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(session_id, user, "giao_vien")
    reason = body.ly_do.strip()
    if not reason:
        raise HTTPException(400, "Phải ghi lý do điều chỉnh")
    if body.hanh_dong not in ACTIONS:
        raise HTTPException(400, "Thao tác không hợp lệ.")
    if body.hanh_dong == "them_gio" and body.so_giay <= 0:
        raise HTTPException(400, "Số giây thêm phải lớn hơn 0")
    with db.ket_noi() as conn:
        assigned = conn.execute(
            "SELECT 1 FROM ca_thi_nguoi_dung WHERE ca_thi=? AND nguoi_dung=?"
            " AND vai_tro_trong_ca='hoc_sinh'", (session_id, student),
        ).fetchone()
        if not assigned:
            raise HTTPException(404, "Học sinh không thuộc ca thi")
        current = attempt_clock.snapshot(conn, session_id, student)
        if current["trang_thai_ca"] != "mo":
            raise HTTPException(409, "Ca thi chưa mở hoặc đã đóng.")
        if current["da_nop"] and body.hanh_dong != "them_gio":
            raise HTTPException(409, "Học sinh đã nộp bài")
        if body.hanh_dong == "tam_dung" and current["tam_dung"]:
            raise HTTPException(409, "Bài thi của em này đang tạm dừng rồi.")
        if body.hanh_dong == "tiep_tuc" and not current["tam_dung"]:
            raise HTTPException(409, "Bài thi của em này không đang tạm dừng.")
        conn.execute(
            "INSERT INTO dieu_chinh_bai_thi"
            " (ca_thi,hoc_sinh,giao_vien,hanh_dong,so_giay,ly_do,tao_luc)"
            " VALUES (?,?,?,?,?,?,?)", (session_id, student, user["ma"],
             body.hanh_dong, body.so_giay if body.hanh_dong == "them_gio" else 0,
             reason[:500], db.bay_gio()),
        )
        audit.log(conn, user["ma"], "dieu_chinh_thoi_gian", "hoc_sinh",
                  student, session_id, after={"hanh_dong": body.hanh_dong,
                  "so_giay": body.so_giay, "ly_do": reason[:500]})
        return _state(conn, session_id, student)


@router.get("/ca/{session_id}/cua-toi")
def my_state(session_id: int, user: dict = Depends(nguoi_dung_hien_tai)):
    student = access.student_code(user, None)
    access.require_session_assignment(session_id, user, "hoc_sinh")
    with db.ket_noi() as conn:
        return {**_state(conn, session_id, student), "may_chu_luc": db.bay_gio()}


@router.post("/ca/{session_id}/bat-dau")
def start_attempt(session_id: int, user: dict = Depends(nguoi_dung_hien_tai)):
    """Student presses start: the server records the clock origin (idempotent)."""
    student = access.student_code(user, None)
    access.require_session_assignment(session_id, user, "hoc_sinh")
    with db.ket_noi() as conn:
        state = attempt_clock.snapshot(conn, session_id, student)
        if state["trang_thai_ca"] != "mo":
            raise HTTPException(409, "Ca thi chưa mở hoặc đã đóng.")
        if state["da_nop"]:
            raise HTTPException(409, "Em đã nộp bài")
        attempt_clock.require_guidance_confirmed(conn, session_id, student)
        attempt_clock.require_round_one_open(conn, session_id, student)
        attempt_clock.start(conn, session_id, student)
        return _state(conn, session_id, student)


@router.get("/ca/{session_id}")
def session_states(session_id: int, user: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(session_id, user, "giao_vien")
    with db.ket_noi() as conn:
        students = conn.execute(
            "SELECT nguoi_dung FROM ca_thi_nguoi_dung WHERE ca_thi=?"
            " AND vai_tro_trong_ca='hoc_sinh' ORDER BY nguoi_dung", (session_id,),
        ).fetchall()
        return [_state(conn, session_id, row["nguoi_dung"]) for row in students]
