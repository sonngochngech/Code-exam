"""Cấu hình toàn hệ thống, đọc từ biến môi trường hoặc file .env.

Mọi thứ có thể thay đổi giữa máy phát triển và máy chủ thật đều nằm ở đây,
không rải rác trong code. Muốn đổi mô hình AI hay đổi nhà cung cấp thì chỉ
sửa file .env, không phải sửa một dòng mã nào.
"""

import os
from pathlib import Path

GOC = Path(__file__).resolve().parent.parent          # thư mục code/
THU_MUC_DATA = GOC / "data"
THU_MUC_HOC_LIEU = Path(os.environ.get("THU_MUC_HOC_LIEU") or THU_MUC_DATA / "hoclieu")   # e2e dùng thư mục tạm
THU_MUC_WEB = GOC / "web"


def _doc_env_file() -> None:
    """Đọc file .env nếu có. Viết tay để không cần thêm thư viện ngoài."""
    f = GOC / ".env"
    if not f.exists():
        return
    for dong in f.read_text(encoding="utf-8").splitlines():
        dong = dong.strip()
        if not dong or dong.startswith("#") or "=" not in dong:
            continue
        ten, gia_tri = dong.split("=", 1)
        ten, gia_tri = ten.strip(), gia_tri.strip().strip('"').strip("'")
        # biến đã đặt sẵn trong môi trường thì được ưu tiên hơn file .env
        os.environ.setdefault(ten, gia_tri)


_doc_env_file()


def _lay(ten: str, mac_dinh: str = "") -> str:
    return os.environ.get(ten, mac_dinh)


# In production, point this file at an encrypted school-managed volume.
DUONG_DAN_DB = Path(_lay("DUONG_DAN_DB", str(THU_MUC_DATA / "hethong.db")))
BAT_BUOC_HTTPS = _lay("BAT_BUOC_HTTPS", "0") == "1"


# ---------------------------------------------------------------- mô hình AI
# Mặc định dùng Claude. Nếu trường muốn đổi sang nhà cung cấp khác thì đặt
# NHA_CUNG_CAP=openai và điền OPENAI_BASE_URL, hệ thống vẫn chạy bình thường.
NHA_CUNG_CAP = _lay("NHA_CUNG_CAP", "claude").lower()

# Khóa API. Để trống thì hệ thống tự chạy ở chế độ giả lập, vẫn thử được
# toàn bộ luồng mà không tốn tiền.
ANTHROPIC_API_KEY = _lay("ANTHROPIC_API_KEY")
OPENAI_API_KEY = _lay("OPENAI_API_KEY")
OPENAI_BASE_URL = _lay("OPENAI_BASE_URL", "https://api.openai.com/v1")

# Chế độ dùng chính Claude Code CLI làm backend, không cần khóa API trả phí.
# Dùng đăng nhập Claude Code sẵn có trên máy chủ. Mọi lời gọi đều cô lập:
# bỏ tool chạy lệnh, bỏ MCP, chạy ở thư mục sandbox trống.
CLAUDE_CLI = _lay("CLAUDE_CLI", "claude")
MO_HINH_CC = _lay("MO_HINH_CC", "")              # để trống thì dùng model mặc định của Claude Code
CC_TIMEOUT = int(_lay("CC_TIMEOUT", "120"))      # giây, tối đa chờ một câu trả lời
CC_SO_LUONG_SONG_SONG = int(_lay("CC_SO_LUONG_SONG_SONG", "3"))  # số tiến trình chạy cùng lúc
CC_GIOI_HAN_KY_TU = int(_lay("CC_GIOI_HAN_KY_TU", "4000"))       # chặn đầu vào quá dài
THU_MUC_CC_SANDBOX = GOC / ".cc_sandbox"         # thư mục trống để chạy claude, không chứa gì nhạy cảm

# Mã mô hình. Xem ghi chú về chi phí trong file .env.example.
MA_MO_HINH = _lay("MA_MO_HINH", "claude-opus-5-5")
MUC_NO_LUC = _lay("MUC_NO_LUC", "medium")   # low | medium | high | xhigh | max
SO_TOKEN_TOI_DA = int(_lay("SO_TOKEN_TOI_DA", "2000"))

# ------------------------------------------------------------------- học liệu
# Số đoạn học liệu lấy ra cho mỗi câu hỏi. Lấy nhiều thì câu trả lời đầy đủ
# hơn nhưng tốn token hơn và dễ lạc đề.
SO_DOAN_TRUY_XUAT = int(_lay("SO_DOAN_TRUY_XUAT", "4"))
# Số từ có nghĩa tối thiểu phải khớp thì đoạn mới được coi là liên quan.
# Hạ xuống 1 thì bắt được nhiều hơn nhưng câu hỏi ngoài chương trình cũng lọt.
SO_TU_KHOP_TOI_THIEU = int(_lay("SO_TU_KHOP_TOI_THIEU", "3"))
DO_DAI_DOAN = int(_lay("DO_DAI_DOAN", "900"))        # số ký tự mỗi đoạn
DO_CHONG_LAN = int(_lay("DO_CHONG_LAN", "150"))      # phần gối đầu giữa hai đoạn

# ------------------------------------------------------------------- giám sát
# Ngưỡng cảnh báo của hệ thống giám sát kỳ thi. Đây là những con số học sinh
# sẽ tự tay chỉnh trong buổi học thứ ba để thấy đánh đổi giữa báo nhầm và bỏ sót.
GIAY_ROI_KHUNG_HINH = float(_lay("GIAY_ROI_KHUNG_HINH", "2.0"))
GIAY_NHIN_RA_NGOAI = float(_lay("GIAY_NHIN_RA_NGOAI", "3.0"))
GIAY_CHUYEN_CUA_SO = float(_lay("GIAY_CHUYEN_CUA_SO", "1.0"))
NGUONG_GOC_NHIN = float(_lay("NGUONG_GOC_NHIN", "0.35"))   # tỉ lệ lệch tâm mắt

# -------------------------------------------------------------------- hệ thống
CONG = int(_lay("CONG", "8000"))
CHE_DO_GO_LOI = _lay("CHE_DO_GO_LOI", "1") == "1"


def dang_gia_lap() -> bool:
    """Trả về True khi chưa cấu hình khóa API, hệ thống chạy chế độ giả lập."""
    if NHA_CUNG_CAP == "claude_code":
        return False                 # dùng Claude Code CLI, không cần khóa API
    if NHA_CUNG_CAP == "claude":
        return not ANTHROPIC_API_KEY
    return not OPENAI_API_KEY
