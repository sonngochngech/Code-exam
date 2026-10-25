"""Xử lý học liệu và truy xuất đoạn liên quan tới câu hỏi.

Vì sao không dùng vector database: thuật toán tìm theo từ khóa BM25 chạy ngay
trên máy, không tốn tiền gọi dịch vụ ngoài, và quan trọng nhất là học sinh
đọc hiểu được từng bước nên trình bày được trước hội đồng. Với kho học liệu
cỡ vài chục chương của một trường thì cách này đủ nhanh và đủ chính xác.

BM25 chấm điểm một đoạn theo ba ý:
  1. Từ trong câu hỏi xuất hiện trong đoạn càng nhiều thì điểm càng cao.
  2. Từ hiếm gặp trong toàn kho thì đáng giá hơn từ phổ biến.
  3. Đoạn quá dài bị phạt, tránh việc đoạn dài tự nhiên thắng chỉ vì nhiều chữ.
"""

from __future__ import annotations

import math
import codecs
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

from . import config, db

# Những từ xuất hiện ở mọi nơi, giữ lại chỉ làm nhiễu kết quả.
TU_DUNG = {
    "là", "và", "của", "có", "cho", "các", "một", "những", "này", "đó", "khi",
    "thì", "với", "được", "trong", "ta", "ở", "để", "bằng", "theo", "như",
    "em", "hãy", "cái", "gì", "sao", "ạ", "nhé", "ơi", "thầy", "cô",
}


