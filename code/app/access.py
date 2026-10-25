"""Small authorization helpers for the prototype.

Actor identity always comes from the authenticated session. Browser-supplied
codes may be checked for compatibility, but are never trusted as identity.
"""

from fastapi import HTTPException

from . import db


def student_code(user: dict, requested_code: str | None = None) -> str:
    if user.get("vai_tro") != "hoc_sinh":
        raise HTTPException(403, "Chức năng này chỉ dành cho học sinh.")
    actual = user["ma"]
    if requested_code and requested_code != actual:
        raise HTTPException(403, "Em chỉ làm bài bằng tài khoản của chính mình.")
    return actual


def teacher_code(user: dict, requested_code: str | None = None) -> str:
    if user.get("vai_tro") != "giao_vien":
        raise HTTPException(403, "Chức năng này chỉ dành cho giáo viên.")
    actual = user["ma"]
    if requested_code and requested_code != actual:
        raise HTTPException(403, "Thầy cô chỉ thao tác được bằng tài khoản của chính mình.")
    return actual


def require_session_assignment(session_id: int, user: dict, role: str | None = None) -> None:
    """Require an explicit assignment for the current session."""
    expected = role or user.get("vai_tro")
    scoped_session = user.get("ca_thi")
    if expected == "hoc_sinh" and scoped_session is not None and scoped_session != session_id:
        raise HTTPException(403, "Mã dự thi này chỉ dùng cho ca thi được cấp, không vào được ca thi khác.")
    with db.ket_noi() as connection:
        row = connection.execute(
            "SELECT 1 FROM ca_thi_nguoi_dung WHERE ca_thi=? AND nguoi_dung=?"
            " AND vai_tro_trong_ca=?",
            (session_id, user["ma"], expected),
        ).fetchone()
    if not row:
        if expected == "giao_vien":
            raise HTTPException(403, "Thầy cô chưa tham gia ca thi này. Bấm Tham gia ở mục Ca của giáo viên khác để cùng phụ trách.")
        raise HTTPException(403, "Em chưa có tên trong ca thi này. Em hỏi thầy cô phụ trách nhé.")


def visible_students_sql() -> str:
    """Subquery of the student codes a teacher may look at (L3, C2).

    A student is visible when they are in the teacher's own class or share a session
    with the teacher. Parameters, in order: the teacher's class, the teacher's code.
    """
    return ("SELECT ma FROM nguoi_dung WHERE vai_tro='hoc_sinh' AND lop=?"
            " UNION SELECT s.nguoi_dung FROM ca_thi_nguoi_dung t JOIN ca_thi_nguoi_dung s"
            " ON s.ca_thi=t.ca_thi AND s.vai_tro_trong_ca='hoc_sinh'"
            " WHERE t.nguoi_dung=? AND t.vai_tro_trong_ca='giao_vien'")


def require_shared_session(teacher: dict, student: str) -> None:
    """A teacher may look at one student's data only for their own class or shared session."""
    with db.ket_noi() as connection:
        row = connection.execute(
            f"SELECT 1 WHERE ? IN ({visible_students_sql()})",
            (student, teacher.get("lop"), teacher["ma"]),
        ).fetchone()
    if not row:
        raise HTTPException(403, "Học sinh này không thuộc lớp hoặc ca thi thầy cô phụ trách.")

