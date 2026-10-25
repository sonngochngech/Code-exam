"""Công cụ dòng lệnh để nạp học liệu và tạo dữ liệu mẫu.

Cách dùng:
    python nap_du_lieu.py hoc-lieu data/hoclieu/decuong_toan.docx "Toán"
    python nap_du_lieu.py de-mau
    python nap_du_lieu.py de-ca-mau
    python nap_du_lieu.py xem
"""

import sys
from pathlib import Path

from app import db, rag


def nap_hoc_lieu(duong_dan: str, mon: str) -> None:
    f = Path(duong_dan)
    if not f.exists():
        print(f"Không tìm thấy file: {f}")
        return
    try:
        so = rag.nap_hoc_lieu(f, mon)
    except rag.LoiDinhDang as e:
        print(f"Không nạp được {f.name}: {e}")
        return
    print(f"Đã nạp {so} đoạn từ {f.name} vào môn {mon}.")


def tao_de_mau() -> None:
    """Tạo một đề mười câu và hai ca thi, khớp với thiết kế nghiên cứu.

    Hai ca dùng chung một đề để hai nhóm làm bài tương đương nhau, chỉ khác
    ở chỗ nhóm TN có hệ thống ghi nhận còn nhóm DC thì không.
    """
    cau_hoi = [
        ("Phương trình x bình phương trừ 5x cộng 6 bằng 0 có nghiệm là",
         ["x bằng 2 hoặc x bằng 3", "x bằng 1 hoặc x bằng 6",
          "x bằng âm 2 hoặc x bằng âm 3", "Vô nghiệm"], 0, "Chương IV", "vua"),
        ("Giá trị của biểu thức căn bậc hai của 49 là",
         ["7", "âm 7", "24,5", "Không xác định"], 0, "Chương I", "de"),
        ("Hàm số y bằng 2x cộng 1 có đồ thị là",
         ["Một đường thẳng", "Một parabol", "Một đường tròn", "Một hypebol"],
         0, "Chương II", "de"),
        ("Trong tam giác vuông, bình phương cạnh huyền bằng",
         ["Tổng bình phương hai cạnh góc vuông", "Hiệu bình phương hai cạnh góc vuông",
          "Tích hai cạnh góc vuông", "Nửa tổng hai cạnh góc vuông"], 0,
         "Chương III", "de"),
        ("Phương trình x bình phương cộng mx cộng 1 bằng 0 có nghiệm kép khi",
         ["m bằng 2 hoặc m bằng âm 2", "m bằng 1", "m bằng 0", "Mọi giá trị của m"],
         0, "Chương IV", "kho"),
        ("Cường độ dòng điện qua điện trở 10 ôm dưới hiệu điện thế 20 vôn là",
         ["2 ampe", "0,5 ampe", "200 ampe", "10 ampe"], 0, "Điện học", "de"),
        ("Công suất của thiết bị có hiệu điện thế 220 vôn và dòng điện 2 ampe là",
         ["440 oát", "110 oát", "222 oát", "220 oát"], 0, "Điện học", "vua"),
        ("Hai điện trở 6 ôm và 3 ôm mắc song song có điện trở tương đương là",
         ["2 ôm", "9 ôm", "4,5 ôm", "18 ôm"], 0, "Điện học", "kho"),
        ("Đơn vị đo công của dòng điện là",
         ["Jun", "Oát", "Vôn", "Ampe"], 0, "Điện học", "de"),
        ("Khi tăng hiệu điện thế lên gấp đôi mà giữ nguyên điện trở thì công suất",
         ["Tăng gấp bốn", "Tăng gấp đôi", "Không đổi", "Giảm một nửa"], 0,
         "Điện học", "kho"),
    ]

    with db.ket_noi() as conn:
        if conn.execute("SELECT COUNT(*) c FROM de_thi").fetchone()["c"] > 0:
            print("Đã có đề thi trong cơ sở dữ liệu, bỏ qua bước tạo mẫu.")
            return

        cur = conn.execute(
            "INSERT INTO de_thi (ten, mon, so_phut, tao_luc) VALUES (?,?,?,?)",
            ("Đề kiểm tra khảo sát Toán và Vật lí", "Toán, Vật lí", 30, db.bay_gio()),
        )
        de_id = cur.lastrowid

        import json
        conn.executemany(
            "INSERT INTO cau_trac_nghiem (de_thi, noi_dung, phuong_an, dap_an,"
            " chuong, muc_do) VALUES (?,?,?,?,?,?)",
            [(de_id, nd, json.dumps(pa, ensure_ascii=False), da, ch, md)
             for nd, pa, da, ch, md in cau_hoi],
        )

        for ten, lop, nhom in (("Ca thi lớp 9A", "9A", "TN"),
                               ("Ca thi lớp 9B", "9B", "DC")):
            conn.execute(
                "INSERT INTO ca_thi (de_thi, ten, lop, nhom, tao_luc)"
                " VALUES (?,?,?,?,?)", (de_id, ten, lop, nhom, db.bay_gio()))

    print(f"Đã tạo đề {de_id} gồm {len(cau_hoi)} câu, kèm hai ca thi 9A và 9B.")


