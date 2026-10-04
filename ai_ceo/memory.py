"""Shared project memory.

Agents write durable facts here (requirements, architecture, decisions,
bugs, test results, file ownership, user feedback) and read a compact
``brief()`` instead of re-deriving context on every call. The brief is
size-bounded because small local models have small context windows.
"""

from __future__ import annotations

from typing import Any

from .db import Store
from .util import new_id, truncate


class MemoryKind:
    OBJECTIVE = "objective"
    REQUIREMENTS = "requirements"
    STRATEGY = "strategy"
    PLAN = "plan"
    ARCHITECTURE = "architecture"
    DESIGN = "design"
    DECISION = "decision"
    CONSTRAINT = "constraint"
    PREFERENCE = "preference"
    BUG = "bug"
    TEST_RESULT = "test_result"
    TEST_PLAN = "test_plan"
    FILE = "file"
    STATE = "state"


class ProjectMemory:
    def __init__(self, store: Store, project_id: str):
        self.store = store
        self.project_id = project_id

    # ---- primitives ------------------------------------------------------------
    def set(self, kind: str, key: str, value: Any, source: str = "system") -> None:
        self.store.upsert_memory(self.project_id, kind, key, value, source)

    def get(self, kind: str, key: str, default: Any = None) -> Any:
        item = self.store.get_memory(self.project_id, kind, key)
        return default if item is None else item.value

    def items(self, kind: str) -> list[dict[str, Any]]:
        return [i.to_dict() for i in self.store.list_memory(self.project_id, kind)]

    def values(self, kind: str) -> list[Any]:
        return [i.value for i in self.store.list_memory(self.project_id, kind)]

    def all(self) -> list[dict[str, Any]]:
        return [i.to_dict() for i in self.store.list_memory(self.project_id)]

    # ---- typed helpers ---------------------------------------------------------
    def record_decision(self, decision: str, rationale: str, by: str) -> None:
        self.set(MemoryKind.DECISION, new_id(), {"decision": decision, "rationale": rationale, "by": by}, by)

    def add_preference(self, text: str) -> None:
        self.set(MemoryKind.PREFERENCE, new_id(), text, "user")

    def add_constraint(self, text: str, source: str = "ceo") -> None:
        existing = set(self.values(MemoryKind.CONSTRAINT))
        if text not in existing:
            self.set(MemoryKind.CONSTRAINT, new_id(), text, source)

    @property
    def requirements(self) -> dict[str, Any]:
        return self.get(MemoryKind.REQUIREMENTS, "spec", {}) or {}

    @property
    def architecture(self) -> dict[str, Any]:
        return self.get(MemoryKind.ARCHITECTURE, "spec", {}) or {}

    @property
    def design(self) -> dict[str, Any]:
        return self.get(MemoryKind.DESIGN, "spec", {}) or {}

    @property
    def strategy(self) -> dict[str, Any]:
        return self.get(MemoryKind.STRATEGY, "plan", {}) or {}

    def file_owner(self, path: str) -> str | None:
        for f in self.architecture.get("files", []):
            if f.get("path") == path:
                return f.get("owner_role")
        return None

    def acceptance_criteria(self) -> list[str]:
        return list(self.requirements.get("acceptance_criteria", []))

    # ---- context brief ---------------------------------------------------------
    def brief(self, max_chars: int = 3000, include: tuple[str, ...] = ("all",)) -> str:
        """A compact, human-readable summary of what the company knows so far."""
        want = (lambda k: True) if "all" in include else (lambda k: k in include)
        parts: list[str] = []

        objective = self.get(MemoryKind.OBJECTIVE, "main")
        if objective and want("objective"):
            parts.append(f"OBJECTIVE: {objective.get('objective', '')}")
            if objective.get("app_type"):
                parts.append(f"APP TYPE: {objective['app_type']}")

        constraints = self.values(MemoryKind.CONSTRAINT)
        if constraints and want("constraints"):
            parts.append("CONSTRAINTS:\n" + "\n".join(f"- {c}" for c in constraints[:8]))

        prefs = self.values(MemoryKind.PREFERENCE)
        if prefs and want("preferences"):
            parts.append("USER FEEDBACK (highest priority):\n" + "\n".join(f"- {p}" for p in prefs[-6:]))

        req = self.requirements
        if req and want("requirements"):
            feats = req.get("features", [])
            lines = [f"- [{f.get('priority', 'must')}] {f.get('name')}: {f.get('description', '')}" for f in feats[:10]]
            parts.append("FEATURES:\n" + "\n".join(lines))
            ac = req.get("acceptance_criteria", [])
            if ac:
                parts.append("ACCEPTANCE CRITERIA:\n" + "\n".join(f"- {c}" for c in ac[:10]))

        arch = self.architecture
        if arch and want("architecture"):
            stack = arch.get("stack", {})
            parts.append(
                "ARCHITECTURE: "
                + ", ".join(f"{k}={v}" for k, v in stack.items() if v)
                + f"; backend={'yes' if arch.get('needs_backend') else 'no'}"
            )
            files = arch.get("files", [])
            if files:
                parts.append(
                    "FILES:\n" + "\n".join(f"- {f['path']} ({f.get('owner_role')}): {f.get('purpose', '')}" for f in files)
                )
            endpoints = arch.get("api_endpoints", [])
            if endpoints:
                parts.append(
                    "API:\n" + "\n".join(f"- {e.get('method')} {e.get('path')}: {e.get('description', '')}" for e in endpoints[:10])
                )

        decisions = self.values(MemoryKind.DECISION)
        if decisions and want("decisions"):
            parts.append("DECISIONS:\n" + "\n".join(f"- {d.get('decision')}" for d in decisions[-6:]))

        bugs = [b for b in self.values(MemoryKind.BUG) if b.get("status") == "open"]
        if bugs and want("bugs"):
            parts.append("OPEN BUGS:\n" + "\n".join(f"- {b.get('message')}" for b in bugs[:8]))

        return truncate("\n\n".join(parts), max_chars)
