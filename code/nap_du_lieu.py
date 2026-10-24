"""Công cụ dòng lệnh để nạp học liệu và tạo dữ liệu mẫu.

Cách dùng:
    python nap_du_lieu.py hoc-lieu data/hoclieu/decuong_toan.docx "Toán"
    python nap_du_lieu.py de-mau
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
    so = rag.nap_hoc_lieu(f, mon)
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
    elif lenh == "xem":
        xem()
    else:
        print(f"Không hiểu lệnh: {lenh}")
        print(__doc__)


if __name__ == "__main__":
    main()
