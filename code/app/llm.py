"""Lớp gọi mô hình ngôn ngữ.

Cả hệ thống chỉ gọi AI qua đúng một cửa là hàm sinh_cau_tra_loi(). Nhờ vậy
khi muốn đổi nhà cung cấp, đổi mô hình, hay chạy thử không cần mạng, ta chỉ
sửa file này chứ không đụng tới phần còn lại.

Ba chế độ:
  - claude  : gọi thẳng Claude qua thư viện chính thức của Anthropic
  - openai  : gọi bất kỳ máy chủ nào nói chuẩn OpenAI, kể cả proxy chạy nội bộ
  - gia_lap : không gọi mạng, trả lời theo mẫu, dùng để kiểm thử giao diện
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import threading
import urllib.request
import urllib.error

from . import config


class LoiGoiAI(Exception):
    """Lỗi khi gọi mô hình. Tầng trên bắt lỗi này để báo cho học sinh."""


# ---------------------------------------------------------------------------
# Chế độ 1: Claude
# ---------------------------------------------------------------------------
_client_claude = None


def _lay_client_claude():
    """Tạo client một lần rồi dùng lại, tránh mở kết nối mới mỗi câu hỏi."""
    global _client_claude
    if _client_claude is None:
        try:
            import anthropic
        except ImportError as e:
            raise LoiGoiAI(
                "Chưa cài thư viện anthropic. Chạy: pip install anthropic"
            ) from e
        _client_claude = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client_claude


def _goi_claude(system: str, tin_nhan: list[dict]) -> str:
    import anthropic

    client = _lay_client_claude()
    try:
        phan_hoi = client.beta.messages.create(
            model=config.MA_MO_HINH,
            max_tokens=config.SO_TOKEN_TOI_DA,
            # Khối system là phần ít thay đổi nhất giữa các câu hỏi nên ta
            # đánh dấu cho máy chủ nhớ lại, đỡ tốn tiền ở những lượt sau.
            system=[{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=tin_nhan,
            # Mô hình tự quyết định suy nghĩ sâu tới đâu. Mức nỗ lực để ở
            # medium cho câu hỏi bài tập thông thường, đổi được trong .env.
            thinking={"type": "adaptive"},
            output_config={"effort": config.MUC_NO_LUC},
            # Nếu bộ lọc an toàn từ chối, máy chủ tự chuyển sang mô hình khác
            # thay vì trả về lỗi cho học sinh.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise LoiGoiAI("Khóa API không hợp lệ. Kiểm tra lại file .env") from e
    except anthropic.RateLimitError as e:
        raise LoiGoiAI("Hệ thống đang quá tải, em thử lại sau ít phút nhé") from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            raise LoiGoiAI("Máy chủ AI đang gặp sự cố, em thử lại sau nhé") from e
        raise LoiGoiAI(f"Lỗi gọi AI: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LoiGoiAI("Không kết nối được tới máy chủ AI. Kiểm tra mạng.") from e

    # Bộ lọc an toàn có thể từ chối trả lời. Khi đó phản hồi vẫn là 200 nên
    # phải kiểm tra stop_reason trước khi đọc nội dung.
    if phan_hoi.stop_reason == "refusal":
        raise LoiGoiAI("Câu hỏi này hệ thống chưa trả lời được, em hỏi lại cách khác nhé")

    return _gop_text(phan_hoi.content)


def _gop_text(cac_khoi) -> str:
    """Phản hồi gồm nhiều khối. Ta chỉ lấy khối văn bản, bỏ khối suy nghĩ."""
    phan = [k.text for k in cac_khoi if getattr(k, "type", "") == "text"]
    return "\n".join(phan).strip()


# ---------------------------------------------------------------------------
# Chế độ 1b: Claude Code CLI làm backend
#
# Gọi lệnh `claude -p` sẵn có trên máy, dùng đăng nhập Claude Code, không cần
# khóa API trả phí. ĐÂY LÀ ĐIỂM NHẠY CẢM: đầu vào đến từ Internet công khai,
# nên mọi lời gọi đều bị khóa chặt nhiều lớp:
#   - --restricted           : bỏ các tool chạy lệnh hoặc mã (Bash...) và WebFetch
#   - --strict-mcp-config    : bỏ toàn bộ MCP đang cắm trên máy (Gmail, Drive...)
#   - --disallowed-tools ... : cấm thẳng mọi tool đọc ghi file và mạng
#   - --permission-prompts none : mọi yêu cầu quyền đều bị từ chối tự động
#   - chạy ở thư mục sandbox trống, môi trường tối giản, có timeout
#   - giới hạn số tiến trình song song và độ dài đầu vào
# ---------------------------------------------------------------------------
_han_che_song_song = threading.Semaphore(config.CC_SO_LUONG_SONG_SONG)

_TOOL_CAM = ["Bash", "BashOutput", "KillShell", "Edit", "Write", "Read",
             "Glob", "Grep", "WebFetch", "WebSearch", "Task", "NotebookEdit",
             "TodoWrite"]


def _ghep_hoi_thoai(tin_nhan: list[dict]) -> str:
    """Gộp lịch sử hội thoại thành một đoạn văn bản để đưa vào claude -p."""
    dong = []
    for t in tin_nhan:
        vai = "Học sinh" if t.get("role") == "user" else "Thầy cô"
        dong.append(f"{vai}: {t.get('content', '')}")
    return "\n\n".join(dong)


def _goi_claude_code(system: str, tin_nhan: list[dict]) -> str:
    noi_dung = _ghep_hoi_thoai(tin_nhan)
    if len(noi_dung) > config.CC_GIOI_HAN_KY_TU:
        noi_dung = noi_dung[:config.CC_GIOI_HAN_KY_TU]

    config.THU_MUC_CC_SANDBOX.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.CLAUDE_CLI, "-p", "--output-format", "text",
        "--system-prompt", system,
        "--exclude-dynamic-system-prompt-sections",
        "--restricted", "--strict-mcp-config",
        "--permission-mode", "default", "--permission-prompts", "none",
        "--disallowed-tools", *_TOOL_CAM,
    ]
    if config.MO_HINH_CC:
        cmd += ["--model", config.MO_HINH_CC]

    # Môi trường tối giản, chỉ đủ để claude tìm đăng nhập và chạy.
    moi_truong = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "USER": os.environ.get("USER", ""),
    }

    if not _han_che_song_song.acquire(timeout=8):
        raise LoiGoiAI("Hệ thống đang bận, em thử lại sau ít giây nhé")
    try:
        r = subprocess.run(
            cmd, input=noi_dung, text=True, capture_output=True,
            timeout=config.CC_TIMEOUT, cwd=str(config.THU_MUC_CC_SANDBOX),
            env=moi_truong,
        )
    except FileNotFoundError as e:
        raise LoiGoiAI("Trợ giảng chưa sẵn sàng, thầy cô kiểm tra lại máy chủ") from e
    except subprocess.TimeoutExpired as e:
        raise LoiGoiAI("Hệ thống trả lời quá lâu, em thử lại nhé") from e
    finally:
        _han_che_song_song.release()

    if r.returncode != 0:
        raise LoiGoiAI("Hệ thống chưa trả lời được, em thử lại sau nhé")
    out = (r.stdout or "").strip()
    if not out:
        raise LoiGoiAI("Hệ thống chưa trả lời được, em thử lại nhé")
    return out


# ---------------------------------------------------------------------------
# Chế độ 2: máy chủ nói chuẩn OpenAI
# ---------------------------------------------------------------------------
def _goi_openai(system: str, tin_nhan: list[dict]) -> str:
    """Dùng cho API chính thức của OpenAI hoặc proxy nội bộ cùng chuẩn.

    Viết bằng thư viện chuẩn của Python để không phải cài thêm gói nào.
    """
    body = json.dumps({
        "model": config.MA_MO_HINH,
        "max_tokens": config.SO_TOKEN_TOI_DA,
        "messages": [{"role": "system", "content": system}] + tin_nhan,
    }).encode("utf-8")

    req = urllib.request.Request(
        config.OPENAI_BASE_URL.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            kq = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LoiGoiAI(f"Máy chủ AI trả về lỗi {e.code}") from e
    except urllib.error.URLError as e:
        raise LoiGoiAI("Không kết nối được tới máy chủ AI") from e

    try:
        return kq["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise LoiGoiAI("Máy chủ AI trả về dữ liệu không đúng dạng") from e


# ---------------------------------------------------------------------------
# Chế độ 3: giả lập, không cần mạng
# ---------------------------------------------------------------------------
_MAU_GOI_MO = [
    "Trước hết em đọc lại đề và cho thầy cô biết: đề cho những dữ kiện nào, "
    "và yêu cầu tìm cái gì?",
    "Em thử nhớ lại xem dạng bài này thuộc chương nào mình vừa học. "
    "Công thức nào liên quan tới dữ kiện đề cho?",
    "Em đã viết được bước đầu tiên chưa? Viết ra cho thầy cô xem rồi mình đi tiếp nhé.",
    "Gần đúng rồi đấy. Em kiểm tra lại dấu ở bước vừa rồi xem có gì chưa ổn không?",
]


_MAU_DE = """\
MỨC DỄ
1. Một hình trụ có bán kính đáy 3cm và chiều cao 5cm. Tính thể tích.
   Gợi ý: Em viết lại công thức thể tích trước đã.
   Đáp số: 45 pi cm khối

