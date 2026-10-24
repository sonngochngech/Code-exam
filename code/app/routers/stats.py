"""Thống kê cho cả hai hệ thống.

Phần cho hệ thống 1 là bảng điểm yếu của lớp, phục vụ giáo viên điều chỉnh
tiết dạy. Phần cho hệ thống 2 là phân tích nghiên cứu, tính kiểm định t và
độ chính xác phán đoán của giáo viên.

Các hàm thống kê viết tay để không phải cài thêm thư viện, và để học sinh
đọc hiểu được công thức khi trình bày.
"""

from __future__ import annotations

import math
from collections import Counter

from fastapi import APIRouter, Depends

from .. import db
from ..auth import chi_giao_vien

# Mọi thống kê đều dành cho giáo viên.
router = APIRouter(prefix="/api/stats", tags=["thong ke"],
                   dependencies=[Depends(chi_giao_vien)])


# ---------------------------------------------------------------------------
# Hàm thống kê cơ bản
# ---------------------------------------------------------------------------
def trung_binh(a: list[float]) -> float:
    return sum(a) / len(a) if a else 0.0


def do_lech_chuan(a: list[float]) -> float:
    """Độ lệch chuẩn mẫu, chia cho n trừ 1."""
    if len(a) < 2:
        return 0.0
    m = trung_binh(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / (len(a) - 1))


def _gammaln(x: float) -> float:
    c = [76.18009172947146, -86.50532032941677, 24.01409824083091,
         -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5]
    y, tmp = x, x + 5.5
    tmp -= (x + 0.5) * math.log(tmp)
    ser = 1.000000000190015
    for j in range(6):
        y += 1
        ser += c[j] / y
    return -tmp + math.log(2.5066282746310005 * ser / x)


def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1 / d
        de = d * c
        h *= de
        if abs(de - 1) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(_gammaln(a + b) - _gammaln(a) - _gammaln(b)
                  + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def p_tu_t(t: float, df: float) -> float:
    """Giá trị p hai đuôi của phân phối t."""
    if df <= 0:
        return 1.0
    return _betai(df / 2, 0.5, df / (df + t * t))


def kiem_dinh_t_doc_lap(a: list[float], b: list[float]) -> dict:
    """So sánh hai nhóm khác nhau, dùng hiệu chỉnh Welch cho phương sai lệch."""
    if len(a) < 2 or len(b) < 2:
        return {"t": None, "df": None, "p": None, "d": None}
    va, vb = do_lech_chuan(a) ** 2, do_lech_chuan(b) ** 2
    na, nb = len(a), len(b)
    mau = math.sqrt(va / na + vb / nb)
    if mau == 0:
        return {"t": None, "df": None, "p": None, "d": None}
    t = (trung_binh(a) - trung_binh(b)) / mau
    df = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    sp = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return {
        "t": round(t, 3), "df": round(df, 1), "p": round(p_tu_t(t, df), 4),
        "d": round((trung_binh(a) - trung_binh(b)) / sp, 2) if sp else None,
    }


# ---------------------------------------------------------------------------
# Hệ thống 1: bảng điểm yếu của lớp
# ---------------------------------------------------------------------------
@router.get("/tro-giang")
def thong_ke_tro_giang(mon: str | None = None):
    """Ba con số giáo viên cần: dạng bài vướng nhiều nhất, em hỏi lặp lại,
    và giờ cao điểm trong tuần."""
    dieu_kien, tham_so = "", []
    if mon:
        dieu_kien, tham_so = " WHERE mon = ?", [mon]

    with db.ket_noi() as conn:
        tong = conn.execute(
            f"SELECT COUNT(*) c FROM cau_hoi{dieu_kien}", tham_so).fetchone()["c"]

        dang_bai = conn.execute(
            f"SELECT COALESCE(NULLIF(dang_bai,''), chuong) nhan, COUNT(*) so_cau"
            f" FROM cau_hoi{dieu_kien} GROUP BY nhan ORDER BY so_cau DESC LIMIT 8",
            tham_so).fetchall()

        # Học sinh hỏi đi hỏi lại cùng một dạng bài từ ba lần trở lên.
        lap_lai = conn.execute(
            f"SELECT nguoi_dung, COALESCE(NULLIF(dang_bai,''), chuong) nhan,"
            f" COUNT(*) so_lan FROM cau_hoi{dieu_kien} GROUP BY nguoi_dung, nhan"
            f" HAVING so_lan >= 3 ORDER BY so_lan DESC LIMIT 15", tham_so).fetchall()

        theo_gio = conn.execute(
            f"SELECT substr(tao_luc, 12, 2) gio, COUNT(*) so_cau"
            f" FROM cau_hoi{dieu_kien} GROUP BY gio ORDER BY gio", tham_so).fetchall()

    return {
        "tong_cau_hoi": tong,
        "dang_bai_vuong_nhat": [
            {**dict(d), "ty_le": round(d["so_cau"] / tong * 100, 1) if tong else 0}
            for d in dang_bai
        ],
        "hoi_lap_lai": [dict(d) for d in lap_lai],
        "theo_gio": [dict(d) for d in theo_gio],
    }


# ---------------------------------------------------------------------------
# Hệ thống 2: phân tích nghiên cứu
# ---------------------------------------------------------------------------
def _do_chinh_xac(cap: list[tuple[int, int]]) -> dict:
    """Nhận danh sách (phán đoán, thực tế) với giá trị 0 hoặc 1."""
    tp = tn = fp = fn = 0
    for du_doan, thuc in cap:
        if du_doan == 1 and thuc == 1:
            tp += 1
        elif du_doan == 0 and thuc == 0:
            tn += 1
        elif du_doan == 1 and thuc == 0:
            fp += 1
        else:
            fn += 1
    n = len(cap)
    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "chinh_xac": round((tp + tn) / n, 3) if n else None,
        "do_nhay": round(tp / (tp + fn), 3) if tp + fn else None,
        "do_dac_hieu": round(tn / (tn + fp), 3) if tn + fp else None,
        "so_nghi_oan": fp,
    }


