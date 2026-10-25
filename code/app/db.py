"""Lớp cơ sở dữ liệu. Dùng SQLite nên không phải cài thêm máy chủ nào.

Toàn bộ dữ liệu của cả hai hệ thống nằm trong một file duy nhất là
data/hethong.db. Muốn sao lưu thì chỉ cần chép file đó đi.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
-- ============ dùng chung cho cả hai hệ thống ============
CREATE TABLE IF NOT EXISTS nguoi_dung (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ma          TEXT UNIQUE NOT NULL,      -- mã đăng nhập, ví dụ hs001
    ho_ten      TEXT NOT NULL,
    vai_tro     TEXT NOT NULL,             -- hoc_sinh | giao_vien
    lop         TEXT,
    tao_luc     TEXT NOT NULL
);

-- ============ hệ thống 1: AI trợ giảng ============
CREATE TABLE IF NOT EXISTS hoc_lieu (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mon         TEXT NOT NULL,             -- Toán | Vật lí
    chuong      TEXT NOT NULL,
    bai         TEXT NOT NULL,
    dang_bai    TEXT,
    noi_dung    TEXT NOT NULL,
    nguon       TEXT,                      -- tên file gốc
    tao_luc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hoc_lieu_mon ON hoc_lieu(mon);

CREATE TABLE IF NOT EXISTS noi_dung_huong_dan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phien_ban INTEGER UNIQUE NOT NULL,
    noi_dung TEXT NOT NULL,
    cau_hoi TEXT NOT NULL,
    dap_an TEXT NOT NULL,
    video_url TEXT,
    phu_de_url TEXT,
    tao_luc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cau_hoi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nguoi_dung  TEXT NOT NULL,
    mon         TEXT,
    noi_dung    TEXT NOT NULL,
    tra_loi     TEXT,
    chuong      TEXT,                      -- nhãn phân loại tự động
    dang_bai    TEXT,
    luot        INTEGER DEFAULT 1,         -- lượt thứ mấy trong cùng một mạch hỏi
    da_lo_dap_an INTEGER DEFAULT 0,        -- cờ kiểm thử, giáo viên chấm tay
    tao_luc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cau_hoi_nguoi ON cau_hoi(nguoi_dung);
CREATE INDEX IF NOT EXISTS idx_cau_hoi_dang ON cau_hoi(dang_bai);

-- ============ hệ thống 2: giám sát kỳ thi ============
CREATE TABLE IF NOT EXISTS de_thi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ten         TEXT NOT NULL,
    mon         TEXT,
    so_phut     INTEGER NOT NULL DEFAULT 45,
    tao_luc     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cau_trac_nghiem (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    de_thi      INTEGER NOT NULL REFERENCES de_thi(id),
    noi_dung    TEXT NOT NULL,
    phuong_an   TEXT NOT NULL,             -- JSON danh sách phương án
    dap_an      INTEGER NOT NULL,          -- chỉ số phương án đúng
    chuong      TEXT,
    muc_do      TEXT                       -- de | vua | kho
);

CREATE TABLE IF NOT EXISTS ca_thi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    de_thi      INTEGER NOT NULL REFERENCES de_thi(id),
    ten         TEXT NOT NULL,
    lop         TEXT,
    nhom        TEXT NOT NULL,             -- TN (có giám sát) | DC (đối chứng)
    muc_giam_sat TEXT NOT NULL DEFAULT 'day_du',  -- khong | co_ban | day_du
    trang_thai TEXT NOT NULL DEFAULT 'nhap',      -- nhap | mo | dong
    quy_dinh TEXT NOT NULL DEFAULT '',
    phut_phan_hoi INTEGER NOT NULL DEFAULT 60,
    phut_xu_ly_gv INTEGER NOT NULL DEFAULT 1440,
    cho_phep_gia_han INTEGER NOT NULL DEFAULT 1,
    phien_ban_huong_dan INTEGER NOT NULL DEFAULT 1,
    so_ngay_luu_anh INTEGER NOT NULL DEFAULT 30,
    ma_nghien_cuu_cap TEXT,
    giai_doan TEXT,
    ma_phong TEXT,
    bat_dau     TEXT,
    ket_thuc    TEXT,
    tao_luc     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ca_thi_nguoi_dung (
    ca_thi      INTEGER NOT NULL REFERENCES ca_thi(id),
    nguoi_dung  TEXT NOT NULL,
    vai_tro_trong_ca TEXT NOT NULL,         -- hoc_sinh | giao_vien
    PRIMARY KEY (ca_thi, nguoi_dung)
);
CREATE INDEX IF NOT EXISTS idx_phan_cong_nguoi
    ON ca_thi_nguoi_dung(nguoi_dung, ca_thi);

-- ADD-EXAM-CODE: mã đăng nhập ngẫu nhiên theo học sinh và ca thi. Chỉ lưu băm.
CREATE TABLE IF NOT EXISTS ma_du_thi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh TEXT NOT NULL,
    ma_bam TEXT UNIQUE NOT NULL,
    dang_hoat_dong INTEGER NOT NULL DEFAULT 1,
    tao_boi TEXT NOT NULL,
    tao_luc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ma_du_thi_ca_hoc_sinh
    ON ma_du_thi(ca_thi, hoc_sinh, dang_hoat_dong);

CREATE TABLE IF NOT EXISTS cau_hinh_giam_sat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi INTEGER NOT NULL REFERENCES ca_thi(id),
    phien_ban INTEGER NOT NULL,
    giay_roi_khung_hinh REAL NOT NULL,
    giay_nguoi_thu_hai REAL NOT NULL,
    giay_nhin_ra_ngoai REAL NOT NULL,
    giay_chuyen_cua_so REAL NOT NULL,
    nguong_goc_nhin REAL NOT NULL,
    tao_boi TEXT NOT NULL,
    tao_luc TEXT NOT NULL,
    UNIQUE(ca_thi, phien_ban)
);

CREATE TABLE IF NOT EXISTS bai_lam (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi      INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh    TEXT NOT NULL,
    tra_loi     TEXT,                      -- JSON map cau_id -> chi so phuong an
    diem        REAL,
    nop_luc     TEXT,
    tao_luc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bai_lam_ca ON bai_lam(ca_thi);

CREATE TABLE IF NOT EXISTS moc_bat_thuong (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi      INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh    TEXT NOT NULL,
    loai        TEXT NOT NULL,             -- roi_khung_hinh | nguoi_thu_hai |
                                           -- nhin_ra_ngoai | chuyen_cua_so
    giay        REAL NOT NULL,             -- giây thứ mấy kể từ lúc bắt đầu
    keo_dai     REAL,                      -- kéo dài bao lâu
    anh         TEXT,                      -- ảnh bằng chứng dạng base64
    nguong_ap_dung REAL,
    phien_ban_cau_hinh INTEGER,
    tao_luc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moc_ca ON moc_bat_thuong(ca_thi, hoc_sinh);

-- Trạng thái kỹ thuật được lưu riêng, không phải bằng chứng hành vi.
CREATE TABLE IF NOT EXISTS trang_thai_ky_thuat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh TEXT NOT NULL,
    camera INTEGER NOT NULL,
    mo_hinh INTEGER NOT NULL,
    ket_noi INTEGER NOT NULL,
    toan_man_hinh INTEGER NOT NULL,
    chi_tiet TEXT,
    cap_nhat_luc TEXT NOT NULL,
    UNIQUE(ca_thi, hoc_sinh)
);
CREATE INDEX IF NOT EXISTS idx_ky_thuat_ca
    ON trang_thai_ky_thuat(ca_thi, hoc_sinh);

CREATE TABLE IF NOT EXISTS phan_doan (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi      INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh    TEXT NOT NULL,
    giao_vien   TEXT NOT NULL,
    vong        INTEGER NOT NULL,          -- 1 chưa xem dữ liệu, 2 đã xem
    muc_nghi_ngo INTEGER NOT NULL,         -- 0 đến 3
    ghi_chu     TEXT,
    loai_thay_doi TEXT,
    tao_luc     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_phan_doan
    ON phan_doan(ca_thi, hoc_sinh, giao_vien, vong);

CREATE TABLE IF NOT EXISTS ket_luan_ho_so (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh TEXT NOT NULL,
    phien_ban INTEGER NOT NULL,
    trang_thai TEXT NOT NULL,
    can_cu TEXT NOT NULL,
    nguoi_xu_ly TEXT NOT NULL,
    tao_luc TEXT NOT NULL,
    UNIQUE(ca_thi, hoc_sinh, phien_ban)
);
CREATE INDEX IF NOT EXISTS idx_ket_luan_ho_so
    ON ket_luan_ho_so(ca_thi, hoc_sinh, phien_ban);

-- Quy trình liên kết TRƯỚC – TRONG – SAU buổi thi (một phần của giải pháp) --

-- Trước buổi thi: học sinh xem video hướng dẫn, trả lời câu hỏi tình huống
-- rồi xác nhận "đã hiểu và đồng ý". Dùng để thống kê số em đã chuẩn bị.
CREATE TABLE IF NOT EXISTS xac_nhan_truoc_thi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi      INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh    TEXT NOT NULL,
    da_xem_video INTEGER DEFAULT 0,
    da_doc_ban_chu INTEGER DEFAULT 0,     -- M4: đọc bản chữ, tách khỏi xem video
    tra_loi_tinh_huong TEXT,               -- JSON đáp án câu hỏi tình huống
    dong_y      INTEGER DEFAULT 0,         -- đã bấm "Tôi đã hiểu và đồng ý"
    phien_ban_huong_dan INTEGER NOT NULL DEFAULT 1,
    tao_luc     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_xac_nhan_truoc
    ON xac_nhan_truoc_thi(ca_thi, hoc_sinh);

-- Trong buổi thi: học sinh bấm nút hỗ trợ ngay trên trang làm bài. Hệ thống
-- tự ghi mã học sinh, phòng (lớp), thời điểm và nội dung. Giáo viên tiếp nhận,
-- ghi cách xử lí và thời gian gián đoạn; cảnh báo AI không tự động trừ điểm.
CREATE TABLE IF NOT EXISTS yeu_cau_ho_tro (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi      INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh    TEXT NOT NULL,
    lop         TEXT,
    loai        TEXT,                      -- mat_mang | thiet_bi | loi_thoi_gian | xin_ra_ngoai | can_ca_nhan | khac
    noi_dung    TEXT,
    moc_id      INTEGER REFERENCES moc_bat_thuong(id),
    giay_trong_bai REAL,
    trang_thai  TEXT NOT NULL DEFAULT 'moi',   -- moi | dang_xu_ly | xong
    phan_hoi_gv TEXT,
    giay_gian_doan REAL,
    giao_vien   TEXT,
    tao_luc     TEXT NOT NULL,
    xu_ly_luc   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ho_tro_ca ON yeu_cau_ho_tro(ca_thi, trang_thai);

CREATE TABLE IF NOT EXISTS dieu_chinh_bai_thi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh TEXT NOT NULL,
    giao_vien TEXT NOT NULL,
    hanh_dong TEXT NOT NULL,              -- tam_dung | tiep_tuc | them_gio
    so_giay INTEGER NOT NULL DEFAULT 0,
    ly_do TEXT NOT NULL,
    tao_luc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dieu_chinh_bai
    ON dieu_chinh_bai_thi(ca_thi, hoc_sinh, id);

-- FR-043: một yêu cầu hỗ trợ có thể liên kết với nhiều sự kiện (giáo viên gắn thêm).
CREATE TABLE IF NOT EXISTS yeu_cau_ho_tro_moc (
    yeu_cau INTEGER NOT NULL REFERENCES yeu_cau_ho_tro(id),
    moc_id  INTEGER NOT NULL REFERENCES moc_bat_thuong(id),
    giao_vien TEXT NOT NULL,
    tao_luc TEXT NOT NULL,
    PRIMARY KEY (yeu_cau, moc_id)
);

-- Thời điểm học sinh bắt đầu làm bài, do máy chủ ghi để tính đồng hồ và hạn nộp.
CREATE TABLE IF NOT EXISTS luot_lam_bai (
    ca_thi   INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh TEXT NOT NULL,
    bat_dau  TEXT NOT NULL,
    PRIMARY KEY (ca_thi, hoc_sinh)
);

-- C6: lúc đề được phát lần đầu. Chỉ dùng làm mốc dự phòng cho hạn nộp khi học sinh
-- chưa bấm "Bắt đầu"; đồng hồ làm bài vẫn tính từ luot_lam_bai.
CREATE TABLE IF NOT EXISTS phat_de (
    ca_thi   INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh TEXT NOT NULL,
    luc      TEXT NOT NULL,
    tron     INTEGER NOT NULL DEFAULT 1,   -- M2: đề phát lần đầu có trộn không
    PRIMARY KEY (ca_thi, hoc_sinh)
);

-- C4: các bước nâng cấp dữ liệu chỉ chạy một lần, để không làm lại mỗi lần khởi động.
CREATE TABLE IF NOT EXISTS da_di_tru (
    ten TEXT PRIMARY KEY,
    luc TEXT NOT NULL
);

-- Sau buổi thi: trong vòng một giờ, học sinh xem lại những sự kiện được phép
-- tiếp cận và chọn "đồng ý", "không đồng ý" hoặc "cần làm rõ" kèm giải thích.
-- Lựa chọn là phản hồi với mô tả sự kiện, không phải tự nhận hay tự bác bỏ.
CREATE TABLE IF NOT EXISTS phan_hoi_sau_thi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi      INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh    TEXT NOT NULL,
    moc_id      INTEGER,                   -- mốc liên quan; NULL là phản hồi chung
    lua_chon    TEXT NOT NULL,             -- dong_y | khong_dong_y | can_lam_ro
    giai_thich  TEXT,
    tao_luc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_phan_hoi_ca ON phan_hoi_sau_thi(ca_thi, hoc_sinh);

CREATE TABLE IF NOT EXISTS gia_han_phan_hoi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi INTEGER NOT NULL REFERENCES ca_thi(id),
    hoc_sinh TEXT NOT NULL,
    them_phut INTEGER NOT NULL,
    ly_do TEXT NOT NULL,
    giao_vien TEXT NOT NULL,
    tao_luc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gia_han_phan_hoi
    ON gia_han_phan_hoi(ca_thi, hoc_sinh, id);

CREATE TABLE IF NOT EXISTS nhat_ky_kiem_toan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ca_thi INTEGER,
    chu_the TEXT NOT NULL,
    hanh_dong TEXT NOT NULL,
    loai_doi_tuong TEXT NOT NULL,
    ma_doi_tuong TEXT,
    du_lieu_truoc TEXT,
    du_lieu_sau TEXT,
    tao_luc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nhat_ky_ca
    ON nhat_ky_kiem_toan(ca_thi, id);
"""


