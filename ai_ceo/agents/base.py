"""Agent framework.

An agent receives an ``AgentContext`` (project, task, memory, workspace,
git, LLM) and returns an ``AgentResult``. Agents never write files or
create tasks directly: they return them, and the orchestrator applies the
result atomically (write files, commit to git, persist outputs and
reports, schedule follow-up tasks). That keeps every side effect auditable
and lets a failed attempt be retried cleanly.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from pydantic import BaseModel

from ..db import Project, Task
from ..llm import CallContext
from ..memory import ProjectMemory
from ..prompts import render
from ..states import TaskKind
from ..workspace import GitRepo, Workspace

if TYPE_CHECKING:
    from ..services import Services

T = TypeVar("T", bound=BaseModel)


class AgentError(Exception):
    """The agent could not complete its task. Retryable unless stated otherwise."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class TaskSpec:
    """A follow-up task an agent asks the orchestrator to create."""

    key: str
    title: str
    role: str
    kind: TaskKind
    description: str = ""
    priority: int = 3
    input: dict[str, Any] = field(default_factory=dict)
    depends_on_keys: list[str] = field(default_factory=list)
    depends_on_ids: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    commit_message: str = ""
    report: dict[str, Any] | None = None
    new_tasks: list[TaskSpec] = field(default_factory=list)


@dataclass
class AgentContext:
    services: Services
    project: Project
    task: Task
    memory: ProjectMemory
    workspace: Workspace
    git: GitRepo
    agent_title: str
    git_lock: asyncio.Lock
    previous_error: str = ""

    @property
    def settings(self):  # noqa: ANN201 - Settings, avoided import cycle
        return self.services.settings

    async def commit_files(self, files: dict[str, str], message: str) -> str | None:
        """Write files (path-validated) and commit them as this agent. Serialised per project."""
        async with self.git_lock:
            for path, content in files.items():
                self.workspace.write(path, content)
            return await asyncio.to_thread(self.git.commit_all, message, self.agent_title)

    def call_ctx(self) -> CallContext:
        tracker = self.services.tracker
        events = self.services.events
        project_id, task_id, role = self.project.id, self.task.id, self.task.role

        def on_progress(purpose: str, tokens: int) -> None:
            tracker.progress(role, tokens)
            events.emit(
                project_id,
                "agent_progress",
                f"{self.agent_title}: {purpose} ({tokens} tokens)",
                agent=role,
                task_id=task_id,
                data={"tokens": tokens, "purpose": purpose},
                persist=False,
            )

        return CallContext(role=role, project_id=project_id, task_id=task_id, on_progress=on_progress)

    def note(self, message: str, *, level: str = "info", type: str = "agent_note", data: dict[str, Any] | None = None) -> None:
        self.services.events.emit(
            self.project.id, type, message, agent=self.task.role, task_id=self.task.id, level=level, data=data
        )

    async def structured(self, schema: type[T], prompt: str, purpose: str, max_tokens: int = 1500, **values: Any) -> T:
        system, user = render(prompt, **values)
        if self.previous_error:
            user += f"\n\nNOTE: a previous attempt failed with: {self.previous_error[:400]}. Avoid that problem."
        result, _ = await self.services.llm.structured(
            self.call_ctx(), schema, system=system, prompt=user, purpose=purpose, max_tokens=max_tokens
        )
        return result

    async def text(self, prompt: str, purpose: str, max_tokens: int = 3500, **values: Any) -> tuple[str, bool]:
        """Returns (text, truncated)."""
        system, user = render(prompt, **values)
        resp = await self.services.llm.text(self.call_ctx(), system=system, prompt=user, purpose=purpose, max_tokens=max_tokens)
        return resp.text, resp.truncated


class Agent(ABC):
    role: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str]
    kinds: ClassVar[frozenset[TaskKind]]
    uses_llm: ClassVar[bool] = True

    @abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult: ...

    def info(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "title": self.title,
            "description": self.description,
            "kinds": sorted(k.value for k in self.kinds),
            "uses_llm": self.uses_llm,
        }
