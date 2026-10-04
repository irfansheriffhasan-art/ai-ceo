"""Live agent status for the Agent Monitor."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..states import AgentStatus

if TYPE_CHECKING:
    from ..agents import AgentRegistry
    from ..events import EventBus


@dataclass
class _Active:
    task_id: str
    task_title: str
    project_id: str
    started: float
    attempt: int
    tokens: int = 0


@dataclass
class _AgentState:
    role: str
    active: dict[str, _Active] = field(default_factory=dict)
    retrying: bool = False
    last_error: str = ""
    last_summary: str = ""
    last_activity: float = 0.0
    completed: int = 0
    failed: int = 0


class AgentTracker:
    def __init__(self, registry: AgentRegistry, events: EventBus):
        self.registry = registry
        self.events = events
        self._states = {role: _AgentState(role) for role in registry.roles()}

    def _state(self, role: str) -> _AgentState:
        return self._states.setdefault(role, _AgentState(role))

    def start(self, role: str, project_id: str, task_id: str, title: str, attempt: int) -> None:
        st = self._state(role)
        st.active[task_id] = _Active(task_id, title, project_id, time.time(), attempt)
        st.retrying = attempt > 1
        st.last_activity = time.time()
        self._broadcast(role, project_id)

    def progress(self, role: str, tokens: int) -> None:
        st = self._state(role)
        for a in st.active.values():
            a.tokens = tokens
        st.last_activity = time.time()

    def finish(self, role: str, project_id: str, task_id: str, ok: bool, summary: str) -> None:
        st = self._state(role)
        st.active.pop(task_id, None)
        st.retrying = False
        st.last_activity = time.time()
        if ok:
            st.completed += 1
            st.last_summary = summary[:300]
            st.last_error = ""
        else:
            st.failed += 1
            st.last_error = summary[:300]
        self._broadcast(role, project_id)

    def status(self, role: str) -> AgentStatus:
        st = self._state(role)
        if st.active:
            return AgentStatus.RETRYING if st.retrying else AgentStatus.WORKING
        if st.last_error and st.failed and not st.last_summary:
            return AgentStatus.ERROR
        return AgentStatus.IDLE

    def snapshot(self, project_id: str | None = None) -> list[dict[str, Any]]:
        out = []
        now = time.time()
        for agent in self.registry.all():
            st = self._state(agent.role)
            active = [a for a in st.active.values() if project_id is None or a.project_id == project_id]
            current = max(active, key=lambda a: a.started) if active else None
            out.append(
                {
                    **agent.info(),
                    "status": (AgentStatus.RETRYING if st.retrying else AgentStatus.WORKING) if current else self.status(agent.role),
                    "current_task": None
                    if current is None
                    else {
                        "id": current.task_id,
                        "title": current.task_title,
                        "project_id": current.project_id,
                        "elapsed_s": round(now - current.started, 1),
                        "attempt": current.attempt,
                        "tokens": current.tokens,
                    },
                    "last_activity": st.last_activity or None,
                    "last_summary": st.last_summary,
                    "last_error": st.last_error,
                    "completed": st.completed,
                    "failed": st.failed,
                }
            )
        return out

    def _broadcast(self, role: str, project_id: str) -> None:
        self.events.emit(project_id, "agent_status", f"{self.registry.title(role)} is {self.status(role)}", agent=role, persist=False)