def bo_dau(s: str) -> str:
    """Bỏ dấu tiếng Việt để câu hỏi gõ không dấu vẫn tìm được."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def tach_tu(s: str) -> list[str]:
    """Hạ chữ thường, bỏ dấu câu, tách theo khoảng trắng, loại từ dừng."""
    s = s.lower()
    s = re.sub(r"[^\w\sÀ-ỹ]", " ", s)
    tu = [t for t in s.split() if t and t not in TU_DUNG and len(t) > 1]
    # giữ cả bản không dấu để khớp được khi học sinh gõ thiếu dấu
    return tu + [bo_dau(t) for t in tu]


# ---------------------------------------------------------------------------
# Đọc file Word
# ---------------------------------------------------------------------------
class LoiDinhDang(ValueError):
    """Tệp không đọc được vì định dạng hoặc nội dung. Câu thông báo đủ an toàn để hiện cho giáo viên."""


GIOI_HAN_GIAI_NEN = 30_000_000        # byte; tệp Word thật hiếm khi vượt vài MB chữ


def doc_van_ban(duong_dan: Path) -> str:
    """Đọc tệp .txt/.md. Nhận UTF-8 (có hoặc không BOM) và UTF-16 có BOM (Notepad chọn "Unicode").

    Bảng mã khác, ví dụ Windows-1258, bị từ chối thay vì đọc lệch: bỏ qua byte lạ sẽ làm mất dấu
    tiếng Việt mà vẫn báo nạp thành công.
    """
    du_lieu = duong_dan.read_bytes()
    try:
        if du_lieu.startswith(codecs.BOM_UTF8):
            return du_lieu[len(codecs.BOM_UTF8):].decode("utf-8")
        if du_lieu.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return du_lieu.decode("utf-16")
        return du_lieu.decode("utf-8")
    except UnicodeDecodeError:
        raise LoiDinhDang("Tệp không phải UTF-8. Thầy cô lưu lại dạng UTF-8 "
                          "(Notepad: Lưu thành, mục Mã hóa chọn UTF-8) rồi nạp lại.") from None


def doc_file_word(duong_dan: Path) -> str:
    """Lấy phần chữ trong file .docx mà không cần cài thư viện ngoài.

    File .docx thực chất là một file nén chứa XML. Ta mở nó ra, đọc
    word/document.xml rồi bóc hết thẻ XML đi là còn lại nội dung.
    """
    with zipfile.ZipFile(duong_dan) as z:
        if z.getinfo("word/document.xml").file_size > GIOI_HAN_GIAI_NEN:      # tệp nén bom
            raise LoiDinhDang("Tệp Word quá lớn khi giải nén, hệ thống không đọc được.")
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"<w:p[ >]", "\n<w:p ", xml)          # mỗi đoạn văn một dòng
    xml = re.sub(r"<w:tab/>", "\t", xml)
    chu = re.sub(r"<[^>]+>", "", xml)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        chu = chu.replace(a, b)
    return "\n".join(d.strip() for d in chu.split("\n") if d.strip())


# ---------------------------------------------------------------------------
# Cắt học liệu thành đoạn và đoán nhãn chương, bài
# ---------------------------------------------------------------------------
MAU_CHUONG = re.compile(r"^(chương|chuong|phần|phan)\s+([IVXLC\d]+)[.:\s]*(.*)$", re.I)
MAU_BAI = re.compile(r"^(bài|bai)\s+(\d+)[.:\s]*(.*)$", re.I)
MAU_DANG = re.compile(r"^(dạng|dang)\s*(\d*)[.:\s]*(.*)$", re.I)


def chia_doan(noi_dung: str, mon: str, nguon: str) -> list[dict]:
    """Cắt văn bản thành các đoạn, mỗi đoạn mang nhãn chương, bài, dạng bài.

    Nhãn được suy ra từ các dòng tiêu đề dạng "Chương I", "Bài 3", "Dạng 2".
    Dòng nào chưa gặp tiêu đề nào thì xếp vào mục chưa phân loại, giáo viên
    sửa lại sau trong trang quản trị.
    """
    chuong, bai, dang = "Chưa phân loại", "Chưa phân loại", ""
    cac_doan: list[dict] = []
    dem = []

    def chot():
        """Gom những dòng đang tích lại thành một hoặc nhiều đoạn."""
        if not dem:
            return
        van_ban = "\n".join(dem).strip()
        dem.clear()
        if not van_ban:
            return
        for phan in _cat_theo_do_dai(van_ban):
            cac_doan.append({
                "mon": mon, "chuong": chuong, "bai": bai,
                "dang_bai": dang, "noi_dung": phan, "nguon": nguon,
            })

    for dong in noi_dung.split("\n"):
        d = dong.strip()
        if not d:
            continue
        if m := MAU_CHUONG.match(d):
            chot()
            chuong = f"Chương {m.group(2)}" + (f": {m.group(3)}" if m.group(3) else "")
            # Sang chương mới thì nhãn bài và dạng bài của chương cũ hết hiệu lực,
            # nếu không xóa thì đoạn đầu chương mới sẽ mang nhãn của chương trước.
            bai, dang = "Chưa phân loại", ""
            continue
        if m := MAU_BAI.match(d):
            chot()
            bai = f"Bài {m.group(2)}" + (f": {m.group(3)}" if m.group(3) else "")
            dang = ""
            continue
        if m := MAU_DANG.match(d):
            chot()
            dang = m.group(3) or f"Dạng {m.group(2)}"
            continue
        dem.append(d)

    chot()
    return cac_doan


def _cat_theo_do_dai(van_ban: str) -> list[str]:
    """Cắt đoạn dài thành nhiều mẩu có gối đầu, để câu bị cắt giữa chừng
    vẫn còn nguyên ngữ cảnh ở mẩu kế tiếp."""
    dai, chong = config.DO_DAI_DOAN, config.DO_CHONG_LAN
    if len(van_ban) <= dai:
        return [van_ban]
    mau, i = [], 0
    while i < len(van_ban):
        mau.append(van_ban[i:i + dai])
        i += dai - chong
    return mau


def nap_hoc_lieu(duong_dan: Path, mon: str) -> int:
    """Đọc một file học liệu và ghi vào cơ sở dữ liệu. Trả về số đoạn đã nạp."""
    if duong_dan.suffix.lower() == ".docx":
        noi_dung = doc_file_word(duong_dan)
    else:
        noi_dung = doc_van_ban(duong_dan)

    cac_doan = chia_doan(noi_dung, mon, duong_dan.name)
    if not cac_doan:
        raise LoiDinhDang("Tệp không có nội dung để nạp.")
    with db.ket_noi() as conn:
        conn.executemany(
            "INSERT INTO hoc_lieu (mon, chuong, bai, dang_bai, noi_dung, nguon, tao_luc)"
            " VALUES (?,?,?,?,?,?,?)",
            [(d["mon"], d["chuong"], d["bai"], d["dang_bai"],
              d["noi_dung"], d["nguon"], db.bay_gio()) for d in cac_doan],
        )
    return len(cac_doan)


# ---------------------------------------------------------------------------
# Tìm đoạn liên quan bằng BM25
# ---------------------------------------------------------------------------
K1 = 1.5    # mức độ coi trọng việc một từ lặp lại nhiều lần
B = 0.75    # mức độ phạt đoạn dài

# Từ xuất hiện ở quá tỉ lệ này của kho được coi là từ nền, không tính khi
# kiểm tra độ liên quan. Giá trị 0,60 chọn bằng cách quét tham số, đo trên bộ
# 38 câu hỏi thật và 12 câu ngoài phạm vi. Trên kho cỡ vài chục đoạn thì cơ chế
# này chưa phát huy tác dụng, nhưng sẽ cần khi kho lớn lên hàng trăm đoạn.
TY_LE_TU_NEN = 0.60


def _tai_kho() -> list[dict]:
    with db.ket_noi() as conn:
        dong = conn.execute(
            "SELECT id, mon, chuong, bai, dang_bai, noi_dung FROM hoc_lieu"
        ).fetchall()
    return [dict(d) for d in dong]


def tim_doan_lien_quan(cau_hoi: str, mon: str | None = None,
                       so_luong: int | None = None) -> list[dict]:
    """Trả về danh sách đoạn học liệu gần nhất với câu hỏi, kèm điểm BM25."""
    so_luong = so_luong or config.SO_DOAN_TRUY_XUAT
    kho = _tai_kho()
    if mon:
        kho = [d for d in kho if d["mon"] == mon]
    if not kho:
        return []

    # Bước 1: tách từ cho mọi đoạn và tính độ dài trung bình.
    tu_doan = [tach_tu(d["noi_dung"]) for d in kho]
    do_dai = [len(t) for t in tu_doan]
    do_dai_tb = sum(do_dai) / len(do_dai) if do_dai else 1

    # Bước 2: đếm xem mỗi từ xuất hiện ở bao nhiêu đoạn, để biết từ nào hiếm.
    so_doan_chua = Counter()
    for t in tu_doan:
        for tu in set(t):
            so_doan_chua[tu] += 1
    N = len(kho)

    # Bước 3: chấm điểm từng đoạn theo công thức BM25.
    tu_hoi = tach_tu(cau_hoi)
    diem = []
    for i, t in enumerate(tu_doan):
        dem = Counter(t)
        s = 0.0
        for tu in tu_hoi:
            if tu not in dem:
                continue
            n = so_doan_chua[tu]
            idf = math.log(1 + (N - n + 0.5) / (n + 0.5))      # từ hiếm, điểm cao
            tf = dem[tu]
            s += idf * tf * (K1 + 1) / (
                tf + K1 * (1 - B + B * do_dai[i] / do_dai_tb)
            )
        diem.append(s)

    # Bước 4: loại những đoạn chỉ khớp hú họa.
    # Vì ta so khớp cả bản bỏ dấu nên một câu ngoài phạm vi, ví dụ "giá vàng hôm
    # nay bao nhiêu", vẫn ăn điểm nhờ trùng những từ phổ thông như "bao nhiêu".
    # Cách chặn: chỉ đếm những từ ĐẶC TRƯNG, tức từ hiếm gặp trong kho. Từ nào
    # xuất hiện ở quá nửa số đoạn thì coi như từ nền, không tính là bằng chứng
    # liên quan. Nhờ vậy "ôm", "delta", "khúc xạ" được tính còn "thế nào" thì không.
    nguong_pho_bien = max(2, int(N * TY_LE_TU_NEN))
    tu_dac_trung = {
        t for t in tu_hoi
        if len(t) >= 3 and 0 < so_doan_chua[t] <= nguong_pho_bien
    }

    def so_tu_khop(i: int) -> int:
        return len(tu_dac_trung & set(tu_doan[i]))

    thu_tu = sorted(range(len(kho)), key=lambda i: diem[i], reverse=True)
    ket_qua = []
    for i in thu_tu[:so_luong]:
        if diem[i] <= 0 or so_tu_khop(i) < config.SO_TU_KHOP_TOI_THIEU:
            continue
        d = dict(kho[i])
        d["diem"] = round(diem[i], 3)
        d["so_tu_khop"] = so_tu_khop(i)
        ket_qua.append(d)
    return ket_qua


def phan_loai_cau_hoi(cau_hoi: str, mon: str | None = None) -> tuple[str, str]:
    """Đoán câu hỏi thuộc chương nào và dạng bài nào.

    Cách làm: lấy đoạn học liệu khớp nhất rồi mượn nhãn của đoạn đó. Đơn giản
    nhưng hiệu quả, vì nếu câu hỏi khớp với một đoạn trong Chương II thì nhiều
    khả năng nó đúng là câu hỏi của Chương II.
    """
    doan = tim_doan_lien_quan(cau_hoi, mon, so_luong=1)
    if not doan:
        return "Chưa phân loại", ""
    return doan[0]["chuong"], doan[0]["dang_bai"] or doan[0]["bai"]
