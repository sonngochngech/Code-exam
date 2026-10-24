"""Xác thực và phân quyền cho API.

Bản trước không có xác thực: ai biết đường dẫn cũng gọi được mọi endpoint,
kể cả xóa học liệu hay đọc ảnh bằng chứng. Ở đây thêm một lớp mỏng:

  - Khi đăng nhập thành công, máy chủ cấp một token ngẫu nhiên và nhớ token
    đó ứng với người dùng nào.
  - Mỗi lời gọi API kèm token trong tiêu đề Authorization. Thiếu hoặc sai
    token thì trả 401.
  - Endpoint dành cho giáo viên kiểm tra thêm vai trò, sai thì trả 403.

Token giữ trong bộ nhớ tiến trình. Đủ cho phạm vi một máy chủ của trường; khi
mở rộng có thể thay bằng bảng phiên trong cơ sở dữ liệu mà không đổi phần gọi.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException

from . import db

# token -> thông tin người dùng
_PHIEN: dict[str, dict] = {}


def tao_phien(nguoi_dung: dict, ca_thi: int | None = None) -> str:
    """Cấp token mới cho một người dùng vừa đăng nhập."""
    token = secrets.token_urlsafe(32)
    _PHIEN[token] = {
        "ma": nguoi_dung["ma"],
        "ho_ten": nguoi_dung["ho_ten"],
        "vai_tro": nguoi_dung["vai_tro"],
        "lop": nguoi_dung["lop"],
        "ca_thi": ca_thi,
    }
    return token


def xoa_phien(token: str) -> None:
    _PHIEN.pop(token, None)


def _doc_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    phan = authorization.split(" ", 1)
    if len(phan) == 2 and phan[0].lower() == "bearer":
        return phan[1].strip()
    return authorization.strip()


def nguoi_dung_hien_tai(authorization: str | None = Header(default=None)) -> dict:
    """Phụ thuộc dùng cho endpoint cần đăng nhập, bất kể vai trò."""
    token = _doc_token(authorization)
    nd = _PHIEN.get(token) if token else None
    if not nd:
        raise HTTPException(401, "Cần đăng nhập để dùng chức năng này.")
    return nd


def chi_giao_vien(nd: dict = Depends(nguoi_dung_hien_tai)) -> dict:
    """Phụ thuộc dùng cho endpoint chỉ dành cho giáo viên."""
    if nd.get("vai_tro") != "giao_vien":
        raise HTTPException(403, "Chức năng này dành cho giáo viên.")
    return nd
