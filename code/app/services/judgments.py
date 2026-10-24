"""Two-round teacher judgment rules (FR-050 through FR-056)."""

from fastapi import HTTPException

from .. import db
from . import audit, evidence


def submit(session_id: int, user: dict, round_number: int,
           levels: dict[str, int], notes: dict[str, str]) -> int:
    teacher = evidence.require_teacher_access(session_id, user)
    if round_number not in (1, 2):
        raise HTTPException(400, "Vòng phải là 1 hoặc 2")
    if not levels:
        raise HTTPException(400, "Chưa có phán đoán nào")
    if any(not isinstance(value, int) or value < 0 or value > 3
           for value in levels.values()):
        raise HTTPException(400, "Mức nghi ngờ phải là số nguyên từ 0 đến 3")

    with db.ket_noi() as connection:
        submitted = {
            row["hoc_sinh"] for row in connection.execute(
                "SELECT DISTINCT hoc_sinh FROM bai_lam WHERE ca_thi=?", (session_id,)
            )
        }
        # Round one may be completed for the students still missing (a late submission
        # before this check existed). The teacher has seen no machine data yet, because
        # the evidence gate stays locked until every submitted student is judged, so
        # the judgment is still blind. Judged students stay locked.
        judged_r1 = {row["hoc_sinh"] for row in connection.execute(
            "SELECT hoc_sinh FROM phan_doan WHERE ca_thi=? AND giao_vien=? AND vong=1",
            (session_id, teacher))}
        completing = round_number == 1 and bool(judged_r1) and judged_r1 != submitted
        expected = (submitted - judged_r1) if completing else submitted
        if set(levels) != expected:
            if completing:
                raise HTTPException(
                    400, "Vòng 1 mới có một phần. Chỉ nộp cho các học sinh còn thiếu: "
                    + ", ".join(sorted(expected)))
            raise HTTPException(400, "Phải phán đoán đủ các học sinh đã nộp bài")

        if round_number == 1:
            working = [row["hoc_sinh"] for row in connection.execute(
                "SELECT l.hoc_sinh FROM luot_lam_bai l JOIN ca_thi c ON c.id=l.ca_thi"
                " WHERE l.ca_thi=? AND c.trang_thai='mo' AND NOT EXISTS ("
                " SELECT 1 FROM bai_lam b WHERE b.ca_thi=l.ca_thi AND b.hoc_sinh=l.hoc_sinh)",
                (session_id,))]
            if working:
                raise HTTPException(
                    409, "Còn học sinh đang làm bài (" + ", ".join(working[:5])
                    + "). Chờ các em nộp hoặc đóng ca rồi mới nộp vòng 1.")

        existing = connection.execute(
            "SELECT COUNT(*) c FROM phan_doan WHERE ca_thi=? AND giao_vien=? AND vong=?",
            (session_id, teacher, round_number),
        ).fetchone()["c"]
        if existing and not completing:
            raise HTTPException(409, f"Phán đoán vòng {round_number} đã được khóa")

        first_round = {}
        if round_number == 2:
            first_round = {
                row["hoc_sinh"]: row["muc_nghi_ngo"]
                for row in connection.execute(
                    "SELECT hoc_sinh, muc_nghi_ngo FROM phan_doan"
                    " WHERE ca_thi=? AND giao_vien=? AND vong=1",
                    (session_id, teacher),
                )
            }
            if set(first_round) != submitted:
                raise HTTPException(400, "Phải nộp đủ phán đoán vòng 1 trước vòng 2")
            missing_reason = [student for student, level in levels.items()
                              if level != first_round[student]
                              and not (notes.get(student) or "").strip()]
            if missing_reason:
                raise HTTPException(400, "Đổi phán đoán phải nêu căn cứ cụ thể")

        rows = []
        for student, level in levels.items():
            change_type = None
            if round_number == 2:
                change_type = "giu_nguyen" if level == first_round[student] else "doi_co_can_cu"
            rows.append((session_id, student, teacher, round_number, level,
                         (notes.get(student) or "").strip()[:500], change_type, db.bay_gio()))
        connection.executemany(
            "INSERT INTO phan_doan (ca_thi, hoc_sinh, giao_vien, vong,"
            " muc_nghi_ngo, ghi_chu, loai_thay_doi, tao_luc) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        audit.log(connection, teacher, "nop_phan_doan", "phan_doan",
                  f"vong-{round_number}", session_id,
                  after={"vong": round_number, "muc": levels, "ghi_chu": notes})
    return len(rows)
