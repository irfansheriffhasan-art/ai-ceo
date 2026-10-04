"""Prompt templates.

Each ``*.md`` file holds a system prompt and a user prompt separated by a
line containing only ``---USER---``. Placeholders are ``{{name}}``; a
missing variable raises immediately so template bugs surface in tests,
not as silently degraded prompts.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent
_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_SEPARATOR = "---USER---"


@lru_cache
def _load(name: str) -> tuple[str, str]:
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    if _SEPARATOR not in text:
        raise ValueError(f"prompt {name} has no {_SEPARATOR} separator")
    system, user = text.split(_SEPARATOR, 1)
    return system.strip(), user.strip()


def _fill(template: str, values: dict[str, object], name: str) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"prompt {name!r} needs variable {key!r}")
        return str(values[key])

    out = _VAR.sub(sub, template)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def render(name: str, **values: object) -> tuple[str, str]:
    """Return (system, user) for prompt ``name``."""
    system, user = _load(name)
    return _fill(system, values, name), _fill(user, values, name)


def available() -> list[str]:
    return sorted(p.stem for p in _DIR.glob("*.md"))
