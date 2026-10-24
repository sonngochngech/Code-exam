"""Trang quản trị: nạp học liệu, soạn đề, mở ca thi, xuất dữ liệu.

Trước đây những việc này phải gõ lệnh. Đưa lên web để giáo viên tự làm được
mà không cần ai hỗ trợ, và để học sinh trình bày được trọn vòng đời sản phẩm
trước hội đồng.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import access, config, db, rag
from ..auth import chi_giao_vien
from ..services import audit, feedback_deadlines, monitoring_config

# Toàn bộ trang quản trị chỉ dành cho giáo viên: gắn phụ thuộc kiểm tra vai trò
# cho mọi endpoint trong router này.
router = APIRouter(prefix="/api/admin", tags=["quan tri"],
                   dependencies=[Depends(chi_giao_vien)])


# ---------------------------------------------------------------------------
# Học liệu
# ---------------------------------------------------------------------------
@router.post("/hoc-lieu/nap")
async def nap_hoc_lieu(mon: str = Form(...), tep: UploadFile = File(...)):
    """Nhận file đề cương từ trình duyệt rồi cắt đoạn, gắn nhãn và lưu."""
    # Làm sạch tên file: chỉ giữ phần tên, bỏ mọi thành phần đường dẫn để tránh
    # vượt thư mục (ví dụ tên "../../x" ghi ra ngoài thư mục học liệu).
    ten_an_toan = os.path.basename((tep.filename or "").replace("\\", "/"))
    if not ten_an_toan or ten_an_toan in (".", ".."):
        raise HTTPException(400, "Tên file không hợp lệ")

    duoi = ten_an_toan.lower().rsplit(".", 1)[-1]
    if duoi not in ("docx", "txt", "md"):
        raise HTTPException(400, "Chỉ nhận file .docx, .txt hoặc .md")

    config.THU_MUC_HOC_LIEU.mkdir(parents=True, exist_ok=True)
    thu_muc = config.THU_MUC_HOC_LIEU.resolve()
    dich = (thu_muc / ten_an_toan).resolve()
    # Chốt chặn thứ hai: đích phải nằm trong thư mục học liệu.
    if thu_muc not in dich.parents:
        raise HTTPException(400, "Tên file không hợp lệ")
    with dich.open("wb") as f:
        shutil.copyfileobj(tep.file, f)

    try:
        so_doan = rag.nap_hoc_lieu(dich, mon)
    except Exception as e:
        raise HTTPException(400, f"Không đọc được file: {e}")

    return {"tep": ten_an_toan, "mon": mon, "so_doan": so_doan}


@router.get("/hoc-lieu")
def danh_sach_doan(mon: str | None = None, chuong: str | None = None,
                   trang: int = 1, moi_trang: int = 20):
    dieu_kien, tham_so = [], []
    if mon:
        dieu_kien.append("mon = ?")
        tham_so.append(mon)
    if chuong:
        dieu_kien.append("chuong = ?")
        tham_so.append(chuong)
    dk = (" WHERE " + " AND ".join(dieu_kien)) if dieu_kien else ""

    with db.ket_noi() as conn:
        tong = conn.execute(f"SELECT COUNT(*) c FROM hoc_lieu{dk}",
                            tham_so).fetchone()["c"]
        dong = conn.execute(
            f"SELECT id, mon, chuong, bai, dang_bai, nguon,"
            f" substr(noi_dung, 1, 160) trich FROM hoc_lieu{dk}"
            f" ORDER BY id LIMIT ? OFFSET ?",
            tham_so + [moi_trang, (trang - 1) * moi_trang]).fetchall()
    return {"tong": tong, "trang": trang, "moi_trang": moi_trang,
            "danh_sach": [dict(d) for d in dong]}


class SuaNhan(BaseModel):
    chuong: str | None = None
    bai: str | None = None
    dang_bai: str | None = None


@router.put("/hoc-lieu/{doan_id}")
def sua_nhan(doan_id: int, s: SuaNhan):
    """Sửa nhãn cho đoạn mà máy đoán sai. Phần này giáo viên dùng nhiều."""
    dat, tham_so = [], []
    for ten, gt in (("chuong", s.chuong), ("bai", s.bai), ("dang_bai", s.dang_bai)):
        if gt is not None:
            dat.append(f"{ten} = ?")
            tham_so.append(gt)
    if not dat:
        raise HTTPException(400, "Không có gì để sửa")
    with db.ket_noi() as conn:
        conn.execute(f"UPDATE hoc_lieu SET {', '.join(dat)} WHERE id = ?",
                     tham_so + [doan_id])
    return {"da_sua": doan_id}


@router.delete("/hoc-lieu/{doan_id}")
def xoa_doan(doan_id: int):
    with db.ket_noi() as conn:
        conn.execute("DELETE FROM hoc_lieu WHERE id = ?", (doan_id,))
    return {"da_xoa": doan_id}


@router.delete("/hoc-lieu")
def xoa_theo_nguon(nguon: str):
    """Xóa toàn bộ đoạn đến từ một file, dùng khi nạp nhầm."""
    with db.ket_noi() as conn:
        cur = conn.execute("DELETE FROM hoc_lieu WHERE nguon = ?", (nguon,))
    return {"so_doan_da_xoa": cur.rowcount}


# ---------------------------------------------------------------------------
# Xuất dữ liệu để phân tích
# ---------------------------------------------------------------------------
def _xuat_csv(ten_tep: str, tieu_de: list[str], dong: list[list]):
    bo_dem = io.StringIO()
    bo_dem.write("﻿")                 # để Excel đọc đúng tiếng Việt
    w = csv.writer(bo_dem)
    w.writerow(tieu_de)
    w.writerows(dong)
    bo_dem.seek(0)
    return StreamingResponse(
        iter([bo_dem.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{ten_tep}"'})


def _du_lieu_ca(conn, ca_id: int) -> tuple[dict, list[dict]]:
    session = conn.execute("SELECT * FROM ca_thi WHERE id=?", (ca_id,)).fetchone()
    if not session:
        raise HTTPException(404, "Không tìm thấy ca thi")
    cfg = monitoring_config.latest(conn, ca_id)
    students = conn.execute(
        "SELECT hoc_sinh,diem,nop_luc FROM bai_lam WHERE ca_thi=? ORDER BY hoc_sinh",
        (ca_id,),
    ).fetchall()
    rows = []
    for attempt in students:
        student = attempt["hoc_sinh"]
        events = [dict(x) for x in conn.execute(
            "SELECT loai,COUNT(*) so_luong,MAX(phien_ban_cau_hinh) phien_ban_ap_dung"
            " FROM moc_bat_thuong WHERE ca_thi=? AND hoc_sinh=? GROUP BY loai",
            (ca_id, student)).fetchall()]
        technical = conn.execute(
            "SELECT camera,mo_hinh,ket_noi,toan_man_hinh,chi_tiet,cap_nhat_luc"
            " FROM trang_thai_ky_thuat WHERE ca_thi=? AND hoc_sinh=?",
            (ca_id, student)).fetchone()
        support = [dict(x) for x in conn.execute(
            "SELECT loai,trang_thai,giay_gian_doan,giao_vien,tao_luc,xu_ly_luc"
            " FROM yeu_cau_ho_tro WHERE ca_thi=? AND hoc_sinh=? ORDER BY id",
            (ca_id, student)).fetchall()]
        judgments = [dict(x) for x in conn.execute(
            "SELECT giao_vien,vong,muc_nghi_ngo,ghi_chu,loai_thay_doi,tao_luc"
            " FROM phan_doan WHERE ca_thi=? AND hoc_sinh=? ORDER BY giao_vien,vong",
            (ca_id, student)).fetchall()]
        feedback = [dict(x) for x in conn.execute(
            "SELECT moc_id,lua_chon,giai_thich,tao_luc FROM phan_hoi_sau_thi"
            " WHERE ca_thi=? AND hoc_sinh=? ORDER BY id", (ca_id, student)).fetchall()]
        decisions = [dict(x) for x in conn.execute(
            "SELECT phien_ban,trang_thai,can_cu,nguoi_xu_ly,tao_luc"
            " FROM ket_luan_ho_so WHERE ca_thi=? AND hoc_sinh=? ORDER BY phien_ban",
            (ca_id, student)).fetchall()]
        deadline = feedback_deadlines.status(conn, ca_id, student)
        rows.append({
            "ma_hoc_sinh": student, "diem": attempt["diem"], "nop_luc": attempt["nop_luc"],
            "cau_hinh": {k: cfg[k] for k in monitoring_config.DEFAULTS | {"phien_ban": 0}},
            "su_kien_he_thong": events,
            "su_co_ky_thuat": dict(technical) if technical else None,
            "ho_tro": support, "phan_doan_giao_vien": judgments,
            "phan_hoi_hoc_sinh": feedback,
            "trang_thai_phan_hoi": "da_phan_hoi" if feedback else (
                "khong_phan_hoi" if deadline["het_han"] else "chua_phan_hoi"),
            "ket_luan_con_nguoi": decisions,
        })
    return dict(session), rows


@router.get("/xuat/cau-hoi")
def xuat_cau_hoi():
    """Toàn bộ nhật ký hỏi bài. Dùng cho phụ lục báo cáo dự án 1."""
    with db.ket_noi() as conn:
        dong = conn.execute(
            "SELECT id, nguoi_dung, mon, chuong, dang_bai, luot, tao_luc,"
            " noi_dung FROM cau_hoi ORDER BY id").fetchall()
    return _xuat_csv(
        "nhat-ky-cau-hoi.csv",
        ["Ma", "Hoc sinh", "Mon", "Chuong", "Dang bai", "Luot", "Thoi diem", "Cau hoi"],
        [[d["id"], d["nguoi_dung"], d["mon"], d["chuong"], d["dang_bai"],
          d["luot"], d["tao_luc"], d["noi_dung"]] for d in dong])


@router.get("/xuat/ca-thi/{ca_id}")
def xuat_ca_thi(ca_id: int, user: dict = Depends(chi_giao_vien)):
    """De-identified complete context, one row per student code."""
    access.require_session_assignment(ca_id, user, "giao_vien")
    with db.ket_noi() as conn:
        session, rows = _du_lieu_ca(conn, ca_id)
        teachers = conn.execute(
            "SELECT nguoi_dung FROM ca_thi_nguoi_dung"
            " WHERE ca_thi=? AND vai_tro_trong_ca='giao_vien' ORDER BY nguoi_dung",
            (ca_id,),
        ).fetchall()

    def packed(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    return _xuat_csv(
        f"ca-thi-{ca_id}.csv",
        ["Ma nghien cuu cap", "Giai doan", "Ma phong", "Ma giao vien",
         "Ma hoc sinh", "Diem", "Nop luc", "Cau hinh ap dung",
         "Su kien he thong", "Su co ky thuat", "Ho tro",
         "Phan doan giao vien", "Phan hoi hoc sinh", "Trang thai phan hoi",
         "Ket luan con nguoi"],
        [[session["ma_nghien_cuu_cap"] or "", session["giai_doan"] or "",
          session["ma_phong"] or "",
          ",".join(row["nguoi_dung"] for row in teachers),
          r["ma_hoc_sinh"], r["diem"], r["nop_luc"], packed(r["cau_hinh"]),
          packed(r["su_kien_he_thong"]), packed(r["su_co_ky_thuat"]),
          packed(r["ho_tro"]), packed(r["phan_doan_giao_vien"]),
          packed(r["phan_hoi_hoc_sinh"]), r["trang_thai_phan_hoi"],
          packed(r["ket_luan_con_nguoi"])] for r in rows])


@router.get("/bao-cao/ca-thi/{ca_id}")
def bao_cao_buoi_thi(ca_id: int, user: dict = Depends(chi_giao_vien)):
    """Báo cáo tổng hợp một buổi thi, hiện trên web và in được."""
    access.require_session_assignment(ca_id, user, "giao_vien")
    with db.ket_noi() as conn:
        ca, rows = _du_lieu_ca(conn, ca_id)
    diem = [r["diem"] for r in rows if r["diem"] is not None]
    return {
        "ca_thi": ca, "so_hoc_sinh": len(rows),
        "diem_trung_binh": round(sum(diem) / len(diem), 2) if diem else None,
        "diem_cao_nhat": max(diem) if diem else None,
        "diem_thap_nhat": min(diem) if diem else None,
        "su_kien_he_thong": [x for r in rows for x in r["su_kien_he_thong"]],
        "su_co_ky_thuat": [r["su_co_ky_thuat"] for r in rows if r["su_co_ky_thuat"]],
        "ho_tro": [x for r in rows for x in r["ho_tro"]],
        "thay_doi_phan_doan": [x for r in rows for x in r["phan_doan_giao_vien"]
                              if x["vong"] == 2],
        "phan_hoi_hoc_sinh": [{"ma_hoc_sinh": r["ma_hoc_sinh"],
                                "trang_thai": r["trang_thai_phan_hoi"],
                                "phan_hoi": r["phan_hoi_hoc_sinh"]} for r in rows],
        "ket_luan_con_nguoi": [x for r in rows for x in r["ket_luan_con_nguoi"]],
    }


# ---------------------------------------------------------------------------
# Xóa dữ liệu thử nghiệm
# ---------------------------------------------------------------------------
@router.post("/ca-thi/{ca_id}/don-anh-het-han")
def don_anh_het_han(ca_id: int, user: dict = Depends(chi_giao_vien)):
    """BL-21: remove expired image payloads while retaining event metadata."""
    access.require_session_assignment(ca_id, user, "giao_vien")
    with db.ket_noi() as conn:
        session = conn.execute(
            "SELECT so_ngay_luu_anh FROM ca_thi WHERE id=?", (ca_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Không tìm thấy ca thi")
        days = session["so_ngay_luu_anh"]
        cur = conn.execute(
            "UPDATE moc_bat_thuong SET anh=NULL WHERE ca_thi=? AND anh IS NOT NULL"
            " AND datetime(tao_luc) < datetime('now', ?)",
            (ca_id, f"-{days} days"),
        )
        audit.log(conn, user["ma"], "don_anh_het_han", "ca_thi", ca_id, ca_id,
                  after={"so_anh_da_xoa": cur.rowcount,
                         "so_ngay_luu_anh": days})
    return {"so_anh_da_xoa": cur.rowcount, "so_ngay_luu_anh": days}


@router.delete("/ca-thi/{ca_id}/du-lieu")
def xoa_du_lieu_ca(ca_id: int, user: dict = Depends(chi_giao_vien)):
    """Xóa bài làm, mốc và phán đoán của một ca, giữ lại đề và ca thi.

    Dùng khi chạy thử nhiều lần trước buổi thi thật, để dữ liệu tập dượt
    không lẫn vào dữ liệu nghiên cứu.
    """
    access.require_session_assignment(ca_id, user, "giao_vien")
    with db.ket_noi() as conn:
        session = conn.execute("SELECT trang_thai FROM ca_thi WHERE id=?", (ca_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Không tìm thấy ca thi")
        # Judgments are immutable and a closed session holds research data, so
        # only rehearsal data (no teacher judgment yet) may be wiped.
        judged = conn.execute("SELECT 1 FROM phan_doan WHERE ca_thi=? LIMIT 1", (ca_id,)).fetchone()
        if session["trang_thai"] == "dong" or judged:
            raise HTTPException(409, "Không xóa được: ca đã đóng hoặc đã có phán đoán của giáo viên")
        dem = {}
        for bang in ("bai_lam", "moc_bat_thuong", "luot_lam_bai", "dieu_chinh_bai_thi"):
            cur = conn.execute(f"DELETE FROM {bang} WHERE ca_thi = ?", (ca_id,))
            dem[bang] = cur.rowcount
        dem["phan_doan"] = 0
        audit.log(conn, user["ma"], "xoa_du_lieu_tap_duot", "ca_thi", ca_id, ca_id, after=dem)
    return {"da_xoa": dem}