# Dữ liệu mẫu cho thử tay: chỉ đề thi và ca thi, không có học sinh, bài làm hay mốc nào.
_QUY_DINH_MAU = ("Được dùng nháp và máy tính cầm tay. Không dùng tài liệu và điện thoại. "
                 "Cần hỗ trợ thì bấm nút Cần hỗ trợ, không tự ý rời chỗ.")
_DE_MAU = [
    ("Toán 9 - Căn bậc hai (10 câu)", "Toán", 30, "Căn bậc hai", [
        ("Căn bậc hai số học của 49 là?", ["5", "6", "7", "8"], 2, "de"),
        ("Giá trị của √((-3)²) là?", ["-3", "3", "9", "0"], 1, "de"),
        ("Biểu thức √(x - 2) xác định khi nào?", ["x ≥ 2", "x > 2", "x ≤ 2", "x ≥ 0"], 0, "vua"),
        ("Rút gọn √12 được kết quả là?", ["2√3", "3√2", "4√3", "6"], 0, "vua"),
        ("Giá trị của √16 · √9 là?", ["12", "7", "25", "144"], 0, "de"),
        ("Giá trị của √50 − √2 là?", ["√48", "4√2", "5√2", "6√2"], 1, "kho"),
        ("Trục căn thức ở mẫu của 1/√2 được?", ["√2/2", "2√2", "1/2", "√2"], 0, "vua"),
        ("So sánh √5 và 2 ta có?", ["√5 > 2", "√5 < 2", "√5 = 2", "Không so sánh được"], 0, "de"),
        ("Giá trị của √25 là?", ["±5", "5", "-5", "25"], 1, "de"),
        ("Tìm x biết √x = 4.", ["16", "8", "4", "2"], 0, "vua"),
    ]),
    ("Toán 9 - Hàm số bậc nhất (6 câu)", "Toán", 20, "Hàm số bậc nhất", [
        ("Hàm số nào sau đây là hàm số bậc nhất?", ["y = 2x + 1", "y = x²", "y = 3/x", "y = 5"], 0, "de"),
        ("Hệ số góc của đường thẳng y = -3x + 2 là?", ["2", "-3", "3", "-2"], 1, "de"),
        ("Đồ thị hàm số y = 2x - 4 cắt trục tung tại điểm nào?", ["(0; -4)", "(2; 0)", "(0; 4)", "(-4; 0)"], 0, "vua"),
        ("Hai đường thẳng y = 2x + 1 và y = 2x - 3 có vị trí tương đối nào?",
         ["Cắt nhau", "Song song", "Trùng nhau", "Vuông góc"], 1, "vua"),
        ("Hàm số y = (m - 1)x + 3 đồng biến khi nào?", ["m > 1", "m < 1", "m = 1", "m > 0"], 0, "vua"),
        ("Đường thẳng đi qua A(1; 3) và có hệ số góc 2 là?",
         ["y = 2x + 1", "y = 2x + 3", "y = x + 2", "y = 3x"], 0, "kho"),
    ]),
    ("Khoa học tự nhiên 9 - Khảo sát nhanh (5 câu)", "Khoa học tự nhiên", 15, "Tổng hợp", [
        ("Đơn vị của cường độ dòng điện là?", ["Vôn", "Ampe", "Ôm", "Oát"], 1, "de"),
        ("Chất nào sau đây là chất tinh khiết?", ["Nước muối", "Không khí", "Nước cất", "Sữa"], 2, "de"),
        ("Bào quan thực hiện quang hợp ở tế bào thực vật là?",
         ["Ti thể", "Lục lạp", "Nhân", "Ribosome"], 1, "vua"),
        ("Công thức tính vận tốc là?", ["v = s/t", "v = s·t", "v = t/s", "v = s + t"], 0, "de"),
        ("Khí nào chiếm tỉ lệ lớn nhất trong không khí?",
         ["Oxi", "Nitơ", "Cacbon đioxit", "Hiđro"], 1, "vua"),
    ]),
]
# (tên ca, chỉ số đề, lớp, mức giám sát, giáo viên tạo, trạng thái, giáo viên thứ hai tham gia)
_CA_MAU = [
    ("Kiểm tra 15 phút - Căn bậc hai (9A)", 0, "9A", "day_du", "gv01", "nhap", False),
    ("Giữa kỳ - Căn bậc hai (9A + 9B)", 0, "9A, 9B", "day_du", "gv01", "mo", True),
    ("Ôn tập - Hàm số bậc nhất (9B)", 1, "9B", "day_du", "gv01", "dong", False),
    ("Khảo sát KHTN - giám sát cơ bản (9A)", 2, "9A", "co_ban", "gv02", "mo", False),
    ("Đối chứng không giám sát - Hàm số (9B)", 1, "9B", "khong", "gv01", "nhap", False),
    ("Ca riêng của gv01 - Căn bậc hai (9B)", 0, "9B", "day_du", "gv01", "mo", False),
]


