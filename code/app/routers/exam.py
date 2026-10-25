"""Hệ thống 2, phần nền tảng thi: kho đề, ca thi và bài làm của học sinh."""

from __future__ import annotations

import json
import random
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .. import access, config, db
from ..auth import chi_giao_vien, nguoi_dung_hien_tai
from ..limits import ShortText
from ..services import (attempt_clock, audit, exam_access_codes, feedback_deadlines,
                        monitoring_config, session_lifecycle)

# Mức giám sát của một ca thi. "khong" là đối chứng không camera; "co_ban" là
# giám sát cơ bản, chưa áp năm nguyên tắc (ngưỡng thấp nên báo nhiều, không báo
# trước tiêu chí, giáo viên xem dữ liệu ngay, một vòng phán đoán); "day_du" là
# đã áp đủ năm nguyên tắc. Hai mức co_ban và day_du dùng để so trước và sau.
MUC_GIAM_SAT = ("khong", "co_ban", "day_du")


def _nguong_theo_muc(muc: str) -> dict:
    """Ngưỡng cảnh báo gửi xuống trình duyệt tuỳ mức giám sát.

    Mức cơ bản đặt ngưỡng gần như bằng không nên ghi nhận mọi dao động, dẫn tới
    nhiều báo nhầm. Mức đầy đủ dùng ngưỡng đã hiệu chỉnh để giảm báo nhầm.
    """
    if muc == "co_ban":
        return {"giay_roi_khung_hinh": 0.0, "giay_nhin_ra_ngoai": 0.0,
                "giay_chuyen_cua_so": 0.0, "nguong_goc_nhin": 0.18}
    return {"giay_roi_khung_hinh": config.GIAY_ROI_KHUNG_HINH,
            "giay_nhin_ra_ngoai": config.GIAY_NHIN_RA_NGOAI,
            "giay_chuyen_cua_so": config.GIAY_CHUYEN_CUA_SO,
            "nguong_goc_nhin": config.NGUONG_GOC_NHIN}

# Mọi endpoint cần đăng nhập; phần soạn đề, mở ca và xem kết quả thêm quyền giáo viên.
router = APIRouter(prefix="/api/exam", tags=["ky thi"],
                   dependencies=[Depends(nguoi_dung_hien_tai)])


# ---------------------------------------------------------------------------
# Kho đề
# ---------------------------------------------------------------------------
class CauMoi(BaseModel):
    noi_dung: str = Field(max_length=2_000)
    phuong_an: list[str] = Field(min_length=2, max_length=8)
    dap_an: int = Field(ge=0)        # chỉ số phương án đúng, tính từ 0
    chuong: ShortText | None = None
    muc_do: ShortText = "vua"        # de | vua | kho

    @field_validator("phuong_an")
    @classmethod
    def _phuong_an_ngan(cls, value):
        if any(len(x) > 500 for x in value):
            raise ValueError("Mỗi phương án tối đa 500 ký tự")
        return value

    @model_validator(mode="after")
    def _dap_an_trong_khoang(self):
        if self.dap_an >= len(self.phuong_an):
            raise ValueError("Đáp án phải là một chỉ số nằm trong các phương án")
        return self


class DeMoi(BaseModel):
    ten: str = Field(max_length=200)
    mon: ShortText | None = None
    so_phut: int = Field(default=45, ge=1, le=600)
    cau_hoi: list[CauMoi] = Field(default=[], max_length=200)


@router.post("/de")
def tao_de(de: DeMoi, _u: dict = Depends(chi_giao_vien)):
    with db.ket_noi() as conn:
        cur = conn.execute(
            "INSERT INTO de_thi (ten, mon, so_phut, tao_luc) VALUES (?,?,?,?)",
            (de.ten, de.mon, de.so_phut, db.bay_gio()),
        )
        de_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO cau_trac_nghiem (de_thi, noi_dung, phuong_an, dap_an,"
            " chuong, muc_do) VALUES (?,?,?,?,?,?)",
            [(de_id, c.noi_dung, json.dumps(c.phuong_an, ensure_ascii=False),
              c.dap_an, c.chuong, c.muc_do) for c in de.cau_hoi],
        )
    return {"de_thi": de_id, "so_cau": len(de.cau_hoi)}


