"""BL-15 feedback windows and explicit extensions."""

from .. import db

# M3: tổng thời gian giáo viên được gia hạn cho một học sinh không vượt quá mức này.
TRAN_GIA_HAN_PHUT = 180


def status(connection, session_id: int, student: str) -> dict:
    session = connection.execute(
        "SELECT phut_phan_hoi,phut_xu_ly_gv,cho_phep_gia_han FROM ca_thi WHERE id=?",
        (session_id,),
    ).fetchone()
    attempt = connection.execute(
        "SELECT nop_luc FROM bai_lam WHERE ca_thi=? AND hoc_sinh=?"
        " ORDER BY id DESC LIMIT 1", (session_id, student),
    ).fetchone()
    extension = connection.execute(
        "SELECT COALESCE(SUM(them_phut),0) FROM gia_han_phan_hoi"
        " WHERE ca_thi=? AND hoc_sinh=?", (session_id, student),
    ).fetchone()[0]
    decision = connection.execute(
        "SELECT tao_luc FROM ket_luan_ho_so WHERE ca_thi=? AND hoc_sinh=?"
        " ORDER BY phien_ban DESC LIMIT 1", (session_id, student),
    ).fetchone()
    cho_phep = bool(session["cho_phep_gia_han"]) if session else True
    if not session or not attempt or not attempt["nop_luc"]:
        return {"phut_con_lai": None, "het_han": False, "them_phut": extension,
                "cho_phep_gia_han": cho_phep, "tran_gia_han_phut": TRAN_GIA_HAN_PHUT,
                "da_nop": False,
                "phut_phan_hoi": session["phut_phan_hoi"] if session else 60,
                "phut_xu_ly_gv": session["phut_xu_ly_gv"] if session else 1440,
                "phut_xu_ly_gv_con_lai": None, "xu_ly_gv_qua_han": False,
                "da_co_ket_luan": bool(decision)}
    elapsed = (db.hien_tai() - db.doc_gio(attempt["nop_luc"])).total_seconds() / 60
    remaining = session["phut_phan_hoi"] + extension - elapsed
    teacher_remaining = session["phut_xu_ly_gv"] - elapsed
    return {"phut_con_lai": round(remaining, 1), "het_han": remaining < 0,
            "them_phut": extension, "phut_phan_hoi": session["phut_phan_hoi"],
            "phut_xu_ly_gv": session["phut_xu_ly_gv"],
            "phut_xu_ly_gv_con_lai": round(teacher_remaining, 1),
            "xu_ly_gv_qua_han": teacher_remaining < 0 and not decision,
            "da_co_ket_luan": bool(decision), "da_nop": True,
            "cho_phep_gia_han": cho_phep, "tran_gia_han_phut": TRAN_GIA_HAN_PHUT}
