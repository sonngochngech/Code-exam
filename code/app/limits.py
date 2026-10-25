"""Shared input bounds (M5).

The limits are generous for real use and tight enough to stop absurd values from
bloating the database or skewing the numbers: negative or infinite seconds,
multi-megabyte text, a million-minute exam.
"""

from typing import Annotated

from pydantic import Field

# A time within one day, in seconds; NaN and infinity are refused.
Seconds = Annotated[float, Field(ge=0, le=86_400, allow_inf_nan=False)]

# Short free text (a code, a label) and long free text (a reason, a note).
ShortText = Annotated[str, Field(max_length=100)]
LongText = Annotated[str, Field(max_length=2_000)]

# Largest request body accepted by the API, and the larger one for file uploads.
MAX_BODY_BYTES = 1_000_000
MAX_UPLOAD_BYTES = 20_000_000
UPLOAD_PATHS = ("/api/admin/hoc-lieu/nap",)

# Longest single teacher time adjustment, in seconds (three hours).
MAX_EXTRA_SECONDS = 3 * 3600