@router.get("/de")
def danh_sach_de(_u: dict = Depends(chi_giao_vien)):
    with db.ket_noi() as conn:
        dong = conn.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM cau_trac_nghiem c WHERE c.de_thi = d.id)"
            " so_cau FROM de_thi d ORDER BY d.id DESC"
        ).fetchall()
    return [dict(d) for d in dong]


# ---------------------------------------------------------------------------
# Ca thi
# ---------------------------------------------------------------------------
class CaMoi(BaseModel):
    de_thi: int
    ten: str = Field(max_length=200)
    lop: ShortText | None = None
    muc_giam_sat: ShortText = "day_du"     # khong | co_ban | day_du
    nhom: ShortText | None = None          # tự suy ra từ mức nếu không truyền
    quy_dinh: str = Field(default="", max_length=4_000)
    phut_phan_hoi: int = Field(default=60, le=10_080)
    phut_xu_ly_gv: int = Field(default=1440, le=43_200)
    cho_phep_gia_han: bool = True
    so_ngay_luu_anh: int = Field(default=30, le=3_650)
    ma_nghien_cuu_cap: ShortText | None = None
    giai_doan: ShortText | None = None
    ma_phong: ShortText | None = None


def _tach_lop(nhan: str | None) -> list[str]:
    """F1: "9A, 9B" -> ["9A", "9B"]; bỏ khoảng trắng, bỏ trùng, giữ thứ tự."""
    thu_tu: dict[str, None] = {}
    for phan in re.split(r"[,;]", nhan or ""):
        if phan.strip():
            thu_tu[phan.strip()] = None
    return list(thu_tu)


