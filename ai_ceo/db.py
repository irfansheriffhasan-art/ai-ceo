"""Persistent state: projects, tasks, events, memory, reports and LLM call traces.

SQLite (WAL mode) through SQLAlchemy 2.x. The ``Store`` class is the only
place that opens sessions; every method uses a short-lived session and
returns detached ORM objects or plain dicts, so callers never hold a
connection across an ``await``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .states import ProjectStatus, TaskStatus
from .util import iso, new_id, utcnow


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(64))
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=ProjectStatus.CREATED)
    phase: Mapped[str] = mapped_column(String(32), default="requirements")
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    workspace_path: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "objective": self.objective,
            "status": self.status,
            "phase": self.phase,
            "iteration": self.iteration,
            "progress": self.progress,
            "workspace_path": self.workspace_path,
            "settings": self.settings or {},
            "status_reason": self.status_reason,
            "preview_url": self.preview_url,
            "summary": self.summary,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.BACKLOG)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 = highest
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_s: Mapped[float] = mapped_column(Float, default=1200.0)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="ceo")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "role": self.role,
            "kind": self.kind,
            "status": self.status,
            "priority": self.priority,
            "depends_on": self.depends_on or [],
            "iteration": self.iteration,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "timeout_s": self.timeout_s,
            "input": self.input or {},
            "output": self.output or {},
            "summary": self.summary,
            "error": self.error,
            "parent_id": self.parent_id,
            "created_by": self.created_by,
            "seq": self.seq,
            "created_at": iso(self.created_at),
            "started_at": iso(self.started_at),
            "finished_at": iso(self.finished_at),
        }


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    type: Mapped[str] = mapped_column(String(48))
    level: Mapped[str] = mapped_column(String(16), default="info")
    agent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "ts": iso(self.ts),
            "type": self.type,
            "level": self.level,
            "agent": self.agent,
            "task_id": self.task_id,
            "message": self.message,
            "data": self.data or {},
        }


class MemoryItem(Base):
    __tablename__ = "memory"
    __table_args__ = (UniqueConstraint("project_id", "kind", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[Any] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(32), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }


class Report(Base):
    """Output of a verification step: test run, security scan, code review, final review."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "kind": self.kind,
            "iteration": self.iteration,
            "passed": self.passed,
            "score": self.score,
            "summary": self.summary,
            "details": self.details or {},
            "commit": self.commit,
            "created_at": iso(self.created_at),
        }


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="")
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(120), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    prompt_preview: Mapped[str] = mapped_column(Text, default="")
    response_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self, include_response: bool = False) -> dict[str, Any]:
        d = {
            "id": self.id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "purpose": self.purpose,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "ok": self.ok,
            "error": self.error,
            "created_at": iso(self.created_at),
        }
        if include_response:
            d["prompt_preview"] = self.prompt_preview
            d["response_text"] = self.response_text
        return d


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


