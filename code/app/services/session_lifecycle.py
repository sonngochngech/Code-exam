"""BL-14 session state and safe pre-attempt editing rules."""

from fastapi import HTTPException

from .. import db


def require_open(connection, session_id: int):
    row = connection.execute(
        "SELECT * FROM ca_thi WHERE id=?", (session_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy ca thi")
    if row["trang_thai"] != "mo":
        raise HTTPException(409, "Ca thi chưa mở hoặc đã đóng")
    return row


def update_draft(session_id: int, name: str, classroom: str | None,
                 rules: str, monitoring_level: str, feedback_minutes: int,
                 teacher_minutes: int, allow_extension: bool,
                 image_retention_days: int, paired_study_code: str | None = None,
                 study_phase: str | None = None, room_code: str | None = None) -> dict:
    if feedback_minutes <= 0 or teacher_minutes <= 0 or image_retention_days <= 0:
        raise HTTPException(400, "Thời hạn phải lớn hơn 0 phút")
    with db.ket_noi() as connection:
        session = connection.execute("SELECT * FROM ca_thi WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Không tìm thấy ca thi")
        attempts = connection.execute(
            "SELECT 1 FROM bai_lam WHERE ca_thi=? LIMIT 1", (session_id,),
        ).fetchone()
        if attempts:
            raise HTTPException(409, "Không thể sửa cấu hình ca sau khi đã có bài làm")
        if session["trang_thai"] != "nhap":
            raise HTTPException(409, "Chỉ ca ở trạng thái nháp mới được sửa")
        connection.execute(
            "UPDATE ca_thi SET ten=?,lop=?,quy_dinh=?,muc_giam_sat=?,"
            " phut_phan_hoi=?,phut_xu_ly_gv=?,cho_phep_gia_han=?,so_ngay_luu_anh=?,"
            " ma_nghien_cuu_cap=?,giai_doan=?,ma_phong=?"
            " WHERE id=?",
            (name.strip()[:200], classroom, rules.strip()[:4000], monitoring_level,
             feedback_minutes, teacher_minutes, int(allow_extension),
             image_retention_days, paired_study_code, study_phase, room_code, session_id),
        )
        return dict(connection.execute("SELECT * FROM ca_thi WHERE id=?", (session_id,)).fetchone())


def transition(session_id: int, target: str) -> dict:
    allowed = {("nhap", "mo"), ("mo", "dong")}
    with db.ket_noi() as connection:
        session = connection.execute("SELECT * FROM ca_thi WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Không tìm thấy ca thi")
        if (session["trang_thai"], target) not in allowed:
            raise HTTPException(409, "Chuyển trạng thái ca thi không hợp lệ")
        if target == "mo" and not connection.execute(
                "SELECT 1 FROM cau_trac_nghiem WHERE de_thi=? LIMIT 1",
                (session["de_thi"],)).fetchone():                       # M9a
            raise HTTPException(409, "Đề thi chưa có câu hỏi nào nên chưa mở ca được")
        if target == "mo" and session["ma_nghien_cuu_cap"]:
            _validate_paired_study(connection, session)
        now = db.bay_gio()
        if target == "mo":
            connection.execute(
                "UPDATE ca_thi SET trang_thai='mo',bat_dau=? WHERE id=?", (now, session_id))
        else:
            connection.execute(
                "UPDATE ca_thi SET trang_thai='dong',ket_thuc=? WHERE id=?", (now, session_id))
        return dict(connection.execute("SELECT * FROM ca_thi WHERE id=?", (session_id,)).fetchone())


def _assignment_set(connection, session_id: int, role: str) -> set[str]:
    return {row["nguoi_dung"] for row in connection.execute(
        "SELECT nguoi_dung FROM ca_thi_nguoi_dung"
        " WHERE ca_thi=? AND vai_tro_trong_ca=?", (session_id, role)
    ).fetchall()}


def _validate_paired_study(connection, session) -> None:
    """BL-23: validate the small, explicit pre/post study structure."""
    if session["giai_doan"] not in {"tien_tac_dong", "hau_tac_dong"} or not session["ma_phong"]:
        raise HTTPException(409, "Ca ghép cặp phải có giai đoạn và mã phòng")
    counterpart = connection.execute(
        "SELECT * FROM ca_thi WHERE ma_nghien_cuu_cap=? AND id<>? AND giai_doan<>?",
        (session["ma_nghien_cuu_cap"], session["id"], session["giai_doan"]),
    ).fetchone()
    if not counterpart:
        raise HTTPException(409, "Chưa có ca trước/sau tác động ghép cặp")
    if counterpart["ma_phong"] != session["ma_phong"]:
        raise HTTPException(409, "Hai ca ghép cặp phải cùng mã phòng")
    teachers = _assignment_set(connection, session["id"], "giao_vien")
    other_teachers = _assignment_set(connection, counterpart["id"], "giao_vien")
    students = _assignment_set(connection, session["id"], "hoc_sinh")
    other_students = _assignment_set(connection, counterpart["id"], "hoc_sinh")
    if len(teachers) != 2 or teachers != other_teachers:
        raise HTTPException(409, "Hai ca phải có cùng đúng hai giáo viên")
    if not students or students != other_students:
        raise HTTPException(409, "Hai ca phải có cùng danh sách mã học sinh")