@router.get("/lop")
def danh_sach_lop(_u: dict = Depends(chi_giao_vien)):
    """F1: các lớp đang có học sinh, để chọn khi tạo ca."""
    with db.ket_noi() as conn:
        rows = conn.execute(
            "SELECT lop, COUNT(*) so_hoc_sinh FROM nguoi_dung"
            " WHERE vai_tro='hoc_sinh' AND lop IS NOT NULL AND lop<>'' GROUP BY lop ORDER BY lop"
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/ca")
def tao_ca(ca: CaMoi, _u: dict = Depends(chi_giao_vien)):
    if ca.phut_phan_hoi <= 0 or ca.phut_xu_ly_gv <= 0 or ca.so_ngay_luu_anh <= 0:
        raise HTTPException(400, "Thời hạn phải lớn hơn 0 phút")
    muc = ca.muc_giam_sat if ca.muc_giam_sat in MUC_GIAM_SAT else "day_du"
    # Giữ nhãn nhóm cho phần so sánh cũ: không giám sát xếp vào đối chứng.
    nhom = ca.nhom or ("DC" if muc == "khong" else "TN")
    cac_lop = _tach_lop(ca.lop)
    with db.ket_noi() as conn:
        co_hs = {r["lop"] for r in conn.execute(
            "SELECT DISTINCT lop FROM nguoi_dung WHERE vai_tro='hoc_sinh'")}
        khong_co = [lop for lop in cac_lop if lop not in co_hs]
        if khong_co:                       # F1: lớp gõ sai thì báo, không tạo ca rỗng trong im lặng
            raise HTTPException(422, "Không có học sinh nào thuộc lớp: " + ", ".join(khong_co))
        cur = conn.execute(
            "INSERT INTO ca_thi (de_thi,ten,lop,nhom,muc_giam_sat,trang_thai,quy_dinh,"
            " phut_phan_hoi,phut_xu_ly_gv,cho_phep_gia_han,so_ngay_luu_anh,"
            " ma_nghien_cuu_cap,giai_doan,ma_phong,tao_luc)"
            " VALUES (?,?,?,?,?,'nhap',?,?,?,?,?,?,?,?,?)",
            (ca.de_thi, ca.ten, ", ".join(cac_lop) or None, nhom, muc, ca.quy_dinh.strip()[:4000],
             ca.phut_phan_hoi, ca.phut_xu_ly_gv, int(ca.cho_phep_gia_han),
             ca.so_ngay_luu_anh, ca.ma_nghien_cuu_cap, ca.giai_doan, ca.ma_phong,
             db.bay_gio()),
        )
        ca_id = cur.lastrowid
        conn.execute(
            "INSERT OR IGNORE INTO ca_thi_nguoi_dung"
            " (ca_thi, nguoi_dung, vai_tro_trong_ca) VALUES (?,?,'giao_vien')",
            (ca_id, _u["ma"]),
        )
        for lop in cac_lop:
            conn.execute(
                "INSERT OR IGNORE INTO ca_thi_nguoi_dung"
                " (ca_thi, nguoi_dung, vai_tro_trong_ca)"
                " SELECT ?, ma, 'hoc_sinh' FROM nguoi_dung"
                " WHERE vai_tro='hoc_sinh' AND lop=?",
                (ca_id, lop),
            )
        so_hoc_sinh = conn.execute(
            "SELECT COUNT(*) n FROM ca_thi_nguoi_dung WHERE ca_thi=? AND vai_tro_trong_ca='hoc_sinh'",
            (ca_id,)).fetchone()["n"]
        monitoring_config.ensure_initial(conn, ca_id, _u["ma"])
    return {"ca_thi": ca_id, "muc_giam_sat": muc, "so_hoc_sinh": so_hoc_sinh}


class SuaCa(BaseModel):
    ten: str = Field(max_length=200)
    lop: ShortText | None = None
    muc_giam_sat: ShortText = "day_du"
    quy_dinh: str = Field(default="", max_length=4_000)
    phut_phan_hoi: int = Field(default=60, le=10_080)
    phut_xu_ly_gv: int = Field(default=1440, le=43_200)
    cho_phep_gia_han: bool = True
    so_ngay_luu_anh: int = Field(default=30, le=3_650)
    ma_nghien_cuu_cap: ShortText | None = None
    giai_doan: ShortText | None = None
    ma_phong: ShortText | None = None


@router.put("/ca/{ca_id}")
def sua_ca(ca_id: int, body: SuaCa, user: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, user, "giao_vien")
    level = body.muc_giam_sat if body.muc_giam_sat in MUC_GIAM_SAT else "day_du"
    return session_lifecycle.update_draft(
        ca_id, body.ten, body.lop, body.quy_dinh, level,
        body.phut_phan_hoi, body.phut_xu_ly_gv, body.cho_phep_gia_han,
        body.so_ngay_luu_anh, body.ma_nghien_cuu_cap, body.giai_doan, body.ma_phong)


class TrangThaiCa(BaseModel):
    trang_thai: str


@router.post("/ca/{ca_id}/trang-thai")
def doi_trang_thai_ca(ca_id: int, body: TrangThaiCa,
                      user: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, user, "giao_vien")
    return session_lifecycle.transition(ca_id, body.trang_thai)


@router.get("/ca")
def danh_sach_ca(user: dict = Depends(nguoi_dung_hien_tai)):
    with db.ket_noi() as conn:
        scoped = user.get("ca_thi")
        dong = conn.execute(
            "SELECT c.*, d.ten ten_de, d.so_phut,"
            " (SELECT COUNT(*) FROM bai_lam b WHERE b.ca_thi=c.id AND b.hoc_sinh=p.nguoi_dung) da_nop,"
            " (SELECT COUNT(*) FROM ca_thi_nguoi_dung h WHERE h.ca_thi=c.id"
            "  AND h.vai_tro_trong_ca='hoc_sinh') so_hoc_sinh,"
            " (SELECT COUNT(*) FROM cau_trac_nghiem q WHERE q.de_thi=c.de_thi) so_cau,"
            " (SELECT COUNT(DISTINCT b2.hoc_sinh) FROM bai_lam b2 WHERE b2.ca_thi=c.id) so_da_nop,"
            " (SELECT COUNT(*) FROM luot_lam_bai l WHERE l.ca_thi=c.id AND c.trang_thai='mo'"
            "  AND NOT EXISTS (SELECT 1 FROM bai_lam b WHERE b.ca_thi=l.ca_thi AND b.hoc_sinh=l.hoc_sinh)"
            " ) dang_lam FROM ca_thi c"
            " JOIN de_thi d ON d.id = c.de_thi"
            " JOIN ca_thi_nguoi_dung p ON p.ca_thi=c.id"
            " WHERE p.nguoi_dung=? AND p.vai_tro_trong_ca=?"
            " AND (? IS NULL OR c.id=?) ORDER BY c.id DESC",
            (user["ma"], user["vai_tro"], scoped, scoped),
        ).fetchall()
    return [dict(d) for d in dong]


@router.get("/ca/tat-ca")
def tat_ca_ca_thi(user: dict = Depends(chi_giao_vien)):
    """F4: mọi giáo viên thấy mọi ca (chỉ thông tin chung, không có dữ liệu máy hay bài làm).
    Muốn thao tác trên ca của người khác thì phải tham gia ca đó."""
    with db.ket_noi() as conn:
        rows = conn.execute(
            "SELECT c.id, c.ten, c.lop, c.trang_thai, d.ten ten_de,"
            " (SELECT COUNT(*) FROM ca_thi_nguoi_dung h WHERE h.ca_thi=c.id"
            "  AND h.vai_tro_trong_ca='hoc_sinh') so_hoc_sinh,"
            " (SELECT group_concat(g.nguoi_dung) FROM ca_thi_nguoi_dung g WHERE g.ca_thi=c.id"
            "  AND g.vai_tro_trong_ca='giao_vien') giao_vien"
            " FROM ca_thi c JOIN de_thi d ON d.id=c.de_thi ORDER BY c.id DESC").fetchall()
        tham_gia = {r["ca_thi"] for r in conn.execute(
            "SELECT ca_thi FROM ca_thi_nguoi_dung WHERE nguoi_dung=? AND vai_tro_trong_ca='giao_vien'",
            (user["ma"],))}
    return [{**dict(r), "giao_vien": (r["giao_vien"] or "").split(",") if r["giao_vien"] else [],
             "da_tham_gia": r["id"] in tham_gia} for r in rows]


@router.post("/ca/{ca_id}/tham-gia")
def tham_gia_ca(ca_id: int, user: dict = Depends(chi_giao_vien)):
    """F4: giáo viên tự thêm mình vào một ca. Cổng bằng chứng vẫn tính theo từng giáo viên."""
    with db.ket_noi() as conn:
        if not conn.execute("SELECT 1 FROM ca_thi WHERE id=?", (ca_id,)).fetchone():
            raise HTTPException(404, "Không tìm thấy ca thi")
        moi = conn.execute(
            "INSERT OR IGNORE INTO ca_thi_nguoi_dung (ca_thi, nguoi_dung, vai_tro_trong_ca)"
            " VALUES (?,?,'giao_vien')", (ca_id, user["ma"])).rowcount
        if moi:
            audit.log(conn, user["ma"], "tham_gia_ca", "ca_thi", str(ca_id), ca_id)
    return {"ca_thi": ca_id, "da_tham_gia": True}


@router.post("/ca/{ca_id}/ma-du-thi/{hoc_sinh}")
def cap_lai_ma_mot_hoc_sinh(ca_id: int, hoc_sinh: str, user: dict = Depends(chi_giao_vien)):
    """F3: học sinh quên mã thì cấp mã mới cho riêng em đó, mã cũ của em đó hết hiệu lực."""
    access.require_session_assignment(ca_id, user, "giao_vien")
    return exam_access_codes.reissue_for_student(ca_id, user["ma"], hoc_sinh)


@router.post("/ca/{ca_id}/ma-du-thi")
def sinh_ma_du_thi(ca_id: int, user: dict = Depends(chi_giao_vien)):
    """Generate/rotate one short login code per assigned student."""
    access.require_session_assignment(ca_id, user, "giao_vien")
    return {"ca_thi": ca_id,
            "ma": exam_access_codes.generate_for_session(ca_id, user["ma"])}


@router.delete("/ca/{ca_id}/ma-du-thi")
def thu_hoi_tat_ca_ma(ca_id: int, user: dict = Depends(chi_giao_vien)):
    """Withdraw every active exam code of the session (Phiếu 3: cấp/thu hồi mã dự thi)."""
    access.require_session_assignment(ca_id, user, "giao_vien")
    return {"ca_thi": ca_id, "so_ma_da_thu_hoi": exam_access_codes.revoke(ca_id, user["ma"])}


@router.delete("/ca/{ca_id}/ma-du-thi/{hoc_sinh}")
def thu_hoi_ma_mot_hoc_sinh(ca_id: int, hoc_sinh: str, user: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, user, "giao_vien")
    return {"ca_thi": ca_id, "hoc_sinh": hoc_sinh,
            "so_ma_da_thu_hoi": exam_access_codes.revoke(ca_id, user["ma"], hoc_sinh)}


@router.get("/nguoi-dung")
def danh_sach_nguoi_dung(_u: dict = Depends(chi_giao_vien)):
    """Minimal account catalogue for the BL-02 assignment form."""
    with db.ket_noi() as conn:
        rows = conn.execute(
            "SELECT ma,ho_ten,vai_tro,lop FROM nguoi_dung ORDER BY vai_tro DESC,ma"
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/ca/{ca_id}/thong-tin-cong-khai")
def thong_tin_cong_khai(ca_id: int, user: dict = Depends(nguoi_dung_hien_tai)):
    """BL-24: inspect criteria and the active, versioned session configuration."""
    access.require_session_assignment(ca_id, user)
    with db.ket_noi() as conn:
        session = conn.execute(
            "SELECT id,ten,muc_giam_sat,quy_dinh,phut_phan_hoi,cho_phep_gia_han"
            " FROM ca_thi WHERE id=?", (ca_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Không tìm thấy ca thi")
        active = monitoring_config.latest(conn, ca_id)
    return {
        "ca_thi": dict(session),
        "bon_tieu_chi": [
            {"ma": "roi_khung_hinh", "ten": "Không có khuôn mặt trong khung hình",
             "nguong_giay": active["giay_roi_khung_hinh"]},
            {"ma": "nguoi_thu_hai", "ten": "Từ hai khuôn mặt trở lên",
             "nguong_giay": active["giay_nguoi_thu_hai"]},
            {"ma": "nhin_ra_ngoai", "ten": "Nhìn ra ngoài màn hình",
             "nguong_giay": active["giay_nhin_ra_ngoai"],
             "nguong_goc_nhin": active["nguong_goc_nhin"]},
            {"ma": "chuyen_cua_so", "ten": "Chuyển cửa sổ hoặc mất tiêu điểm",
             "nguong_giay": active["giay_chuyen_cua_so"]},
        ],
        "cau_hinh_dang_ap_dung": {
            key: active[key] for key in monitoring_config.DEFAULTS | {"phien_ban": 0}
        },
        "ma_nguon": {
            "thu_muc": "code/",
            "tep_khoi_dong": "code/app/main.py",
            "kiem_thu": "code/tests/",
        },
        "tran_gia_han_phut": feedback_deadlines.TRAN_GIA_HAN_PHUT,
        "tuyen_bo": "Cảnh báo chỉ là dữ liệu hỗ trợ; con người ra kết luận cuối cùng.",
        "chinh_sach_nghien_cuu": (
            "Dữ liệu nghiên cứu không dùng để tính điểm chính thức, "
            "đánh giá hạnh kiểm hoặc kỷ luật tự động."
        ),
    }


class PhanCongCa(BaseModel):
    hoc_sinh: list[str] = []
    giao_vien: list[str] = []


@router.get("/ca/{ca_id}/phan-cong")
def lay_phan_cong(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, _u, "giao_vien")
    with db.ket_noi() as conn:
        rows = conn.execute(
            "SELECT nguoi_dung, vai_tro_trong_ca FROM ca_thi_nguoi_dung"
            " WHERE ca_thi=? ORDER BY vai_tro_trong_ca, nguoi_dung", (ca_id,)
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/ca/{ca_id}/phan-cong")
def dat_phan_cong(ca_id: int, body: PhanCongCa,
                  _u: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, _u, "giao_vien")
    with db.ket_noi() as conn:
        session = conn.execute("SELECT trang_thai FROM ca_thi WHERE id=?", (ca_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Không tìm thấy ca thi")
        if session["trang_thai"] != "nhap":
            raise HTTPException(409, "Chỉ phân công khi ca còn là bản nháp")
        requested_students = set(body.hoc_sinh)
        requested_teachers = set(body.giao_vien) | {_u["ma"]}
        valid_students = {row["ma"] for row in conn.execute(
            "SELECT ma FROM nguoi_dung WHERE vai_tro='hoc_sinh'"
        ).fetchall()}
        valid_teachers = {row["ma"] for row in conn.execute(
            "SELECT ma FROM nguoi_dung WHERE vai_tro='giao_vien'"
        ).fetchall()}
        if not requested_students <= valid_students or not requested_teachers <= valid_teachers:
            raise HTTPException(400, "Mã người dùng hoặc vai trò không hợp lệ")
        entries = [(ca_id, code, "hoc_sinh") for code in requested_students]
        entries += [(ca_id, code, "giao_vien") for code in requested_teachers]
        conn.execute("DELETE FROM ca_thi_nguoi_dung WHERE ca_thi=?", (ca_id,))
        conn.executemany(
            "INSERT INTO ca_thi_nguoi_dung"
            " (ca_thi, nguoi_dung, vai_tro_trong_ca) VALUES (?,?,?)", entries
        )
        audit.log(conn, _u["ma"], "doi_phan_cong", "ca_thi", str(ca_id), ca_id,
                  after={"giao_vien": sorted(requested_teachers),
                         "so_hoc_sinh": len(requested_students)})
    return {"da_ghi": len(entries)}


class CauHinhGiamSat(BaseModel):
    giay_roi_khung_hinh: float = 10
    giay_nguoi_thu_hai: float = 3
    giay_nhin_ra_ngoai: float = 8
    giay_chuyen_cua_so: float = 0
    nguong_goc_nhin: float = 0.35


@router.get("/ca/{ca_id}/cau-hinh")
def lay_cau_hinh(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, _u, "giao_vien")
    with db.ket_noi() as conn:
        return monitoring_config.latest(conn, ca_id)


@router.put("/ca/{ca_id}/cau-hinh")
def dat_cau_hinh(ca_id: int, body: CauHinhGiamSat,
                 _u: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, _u, "giao_vien")
    return monitoring_config.create_version(ca_id, _u["ma"], body.model_dump())


def _xep_de(ca_id: int, hoc_sinh: str, cau, tron: bool) -> list[dict]:
    """Thứ tự câu và phương án của một học sinh, dựng từ seed cố định.

    Dùng chung cho việc phát đề và chấm điểm (M2): máy chủ tự dựng lại thứ tự này
    khi chấm, không tin thứ tự do trình duyệt gửi lên.
    """
    rng = random.Random(f"{ca_id}:{hoc_sinh}")      # trộn cố định theo học sinh
    ds = [dict(c) for c in cau]
    for c in ds:
        pa = json.loads(c["phuong_an"])
        thu_tu = list(range(len(pa)))
        if tron:
            rng.shuffle(thu_tu)
        c["phuong_an"] = [pa[i] for i in thu_tu]
        c["anh_xa"] = thu_tu            # vị trí hiển thị -> vị trí gốc
    if tron:
        rng.shuffle(ds)
    return ds


@router.get("/ca/{ca_id}/de")
def lay_de_cho_hoc_sinh(ca_id: int, hoc_sinh: str | None = None,
                        tron: bool = True,
                        nd: dict = Depends(nguoi_dung_hien_tai)):
    """Trả đề cho học sinh làm bài. Không kèm đáp án.

    Thứ tự câu và thứ tự phương án được trộn theo mã học sinh, nên mỗi em
    nhận một thứ tự khác nhau nhưng mở lại trang vẫn giữ nguyên thứ tự cũ.
    """
    hoc_sinh = access.student_code(nd, hoc_sinh)
    access.require_session_assignment(ca_id, nd, "hoc_sinh")
    with db.ket_noi() as conn:
        ca = session_lifecycle.require_open(conn, ca_id)
        if attempt_clock.snapshot(conn, ca_id, hoc_sinh)["da_nop"]:
            raise HTTPException(409, "Em đã nộp bài ca này")
        attempt_clock.note_issued(conn, ca_id, hoc_sinh, tron)       # C6, M2
        de = conn.execute("SELECT * FROM de_thi WHERE id = ?", (ca["de_thi"],)).fetchone()
        cau = conn.execute(
            "SELECT id, noi_dung, phuong_an, chuong, muc_do FROM cau_trac_nghiem"
            " WHERE de_thi = ? ORDER BY id", (ca["de_thi"],)
        ).fetchall()

    ds = _xep_de(ca_id, hoc_sinh, cau, tron)

    muc = ca["muc_giam_sat"] if "muc_giam_sat" in ca.keys() else (
        "day_du" if ca["nhom"] == "TN" else "khong")
    with db.ket_noi() as conn:
        cau_hinh = monitoring_config.latest(conn, ca_id)
    nguong = {key: cau_hinh[key] for key in monitoring_config.DEFAULTS}
    nguong["phien_ban"] = cau_hinh["phien_ban"]
    if muc == "co_ban":
        nguong.update(_nguong_theo_muc(muc))
    return {
        "ca_thi": ca_id,
        "ten_de": de["ten"],
        "so_phut": de["so_phut"],
        "nhom": ca["nhom"],
        "muc_giam_sat": muc,
        "co_giam_sat": muc != "khong",
        "quy_dinh": ca["quy_dinh"],
        "phien_ban_huong_dan": ca["phien_ban_huong_dan"],
        "nguong": nguong,
        "cau_hoi": ds,
    }


# ---------------------------------------------------------------------------
# Nộp bài
# ---------------------------------------------------------------------------
class BaiNop(BaseModel):
    ca_thi: int
    hoc_sinh: str
    tra_loi: dict[str, int]          # {"cau_id": chi_so_phuong_an_da_tron}
    # M2: không còn nhận thứ tự trộn từ trình duyệt. Client cũ vẫn gửi anh_xa thì
    # trường thừa bị bỏ qua; máy chủ tự dựng lại thứ tự từ seed.


@router.post("/nop")
def nop_bai(bai: BaiNop, nd: dict = Depends(nguoi_dung_hien_tai)):
    """Chấm điểm ngay khi nộp. Quy đổi thứ tự đã trộn về đáp án gốc."""
    hoc_sinh = access.student_code(nd, bai.hoc_sinh)
    access.require_session_assignment(bai.ca_thi, nd, "hoc_sinh")
    with db.ket_noi() as conn:
        # One writer at a time so concurrent submissions cannot both insert an attempt.
        conn.execute("BEGIN IMMEDIATE")
        # Open or just-closed, not paused, in time (server-side clock).
        attempt_clock.require_can_submit(conn, bai.ca_thi, hoc_sinh)
        cau = conn.execute(
            "SELECT c.id, c.dap_an, c.phuong_an FROM cau_trac_nghiem c"
            " JOIN ca_thi ca ON ca.de_thi = c.de_thi WHERE ca.id = ? ORDER BY c.id",
            (bai.ca_thi,),
        ).fetchall()
        dap_an_goc = {str(c["id"]): c["dap_an"] for c in cau}

        # A queued final submission may be replayed after the server already accepted it.
        # Return the original result instead of creating a second attempt.
        existing = conn.execute(
            "SELECT diem FROM bai_lam WHERE ca_thi=? AND hoc_sinh=?"
            " ORDER BY id LIMIT 1", (bai.ca_thi, hoc_sinh),
        ).fetchone()
        if existing:
            correct = round(existing["diem"] * len(dap_an_goc) / 10) if dap_an_goc else 0
            return {"so_cau_dung": correct, "tong_so_cau": len(dap_an_goc),
                    "diem": existing["diem"], "da_ton_tai": True}

        # Round one is locked against the set of submitted students; a new attempt
        # afterwards would make the evidence gate unreachable for good.
        attempt_clock.require_round_one_open(conn, bai.ca_thi, hoc_sinh)
        attempt_clock.require_guidance_confirmed(conn, bai.ca_thi, hoc_sinh)
        attempt_clock.start(conn, bai.ca_thi, hoc_sinh)
        issued = conn.execute("SELECT tron FROM phat_de WHERE ca_thi=? AND hoc_sinh=?",
                              (bai.ca_thi, hoc_sinh)).fetchone()
        thu_tu_goc = {str(c["id"]): c["anh_xa"] for c in _xep_de(
            bai.ca_thi, hoc_sinh, cau, bool(issued["tron"]) if issued else True)}
        dung = 0
        for ma_cau, chon in bai.tra_loi.items():
            thu_tu = thu_tu_goc.get(ma_cau)
            if thu_tu is None or not 0 <= chon < len(thu_tu):      # M1
                continue
            if thu_tu[chon] == dap_an_goc[ma_cau]:
                dung += 1

        diem = round(dung / len(dap_an_goc) * 10, 2) if dap_an_goc else 0.0
        conn.execute(
            "INSERT INTO bai_lam (ca_thi, hoc_sinh, tra_loi, diem, nop_luc, tao_luc)"
            " VALUES (?,?,?,?,?,?)",
            (bai.ca_thi, hoc_sinh, json.dumps(bai.tra_loi), diem,
             db.bay_gio(), db.bay_gio()),
        )
    return {"so_cau_dung": dung, "tong_so_cau": len(dap_an_goc), "diem": diem}


@router.get("/ca/{ca_id}/ket-qua")
def ket_qua_ca(ca_id: int, _u: dict = Depends(chi_giao_vien)):
    access.require_session_assignment(ca_id, _u, "giao_vien")
    with db.ket_noi() as conn:
        dong = conn.execute(
            "SELECT hoc_sinh, diem, nop_luc FROM bai_lam WHERE ca_thi = ?"
            " ORDER BY hoc_sinh", (ca_id,)
        ).fetchall()
    return [dict(d) for d in dong]