class Store:
    """Repository over the SQLite database."""

    def __init__(self, db_path: Path | str):
        url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{Path(db_path).as_posix()}"
        self.engine = create_engine(url, connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", _sqlite_pragmas)
        Base.metadata.create_all(self.engine)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._seq_lock = threading.Lock()

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._sessions()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ---- projects ------------------------------------------------------------
    def create_project(self, **fields: Any) -> Project:
        with self.session() as s:
            p = Project(**fields)
            s.add(p)
            s.flush()
            return p

    def get_project(self, project_id: str) -> Project | None:
        with self.session() as s:
            return s.get(Project, project_id)

    def list_projects(self) -> list[Project]:
        with self.session() as s:
            return list(s.scalars(select(Project).order_by(Project.created_at.desc())))

    def update_project(self, project_id: str, **fields: Any) -> Project:
        with self.session() as s:
            p = s.get(Project, project_id)
            if p is None:
                raise KeyError(project_id)
            for k, v in fields.items():
                setattr(p, k, v)
            p.updated_at = utcnow()
            s.flush()
            return p

    # ---- tasks ---------------------------------------------------------------
    def create_task(self, **fields: Any) -> Task:
        with self._seq_lock, self.session() as s:
            max_seq = s.scalar(
                select(func.max(Task.seq)).where(Task.project_id == fields["project_id"])
            )
            t = Task(seq=(max_seq or 0) + 1, **fields)
            s.add(t)
            s.flush()
            return t

    def get_task(self, task_id: str) -> Task | None:
        with self.session() as s:
            return s.get(Task, task_id)

    def list_tasks(self, project_id: str) -> list[Task]:
        with self.session() as s:
            return list(s.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.seq)))

    def update_task(self, task_id: str, **fields: Any) -> Task:
        with self.session() as s:
            t = s.get(Task, task_id)
            if t is None:
                raise KeyError(task_id)
            for k, v in fields.items():
                setattr(t, k, v)
            s.flush()
            return t

    # ---- events --------------------------------------------------------------
    def add_event(self, **fields: Any) -> EventRow:
        with self.session() as s:
            e = EventRow(**fields)
            s.add(e)
            s.flush()
            return e

    def list_events(self, project_id: str | None, after_id: int = 0, limit: int = 200) -> list[EventRow]:
        with self.session() as s:
            q = select(EventRow).where(EventRow.id > after_id)
            if project_id:
                q = q.where(EventRow.project_id == project_id)
            q = q.order_by(EventRow.id.desc()).limit(limit)
            return list(reversed(list(s.scalars(q))))

    # ---- memory --------------------------------------------------------------
    def upsert_memory(self, project_id: str, kind: str, key: str, value: Any, source: str) -> MemoryItem:
        with self.session() as s:
            item = s.scalar(
                select(MemoryItem).where(
                    MemoryItem.project_id == project_id, MemoryItem.kind == kind, MemoryItem.key == key
                )
            )
            if item is None:
                item = MemoryItem(project_id=project_id, kind=kind, key=key, value=value, source=source)
                s.add(item)
            else:
                item.value = value
                item.source = source
                item.updated_at = utcnow()
            s.flush()
            return item

    def list_memory(self, project_id: str, kind: str | None = None) -> list[MemoryItem]:
        with self.session() as s:
            q = select(MemoryItem).where(MemoryItem.project_id == project_id)
            if kind:
                q = q.where(MemoryItem.kind == kind)
            return list(s.scalars(q.order_by(MemoryItem.id)))

    def get_memory(self, project_id: str, kind: str, key: str) -> MemoryItem | None:
        with self.session() as s:
            return s.scalar(
                select(MemoryItem).where(
                    MemoryItem.project_id == project_id, MemoryItem.kind == kind, MemoryItem.key == key
                )
            )

    # ---- reports -------------------------------------------------------------
    def add_report(self, **fields: Any) -> Report:
        with self.session() as s:
            r = Report(**fields)
            s.add(r)
            s.flush()
            return r

    def list_reports(self, project_id: str, kind: str | None = None) -> list[Report]:
        with self.session() as s:
            q = select(Report).where(Report.project_id == project_id)
            if kind:
                q = q.where(Report.kind == kind)
            return list(s.scalars(q.order_by(Report.created_at)))

    def get_report(self, report_id: str) -> Report | None:
        with self.session() as s:
            return s.get(Report, report_id)

    # ---- LLM calls -----------------------------------------------------------
    def add_llm_call(self, **fields: Any) -> LLMCall:
        with self.session() as s:
            c = LLMCall(**fields)
            s.add(c)
            s.flush()
            return c

    def list_llm_calls(self, project_id: str, limit: int = 200) -> list[LLMCall]:
        with self.session() as s:
            q = (
                select(LLMCall)
                .where(LLMCall.project_id == project_id)
                .order_by(LLMCall.id.desc())
                .limit(limit)
            )
            return list(s.scalars(q))

    def get_llm_call(self, call_id: int) -> LLMCall | None:
        with self.session() as s:
            return s.get(LLMCall, call_id)

    def llm_usage(self, project_id: str) -> dict[str, int]:
        with self.session() as s:
            row = s.execute(
                select(
                    func.count(LLMCall.id),
                    func.coalesce(func.sum(LLMCall.input_tokens), 0),
                    func.coalesce(func.sum(LLMCall.output_tokens), 0),
                    func.coalesce(func.sum(LLMCall.latency_ms), 0),
                ).where(LLMCall.project_id == project_id)
            ).one()
            return {"calls": row[0], "input_tokens": row[1], "output_tokens": row[2], "latency_ms": row[3]}
