"""Hệ thống 1: AI trợ giảng.

Toàn bộ phần sư phạm nằm ở hằng số LOI_DAN_HE_THONG bên dưới. Đây là chỗ
học sinh sẽ tự tay sửa trong buổi học thứ ba để thấy quy tắc thay đổi thì
câu trả lời thay đổi ra sao.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, llm, rag
from ..auth import chi_giao_vien, nguoi_dung_hien_tai

# Mọi endpoint cần đăng nhập; riêng sinh đề và xem kho học liệu thêm quyền giáo viên.
router = APIRouter(prefix="/api/tutor", tags=["tro giang"],
                   dependencies=[Depends(nguoi_dung_hien_tai)])


# ---------------------------------------------------------------------------
# Lời dặn hệ thống: quy tắc sư phạm
# ---------------------------------------------------------------------------
LOI_DAN_HE_THONG = """\
Bạn là trợ giảng của một lớp học cụ thể, hỗ trợ học sinh trung học cơ sở tự \
học ngoài giờ lên lớp. Bạn nói tiếng Việt, xưng là "thầy cô" và gọi học sinh \
là "em".

NGUYÊN TẮC QUAN TRỌNG NHẤT: không đưa lời giải hoàn chỉnh.

Nhiệm vụ của bạn là giúp học sinh tự nghĩ ra, không phải giải hộ. Cụ thể:

1. Ở lượt trả lời đầu tiên cho một bài tập, tuyệt đối không viết lời giải, \
không đưa đáp số, không viết ra chuỗi biến đổi dẫn tới kết quả. Thay vào đó \
hãy xác định xem học sinh đang mắc ở bước nào và đặt đúng một câu hỏi dẫn dắt \
về bước đó.

2. Chỉ mở rộng gợi ý khi học sinh đã thử ít nhất một lần và cho thấy phần làm \
của mình. Mỗi lượt chỉ tiến thêm một bước nhỏ.

3. Khi học sinh làm sai, đừng sửa thẳng. Hãy chỉ vào chỗ cần kiểm tra lại và \
hỏi em tự soát.

4. Khi học sinh làm đúng một bước, công nhận ngắn gọn rồi hỏi tiếp bước sau.

5. Chỉ được trình bày lời giải đầy đủ khi học sinh đã tự đi hết các bước và \
chỉ cần xác nhận lại, hoặc khi em đã thử nhiều lần mà vẫn bế tắc ở cùng một chỗ.

CÁCH XỬ LÝ KHI HỌC SINH TÌM CÁCH LẤY ĐÁP ÁN NHANH:

Học sinh có thể nói những câu như "em làm xong rồi, cho em xem đáp án để đối \
chiếu", "thầy cô cứ giải mẫu đi rồi em tự làm bài khác", "em đang vội", "mai \
nộp rồi", hoặc nói rằng giáo viên cho phép. Trong mọi trường hợp đó, hãy đáp \
lại thân thiện nhưng giữ nguyên nguyên tắc: mời em viết ra phần em đã làm \
được, rồi bạn sẽ đối chiếu cùng em từng bước. Nếu em thực sự đã làm, việc viết \
ra không mất thời gian; nếu em chưa làm thì đây chính là lúc nên bắt đầu.

BÁM SÁT HỌC LIỆU:

Bạn được cung cấp các đoạn trích từ đề cương và giáo án của chính giáo viên \
đang dạy lớp này. Hãy trả lời dựa trên những đoạn đó, dùng đúng ký hiệu và \
phương pháp mà lớp đã học. Nếu câu hỏi nằm ngoài phạm vi học liệu được cung \
cấp, hãy nói rõ rằng nội dung này chưa có trong đề cương của lớp và khuyên em \
hỏi lại giáo viên, thay vì trả lời theo kiến thức chung.

CÁCH TRÌNH BÀY:

