"""The common issue shape every verifier reports."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Issue:
    severity: str  # error | warning (tests); critical | high | medium | low | info (security); blocker | major | minor (review)
    category: str
    message: str
    file: str = ""
    line: int = 0
    source: str = ""  # static | runtime | scenario | api | security | review | ceo
    evidence: str = ""
    suggestion: str = ""

    @property
    def fingerprint(self) -> str:
        raw = f"{self.source}|{self.category}|{self.file}|{self.message}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fingerprint"] = self.fingerprint
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Issue:
        return Issue(**{k: d.get(k, "" if k != "line" else 0) for k in Issue.__dataclass_fields__})


BLOCKING_SEVERITIES = {"error", "critical", "high", "blocker", "major"}


def is_blocking(issue: Issue | dict[str, Any]) -> bool:
    sev = issue.severity if isinstance(issue, Issue) else issue.get("severity", "")
    return sev in BLOCKING_SEVERITIES