def tao_de_ca_mau() -> None:
    """Tạo ba đề và sáu ca thi ở các trạng thái khác nhau để thử tay.

    Dùng đúng các hàm của ứng dụng nên dữ liệu có cùng cấu trúc với dữ liệu tạo trên web.
    Cần có sẵn hai giáo viên gv01 và gv02 (tài khoản mẫu). Chạy lại không tạo thêm.
    """
    from app.routers import exam
    from app.services import session_lifecycle

    with db.ket_noi() as conn:
        da_co = conn.execute("SELECT 1 FROM de_thi WHERE ten=?", (_DE_MAU[0][0],)).fetchone()
        thieu = [m for m in ("gv01", "gv02") if not conn.execute(
            "SELECT 1 FROM nguoi_dung WHERE ma=? AND vai_tro='giao_vien'", (m,)).fetchone()]
    if da_co:
        print("Đã có đề mẫu trong cơ sở dữ liệu, bỏ qua bước tạo mẫu.")
        return
    if thieu:
        print("Thiếu tài khoản giáo viên mẫu: " + ", ".join(thieu))
        return

    giao_vien = {"gv01": {"ma": "gv01", "vai_tro": "giao_vien"},
                 "gv02": {"ma": "gv02", "vai_tro": "giao_vien"}}
    ma_de = []
    for ten, mon, so_phut, chuong, cau in _DE_MAU:
        de = exam.DeMoi(ten=ten, mon=mon, so_phut=so_phut, cau_hoi=[
            exam.CauMoi(noi_dung=nd, phuong_an=pa, dap_an=da, chuong=chuong, muc_do=md)
            for nd, pa, da, md in cau])
        ma_de.append(exam.tao_de(de, giao_vien["gv01"])["de_thi"])

    for ten, chi_so_de, lop, muc, nguoi_tao, trang_thai, them_gv in _CA_MAU:
        ca = exam.tao_ca(exam.CaMoi(
            de_thi=ma_de[chi_so_de], ten=ten, lop=lop, muc_giam_sat=muc,
            quy_dinh=_QUY_DINH_MAU, phut_phan_hoi=10080, phut_xu_ly_gv=10080),
            giao_vien[nguoi_tao])["ca_thi"]
        if them_gv:
            exam.tham_gia_ca(ca, giao_vien["gv02"])
        if trang_thai in ("mo", "dong"):
            session_lifecycle.transition(ca, "mo")
        if trang_thai == "dong":
            session_lifecycle.transition(ca, "dong")

    print(f"Đã tạo {len(ma_de)} đề và {len(_CA_MAU)} ca thi mẫu "
          "(nháp, đang mở, đã đóng; có ca của gv02 và ca gv02 tham gia).")


def xem() -> None:
    with db.ket_noi() as conn:
        for bang in ("nguoi_dung", "hoc_lieu", "cau_hoi", "de_thi",
                     "cau_trac_nghiem", "ca_thi", "bai_lam",
                     "moc_bat_thuong", "phan_doan"):
            c = conn.execute(f"SELECT COUNT(*) c FROM {bang}").fetchone()["c"]
            print(f"  {bang:20s} {c:5d}")


def main() -> None:
    db.khoi_tao()
    if len(sys.argv) < 2:
        print(__doc__)
        return
    lenh = sys.argv[1]
    if lenh == "hoc-lieu":
        if len(sys.argv) < 4:
            print('Thiếu tham số. Ví dụ: python nap_du_lieu.py hoc-lieu file.docx "Toán"')
            return
        nap_hoc_lieu(sys.argv[2], sys.argv[3])
    elif lenh == "de-mau":
        tao_de_mau()
    elif lenh == "de-ca-mau":
        tao_de_ca_mau()
    elif lenh == "xem":
        xem()
    else:
        print(f"Không hiểu lệnh: {lenh}")
        print(__doc__)


if __name__ == "__main__":
    main()
