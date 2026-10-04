"""ProjectRunner: executes one project's task graph.

- launches ready tasks (dependencies satisfied) by priority, in parallel up
  to ``max_parallel_tasks``; LLM calls are additionally throttled globally
- per-task timeout, retries with the previous error fed back to the agent
- applies results atomically: files -> git commit, reports, follow-up tasks
- pause is graceful (running tasks finish); stop cancels in-flight work
- asks the CEO policy what to do whenever the graph runs dry
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..agents import AgentContext, AgentResult
from ..db import Task
from ..log import get_logger
from ..memory import ProjectMemory
from ..states import (
    KIND_PHASE,
    PHASE_ORDER,
    Phase,
    ProjectStatus,
    TaskKind,
    TaskStatus,
    running_status_for,
)
from ..util import utcnow
from ..workspace import GitRepo, UnsafePathError, Workspace
from .policy import CEOPolicy
from .taskgraph import create_from_specs, deps_satisfied

if TYPE_CHECKING:
    from ..services import Services

log = get_logger("runner")
STOPPED_MARKER = "stopped by user"


def _describe(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timed out"
    text = str(exc).strip() or type(exc).__name__
    return text[:600]


class ProjectRunner:
    def __init__(self, services: Services, project_id: str, on_exit: Callable[[str], None] | None = None):
        self.s = services
        self.pid = project_id
        self.policy = CEOPolicy(services, project_id)
        self.git_lock = asyncio.Lock()
        self._running: dict[str, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._stop_requested = False
        self._on_exit = on_exit
        self.main: asyncio.Task[None] | None = None

    # ---- control ---------------------------------------------------------------------
    def start(self) -> asyncio.Task[None]:
        self.main = asyncio.create_task(self._loop(), name=f"runner-{self.pid}")
        return self.main

    def wake(self) -> None:
        self._wake.set()

    def request_stop(self) -> None:
        self._stop_requested = True
        self.wake()

    def cancel_task(self, task_id: str) -> bool:
        t = self._running.get(task_id)
        if t is None:
            return False
        t.cancel()
        return True

    @property
    def active(self) -> bool:
        return self.main is not None and not self.main.done()

    # ---- main loop --------------------------------------------------------------------
    async def _loop(self) -> None:
        idle_advances = 0
        try:
            while True:
                if self._stop_requested:
                    await self._cancel_all()
                    break
                project = self.s.store.get_project(self.pid)
                if project is None:
                    break
                if project.status != ProjectStatus.RUNNING:
                    if self._running:  # graceful pause: let in-flight tasks finish
                        await self._wait_any()
                        continue
                    break

                tasks = self.s.store.list_tasks(self.pid)
                by_id = {t.id: t for t in tasks}
                ready: list[Task] = []
                for t in tasks:
                    waiting = t.status in (TaskStatus.BACKLOG, TaskStatus.PLANNED) and t.id not in self._running
                    if waiting and deps_satisfied(t, by_id):
                        if t.status == TaskStatus.BACKLOG:
                            self.s.store.update_task(t.id, status=TaskStatus.PLANNED)
                        ready.append(t)
                ready.sort(key=lambda t: (t.priority, t.seq))
                slots = max(1, self.s.settings.max_parallel_tasks) - len(self._running)
                for t in ready[: max(0, slots)]:
                    self._launch(t)
                    idle_advances = 0

                if not self._running:
                    if idle_advances >= 3:
                        self.policy.escalate("The orchestrator made no progress after repeated planning attempts.")
                        break
                    outcome = await self.policy.advance()
                    idle_advances += 1
                    self._update_progress()
                    if outcome == "stop":
                        break
                    continue
                await self._wait_any()
        except Exception as e:  # noqa: BLE001 - never let a runner crash silently
            log.exception("runner crashed", extra={"project_id": self.pid})
            self.s.store.update_project(
                self.pid, status=ProjectStatus.NEEDS_ATTENTION, status_reason=f"Orchestrator error: {_describe(e)}"
            )
            self.s.events.emit(self.pid, "error", f"Orchestrator error: {_describe(e)}", level="error")
        finally:
            self._update_progress()
            if self._on_exit:
                self._on_exit(self.pid)

    def _launch(self, task: Task) -> None:
        self._running[task.id] = asyncio.create_task(self._execute(task.id), name=f"task-{task.id}")

    async def _wait_any(self) -> None:
        self._wake.clear()
        waiter = asyncio.create_task(self._wake.wait())
        try:
            await asyncio.wait([*self._running.values(), waiter], return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()

    async def _cancel_all(self) -> None:
        for t in list(self._running.values()):
            t.cancel()
        if self._running:
            await asyncio.gather(*self._running.values(), return_exceptions=True)
        for t in self.s.store.list_tasks(self.pid):
            if t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                self.s.store.update_task(t.id, status=TaskStatus.CANCELLED, error=STOPPED_MARKER, finished_at=utcnow())

    # ---- task execution ---------------------------------------------------------------
    async def _execute(self, task_id: str) -> None:
        try:
            await self._execute_inner(task_id)
        finally:
            self._running.pop(task_id, None)
            self.wake()

    async def _execute_inner(self, task_id: str) -> None:
        task = self.s.store.get_task(task_id)
        project = self.s.store.get_project(self.pid)
        if task is None or project is None:
            return
        agent = self.s.registry.get(task.role)
        kind = TaskKind(task.kind)
        previous_error = ""
        phase = KIND_PHASE.get(kind, Phase.IMPLEMENTATION)
        if project.phase != phase:
            self.s.store.update_project(self.pid, phase=phase)

        while True:
            task = self.s.store.update_task(
                task_id,
                status=running_status_for(kind),
                attempts=task.attempts + 1,
                started_at=task.started_at or utcnow(),
            )
            attempt_note = f" (attempt {task.attempts}/{task.max_attempts})" if task.attempts > 1 else ""
            self.s.tracker.start(task.role, self.pid, task.id, task.title, task.attempts)
            self.s.events.emit(
                self.pid, "task_started", f"{agent.title} started: {task.title}{attempt_note}", agent=task.role, task_id=task.id
            )
            project = self.s.store.get_project(self.pid)
            assert project is not None
            ctx = AgentContext(
                services=self.s,
                project=project,
                task=task,
                memory=ProjectMemory(self.s.store, self.pid),
                workspace=Workspace(Path(project.workspace_path)),
                git=GitRepo(Path(project.workspace_path)),
                agent_title=agent.title,
                git_lock=self.git_lock,
                previous_error=previous_error,
            )
            try:
                result = await asyncio.wait_for(agent.run(ctx), timeout=task.timeout_s)
                await self._apply(ctx, result)
                self.s.tracker.finish(task.role, self.pid, task.id, True, result.summary)
                return
            except asyncio.CancelledError:
                self.s.store.update_task(task_id, status=TaskStatus.CANCELLED, error=STOPPED_MARKER, finished_at=utcnow())
                self.s.tracker.finish(task.role, self.pid, task.id, False, "cancelled")
                self.s.events.emit(self.pid, "task_cancelled", f"{agent.title} stopped: {task.title}", agent=task.role, task_id=task.id, level="warning")
                raise
            except Exception as e:  # noqa: BLE001 - every agent failure is handled the same way
                msg = _describe(e)
                if isinstance(e, TimeoutError):
                    msg = f"timed out after {task.timeout_s:.0f}s"
                retryable = getattr(e, "retryable", True) and not isinstance(e, UnsafePathError | KeyError)
                log.warning("task %s attempt %d failed: %s", task.title, task.attempts, msg, extra={"project_id": self.pid})
                if retryable and task.attempts < task.max_attempts:
                    previous_error = msg
                    self.s.store.update_task(task_id, error=msg)
                    self.s.events.emit(
                        self.pid,
                        "task_retry",
                        f"{agent.title} attempt {task.attempts}/{task.max_attempts} failed — retrying: {msg[:200]}",
                        agent=task.role,
                        task_id=task.id,
                        level="warning",
                    )
                    await asyncio.sleep(min(2 * task.attempts, 10))
                    continue
                self.s.store.update_task(task_id, status=TaskStatus.FAILED, error=msg, finished_at=utcnow())
                self.s.tracker.finish(task.role, self.pid, task.id, False, msg)
                self.s.events.emit(
                    self.pid, "task_failed", f"{agent.title} failed: {task.title} — {msg[:240]}", agent=task.role, task_id=task.id, level="error"
                )
                return

    async def _apply(self, ctx: AgentContext, result: AgentResult) -> None:
        task, project = ctx.task, ctx.project
        commit = None
        if result.files:
            commit = await ctx.commit_files(result.files, result.commit_message or f"{task.role}: {task.title}")
        if result.new_tasks:
            created = create_from_specs(
                self.s.store,
                self.pid,
                result.new_tasks,
                iteration=project.iteration,
                created_by=task.role,
                max_attempts=self.s.settings.task_max_attempts,
                timeout_s=self.s.settings.task_timeout_s,
            )
            self.s.events.emit(
                self.pid,
                "tasks_created",
                f"{ctx.agent_title} scheduled {len(created)} task(s): " + ", ".join(t.title for t in created),
                agent=task.role,
                task_id=task.id,
            )
        if result.report:
            r = result.report
            self.s.store.add_report(
                project_id=self.pid,
                task_id=task.id,
                kind=r["kind"],
                iteration=project.iteration,
                passed=bool(r.get("passed")),
                score=float(r.get("score", 0.0)),
                summary=r.get("summary", ""),
                details=r.get("details", {}),
                commit=await asyncio.to_thread(ctx.git.head),
            )
        self.s.store.update_task(
            task.id,
            status=TaskStatus.COMPLETED,
            output=result.output,
            summary=result.summary,
            error="",
            finished_at=utcnow(),
        )
        level = "info"
        if result.report and not result.report.get("passed", True):
            level = "warning"
        data = {"files": list(result.files), "commit": commit} if result.files else None
        self.s.events.emit(
            self.pid,
            "task_completed",
            f"{ctx.agent_title} completed {task.title}: {result.summary}",
            agent=task.role,
            task_id=task.id,
            level=level,
            data=data,
        )
        self._update_progress()

    def _update_progress(self) -> None:
        project = self.s.store.get_project(self.pid)
        if project is None:
            return
        if project.status == ProjectStatus.COMPLETED:
            progress = 100.0
        else:
            tasks = self.s.store.list_tasks(self.pid)
            done = sum(1 for t in tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED))
            task_frac = done / len(tasks) if tasks else 0.0
            phases = [p for p in PHASE_ORDER if p != Phase.DONE]
            phase_frac = phases.index(Phase(project.phase)) / (len(phases) - 1) if project.phase in phases else 1.0
            progress = round(100 * (0.6 * phase_frac + 0.4 * task_frac), 1)
            progress = min(99.0, max(project.progress, progress))
        if progress != project.progress:
            self.s.store.update_project(self.pid, progress=progress)