2. Hình trụ có đường kính đáy 8cm, chiều cao 10cm. Tính thể tích.
   Gợi ý: Đề cho đường kính, công thức cần bán kính.
   Đáp số: 160 pi cm khối

MỨC VỪA
3. Thể tích hình trụ là 100 pi cm khối, chiều cao 4cm. Tính bán kính đáy.
   Gợi ý: Thay số vào công thức rồi giải ra bán kính.
   Đáp số: 5cm

4. Hai hình trụ cùng chiều cao, bán kính hơn kém nhau gấp đôi. So sánh thể tích.
   Gợi ý: Bán kính vào công thức ở dạng bình phương.
   Đáp số: Thể tích gấp bốn lần

MỨC KHÓ
5. Hình trụ có diện tích xung quanh 60 pi và thể tích 150 pi. Tìm bán kính và chiều cao.
   Gợi ý: Lập hệ hai phương trình từ hai dữ kiện.
   Đáp số: Bán kính 5cm, chiều cao 6cm

6. Cắt hình trụ bán kính 6cm bằng mặt phẳng song song trục, cách trục 4cm.
   Tính diện tích thiết diện biết chiều cao hình trụ là 10cm.
   Gợi ý: Thiết diện là hình chữ nhật, cần tìm chiều rộng bằng định lý Pytago.
   Đáp số: 40 căn 5 cm vuông