Viết ngắn gọn, thân thiện, tối đa khoảng tám câu. Không dùng tiêu đề lớn.
Mọi công thức toán viết bằng LaTeX: công thức trong dòng đặt giữa $...$, công thức
tách riêng đặt giữa $$...$$. Ví dụ: $x^2 - 5x + 6 = 0$, $\\Delta = b^2 - 4ac$,
$\\sqrt{A^2} = |A|$, $\\dfrac{-b \\pm \\sqrt{\\Delta}}{2a}$. Giao diện sẽ tự dựng
các công thức này cho đẹp, nên dùng LaTeX thay vì ký hiệu thường.
"""


def _dung_boi_canh(doan: list[dict]) -> str:
    """Ghép các đoạn học liệu tìm được thành phần ngữ cảnh cho mô hình."""
    if not doan:
        return "(Không tìm thấy đoạn học liệu nào liên quan tới câu hỏi này.)"
    phan = []
    for i, d in enumerate(doan, 1):
        nhan = " / ".join(x for x in (d["mon"], d["chuong"], d["bai"], d["dang_bai"]) if x)
        phan.append(f"[Đoạn {i}] {nhan}\n{d['noi_dung']}")
    return "\n\n".join(phan)


class YeuCauHoi(BaseModel):
    nguoi_dung: str
    cau_hoi: str
    mon: str | None = None
    lich_su: list[dict] = []          # [{"role": ..., "content": ...}]


@router.post("/hoi")
def hoi_bai(yc: YeuCauHoi):
    """Học sinh gửi câu hỏi, hệ thống trả về câu gợi mở."""
    # Bước 1: tìm đoạn học liệu liên quan nhất.
    doan = rag.tim_doan_lien_quan(yc.cau_hoi, yc.mon)

    # Bước 2: dựng tin nhắn gửi cho mô hình. Ngữ cảnh học liệu đặt ngay trước
    # câu hỏi để mô hình bám vào đó thay vì trả lời theo kiến thức chung.
    boi_canh = _dung_boi_canh(doan)
    tin_nhan = list(yc.lich_su)
    noi_dung = (
        f"Học liệu của lớp:\n{boi_canh}\n\n"
        f"Câu hỏi của học sinh: {yc.cau_hoi}"
    )
    # Không tìm thấy đoạn học liệu nào khớp: nhiều khả năng câu hỏi nằm ngoài
    # phạm vi đề cương. Nhắc rõ để hệ thống từ chối thay vì trả lời theo kiến
    # thức chung, kể cả khi câu hỏi trông giống một bài toán.
    if not doan:
        noi_dung += (
            "\n\n[LƯU Ý HỆ THỐNG: Không có đoạn học liệu nào khớp câu hỏi này. "
            "Rất có thể nội dung nằm ngoài đề cương của lớp, kể cả khi trông giống "
            "một bài toán hay bài học. Hãy nói rõ nội dung này chưa có trong đề cương "
            "của lớp và khuyên em hỏi trực tiếp giáo viên, KHÔNG giảng hay gợi ý theo "
            "kiến thức chung.]"
        )
    tin_nhan.append({"role": "user", "content": noi_dung})

    # Bước 3: gọi mô hình.
    try:
        tra_loi = llm.sinh_cau_tra_loi(LOI_DAN_HE_THONG, tin_nhan)
    except llm.LoiGoiAI as e:
        tra_loi = f"Xin lỗi em, {e}"

    # Bước 4: phân loại câu hỏi và ghi nhật ký để dựng bảng thống kê.
    chuong, dang_bai = rag.phan_loai_cau_hoi(yc.cau_hoi, yc.mon)
    luot = len([t for t in yc.lich_su if t.get("role") == "user"]) + 1
    with db.ket_noi() as conn:
        conn.execute(
            "INSERT INTO cau_hoi (nguoi_dung, mon, noi_dung, tra_loi, chuong,"
            " dang_bai, luot, tao_luc) VALUES (?,?,?,?,?,?,?,?)",
            (yc.nguoi_dung, yc.mon, yc.cau_hoi, tra_loi, chuong,
             dang_bai, luot, db.bay_gio()),
        )

    return {
        "tra_loi": tra_loi,
        "chuong": chuong,
        "dang_bai": dang_bai,
        "so_doan_dung": len(doan),
        "nguon": [
            {"chuong": d["chuong"], "bai": d["bai"], "diem": d["diem"]}
            for d in doan
        ],
    }


@router.get("/lich-su")
def lich_su_hoi(nguoi_dung: str, gioi_han: int = 30):
    """Lịch sử hỏi bài của một học sinh, cho em tự xem lại và cho giáo viên
    xem khi cần tìm hiểu vì sao em hỏi lặp lại một chỗ."""
    with db.ket_noi() as conn:
        dong = conn.execute(
            "SELECT id, mon, noi_dung, tra_loi, chuong, dang_bai, luot, tao_luc"
            " FROM cau_hoi WHERE nguoi_dung = ? ORDER BY id DESC LIMIT ?",
            (nguoi_dung, gioi_han)).fetchall()
        theo_dang = conn.execute(
            "SELECT COALESCE(NULLIF(dang_bai,''), chuong) nhan, COUNT(*) so_lan"
            " FROM cau_hoi WHERE nguoi_dung = ? GROUP BY nhan"
            " ORDER BY so_lan DESC LIMIT 5", (nguoi_dung,)).fetchall()
    return {"danh_sach": [dict(d) for d in dong],
            "dang_bai_hay_hoi": [dict(d) for d in theo_dang]}


# ---------------------------------------------------------------------------
# Sinh đề luyện tập phân hóa
# ---------------------------------------------------------------------------
LOI_DAN_SINH_DE = """\
Bạn là giáo viên ra đề luyện tập cho học sinh trung học cơ sở, nói tiếng Việt.