def bay_gio() -> str:
    """Giờ hiện tại, kèm múi giờ (L10), ví dụ 2026-10-25T08:30:00+07:00."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def hien_tai() -> datetime:
    return datetime.now().astimezone()


def doc_gio(text: str) -> datetime:
    """Đọc một mốc thời gian đã lưu. Bản ghi cũ không có múi giờ được hiểu là giờ của
    máy chủ lúc ghi (L10)."""
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.astimezone()


@contextmanager
def ket_noi():
    """Mở kết nối, tự commit khi xong và tự đóng kể cả khi có lỗi."""
    config.THU_MUC_DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DUONG_DAN_DB)
    conn.row_factory = sqlite3.Row          # cho phép truy cập cột theo tên
    conn.execute("PRAGMA foreign_keys = ON")
    # L6: WAL để người đọc không chặn người ghi; chờ tối đa 10 giây khi khóa bận.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def khoi_tao() -> None:
    """Tạo bảng nếu chưa có, và nạp sẵn vài tài khoản để chạy thử."""
    with ket_noi() as conn:
        conn.executescript(SCHEMA)
        _nang_cap(conn)
        co_nguoi = conn.execute("SELECT COUNT(*) c FROM nguoi_dung").fetchone()["c"]
        if co_nguoi == 0:
            _nap_tai_khoan_mau(conn)
        _bao_dam_huong_dan_mac_dinh(conn)


def _nang_cap(conn) -> None:
    """Thêm cột mới cho cơ sở dữ liệu đã tạo từ trước, không mất dữ liệu cũ."""
    cot = {r["name"] for r in conn.execute("PRAGMA table_info(ca_thi)")}
    if "muc_giam_sat" not in cot:
        conn.execute(
            "ALTER TABLE ca_thi ADD COLUMN muc_giam_sat TEXT NOT NULL DEFAULT 'day_du'")
        # Ca đối chứng cũ không bật camera, giữ nguyên là không giám sát.
        conn.execute("UPDATE ca_thi SET muc_giam_sat = 'khong' WHERE nhom = 'DC'")
    if "trang_thai" not in cot:
        conn.execute("ALTER TABLE ca_thi ADD COLUMN trang_thai TEXT NOT NULL DEFAULT 'nhap'")
        conn.execute("UPDATE ca_thi SET trang_thai='mo' WHERE bat_dau IS NOT NULL")
    if "quy_dinh" not in cot:
        conn.execute("ALTER TABLE ca_thi ADD COLUMN quy_dinh TEXT NOT NULL DEFAULT ''")
    if "phut_phan_hoi" not in cot:
        conn.execute("ALTER TABLE ca_thi ADD COLUMN phut_phan_hoi INTEGER NOT NULL DEFAULT 60")
    if "phut_xu_ly_gv" not in cot:
        conn.execute("ALTER TABLE ca_thi ADD COLUMN phut_xu_ly_gv INTEGER NOT NULL DEFAULT 1440")
    if "cho_phep_gia_han" not in cot:
        conn.execute("ALTER TABLE ca_thi ADD COLUMN cho_phep_gia_han INTEGER NOT NULL DEFAULT 1")
    if "phien_ban_huong_dan" not in cot:
        conn.execute("ALTER TABLE ca_thi ADD COLUMN phien_ban_huong_dan INTEGER NOT NULL DEFAULT 1")
    if "so_ngay_luu_anh" not in cot:
        conn.execute("ALTER TABLE ca_thi ADD COLUMN so_ngay_luu_anh INTEGER NOT NULL DEFAULT 30")
    for ten in ("ma_nghien_cuu_cap", "giai_doan", "ma_phong"):
        if ten not in cot:
            conn.execute(f"ALTER TABLE ca_thi ADD COLUMN {ten} TEXT")
    # One attempt per student and session. Skipped (not deleted) if old data has duplicates.
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_bai_lam_hs ON bai_lam(ca_thi, hoc_sinh)")
    except sqlite3.IntegrityError:
        pass
    cot_xn = {r["name"] for r in conn.execute("PRAGMA table_info(xac_nhan_truoc_thi)")}
    if "phien_ban_huong_dan" not in cot_xn:
        conn.execute("ALTER TABLE xac_nhan_truoc_thi ADD COLUMN phien_ban_huong_dan INTEGER NOT NULL DEFAULT 1")
    cot_pd = {r["name"] for r in conn.execute("PRAGMA table_info(phan_doan)")}
    if "loai_thay_doi" not in cot_pd:
        conn.execute("ALTER TABLE phan_doan ADD COLUMN loai_thay_doi TEXT")
    cot_moc = {r["name"] for r in conn.execute("PRAGMA table_info(moc_bat_thuong)")}
    if "nguong_ap_dung" not in cot_moc:
        conn.execute("ALTER TABLE moc_bat_thuong ADD COLUMN nguong_ap_dung REAL")
    if "phien_ban_cau_hinh" not in cot_moc:
        conn.execute("ALTER TABLE moc_bat_thuong ADD COLUMN phien_ban_cau_hinh INTEGER")
    if "client_moc_id" not in cot_moc:
        conn.execute("ALTER TABLE moc_bat_thuong ADD COLUMN client_moc_id TEXT")
    # M6: trình duyệt gửi lại mốc sau khi mất mạng thì chỉ lưu một bản. Bản ghi cũ
    # và trang cũ không gửi mã nên không bị ràng buộc.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_moc_client ON moc_bat_thuong"
        "(ca_thi, hoc_sinh, client_moc_id) WHERE client_moc_id IS NOT NULL")
    cot_xn = {r["name"] for r in conn.execute("PRAGMA table_info(xac_nhan_truoc_thi)")}
    if "da_doc_ban_chu" not in cot_xn:
        conn.execute("ALTER TABLE xac_nhan_truoc_thi ADD COLUMN da_doc_ban_chu INTEGER DEFAULT 0")
    cot_ht = {r["name"] for r in conn.execute("PRAGMA table_info(yeu_cau_ho_tro)")}
    if "moc_id" not in cot_ht:
        conn.execute("ALTER TABLE yeu_cau_ho_tro ADD COLUMN moc_id INTEGER")
    if "giay_trong_bai" not in cot_ht:
        conn.execute("ALTER TABLE yeu_cau_ho_tro ADD COLUMN giay_trong_bai REAL")
    _gan_phan_cong_ban_dau(conn)


def _gan_phan_cong_ban_dau(conn) -> None:
    """C4: dữ liệu nguyên mẫu cũ chưa có phân công thì gán đúng một lần.

    Gán học sinh cùng lớp và các giáo viên hiện có để không làm hỏng các ca đã tạo
    trước khi có bảng phân công. Trước đây bước này chạy lại mỗi lần khởi động nên
    phân công đã gỡ bị gán lại. Giờ có dấu đã chạy, và bỏ qua nếu bảng đã có dữ liệu.
    """
    ten = "phan_cong_ban_dau"
    if conn.execute("SELECT 1 FROM da_di_tru WHERE ten=?", (ten,)).fetchone():
        return
    if not conn.execute("SELECT 1 FROM ca_thi_nguoi_dung LIMIT 1").fetchone():
        conn.execute(
            "INSERT OR IGNORE INTO ca_thi_nguoi_dung (ca_thi, nguoi_dung, vai_tro_trong_ca)"
            " SELECT c.id, n.ma, 'hoc_sinh' FROM ca_thi c JOIN nguoi_dung n"
            " ON n.vai_tro='hoc_sinh' AND (c.lop IS NULL OR c.lop='' OR n.lop=c.lop)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO ca_thi_nguoi_dung (ca_thi, nguoi_dung, vai_tro_trong_ca)"
            " SELECT c.id, n.ma, 'giao_vien' FROM ca_thi c CROSS JOIN nguoi_dung n"
            " WHERE n.vai_tro='giao_vien'"
        )
    conn.execute("INSERT INTO da_di_tru (ten, luc) VALUES (?,?)", (ten, bay_gio()))


def _nap_tai_khoan_mau(conn) -> None:
    """Hai lớp mười lăm em, cộng hai giáo viên, khớp với thiết kế nghiên cứu."""
    dong = [("gv01", "Cô Nguyễn Thu Thuỷ", "giao_vien", "9A"),
            ("gv02", "Thầy Lê Văn Hải", "giao_vien", "9B")]
    for lop, tien_to in (("9A", "TN"), ("9B", "DC")):
        for i in range(1, 16):
            ma = f"{tien_to}{i:02d}"
            dong.append((ma, f"Học sinh {ma}", "hoc_sinh", lop))
    conn.executemany(
        "INSERT INTO nguoi_dung (ma, ho_ten, vai_tro, lop, tao_luc) VALUES (?,?,?,?,?)",
        [(a, b, c, d, bay_gio()) for a, b, c, d in dong],
    )


def _bao_dam_huong_dan_mac_dinh(conn) -> None:
    if conn.execute("SELECT 1 FROM noi_dung_huong_dan LIMIT 1").fetchone():
        return
    conn.execute(
        "INSERT INTO noi_dung_huong_dan"
        " (phien_ban,noi_dung,cau_hoi,dap_an,video_url,phu_de_url,tao_luc)"
        " VALUES (1,?,?,?,?,?,?)",
        ("Bốn dấu hiệu được ghi theo ngưỡng; chỉ ảnh nhỏ tại sự kiện được gửi. "
         "Cảnh báo không phải kết luận gian lận.",
         "Khi mất mạng hoặc camera lỗi, em nên làm gì?", "b",
         "/static/da2/huong-dan-truoc-thi.mp4",
         "/static/da2/huong-dan-truoc-thi.vi.vtt", bay_gio()),
    )


def lay_nguoi_dung(ma: str):
    with ket_noi() as conn:
        return conn.execute("SELECT * FROM nguoi_dung WHERE ma = ?", (ma,)).fetchone()
