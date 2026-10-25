"""BL-11 follow-up: server-side attempt clock, pause gate and close gate.

The browser only displays this state. Pause, extra time, the personal deadline
and the closed-session rule are all decided here, so a student cannot keep
working by ignoring the page.

Assumptions (prototype):
- The clock starts when the student presses start (POST .../bat-dau). Without a
  start record the submission deadline runs from when the paper was handed out
  (GET .../de), or from when the session opened (C6).
- A submission is accepted up to GRACE_SECONDS after the deadline (network
  latency / offline-queue replay). Later submissions are rejected.
- Closing the session ends every attempt: the student may still send one final
  submission inside the grace window, and a pause no longer blocks it.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from .. import db

GRACE_SECONDS = 120


def _t(text: str) -> datetime:
    return db.doc_gio(text)


def require_guidance_confirmed(conn, session_id: int, student: str) -> None:
    """FR-022/023: the pre-exam confirmation must exist for the current guidance version."""
    ok = conn.execute(
        "SELECT 1 FROM xac_nhan_truoc_thi x JOIN ca_thi c ON c.id=x.ca_thi"
        " WHERE x.ca_thi=? AND x.hoc_sinh=? AND x.dong_y=1"
        " AND x.phien_ban_huong_dan=c.phien_ban_huong_dan", (session_id, student)).fetchone()
    if not ok:
        raise HTTPException(403, "Em cần hoàn thành hướng dẫn và xác nhận trước khi làm bài")


def require_round_one_open(conn, session_id: int, student: str) -> None:
    """A brand-new attempt after teachers locked round one would make the evidence
    gate unreachable (round one is immutable). Refuse it at the start, not at the end."""
    if conn.execute("SELECT 1 FROM bai_lam WHERE ca_thi=? AND hoc_sinh=?",
                    (session_id, student)).fetchone():
        return
    if conn.execute("SELECT 1 FROM luot_lam_bai WHERE ca_thi=? AND hoc_sinh=?",
                    (session_id, student)).fetchone():
        return                              # already started before the lock: may finish
    if conn.execute("SELECT 1 FROM phan_doan WHERE ca_thi=? AND vong=1 LIMIT 1",
                    (session_id,)).fetchone():
        raise HTTPException(409, "Giáo viên đã khóa phán đoán vòng 1; ca này không nhận thêm lượt làm bài mới. Em báo giáo viên hoặc chọn ca khác.")


def note_issued(conn, session_id: int, student: str, shuffled: bool = True) -> None:
    """C6: remember when the paper was first handed out (and, for M2, how it was shuffled).

    It is only a fallback anchor for the submission deadline. The student's own clock
    still starts at 'start', because the guidance and the camera check come between
    receiving the paper and starting it.
    """
    conn.execute(
        "INSERT OR IGNORE INTO phat_de (ca_thi,hoc_sinh,luc,tron) VALUES (?,?,?,?)",
        (session_id, student, db.bay_gio(), int(shuffled)),
    )


def start(conn, session_id: int, student: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO luot_lam_bai (ca_thi,hoc_sinh,bat_dau) VALUES (?,?,?)",
        (session_id, student, db.bay_gio()),
    )


def snapshot(conn, session_id: int, student: str) -> dict:
    """Return the server's view of one student's attempt at this moment."""
    session = conn.execute(
        "SELECT c.trang_thai,c.ket_thuc,c.bat_dau AS mo_luc,d.so_phut FROM ca_thi c"
        " JOIN de_thi d ON d.id=c.de_thi WHERE c.id=?", (session_id,)).fetchone()
    if not session:
        raise HTTPException(404, "Không tìm thấy ca thi")
    started = conn.execute(
        "SELECT bat_dau FROM luot_lam_bai WHERE ca_thi=? AND hoc_sinh=?",
        (session_id, student)).fetchone()
    issued = conn.execute(
        "SELECT luc FROM phat_de WHERE ca_thi=? AND hoc_sinh=?",
        (session_id, student)).fetchone()
    submitted = conn.execute(
        "SELECT diem FROM bai_lam WHERE ca_thi=? AND hoc_sinh=? ORDER BY id LIMIT 1",
        (session_id, student)).fetchone()
    events = conn.execute(
        "SELECT hanh_dong,so_giay,tao_luc FROM dieu_chinh_bai_thi"
        " WHERE ca_thi=? AND hoc_sinh=? ORDER BY id", (session_id, student)).fetchall()

    now = _t(db.bay_gio())
    paused, paused_since, paused_total, extra = False, None, 0.0, 0
    for row in events:
        if row["hanh_dong"] == "tam_dung" and not paused:
            paused, paused_since = True, _t(row["tao_luc"])
        elif row["hanh_dong"] == "tiep_tuc" and paused:
            paused_total += (_t(row["tao_luc"]) - paused_since).total_seconds()
            paused = False
        elif row["hanh_dong"] == "them_gio":
            extra += row["so_giay"]
    if paused:                              # an open pause freezes the clock
        paused_total += (now - paused_since).total_seconds()

    closed = session["trang_thai"] == "dong"

    def left_from(anchor: str) -> float:
        used = (now - _t(anchor)).total_seconds() - paused_total
        value = session["so_phut"] * 60 + extra - used
        if closed and session["ket_thuc"]:
            value = min(value, (_t(session["ket_thuc"]) - now).total_seconds())
        return value

    remaining = left_from(started["bat_dau"]) if started else None
    # C6: with no start record the deadline still exists. It runs from the moment the
    # paper was handed out, or failing that from the moment the session opened.
    fallback_anchor = None if started else (issued["luc"] if issued else session["mo_luc"])
    gate_remaining = remaining if started else (
        left_from(fallback_anchor) if fallback_anchor else None)
    return {
        "da_bat_dau": bool(started), "tam_dung": paused, "them_giay": extra,
        "ca_dong": closed, "da_nop": bool(submitted),
        "diem": submitted["diem"] if submitted else None,
        "con_lai_giay": None if remaining is None else max(0, int(remaining)),
        "het_gio": remaining is not None and remaining <= 0,
        "qua_han_nop": gate_remaining is not None and gate_remaining < -GRACE_SECONDS,
        "trang_thai_ca": session["trang_thai"],
    }


def require_working(conn, session_id: int, student: str) -> dict:
    """Gate for actions that mean 'the student is working' (e.g. proctor marks)."""
    state = snapshot(conn, session_id, student)
    if state["trang_thai_ca"] != "mo":
        raise HTTPException(409, "Ca thi chưa mở hoặc đã đóng")
    # A marker queued offline may arrive after submission; that is still valid.
    if state["tam_dung"] and not state["da_nop"]:
        raise HTTPException(423, "Bài thi đang tạm dừng theo yêu cầu của giáo viên")
    return state


def require_can_submit(conn, session_id: int, student: str) -> dict:
    """Gate for the final submission: open or just-closed, not paused, in time."""
    state = snapshot(conn, session_id, student)
    if state["da_nop"]:
        return state                       # replay is handled by the caller
    if state["trang_thai_ca"] == "nhap" or (
            state["ca_dong"] and not state["da_bat_dau"]):
        raise HTTPException(409, "Ca thi chưa mở hoặc đã đóng")
    if state["tam_dung"] and not state["ca_dong"]:
        raise HTTPException(423, "Bài thi đang tạm dừng theo yêu cầu của giáo viên")
    if state["qua_han_nop"]:
        raise HTTPException(409, "Đã hết giờ làm bài, không nhận bài nộp muộn")
    return state
