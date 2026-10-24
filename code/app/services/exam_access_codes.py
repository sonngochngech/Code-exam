"""ADD-EXAM-CODE: short, revocable student login codes for one exam session."""

from __future__ import annotations

import hashlib
import secrets

from fastapi import HTTPException

from .. import db
from . import audit, feedback_deadlines

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 8


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def generate_for_session(session_id: int, teacher: str) -> list[dict]:
    """Rotate and return one plaintext code per assigned student.

    Plaintext is returned only by this call. SQLite stores only SHA-256 hashes.
    """
    with db.ket_noi() as connection:
        session = connection.execute(
            "SELECT id,trang_thai FROM ca_thi WHERE id=?", (session_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Không tìm thấy ca thi")
        if session["trang_thai"] == "dong":
            raise HTTPException(409, "Ca thi đã đóng; không thể sinh mã mới")
        students = [row["nguoi_dung"] for row in connection.execute(
            "SELECT nguoi_dung FROM ca_thi_nguoi_dung"
            " WHERE ca_thi=? AND vai_tro_trong_ca='hoc_sinh' ORDER BY nguoi_dung",
            (session_id,),
        ).fetchall()]
        if not students:
            raise HTTPException(400, "Ca thi chưa được phân công học sinh")

        connection.execute(
            "UPDATE ma_du_thi SET dang_hoat_dong=0 WHERE ca_thi=?", (session_id,)
        )
        result = []
        for student in students:
            while True:
                code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
                digest = _hash(code)
                exists = connection.execute(
                    "SELECT 1 FROM ma_du_thi WHERE ma_bam=?", (digest,)
                ).fetchone()
                if not exists:
                    break
            connection.execute(
                "INSERT INTO ma_du_thi"
                " (ca_thi,hoc_sinh,ma_bam,dang_hoat_dong,tao_boi,tao_luc)"
                " VALUES (?,?,?,1,?,?)",
                (session_id, student, digest, teacher, db.bay_gio()),
            )
            result.append({"hoc_sinh": student, "ma_du_thi": code})
        audit.log(connection, teacher, "sinh_ma_du_thi", "ca_thi", str(session_id),
                  session_id, after={"so_hoc_sinh": len(result)})
    return result


def resolve(code: str) -> dict | None:
    """Resolve an active code while its session is open, or after it closed for a
    student who submitted and is still inside the post-exam feedback window
    (report section 5: students log in within an hour to review and respond)."""
    normalized = code.strip().upper()
    if len(normalized) != CODE_LENGTH or any(c not in ALPHABET for c in normalized):
        return None
    with db.ket_noi() as connection:
        row = connection.execute(
            "SELECT m.ca_thi,m.hoc_sinh,n.ho_ten,n.vai_tro,n.lop,c.trang_thai"
            " FROM ma_du_thi m JOIN ca_thi c ON c.id=m.ca_thi"
            " JOIN ca_thi_nguoi_dung p ON p.ca_thi=m.ca_thi"
            "  AND p.nguoi_dung=m.hoc_sinh AND p.vai_tro_trong_ca='hoc_sinh'"
            " JOIN nguoi_dung n ON n.ma=m.hoc_sinh"
            " WHERE m.ma_bam=? AND m.dang_hoat_dong=1 AND c.trang_thai IN ('mo','dong')",
            (_hash(normalized),),
        ).fetchone()
        if row and row["trang_thai"] == "dong":
            window = feedback_deadlines.status(connection, row["ca_thi"], row["hoc_sinh"])
            if window["phut_con_lai"] is None or window["het_han"]:
                return None
    if not row:
        return None
    result = dict(row)
    del result["trang_thai"]
    return result


def student_has_active_open_code(student: str) -> bool:
    with db.ket_noi() as connection:
        return connection.execute(
            "SELECT 1 FROM ma_du_thi m JOIN ca_thi c ON c.id=m.ca_thi"
            " WHERE m.hoc_sinh=? AND m.dang_hoat_dong=1 AND c.trang_thai='mo' LIMIT 1",
            (student,),
        ).fetchone() is not None
