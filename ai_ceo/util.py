"""Small shared helpers."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def slugify(text: str, max_len: int = 40) -> str:
    """Filesystem-safe slug. Never empty, bounded length (Windows MAX_PATH)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    text = text[:max_len].rstrip("-")
    return text or "project"


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str, max_len: int) -> str:
    """Strip control characters and bound the length of user-supplied text."""
    return _CONTROL_CHARS.sub("", text).strip()[:max_len]


def truncate(text: str, max_chars: int, marker: str = "\n... [truncated] ...\n") -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    tail = max_chars - head - len(marker)
    return text[:head] + marker + text[-max(tail, 0):]
