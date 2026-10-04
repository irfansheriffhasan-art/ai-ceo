"""Engine: multi-project orchestration and every human control.

The API and CLI only talk to the Engine. Each control validates the
current state, records an auditable event, mutates state and wakes the
project's runner.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..db import Project, Task
from ..log import get_logger
from ..memory import MemoryKind, ProjectMemory
from ..states import (
    RUNNING_TASK_STATUSES,
    Phase,
    ProjectStatus,
    TaskKind,
    TaskStatus,
)
from ..util import clean_text, slugify
from ..workspace import GitRepo, Workspace
from .policy import CEOPolicy
from .runner import STOPPED_MARKER, ProjectRunner

if TYPE_CHECKING:
    from ..services import Services

log = get_logger("engine")


class ControlError(ValueError):
    """A control action is not valid in the current state (HTTP 409)."""


class Engine:
    def __init__(self, services: Services):
        self.s = services
        self.runners: dict[str, ProjectRunner] = {}

    # ---- lifecycle ---------------------------------------------------------------------
    def recover(self) -> None:
        """After a restart nothing is really running: requeue interrupted tasks, park active projects as paused."""
        for p in self.s.store.list_projects():
            for t in self.s.store.list_tasks(p.id):
                if t.status in RUNNING_TASK_STATUSES:
                    self.s.store.update_task(t.id, status=TaskStatus.PLANNED, attempts=max(0, t.attempts - 1))
            if p.status == ProjectStatus.RUNNING:
                self.s.store.update_project(
                    p.id, status=ProjectStatus.PAUSED, status_reason="Interrupted by a server restart — resume to continue."
                )
                self.s.events.emit(p.id, "control", "Project paused: interrupted by a server restart", level="warning")

    async def shutdown(self) -> None:
        """Cancel in-flight work but leave it resumable (projects become paused)."""
        for pid, runner in list(self.runners.items()):
            p = self.s.store.get_project(pid)
            if p and p.status == ProjectStatus.RUNNING:
                self.s.store.update_project(pid, status=ProjectStatus.PAUSED, status_reason="Server shut down — resume to continue.")
            children = list(runner._running.values())
            for child in children:
                child.cancel()
            if runner.main:
                runner.main.cancel()
            await asyncio.gather(*children, *( [runner.main] if runner.main else []), return_exceptions=True)
            for t in self.s.store.list_tasks(pid):
                if t.status == TaskStatus.CANCELLED and t.error == STOPPED_MARKER:
                    self.s.store.update_task(t.id, status=TaskStatus.PLANNED, error="", attempts=max(0, t.attempts - 1))
        self.runners.clear()
        await self.s.aclose()

    def _on_runner_exit(self, pid: str) -> None:
        self.runners.pop(pid, None)

    def _ensure_runner(self, pid: str) -> ProjectRunner:
        runner = self.runners.get(pid)
        if runner is None or not runner.active:
            runner = ProjectRunner(self.s, pid, on_exit=self._on_runner_exit)
            self.runners[pid] = runner
            runner.start()
        else:
            runner.wake()
        return runner

    async def wait(self, pid: str) -> Project:
        """Block until the project's runner exits (used by the CLI)."""
        while True:
            runner = self.runners.get(pid)
            if runner is None or runner.main is None:
                break
            await asyncio.shield(runner.main)
            if self.runners.get(pid) is runner:
                self.runners.pop(pid, None)
        p = self.s.store.get_project(pid)
        assert p is not None
        return p

    # ---- helpers -----------------------------------------------------------------------
    def _project(self, pid: str) -> Project:
        p = self.s.store.get_project(pid)
        if p is None:
            raise KeyError(f"project {pid} not found")
        return p

    def _task(self, tid: str) -> Task:
        t = self.s.store.get_task(tid)
        if t is None:
            raise KeyError(f"task {tid} not found")
        return t

    def _control(self, pid: str, message: str, data: dict[str, Any] | None = None) -> None:
        self.s.events.emit(pid, "control", message, agent="user", data=data)

    # ---- projects ----------------------------------------------------------------------
    def create_project(self, objective: str, name: str | None = None, settings: dict[str, Any] | None = None) -> Project:
        objective = clean_text(objective, 4000)
        if len(objective) < 5:
            raise ControlError("Describe the project in at least a few words.")
        name = clean_text(name or "", 80) or " ".join(objective.split()[:6])
        allowed = {"require_approval", "max_fix_iterations", "app_type"}
        settings = {k: v for k, v in (settings or {}).items() if k in allowed}
        if "max_fix_iterations" in settings:
            settings["max_fix_iterations"] = max(0, min(10, int(settings["max_fix_iterations"])))
        project = self.s.store.create_project(name=name, slug=slugify(name), objective=objective, settings=settings)
        root = self.s.settings.workspaces_dir / f"{project.slug}-{project.id}"
        Workspace(root).create()
        repo = GitRepo(root)
        repo.init()
        repo.checkout("develop", create=True)
        self.s.store.update_project(project.id, workspace_path=str(root))
        CEOPolicy(self.s, project.id).bootstrap()
        self.s.events.emit(project.id, "project_created", f"New project: {name}", agent="user", data={"objective": objective})
        return self._project(project.id)

    async def start(self, pid: str) -> Project:
        p = self._project(pid)
        if p.status not in (ProjectStatus.CREATED, ProjectStatus.PAUSED, ProjectStatus.STOPPED):
            raise ControlError(f"cannot start a project that is {p.status}")
        return await self.resume(pid) if p.status != ProjectStatus.CREATED else self._run(pid, "Project started")

    def _run(self, pid: str, message: str) -> Project:
        self.s.store.update_project(pid, status=ProjectStatus.RUNNING, status_reason="")
        self._control(pid, message)
        self._ensure_runner(pid)
        return self._project(pid)

    async def pause(self, pid: str) -> Project:
        p = self._project(pid)
        if p.status != ProjectStatus.RUNNING:
            raise ControlError(f"cannot pause a project that is {p.status}")
        self.s.store.update_project(pid, status=ProjectStatus.PAUSED, status_reason="Paused by user")
        runner = self.runners.get(pid)
        busy = runner.busy if runner else 0
        self._control(pid, "Project paused" + (f" — waiting for {busy} running task(s) to finish" if busy else ""))
        if runner:
            runner.wake()
        return self._project(pid)

    async def resume(self, pid: str) -> Project:
        p = self._project(pid)
        if p.status not in (ProjectStatus.PAUSED, ProjectStatus.STOPPED, ProjectStatus.NEEDS_ATTENTION):
            raise ControlError(f"cannot resume a project that is {p.status}")
        if p.status == ProjectStatus.STOPPED:
            for t in self.s.store.list_tasks(pid):
                if t.status == TaskStatus.CANCELLED and t.error == STOPPED_MARKER:
                    self.s.store.update_task(t.id, status=TaskStatus.PLANNED, error="", finished_at=None)
        return self._run(pid, "Project resumed")

    async def stop(self, pid: str) -> Project:
        p = self._project(pid)
        if p.status in (ProjectStatus.COMPLETED, ProjectStatus.STOPPED):
            raise ControlError(f"project is already {p.status}")
        self.s.store.update_project(pid, status=ProjectStatus.STOPPED, status_reason="Stopped by user")
        runner = self.runners.get(pid)
        if runner and runner.active:
            runner.request_stop()
            await asyncio.shield(runner.main)  # type: ignore[arg-type]
        else:
            for t in self.s.store.list_tasks(pid):
                if t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    self.s.store.update_task(t.id, status=TaskStatus.CANCELLED, error=STOPPED_MARKER)
        self._control(pid, "Project stopped — in-flight work cancelled")
        return self._project(pid)

    # ---- tasks -------------------------------------------------------------------------
    async def retry_task(self, tid: str) -> Task:
        t = self._task(tid)
        if t.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise ControlError(f"only failed or cancelled tasks can be retried (task is {t.status})")
        self.s.store.update_task(tid, status=TaskStatus.PLANNED, attempts=0, error="", finished_at=None)
        self._control(t.project_id, f"Retry requested: {t.title}", {"task_id": tid})
        await self._kick(t.project_id)
        return self._task(tid)

    async def cancel_task(self, tid: str) -> Task:
        """Skip a task. Downstream tasks treat a skipped dependency as satisfied."""
        t = self._task(tid)
        if t.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            raise ControlError(f"task is already {t.status}")
        runner = self.runners.get(t.project_id)
        if runner:
            await runner.cancel_task(tid)
        self.s.store.update_task(tid, status=TaskStatus.CANCELLED, error="skipped by user")
        self._control(t.project_id, f"Task skipped: {t.title}", {"task_id": tid})
        p = self._project(t.project_id)
        if p.status == ProjectStatus.NEEDS_ATTENTION:
            await self._kick(t.project_id)
        elif runner:
            runner.wake()
        return self._task(tid)

    async def reassign_task(self, tid: str, role: str) -> Task:
        t = self._task(tid)
        if t.status in RUNNING_TASK_STATUSES or t.status == TaskStatus.COMPLETED:
            raise ControlError(f"cannot reassign a task that is {t.status}")
        if not self.s.registry.can_handle(role, t.kind):
            options = ", ".join(self.s.registry.candidates(t.kind))
            raise ControlError(f"{role} cannot do '{t.kind}' tasks (capable: {options})")
        old = t.role
        new_status = TaskStatus.PLANNED if t.status in (TaskStatus.FAILED, TaskStatus.CANCELLED) else t.status
        self.s.store.update_task(tid, role=role, status=new_status, attempts=0, error="")
        ProjectMemory(self.s.store, t.project_id).record_decision(
            f"Reassigned '{t.title}' to {self.s.registry.title(role)}", "Manual reassignment by the client", "user"
        )
        self._control(t.project_id, f"Reassigned '{t.title}' from {self.s.registry.title(old)} to {self.s.registry.title(role)}")
        if new_status == TaskStatus.PLANNED:
            await self._kick(t.project_id)
        return self._task(tid)

    async def _kick(self, pid: str) -> None:
        """Resume an idle/escalated project after a task-level intervention."""
        p = self._project(pid)
        if p.status in (ProjectStatus.NEEDS_ATTENTION, ProjectStatus.FAILED):
            self._run(pid, "Project resumed after intervention")
        elif p.status == ProjectStatus.RUNNING:
            self._ensure_runner(pid)

    # ---- approvals & feedback --------------------------------------------------------------
    async def approve(self, pid: str) -> Project:
        p = self._project(pid)
        if p.status not in (ProjectStatus.AWAITING_APPROVAL, ProjectStatus.NEEDS_ATTENTION):
            raise ControlError(f"nothing to approve (project is {p.status})")
        policy = CEOPolicy(self.s, pid)
        reason = "Client approved the release" + (" despite open issues" if p.status == ProjectStatus.NEEDS_ATTENTION else "")
        # Approving overrides any outstanding failures; otherwise the CEO would re-escalate after deploying.
        for t in self.s.store.list_tasks(pid):
            if t.status == TaskStatus.FAILED:
                self.s.store.update_task(t.id, status=TaskStatus.CANCELLED, error=f"skipped: release approved by client ({t.error[:200]})")
        ProjectMemory(self.s.store, pid).record_decision("Release approved", reason, "user")
        self._control(pid, reason)
        policy.create_deploy(self._project(pid))
        self._ensure_runner(pid)
        return self._project(pid)

    async def reject(self, pid: str, feedback: str) -> Project:
        p = self._project(pid)
        if p.status not in (ProjectStatus.AWAITING_APPROVAL, ProjectStatus.NEEDS_ATTENTION):
            raise ControlError(f"nothing to reject (project is {p.status})")
        return await self._change(p, feedback, "Release rejected with feedback")

    async def feedback(self, pid: str, message: str) -> Project:
        """Client feedback. While running it's noted for upcoming work; when finished it starts a new iteration."""
        p = self._project(pid)
        message = clean_text(message, 2000)
        if not message:
            raise ControlError("feedback is empty")
        mem = ProjectMemory(self.s.store, pid)
        if p.status in (ProjectStatus.RUNNING, ProjectStatus.PAUSED, ProjectStatus.CREATED):
            mem.add_preference(message)
            self._control(pid, f"Client feedback noted — agents will apply it to upcoming work: {message}")
            return p
        if p.status == ProjectStatus.STOPPED:
            raise ControlError("resume the project before sending change requests")
        return await self._change(p, message, "Change request received")

    async def _change(self, p: Project, feedback: str, label: str) -> Project:
        feedback = clean_text(feedback, 2000)
        if not feedback:
            raise ControlError("feedback is empty")
        ProjectMemory(self.s.store, p.id).add_preference(feedback)
        self._control(p.id, f"{label}: {feedback}")
        if p.status == ProjectStatus.COMPLETED:
            self.s.store.update_project(p.id, progress=60.0)
        CEOPolicy(self.s, p.id).plan_change_request(self._project(p.id), feedback)
        self._ensure_runner(p.id)
        return self._project(p.id)

    async def continue_fixing(self, pid: str, extra: int = 2) -> Project:
        p = self._project(pid)
        if p.status != ProjectStatus.NEEDS_ATTENTION:
            raise ControlError(f"project is {p.status}, not waiting for a decision")
        settings = dict(p.settings or {})
        current = int(settings.get("max_fix_iterations", self.s.settings.max_fix_iterations))
        settings["max_fix_iterations"] = min(current + max(1, min(extra, 5)), 15)
        self.s.store.update_project(pid, settings=settings)
        return self._run(pid, f"Granted {extra} more fix iteration(s)")

    # ---- git ---------------------------------------------------------------------------------
    async def rollback(self, pid: str, sha: str) -> dict[str, Any]:
        p = self._project(pid)
        if p.status == ProjectStatus.RUNNING:
            raise ControlError("pause the project before rolling back")
        repo = GitRepo(Path(p.workspace_path))
        new_sha = await asyncio.to_thread(repo.restore_to, sha, f"revert: roll back to {sha[:8]} (requested by client)")
        ProjectMemory(self.s.store, pid).record_decision(f"Rolled back to commit {sha[:8]}", "Requested by the client", "user")
        self._control(pid, f"Rolled back workspace to {sha[:8]}" + (f" (new commit {new_sha[:8]})" if new_sha else " (no changes)"))
        if self.s.previews.url(pid):
            await self.start_preview(pid)
        return {"commit": new_sha}

    # ---- previews ------------------------------------------------------------------------------
    async def start_preview(self, pid: str) -> str:
        p = self._project(pid)
        arch = ProjectMemory(self.s.store, pid).architecture
        if not arch:
            raise ControlError("nothing to preview yet")
        url = await self.s.previews.start(pid, Path(p.workspace_path), bool(arch.get("needs_backend")))
        self.s.store.update_project(pid, preview_url=url)
        self._control(pid, f"Preview started at {url}")
        return url

    async def stop_preview(self, pid: str) -> None:
        await self.s.previews.stop(pid)
        self.s.store.update_project(pid, preview_url=None)
        self._control(pid, "Preview stopped")

    # ---- views ----------------------------------------------------------------------------------
    def snapshot(self, pid: str) -> dict[str, Any]:
        p = self._project(pid)
        tasks = self.s.store.list_tasks(pid)
        counts: dict[str, int] = {}
        for t in tasks:
            counts[t.status] = counts.get(t.status, 0) + 1
        mem = ProjectMemory(self.s.store, pid)
        open_bugs = sum(1 for b in mem.values(MemoryKind.BUG) if b.get("status") == "open")
        runner = self.runners.get(pid)
        return {
            "project": {**p.to_dict(), "preview_url": self.s.previews.url(pid) or (p.preview_url if p.status == ProjectStatus.COMPLETED else None)},
            "tasks": [t.to_dict() for t in tasks],
            "counts": counts,
            "agents": self.s.tracker.snapshot(pid),
            "open_bugs": open_bugs,
            "runner_active": bool(runner and runner.active),
            "running_tasks": runner.busy if runner else 0,
            "usage": self.s.store.llm_usage(pid),
            "phases": [ph.value for ph in Phase],
            "iteration_scores": mem.get(MemoryKind.STATE, "iteration_scores", {}) or {},
        }

    def task_kinds_for_reassign(self, tid: str) -> list[str]:
        t = self._task(tid)
        return self.s.registry.candidates(TaskKind(t.kind))