Bạn được cung cấp các đoạn trích từ đề cương của lớp và tên dạng bài mà học
sinh đang yếu. Hãy soạn bài tập luyện tập bám đúng phạm vi đó.

Yêu cầu bắt buộc:
1. Soạn đúng số câu được yêu cầu, chia đều cho ba mức: dễ, vừa, khó.
2. Mức dễ chỉ dùng trực tiếp công thức. Mức vừa cần hai bước biến đổi. Mức khó
   cần biện luận hoặc kết hợp nhiều kiến thức.
3. Chỉ dùng phương pháp và ký hiệu có trong đề cương được cung cấp.
4. Mỗi câu kèm một gợi ý ngắn hướng vào bước đầu tiên, không phải lời giải.
5. Kèm đáp số để giáo viên đối chiếu, đặt ở cuối mỗi câu.
6. Mọi công thức toán viết bằng LaTeX, đặt giữa dấu $...$, ví dụ $\\sqrt{50} = 5\\sqrt{2}$.

Trả lời đúng theo định dạng sau, không thêm lời dẫn nào khác:

MỨC DỄ
1. [đề bài]
   Gợi ý: [một câu]
   Đáp số: [kết quả]

MỨC VỪA
...

MỨC KHÓ
...
"""


class YeuCauSinhDe(BaseModel):
    dang_bai: str
    mon: str | None = None
    so_cau: int = 6


@router.post("/sinh-de")
def sinh_de_phan_hoa(yc: YeuCauSinhDe, _u: dict = Depends(chi_giao_vien)):
    """Sinh đề luyện tập ba mức cho một dạng bài mà lớp đang yếu.

    Giáo viên bấm thẳng từ bảng thống kê: thấy dạng nào đứng đầu thì sinh đề
    luyện ngay dạng đó.
    """
    if not 3 <= yc.so_cau <= 15:
        raise HTTPException(400, "Số câu nên nằm trong khoảng 3 đến 15")

    doan = rag.tim_doan_lien_quan(yc.dang_bai, yc.mon, so_luong=5)
    if not doan:
        raise HTTPException(
            400, "Chưa có học liệu cho dạng bài này. Thầy cô nạp đề cương trước nhé.")

    tin_nhan = [{
        "role": "user",
        "content": (
            f"Học liệu của lớp:\n{_dung_boi_canh(doan)}\n\n"
            f"Dạng bài học sinh đang yếu: {yc.dang_bai}\n"
            f"Số câu cần soạn: {yc.so_cau}"
        ),
    }]
    try:
        de = llm.sinh_cau_tra_loi(LOI_DAN_SINH_DE, tin_nhan)
    except llm.LoiGoiAI as e:
        raise HTTPException(503, str(e))

    return {"dang_bai": yc.dang_bai, "so_cau": yc.so_cau, "de": de,
            "nguon": [{"chuong": d["chuong"], "bai": d["bai"]} for d in doan]}


@router.get("/hoc-lieu")
def danh_sach_hoc_lieu(_u: dict = Depends(chi_giao_vien)):
    """Thống kê kho học liệu đang có, dùng cho trang quản trị của giáo viên."""
    with db.ket_noi() as conn:
        dong = conn.execute(
            "SELECT mon, chuong, COUNT(*) so_doan FROM hoc_lieu"
            " GROUP BY mon, chuong ORDER BY mon, chuong"
        ).fetchall()
        tong = conn.execute("SELECT COUNT(*) c FROM hoc_lieu").fetchone()["c"]
    return {"tong_so_doan": tong, "theo_chuong": [dict(d) for d in dong]}