"""


def _goi_gia_lap(system: str, tin_nhan: list[dict]) -> str:
    """Trả lời theo mẫu, nhận biết loại yêu cầu từ lời dặn hệ thống.

    Nhờ phân biệt được hai loại, giáo viên vẫn trình diễn trọn vẹn cả phần hỏi
    bài lẫn phần sinh đề khi chưa cắm khóa API, ví dụ lúc tập thuyết trình.
    """
    dau = "[CHẾ ĐỘ GIẢ LẬP, chưa cấu hình khóa API]"
    if "ra đề luyện tập" in system:
        return f"{dau}\n\n{_MAU_DE}"
    cau_hoi = tin_nhan[-1]["content"] if tin_nhan else ""
    return (
        f"{dau}\n\n{random.choice(_MAU_GOI_MO)}\n\n"
        f"(Câu hỏi nhận được: {cau_hoi[:120]})"
    )


# ---------------------------------------------------------------------------
# Cửa duy nhất mà phần còn lại của hệ thống gọi vào
# ---------------------------------------------------------------------------
def sinh_cau_tra_loi(system: str, tin_nhan: list[dict]) -> str:
    """Nhận lời dặn hệ thống và lịch sử hội thoại, trả về câu trả lời dạng chữ.

    tin_nhan có dạng [{"role": "user"|"assistant", "content": "..."}, ...]
    """
    if config.dang_gia_lap():
        return _goi_gia_lap(system, tin_nhan)
    if config.NHA_CUNG_CAP == "claude_code":
        return _goi_claude_code(system, tin_nhan)
    if config.NHA_CUNG_CAP == "claude":
        return _goi_claude(system, tin_nhan)
    return _goi_openai(system, tin_nhan)


def mo_ta_che_do() -> str:
    """Nhãn trạng thái hiển thị ra giao diện. Giữ trung tính, không nêu tên
    nhà cung cấp hay mô hình."""
    if config.dang_gia_lap():
        return "Chế độ thử (chưa cấu hình)"
    return "Trực tuyến"