@router.get("/nghien-cuu/{ca_id}")
def phan_tich_nghien_cuu(ca_id: int, nguong_thuc_te: int = 3,
                         nguong_nghi_ngo: int = 2):
    """Describe events and compare judgments only to independent human decisions.

    ``nguong_thuc_te`` remains accepted for old clients but is deliberately not
    used: machine-event counts are never ground truth.
    """
    with db.ket_noi() as conn:
        moc = conn.execute(
            "SELECT hoc_sinh, COUNT(*) so_moc FROM moc_bat_thuong"
            " WHERE ca_thi = ? GROUP BY hoc_sinh", (ca_id,)).fetchall()
        pd = conn.execute(
            "SELECT hoc_sinh, giao_vien, vong, muc_nghi_ngo FROM phan_doan"
            " WHERE ca_thi = ?", (ca_id,)).fetchall()
        hs = conn.execute(
            "SELECT DISTINCT hoc_sinh FROM bai_lam WHERE ca_thi = ?",
            (ca_id,)).fetchall()
        decisions = conn.execute(
            "SELECT k.hoc_sinh,k.trang_thai FROM ket_luan_ho_so k"
            " JOIN (SELECT hoc_sinh,MAX(phien_ban) v FROM ket_luan_ho_so"
            " WHERE ca_thi=? GROUP BY hoc_sinh) last"
            " ON last.hoc_sinh=k.hoc_sinh AND last.v=k.phien_ban"
            " WHERE k.ca_thi=?", (ca_id, ca_id),
        ).fetchall()

    so_moc = {d["hoc_sinh"]: d["so_moc"] for d in moc}
    danh_sach = [d["hoc_sinh"] for d in hs] or list(so_moc)
    nhan_thuc = {d["hoc_sinh"]: 1 if d["trang_thai"] == "vi_pham" else 0
                 for d in decisions if d["trang_thai"] in ("vi_pham", "khong_vi_pham")}

    theo_vong: dict[int, list[tuple[int, int]]] = {1: [], 2: []}
    for d in pd:
        if d["hoc_sinh"] not in nhan_thuc:
            continue
        du_doan = 1 if d["muc_nghi_ngo"] >= nguong_nghi_ngo else 0
        theo_vong.setdefault(d["vong"], []).append((du_doan, nhan_thuc[d["hoc_sinh"]]))

    kq = {v: _do_chinh_xac(c) for v, c in theo_vong.items() if c}

    cai_thien = None
    if 1 in kq and 2 in kq and kq[1]["chinh_xac"] is not None:
        cai_thien = {
            "chinh_xac": round(kq[2]["chinh_xac"] - kq[1]["chinh_xac"], 3),
            "nghi_oan_giam": kq[1]["so_nghi_oan"] - kq[2]["so_nghi_oan"],
        }

    return {
        "ca_thi": ca_id,
        "so_hoc_sinh": len(danh_sach),
        "so_moc_trung_binh": round(trung_binh([so_moc.get(h, 0) for h in danh_sach]), 2),
        "vong_1": kq.get(1),
        "vong_2": kq.get(2),
        "cai_thien": cai_thien,
        "nguon_nhan_thuc": "ket_luan_con_nguoi",
        "ghi_chu": ("Chưa có đủ kết luận độc lập để tính độ chính xác."
                    if not nhan_thuc else "Sự kiện máy chỉ là dữ liệu mô tả."),
    }


@router.get("/so-sanh-nhom")
def so_sanh_hai_nhom(ca_tn: int, ca_dc: int):
    """So sánh nhóm thực nghiệm và nhóm đối chứng về số hành vi bất thường."""
    with db.ket_noi() as conn:
        def lay(ca_id):
            hs = conn.execute(
                "SELECT DISTINCT hoc_sinh FROM bai_lam WHERE ca_thi = ?",
                (ca_id,)).fetchall()
            moc = conn.execute(
                "SELECT hoc_sinh, COUNT(*) c FROM moc_bat_thuong WHERE ca_thi = ?"
                " GROUP BY hoc_sinh", (ca_id,)).fetchall()
            d = {m["hoc_sinh"]: m["c"] for m in moc}
            return [float(d.get(h["hoc_sinh"], 0)) for h in hs]

        tn, dc = lay(ca_tn), lay(ca_dc)

    return {
        "nhom_thuc_nghiem": {"n": len(tn), "trung_binh": round(trung_binh(tn), 2),
                             "do_lech_chuan": round(do_lech_chuan(tn), 2)},
        "nhom_doi_chung": {"n": len(dc), "trung_binh": round(trung_binh(dc), 2),
                           "do_lech_chuan": round(do_lech_chuan(dc), 2)},
        "kiem_dinh": kiem_dinh_t_doc_lap(tn, dc),
        "ghi_chu": "Cỡ mẫu nhỏ, cần nêu rõ hạn chế này khi viết báo cáo.",
    }
