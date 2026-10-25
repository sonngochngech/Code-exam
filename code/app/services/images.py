"""Evidence image rules (C3).

The browser sends a tiny jpeg (about 160x120) as a data URL. Anything else is
refused on the way in, and the same check runs on the way out so that a row
stored before this check existed is never handed to a teacher's browser.
"""

import base64
import binascii
import re

from fastapi import HTTPException

# A 160x120 jpeg at quality 0.5 is a few KB; the cap leaves room for a larger
# canvas without allowing a request that bloats the database.
MAX_CHARS = 150_000

_FORM = re.compile(r"^data:image/(jpeg|png);base64,([A-Za-z0-9+/]+={0,2})$")
_MAGIC = {"jpeg": b"\xff\xd8\xff", "png": b"\x89PNG\r\n\x1a\n"}


def safe_data_url(value: str | None) -> str | None:
    """Return the value when it is a well-formed jpeg/png data URL, else None."""
    if not value or len(value) > MAX_CHARS:
        return None
    found = _FORM.match(value)
    if not found:
        return None
    kind, payload = found.groups()
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None
    return value if raw.startswith(_MAGIC[kind]) else None


def require_safe(value: str | None) -> str | None:
    """Validate an incoming image; None means 'no image' and is allowed."""
    if value is None:
        return None
    if safe_data_url(value) is None:
        raise HTTPException(
            400, "Ảnh bằng chứng không hợp lệ: chỉ nhận ảnh jpeg hoặc png nhỏ.")
    return value
