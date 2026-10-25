"""Versioned monitoring thresholds kept deliberately small for the prototype."""

import math

from fastapi import HTTPException

from .. import db
from . import audit

MAX_SECONDS = 3600.0      # M5: một ngưỡng theo giây không quá một giờ
MAX_ANGLE = 5.0           # M5: ngưỡng góc nhìn là tỉ lệ lệch, mặc định 0.35

DEFAULTS = {
    "giay_roi_khung_hinh": 10.0,
    "giay_nguoi_thu_hai": 3.0,
    "giay_nhin_ra_ngoai": 8.0,
    "giay_chuyen_cua_so": 0.0,
    "nguong_goc_nhin": 0.35,
}

EVENT_THRESHOLD = {
    "roi_khung_hinh": "giay_roi_khung_hinh",
    "nguoi_thu_hai": "giay_nguoi_thu_hai",
    "nhin_ra_ngoai": "giay_nhin_ra_ngoai",
    "chuyen_cua_so": "giay_chuyen_cua_so",
    "roi_toan_man_hinh": "giay_chuyen_cua_so",
}


def ensure_initial(connection, session_id: int, actor: str) -> None:
    exists = connection.execute(
        "SELECT 1 FROM cau_hinh_giam_sat WHERE ca_thi=?", (session_id,)
    ).fetchone()
    if not exists:
        connection.execute(
            "INSERT INTO cau_hinh_giam_sat (ca_thi,phien_ban,giay_roi_khung_hinh,"
            "giay_nguoi_thu_hai,giay_nhin_ra_ngoai,giay_chuyen_cua_so,"
            "nguong_goc_nhin,tao_boi,tao_luc) VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, 1, DEFAULTS["giay_roi_khung_hinh"],
             DEFAULTS["giay_nguoi_thu_hai"], DEFAULTS["giay_nhin_ra_ngoai"],
             DEFAULTS["giay_chuyen_cua_so"], DEFAULTS["nguong_goc_nhin"],
             actor, db.bay_gio()),
        )


def latest(connection, session_id: int) -> dict:
    row = connection.execute(
        "SELECT * FROM cau_hinh_giam_sat WHERE ca_thi=? ORDER BY phien_ban DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        ensure_initial(connection, session_id, "he_thong")
        row = connection.execute(
            "SELECT * FROM cau_hinh_giam_sat WHERE ca_thi=? ORDER BY phien_ban DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    return dict(row)


def create_version(session_id: int, actor: str, values: dict) -> dict:
    clean = {key: float(values.get(key, DEFAULTS[key])) for key in DEFAULTS}
    if not all(math.isfinite(value) for value in clean.values()):
        raise HTTPException(400, "Ngưỡng phải là một số hợp lệ.")
    if any(value < 0 for value in clean.values()):
        raise HTTPException(400, "Ngưỡng không được là số âm.")
    if any(clean[key] > MAX_SECONDS for key in clean if key != "nguong_goc_nhin") \
            or clean["nguong_goc_nhin"] > MAX_ANGLE:
        raise HTTPException(
            400, f"Ngưỡng giây tối đa {MAX_SECONDS:g}, ngưỡng góc nhìn tối đa {MAX_ANGLE:g}")
    with db.ket_noi() as connection:
        has_attempts = connection.execute(
            "SELECT 1 FROM bai_lam WHERE ca_thi=? LIMIT 1", (session_id,)
        ).fetchone()
        if has_attempts:
            raise HTTPException(409, "Đã có học sinh nộp bài nên không đổi ngưỡng được nữa.")
        current = latest(connection, session_id)
        version = current["phien_ban"] + 1
        connection.execute(
            "INSERT INTO cau_hinh_giam_sat (ca_thi,phien_ban,giay_roi_khung_hinh,"
            "giay_nguoi_thu_hai,giay_nhin_ra_ngoai,giay_chuyen_cua_so,"
            "nguong_goc_nhin,tao_boi,tao_luc) VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, version, clean["giay_roi_khung_hinh"],
             clean["giay_nguoi_thu_hai"], clean["giay_nhin_ra_ngoai"],
             clean["giay_chuyen_cua_so"], clean["nguong_goc_nhin"], actor, db.bay_gio()),
        )
        result = latest(connection, session_id)
        audit.log(connection, actor, "doi_nguong", "cau_hinh_giam_sat", version,
                  session_id, before=current, after=result)
        return result
