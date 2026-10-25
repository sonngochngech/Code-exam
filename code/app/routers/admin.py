"""Trang quản trị: nạp học liệu, soạn đề, mở ca thi, xuất dữ liệu.

Trước đây những việc này phải gõ lệnh. Đưa lên web để giáo viên tự làm được
mà không cần ai hỗ trợ, và để học sinh trình bày được trọn vòng đời sản phẩm
trước hội đồng.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import unicodedata

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from .. import access, config, db, rag
from ..auth import chi_giao_vien
from ..limits import ShortText
from ..services import audit, evidence, feedback_deadlines, monitoring_config

# Toàn bộ trang quản trị chỉ dành cho giáo viên: gắn phụ thuộc kiểm tra vai trò
# cho mọi endpoint trong router này.
router = APIRouter(prefix="/api/admin", tags=["quan tri"],
                   dependencies=[Depends(chi_giao_vien)])


# ---------------------------------------------------------------------------
# Học liệu
# ---------------------------------------------------------------------------
@router.post("/hoc-lieu/nap")
async def nap_hoc_lieu(mon: str = Form(...), tep: UploadFile = File(...),
                       user: dict = Depends(chi_giao_vien)):
    """Nhận file đề cương từ trình duyệt rồi cắt đoạn, gắn nhãn và lưu."""
    mon = mon.strip()
    if not mon or len(mon) > 100:
        raise HTTPException(400, "Môn không hợp lệ: cần có tên môn, tối đa 100 ký tự")
    # Làm sạch tên file: chỉ giữ phần tên, bỏ mọi thành phần đường dẫn để tránh
    # vượt thư mục (ví dụ tên "../../x" ghi ra ngoài thư mục học liệu).
    ten_an_toan = os.path.basename((tep.filename or "").replace("\\", "/"))
    if not ten_an_toan or ten_an_toan in (".", ".."):
        raise HTTPException(400, "Tên tệp không hợp lệ. Thầy cô đổi tên tệp rồi tải lại.")

    duoi = ten_an_toan.lower().rsplit(".", 1)[-1]
    if duoi not in ("docx", "txt", "md"):
        raise HTTPException(400, "Chỉ nhận tệp Word (.docx), văn bản (.txt) hoặc Markdown (.md).")

    with db.ket_noi() as conn:                  # nạp lại cùng tệp sẽ nhân đôi mọi đoạn, nên chặn trước khi ghi
        da_nap = conn.execute("SELECT COUNT(*) c FROM hoc_lieu WHERE nguon = ? AND mon = ?",
                              (ten_an_toan, mon)).fetchone()["c"]
    if da_nap:
        raise HTTPException(409, f"Tệp {ten_an_toan} đã được nạp cho môn {mon} ({da_nap} đoạn). "
                                 "Thầy cô gõ tên tệp vào ô tìm kiếm, chọn tất cả các đoạn tìm thấy rồi bấm Xóa, "
                                 "sau đó nạp lại. Nếu đây là bản khác thì đổi tên tệp.")

    config.THU_MUC_HOC_LIEU.mkdir(parents=True, exist_ok=True)
    thu_muc = config.THU_MUC_HOC_LIEU.resolve()
    dich = (thu_muc / ten_an_toan).resolve()
    # Chốt chặn thứ hai: đích phải nằm trong thư mục học liệu.
    if thu_muc not in dich.parents:
        raise HTTPException(400, "Tên tệp không hợp lệ. Thầy cô đổi tên tệp rồi tải lại.")
    with dich.open("wb") as f:
        shutil.copyfileobj(tep.file, f)

    try:
        so_doan = rag.nap_hoc_lieu(dich, mon)
    except rag.LoiDinhDang as e:
        dich.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    except Exception:
        logging.getLogger("app").exception("Không đọc được học liệu %s", ten_an_toan)
        dich.unlink(missing_ok=True)
        raise HTTPException(400, "Không đọc được tệp. Thầy cô kiểm tra lại định dạng "
                                 "và nội dung rồi thử lại.")

    with db.ket_noi() as conn:
        audit.log(conn, user["ma"], "nap_hoc_lieu", "hoc_lieu", ten_an_toan,
                  after={"tep": ten_an_toan, "mon": mon, "so_doan": so_doan})
    return {"tep": ten_an_toan, "mon": mon, "so_doan": so_doan}


@router.get("/hoc-lieu")
def danh_sach_doan(mon: str | None = Query(None, max_length=100),
                   chuong: str | None = Query(None, max_length=200),
                   tim: str | None = Query(None, max_length=100),
                   trang: int = Query(1, ge=1, le=100_000),
                   moi_trang: int = Query(20, ge=1, le=200)):
    """Danh sách đoạn học liệu, lọc theo môn, chương và từ khóa (Phiếu 1.5)."""
    dieu_kien, tham_so = [], []
    if mon:
        dieu_kien.append("mon = ?")
        tham_so.append(mon)
    if chuong:
        dieu_kien.append("chuong = ?")
        tham_so.append(chuong)
    dk = (" WHERE " + " AND ".join(dieu_kien)) if dieu_kien else ""

    with db.ket_noi() as conn:
        if tim and tim.strip():
            # Tìm không phân biệt hoa thường kể cả chữ có dấu, việc mà LIKE của SQLite
            # không làm được cho chữ ngoài ASCII. Kho học liệu cỡ vài nghìn đoạn nên
            # lọc ở đây là đủ nhanh.
            tu_khoa = tim.strip().casefold()
            khop = [d for d in conn.execute(
                "SELECT id, mon, chuong, bai, dang_bai, nguon, noi_dung"
                f" FROM hoc_lieu{dk} ORDER BY id", tham_so)
                if tu_khoa in " ".join(str(d[k] or "") for k in (
                    "chuong", "bai", "dang_bai", "noi_dung", "nguon")).casefold()]
            tong = len(khop)
            trang_nay = khop[(trang - 1) * moi_trang: trang * moi_trang]
            dong = [{**{k: d[k] for k in ("id", "mon", "chuong", "bai", "dang_bai", "nguon")},
                     "trich": d["noi_dung"][:160]} for d in trang_nay]
            return {"tong": tong, "trang": trang, "moi_trang": moi_trang, "danh_sach": dong}
        tong = conn.execute(f"SELECT COUNT(*) c FROM hoc_lieu{dk}",
                            tham_so).fetchone()["c"]
        dong = conn.execute(
            f"SELECT id, mon, chuong, bai, dang_bai, nguon,"
            f" substr(noi_dung, 1, 160) trich FROM hoc_lieu{dk}"
            f" ORDER BY id LIMIT ? OFFSET ?",
            tham_so + [moi_trang, (trang - 1) * moi_trang]).fetchall()
    return {"tong": tong, "trang": trang, "moi_trang": moi_trang,
            "danh_sach": [dict(d) for d in dong]}


@router.get("/hoc-lieu/chuong")
def danh_sach_chuong(mon: str | None = Query(None, max_length=100)):
    """Các chương đang có, để làm bộ lọc theo chương."""
    with db.ket_noi() as conn:
        dong = conn.execute(
            "SELECT DISTINCT chuong FROM hoc_lieu"
            + (" WHERE mon = ?" if mon else "") + " ORDER BY chuong",
            [mon] if mon else []).fetchall()
    return [d["chuong"] for d in dong if d["chuong"]]


@router.get("/hoc-lieu/{doan_id}")
def xem_doan(doan_id: int):
    """Toàn bộ một đoạn để xem trước (danh sách chỉ trả phần đầu)."""
    with db.ket_noi() as conn:
        d = conn.execute("SELECT id, mon, chuong, bai, dang_bai, noi_dung, nguon"
                         " FROM hoc_lieu WHERE id = ?", (doan_id,)).fetchone()
    if not d:
        raise HTTPException(404, "Không tìm thấy đoạn học liệu")
    return dict(d)


class SuaNhan(BaseModel):
    chuong: ShortText | None = Field(default=None, max_length=200)
    bai: ShortText | None = Field(default=None, max_length=200)
    dang_bai: ShortText | None = Field(default=None, max_length=200)


class NhieuDoan(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class SuaNhieuDoan(NhieuDoan):
    chuong: ShortText | None = Field(default=None, max_length=200)
    bai: ShortText | None = Field(default=None, max_length=200)
    dang_bai: ShortText | None = Field(default=None, max_length=200)


@router.post("/hoc-lieu/xoa-nhieu")
def xoa_nhieu_doan(body: NhieuDoan, user: dict = Depends(chi_giao_vien)):
    """Xóa nhiều đoạn một lần (tối đa 200), ghi vào nhật ký kiểm toán."""
    ids = sorted(set(body.ids))
    with db.ket_noi() as conn:
        cur = conn.execute(
            f"DELETE FROM hoc_lieu WHERE id IN ({','.join('?' for _ in ids)})", ids)
        audit.log(conn, user["ma"], "xoa_nhieu_hoc_lieu", "hoc_lieu", None,
                  after={"so_doan_da_xoa": cur.rowcount, "ids": ids})
    return {"so_doan_da_xoa": cur.rowcount}


@router.post("/hoc-lieu/sua-nhieu")
def sua_nhieu_doan(body: SuaNhieuDoan, user: dict = Depends(chi_giao_vien)):
    """Đổi chương, bài hoặc dạng bài cho nhiều đoạn cùng lúc. Chỉ trường được gửi mới đổi."""
    dat = {k: getattr(body, k) for k in ("chuong", "bai", "dang_bai") if getattr(body, k) is not None}
    if not dat:
        raise HTTPException(400, "Thầy cô chưa nhập nhãn nào để sửa.")
    ids = sorted(set(body.ids))
    with db.ket_noi() as conn:
        cur = conn.execute(
            f"UPDATE hoc_lieu SET {', '.join(f'{k} = ?' for k in dat)}"
            f" WHERE id IN ({','.join('?' for _ in ids)})", [*dat.values(), *ids])
        audit.log(conn, user["ma"], "sua_nhieu_hoc_lieu", "hoc_lieu", None,
                  after={"so_doan_da_sua": cur.rowcount, "ids": ids, "nhan_moi": dat})
    return {"so_doan_da_sua": cur.rowcount}


@router.put("/hoc-lieu/{doan_id}")
def sua_nhan(doan_id: int, s: SuaNhan):
    """Sửa nhãn cho đoạn mà máy đoán sai. Phần này giáo viên dùng nhiều."""
    dat, tham_so = [], []
    for ten, gt in (("chuong", s.chuong), ("bai", s.bai), ("dang_bai", s.dang_bai)):
        if gt is not None:
            dat.append(f"{ten} = ?")
            tham_so.append(gt)
    if not dat:
        raise HTTPException(400, "Thầy cô chưa nhập nhãn nào để sửa.")
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
# Tài khoản học sinh (Phiếu mục 3, bản gọn)
# ---------------------------------------------------------------------------
# Mọi bảng có dữ liệu của một học sinh. Có dòng trong bất kỳ bảng nào thì không xóa được,
# vì đó là dữ liệu nghiên cứu hoặc bài làm.
BANG_DU_LIEU_HOC_SINH = (
    ("bai_lam", "hoc_sinh"), ("moc_bat_thuong", "hoc_sinh"), ("luot_lam_bai", "hoc_sinh"),
    ("phat_de", "hoc_sinh"), ("yeu_cau_ho_tro", "hoc_sinh"), ("phan_hoi_sau_thi", "hoc_sinh"),
    ("xac_nhan_truoc_thi", "hoc_sinh"), ("trang_thai_ky_thuat", "hoc_sinh"),
    ("phan_doan", "hoc_sinh"), ("ket_luan_ho_so", "hoc_sinh"), ("dieu_chinh_bai_thi", "hoc_sinh"),
    ("gia_han_phan_hoi", "hoc_sinh"), ("cau_hoi", "nguoi_dung"),
)
# Ký tự đầu khiến Excel hiểu ô là công thức; không nhận ở tên và lớp để tệp xuất ra an toàn.
KY_TU_CONG_THUC = ("=", "+", "-", "@")
MA_HOC_SINH = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
TOI_DA_DONG_NHAP = 2000


def _lam_sach_ten(ho_ten: str | None, lop: str | None) -> tuple[str, str | None]:
    ho_ten = (ho_ten or "").strip()
    lop = (lop or "").strip() or None
    if not ho_ten:
        raise ValueError("Thiếu họ tên")
    if len(ho_ten) > 100:
        raise ValueError("Họ tên dài quá 100 ký tự")
    if lop and len(lop) > 20:
        raise ValueError("Tên lớp dài quá 20 ký tự")
    for gia_tri in (ho_ten, lop):
        if gia_tri and gia_tri.startswith(KY_TU_CONG_THUC):
            raise ValueError("Họ tên và lớp không được bắt đầu bằng = + - hoặc @")
    return ho_ten, lop


class HocSinhMoi(BaseModel):
    ma: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    ho_ten: str = Field(max_length=100)
    lop: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _kiem_tra(self):
        self.ho_ten, self.lop = _lam_sach_ten(self.ho_ten, self.lop)
        return self


class HocSinhSua(BaseModel):
    ho_ten: str = Field(max_length=100)
    lop: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _kiem_tra(self):
        self.ho_ten, self.lop = _lam_sach_ten(self.ho_ten, self.lop)
        return self


def _hoc_sinh_co_du_lieu(conn) -> set[str]:
    """Mã các học sinh đã có dữ liệu trong bất kỳ bảng nào ở trên."""
    truy_van = " UNION ".join(f"SELECT {cot} AS ma FROM {bang}" for bang, cot in BANG_DU_LIEU_HOC_SINH)
    return {r["ma"] for r in conn.execute(truy_van)}


@router.get("/hoc-sinh")
def danh_sach_hoc_sinh(tim: str | None = Query(None, max_length=100),
                       lop: str | None = Query(None, max_length=20)):
    """Danh sách học sinh. `co_du_lieu` cho biết em đó có bài làm hoặc dữ liệu nên không xóa được."""
    with db.ket_noi() as conn:
        ds = conn.execute("SELECT ma, ho_ten, lop FROM nguoi_dung WHERE vai_tro = 'hoc_sinh'"
                          " ORDER BY lop, ma").fetchall()
        co_du_lieu = _hoc_sinh_co_du_lieu(conn)
        so_ca = {r["nguoi_dung"]: r["n"] for r in conn.execute(
            "SELECT nguoi_dung, COUNT(*) n FROM ca_thi_nguoi_dung WHERE vai_tro_trong_ca = 'hoc_sinh'"
            " GROUP BY nguoi_dung")}
    khoa = (tim or "").strip().casefold()
    return [{**dict(d), "co_du_lieu": d["ma"] in co_du_lieu, "so_ca": so_ca.get(d["ma"], 0)}
            for d in ds
            if (not lop or d["lop"] == lop)
            and (not khoa or khoa in f"{d['ma']} {d['ho_ten']}".casefold())]


@router.post("/hoc-sinh")
def tao_hoc_sinh(body: HocSinhMoi, user: dict = Depends(chi_giao_vien)):
    with db.ket_noi() as conn:
        if conn.execute("SELECT 1 FROM nguoi_dung WHERE ma = ?", (body.ma,)).fetchone():
            raise HTTPException(409, "Mã này đã có trong hệ thống")
        conn.execute("INSERT INTO nguoi_dung (ma, ho_ten, vai_tro, lop, tao_luc) VALUES (?,?,?,?,?)",
                     (body.ma, body.ho_ten, "hoc_sinh", body.lop, db.bay_gio()))
        audit.log(conn, user["ma"], "tao_hoc_sinh", "nguoi_dung", body.ma,
                  after={"ho_ten": body.ho_ten, "lop": body.lop})
    return {"ma": body.ma, "ho_ten": body.ho_ten, "lop": body.lop}


def _lay_hoc_sinh(conn, ma: str):
    hs = conn.execute("SELECT ma, ho_ten, lop FROM nguoi_dung WHERE ma = ? AND vai_tro = 'hoc_sinh'",
                      (ma,)).fetchone()
    if not hs:
        raise HTTPException(404, "Không tìm thấy học sinh")
    return hs


@router.put("/hoc-sinh/{ma}")
def sua_hoc_sinh(ma: str, body: HocSinhSua, user: dict = Depends(chi_giao_vien)):
    with db.ket_noi() as conn:
        truoc = dict(_lay_hoc_sinh(conn, ma))
        conn.execute("UPDATE nguoi_dung SET ho_ten = ?, lop = ? WHERE ma = ?", (body.ho_ten, body.lop, ma))
        audit.log(conn, user["ma"], "sua_hoc_sinh", "nguoi_dung", ma, before=truoc,
                  after={"ma": ma, "ho_ten": body.ho_ten, "lop": body.lop})
    return {"ma": ma, "ho_ten": body.ho_ten, "lop": body.lop}


@router.delete("/hoc-sinh/{ma}")
def xoa_hoc_sinh(ma: str, user: dict = Depends(chi_giao_vien)):
    """Chỉ xóa được học sinh chưa có dữ liệu và chỉ nằm trong các ca còn là bản nháp."""
    with db.ket_noi() as conn:
        truoc = dict(_lay_hoc_sinh(conn, ma))
        dang_trong_ca = conn.execute(
            "SELECT 1 FROM ca_thi_nguoi_dung p JOIN ca_thi c ON c.id = p.ca_thi"
            " WHERE p.nguoi_dung = ? AND c.trang_thai != 'nhap' LIMIT 1", (ma,)).fetchone()
        ly_do = []
        if dang_trong_ca:
            ly_do.append("đang thuộc một ca đã mở hoặc đã đóng")
        if ma in _hoc_sinh_co_du_lieu(conn):
            ly_do.append("đã có bài làm hoặc dữ liệu")
        if ly_do:
            raise HTTPException(409, "Không xóa được vì học sinh " + " và ".join(ly_do) + ".")
        conn.execute("DELETE FROM ma_du_thi WHERE hoc_sinh = ?", (ma,))
        conn.execute("DELETE FROM ca_thi_nguoi_dung WHERE nguoi_dung = ?", (ma,))
        conn.execute("DELETE FROM nguoi_dung WHERE ma = ?", (ma,))
        audit.log(conn, user["ma"], "xoa_hoc_sinh", "nguoi_dung", ma, before=truoc)
    return {"da_xoa": ma}


# --------------------------------------------------------------- nhập danh sách từ CSV hoặc Excel
def _chuan_hoa_tieu_de(chu) -> str:
    chu = unicodedata.normalize("NFD", str(chu or "").strip().lower().replace("đ", "d"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in chu if unicodedata.category(c) != "Mn"))


TEN_COT = {"ma": "ma", "mahocsinh": "ma", "mahs": "ma", "taikhoan": "ma",
           "hoten": "ho_ten", "hovaten": "ho_ten", "ten": "ho_ten",
           "lop": "lop"}


def _doc_bang(ten_tep: str, noi_dung: bytes) -> list[list[str]]:
    """Đọc tệp CSV hoặc xlsx thành các dòng chữ. Mọi lỗi đọc đều thành một thông báo chung."""
    duoi = ten_tep.lower().rsplit(".", 1)[-1] if "." in ten_tep else ""
    if duoi not in ("csv", "xlsx"):
        raise HTTPException(400, "Chỉ nhận tệp Excel (.xlsx) hoặc CSV (.csv).")
    if not noi_dung.strip():
        raise HTTPException(400, "Tệp trống. Thầy cô chọn tệp có dữ liệu.")
    try:
        if duoi == "csv":
            van_ban = noi_dung.decode("utf-8-sig")
            dau_dong = van_ban.splitlines()[0] if van_ban.splitlines() else ""
            phan_cach = max(",;\t", key=dau_dong.count)
            return [[(o or "").strip() for o in dong] for dong in csv.reader(io.StringIO(van_ban), delimiter=phan_cach)]
        from openpyxl import load_workbook
        sach = load_workbook(io.BytesIO(noi_dung), read_only=True, data_only=True)
        try:
            dong = []
            for hang in sach.worksheets[0].iter_rows(values_only=True, max_row=TOI_DA_DONG_NHAP + 2):
                dong.append(["" if o is None else str(o).strip() for o in hang[:6]])
            return dong
        finally:
            sach.close()
    except HTTPException:
        raise
    except Exception:
        logging.getLogger("app").exception("Không đọc được tệp danh sách học sinh %s", ten_tep)
        raise HTTPException(400, "Không đọc được tệp. Thầy cô kiểm tra lại định dạng "
                                 "(CSV lưu dạng UTF-8 hoặc Excel .xlsx) rồi thử lại.")


@router.post("/hoc-sinh/nhap")
async def nhap_hoc_sinh(tep: UploadFile = File(...), ghi: str = Form("0"),
                        user: dict = Depends(chi_giao_vien)):
    """Nhập danh sách học sinh. ghi=0: chỉ kiểm tra và báo lỗi từng dòng; ghi=1: thêm các dòng hợp lệ."""
    bang = _doc_bang(tep.filename or "", await tep.read())
    if not bang or not any(bang[0]):
        raise HTTPException(400, "Tệp thiếu dòng tiêu đề. Dòng đầu cần có các cột Mã, Họ tên và (không bắt buộc) Lớp.")
    cot = {TEN_COT[k]: i for i, o in enumerate(bang[0]) if (k := _chuan_hoa_tieu_de(o)) in TEN_COT}
    thieu = [c for c in ("ma", "ho_ten") if c not in cot]
    if thieu:
        ten_cot = {"ma": "Mã", "ho_ten": "Họ tên"}
        raise HTTPException(400, "Thiếu cột bắt buộc: " + ", ".join(ten_cot[c] for c in thieu) +
                            ". Dòng đầu của tệp cần có các cột Mã, Họ tên và (không bắt buộc) Lớp.")
    dong_du_lieu = [(so_dong, d) for so_dong, d in enumerate(bang[1:], start=2) if any(d)]
    if len(dong_du_lieu) > TOI_DA_DONG_NHAP:
        raise HTTPException(400, f"Tệp có quá {TOI_DA_DONG_NHAP} dòng. Thầy cô chia nhỏ rồi nhập từng phần.")

    lay = lambda d, ten: (d[cot[ten]] if ten in cot and cot[ten] < len(d) else "").strip()
    hop_le, loi, da_thay = [], [], set()
    with db.ket_noi() as conn:
        da_co = {r["ma"] for r in conn.execute("SELECT ma FROM nguoi_dung")}
        for so_dong, d in dong_du_lieu:
            ma = lay(d, "ma")
            try:
                if not MA_HOC_SINH.match(ma):
                    raise ValueError("Mã chỉ gồm chữ, số, gạch nối hoặc gạch dưới, dài 2 đến 20 ký tự")
                if ma in da_thay:
                    raise ValueError("Mã bị trùng ở dòng phía trên trong tệp")
                if ma in da_co:
                    raise ValueError("Mã đã có trong hệ thống")
                ho_ten, lop = _lam_sach_ten(lay(d, "ho_ten"), lay(d, "lop"))
            except ValueError as e:
                loi.append({"dong": so_dong, "ma": ma, "ly_do": str(e)})
                continue
            da_thay.add(ma)
            hop_le.append((ma, ho_ten, lop))
        da_them = 0
        if ghi == "1" and hop_le:
            conn.executemany("INSERT INTO nguoi_dung (ma, ho_ten, vai_tro, lop, tao_luc) VALUES (?,?,'hoc_sinh',?,?)",
                             [(ma, ho_ten, lop, db.bay_gio()) for ma, ho_ten, lop in hop_le])
            da_them = len(hop_le)
            audit.log(conn, user["ma"], "nhap_hoc_sinh", "nguoi_dung", None,
                      after={"tep": (tep.filename or "")[:100], "tong": len(dong_du_lieu),
                             "da_them": da_them, "so_loi": len(loi)})
    return {"tong": len(dong_du_lieu), "hop_le": len(hop_le), "da_them": da_them, "loi": loi}


# ---------------------------------------------------------------------------
# Tổng quan cho giáo viên (Phiếu mục 3)
# ---------------------------------------------------------------------------
@router.get("/tong-quan")
def tong_quan(user: dict = Depends(chi_giao_vien)):
    """Số liệu các ca thầy cô được phân công. Số cảnh báo là dữ liệu máy nên bị khóa đến khi
    thầy cô nộp phán đoán vòng 1 của ca đó, giống mọi chỗ khác (C5)."""
    ca_list = []
    with db.ket_noi() as conn:
        cac_ca = conn.execute(
            "SELECT c.id, c.ten, c.trang_thai, c.muc_giam_sat FROM ca_thi c"
            " JOIN ca_thi_nguoi_dung p ON p.ca_thi = c.id AND p.nguoi_dung = ?"
            " AND p.vai_tro_trong_ca = 'giao_vien' ORDER BY c.id DESC", (user["ma"],)).fetchall()
        for c in cac_ca:
            cid = c["id"]
            dem = lambda sql: conn.execute(sql, (cid,)).fetchone()[0]
            so_hs = dem("SELECT COUNT(*) FROM ca_thi_nguoi_dung WHERE ca_thi=? AND vai_tro_trong_ca='hoc_sinh'")
            da_nop = dem("SELECT COUNT(DISTINCT hoc_sinh) FROM bai_lam WHERE ca_thi=?")
            dang_lam = dem("SELECT COUNT(*) FROM luot_lam_bai l WHERE l.ca_thi=? AND NOT EXISTS ("
                           "SELECT 1 FROM bai_lam b WHERE b.ca_thi=l.ca_thi AND b.hoc_sinh=l.hoc_sinh)"
                           ) if c["trang_thai"] == "mo" else 0
            ho_tro = dem("SELECT COUNT(*) FROM yeu_cau_ho_tro WHERE ca_thi=? AND trang_thai='moi'")
            mo_khoa = c["trang_thai"] == "nhap" or evidence.is_unlocked(conn, cid, user["ma"])
            canh_bao = dem("SELECT COUNT(*) FROM moc_bat_thuong WHERE ca_thi=?") if mo_khoa else None
            ket_luan = {"khong_vi_pham": 0, "can_lam_ro": 0, "vi_pham": 0}
            for r in conn.execute(
                    "SELECT k.trang_thai FROM ket_luan_ho_so k JOIN (SELECT hoc_sinh, MAX(phien_ban) v"
                    " FROM ket_luan_ho_so WHERE ca_thi=? GROUP BY hoc_sinh) l"
                    " ON l.hoc_sinh = k.hoc_sinh AND l.v = k.phien_ban WHERE k.ca_thi=?", (cid, cid)):
                if r["trang_thai"] in ket_luan:
                    ket_luan[r["trang_thai"]] += 1
            ket_luan["chua_ket_luan"] = max(0, da_nop - sum(ket_luan.values()))
            ca_list.append({"id": cid, "ten": c["ten"], "trang_thai": c["trang_thai"],
                            "muc_giam_sat": c["muc_giam_sat"], "so_hoc_sinh": so_hs, "da_nop": da_nop,
                            "dang_lam": dang_lam, "ho_tro_cho": ho_tro, "canh_bao": canh_bao,
                            "ket_luan": ket_luan})
    mo = [c for c in ca_list if c["trang_thai"] == "mo"]
    khoa = [c for c in ca_list if c["canh_bao"] is None]
    xem_duoc = [c for c in ca_list if c["canh_bao"] is not None and c["trang_thai"] != "nhap"]
    # Tổng chỉ cộng các ca đã mở khóa. Chưa có ca nào mở khóa thì không có số nào để hiện:
    # trả None thay vì 0, vì 0 cũng là một thông tin về dữ liệu máy.
    return {"ca_dang_mo": len(mo), "hoc_sinh_dang_thi": sum(c["dang_lam"] for c in mo),
            "ho_tro_cho": sum(c["ho_tro_cho"] for c in ca_list),
            "canh_bao": sum(c["canh_bao"] for c in xem_duoc) if xem_duoc else None,
            "ca_chua_mo_khoa": len(khoa), "ca": ca_list}


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
def xuat_cau_hoi(user: dict = Depends(chi_giao_vien)):
    """Nhật ký hỏi bài của các học sinh thầy cô phụ trách (L3). Dùng cho phụ lục báo cáo."""
    with db.ket_noi() as conn:
        dong = conn.execute(
            "SELECT id, nguoi_dung, mon, chuong, dang_bai, luot, tao_luc,"
            " noi_dung FROM cau_hoi"
            f" WHERE nguoi_dung IN ({access.visible_students_sql()}) ORDER BY id",
            (user.get("lop"), user["ma"])).fetchall()
    return _xuat_csv(
        "nhat-ky-cau-hoi.csv",
        ["Ma", "Hoc sinh", "Mon", "Chuong", "Dang bai", "Luot", "Thoi diem", "Cau hoi"],
        [[d["id"], d["nguoi_dung"], d["mon"], d["chuong"], d["dang_bai"],
          d["luot"], d["tao_luc"], d["noi_dung"]] for d in dong])


@router.get("/xuat/ca-thi/{ca_id}")
def xuat_ca_thi(ca_id: int, user: dict = Depends(chi_giao_vien)):
    """De-identified complete context, one row per student code."""
    evidence.require_evidence_unlocked(ca_id, user)          # C5: assignment + blind round one
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
    evidence.require_evidence_unlocked(ca_id, user)          # C5: assignment + blind round one
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
        for bang in ("bai_lam", "moc_bat_thuong", "luot_lam_bai", "phat_de",
                     "dieu_chinh_bai_thi"):
            cur = conn.execute(f"DELETE FROM {bang} WHERE ca_thi = ?", (ca_id,))
            dem[bang] = cur.rowcount
        dem["phan_doan"] = 0
        audit.log(conn, user["ma"], "xoa_du_lieu_tap_duot", "ca_thi", ca_id, ca_id, after=dem)
    return {"da_xoa": dem}
