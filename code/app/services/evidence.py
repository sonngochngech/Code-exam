"""Server-side evidence access rules (FR-051, BR-006)."""

from fastapi import HTTPException

from .. import access, db


def require_teacher_access(session_id: int, user: dict) -> str:
    teacher = access.teacher_code(user)
    access.require_session_assignment(session_id, user, "giao_vien")
    return teacher


def is_unlocked(connection, session_id: int, teacher: str) -> bool:
    """True when this teacher may see machine data of the session (the blind-round rule)."""
    session = connection.execute(
        "SELECT muc_giam_sat FROM ca_thi WHERE id=?", (session_id,)
    ).fetchone()
    if not session:
        raise HTTPException(404, "Không tìm thấy ca thi")
    if session["muc_giam_sat"] != "day_du":
        return True
    submitted = connection.execute(
        "SELECT COUNT(DISTINCT hoc_sinh) c FROM bai_lam WHERE ca_thi=?",
        (session_id,),
    ).fetchone()["c"]
    judged = connection.execute(
        "SELECT COUNT(DISTINCT hoc_sinh) c FROM phan_doan"
        " WHERE ca_thi=? AND giao_vien=? AND vong=1",
        (session_id, teacher),
    ).fetchone()["c"]
    return submitted > 0 and judged >= submitted


def require_evidence_unlocked(session_id: int, user: dict) -> str:
    teacher = require_teacher_access(session_id, user)
    with db.ket_noi() as connection:
        unlocked = is_unlocked(connection, session_id, teacher)
    if not unlocked:
        raise HTTPException(403, "Phải nộp đủ phán đoán vòng 1 trước khi xem dữ liệu.")
    return teacher
