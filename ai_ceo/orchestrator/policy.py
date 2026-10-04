"""CEO policy: the decision engine that drives the autonomous development loop.

REQUIREMENTS -> PLAN -> ARCHITECT -> IMPLEMENT -> TEST -> REVIEW -> FIX ->
TEST AGAIN -> APPROVE -> DEPLOY

The loop is controlled by deterministic, auditable rules rather than by an
LLM, so a weak model can't derail it. LLM judgement is used where it adds
value (charter, final release review) and every decision is written to
project memory and the activity feed with its reason.

Self-correction:
- failed task      -> retry with error feedback (runner) -> reassign to an
                      escalation engineer with a simplified brief -> escalate
- failed checks    -> correction tasks routed to the owner of each file
- no convergence   -> roll back to the best iteration, escalate to a human
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from ..agents import ESCALATION, TaskSpec
from ..agents.conventions import ROLE_TITLES, build_order, role_for_path
from ..db import Project, Task
from ..memory import MemoryKind, ProjectMemory
from ..states import (
    VERIFICATION_KINDS,
    Phase,
    ProjectStatus,
    TaskKind,
    TaskStatus,
)
from ..verification.issues import Issue
from ..workspace import GitRepo
from .taskgraph import create_from_specs

if TYPE_CHECKING:
    from ..services import Services

Outcome = Literal["continue", "stop"]

_VISUAL_WORDS = ("color", "colour", "style", "design", "look", "layout", "font", "theme", "dark", "css", "spacing", "mobile")
_BACKEND_WORDS = ("api", "server", "backend", "database", "endpoint", "data", "save", "store")


class CEOPolicy:
    def __init__(self, services: Services, project_id: str):
        self.s = services
        self.pid = project_id

    # ---- helpers ---------------------------------------------------------------------
    @property
    def memory(self) -> ProjectMemory:
        return ProjectMemory(self.s.store, self.pid)

    def _project(self) -> Project:
        p = self.s.store.get_project(self.pid)
        assert p is not None
        return p

    def _emit(self, message: str, *, type: str = "ceo_decision", level: str = "info", data: dict[str, Any] | None = None) -> None:
        self.s.events.emit(self.pid, type, message, agent="ceo", level=level, data=data)

    def _decide(self, decision: str, rationale: str, *, level: str = "info") -> None:
        self.memory.record_decision(decision, rationale, "ceo")
        self._emit(f"CEO: {decision}", level=level, data={"rationale": rationale})

    def _create(self, specs: list[TaskSpec], iteration: int) -> list[Task]:
        return create_from_specs(
            self.s.store,
            self.pid,
            specs,
            iteration=iteration,
            created_by="ceo",
            max_attempts=self.s.settings.task_max_attempts,
            timeout_s=self.s.settings.task_timeout_s,
        )

    def _max_fix_iterations(self, project: Project) -> int:
        return int((project.settings or {}).get("max_fix_iterations", self.s.settings.max_fix_iterations))

    def _requires_approval(self, project: Project) -> bool:
        return bool((project.settings or {}).get("require_approval", self.s.settings.require_human_approval))

    def _set_phase(self, phase: Phase) -> None:
        self.s.store.update_project(self.pid, phase=phase)

    def escalate(self, reason: str) -> Outcome:
        self.s.store.update_project(self.pid, status=ProjectStatus.NEEDS_ATTENTION, status_reason=reason)
        self._decide("Escalated to the client — human decision needed", reason, level="warning")
        return "stop"

    # ---- bootstrap -------------------------------------------------------------------
    def bootstrap(self) -> list[Task]:
        """The initial planning pipeline, created when a project starts."""
        specs = [
            TaskSpec("intake", "Define project charter", "ceo", TaskKind.INTAKE, "Understand the client's objective and set scope.", 1),
            TaskSpec(
                "requirements", "Write requirements & acceptance criteria", "product", TaskKind.REQUIREMENTS,
                "User stories, prioritised features and testable acceptance criteria.", 1, depends_on_keys=["intake"],
            ),
            TaskSpec(
                "strategy", "Create delivery strategy", "planner", TaskKind.STRATEGY,
                "Milestones, priorities, risks and definition of done.", 2, depends_on_keys=["requirements"],
            ),
            TaskSpec(
                "architecture", "Design system architecture", "architect", TaskKind.ARCHITECTURE,
                "Stack, file plan with owners, data model, API and decisions.", 1, depends_on_keys=["requirements"],
            ),
            TaskSpec(
                "design", "Design UI/UX", "uiux", TaskKind.DESIGN,
                "Palette, typography, layout, components and accessibility.", 2, depends_on_keys=["requirements"],
            ),
            TaskSpec(
                "breakdown", "Break down work & schedule tasks", "pm", TaskKind.BREAKDOWN,
                "Turn the architecture into implementation tasks with owners and dependencies.", 1,
                depends_on_keys=["architecture", "design", "strategy"],
            ),
        ]  # fmt: skip
        tasks = self._create(specs, iteration=1)
        self.s.store.update_project(self.pid, iteration=1, phase=Phase.REQUIREMENTS)
        self.memory.set(MemoryKind.STATE, "cycle_start", 1, "ceo")
        self._emit(f"CEO created the project plan: {len(tasks)} planning tasks across 5 agents", type="plan_created")
        return tasks

    # ---- main decision point ---------------------------------------------------------
    async def advance(self) -> Outcome:
        """Called by the runner whenever nothing is running or ready."""
        project = self._project()
        tasks = self.s.store.list_tasks(self.pid)
        it = project.iteration

        failed = [t for t in tasks if t.status == TaskStatus.FAILED]
        if failed:
            return self._handle_failures(failed)

        pending = [t for t in tasks if t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)]
        if pending:
            return self.escalate(
                "Scheduling deadlock: tasks are waiting on dependencies that can never complete: "
                + ", ".join(t.title for t in pending[:5])
            )

        current = [t for t in tasks if t.iteration == it]
        kinds = {t.kind for t in current}
        if TaskKind.DEPLOY in kinds:
            return self._finish(project, current)
        if TaskKind.FINAL_REVIEW in kinds:
            final = [t for t in current if t.kind == TaskKind.FINAL_REVIEW][-1]
            return self._after_final_review(project, final)
        if not any(t.kind in (TaskKind.IMPLEMENT, TaskKind.FIX) for t in tasks):
            return self.escalate("Planning finished but no implementation tasks were created.")
        verification = [t for t in current if t.kind in VERIFICATION_KINDS]
        if not verification:
            return self._start_verification(project)
        return await self._evaluate(project, verification)

    # ---- failure recovery ------------------------------------------------------------------
    def _handle_failures(self, failed: list[Task]) -> Outcome:
        for t in failed:
            recovery = int((t.input or {}).get("recovery", 0))
            if recovery >= 1:
                return self.escalate(
                    f"'{t.title}' still failed after retries and CEO recovery. Last error: {t.error[:300]}. "
                    "Retry it, reassign it, skip it, or stop the project."
                )
            new_input = {**(t.input or {}), "recovery": 1, "simplify": True}
            new_role = ESCALATION.get(t.role) if t.kind in (TaskKind.IMPLEMENT, TaskKind.FIX) else None
            self.s.store.update_task(
                t.id, status=TaskStatus.PLANNED, attempts=0, input=new_input, role=new_role or t.role, error=""
            )
            if new_role:
                self._decide(
                    f"Reassigned '{t.title}' from {self.s.registry.title(t.role)} to {self.s.registry.title(new_role)}",
                    f"{self.s.registry.title(t.role)} failed {t.attempts} attempts ({t.error[:160]}). "
                    "Escalation engineer takes over with a simplified brief.",
                    level="warning",
                )
            else:
                self._decide(
                    f"Ordered a recovery retry of '{t.title}' with a simplified approach",
                    f"Task failed {t.attempts} attempts: {t.error[:200]}",
                    level="warning",
                )
        return "continue"

    # ---- verification ---------------------------------------------------------------------
    def _start_verification(self, project: Project) -> Outcome:
        it = project.iteration
        label = "regression" if it > 1 else "acceptance"
        specs = [
            TaskSpec("test", f"Run {label} tests (iteration {it})", "testing", TaskKind.TEST,
                     "Static analysis, browser acceptance scenarios, API tests, regression check.", 1),
            TaskSpec("security", f"Security scan (iteration {it})", "security", TaskKind.SECURITY,
                     "Secrets, injection/XSS, unsafe APIs, validation, auth, configuration, dependencies.", 1),
            TaskSpec("review", f"Code review (iteration {it})", "reviewer", TaskKind.REVIEW,
                     "Review the code against requirements and engineering quality.", 2),
        ]  # fmt: skip
        self._create(specs, iteration=it)
        self._set_phase(Phase.TESTING)
        self._emit(f"CEO sent iteration {it} to QA: testing, security scan and code review run in parallel", type="phase")
        return "continue"

    def _collect_issues(self, verification: list[Task]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Blocking issues from this iteration's reports, plus a per-gate summary."""
        reports = {r.task_id: r for r in self.s.store.list_reports(self.pid)}
        addressed = set(self.memory.get(MemoryKind.STATE, "addressed_review", []) or [])
        project = self._project()
        late = project.iteration - int(self.memory.get(MemoryKind.STATE, "cycle_start", 1) or 1) >= 2
        blocking: dict[str, dict[str, Any]] = {}
        gates: dict[str, Any] = {}
        for t in verification:
            r = reports.get(t.id)
            if r is None:
                continue
            gates[r.kind] = {"passed": r.passed, "score": r.score, "summary": r.summary}
            d = r.details or {}
            if r.kind == "test":
                items = [i for i in d.get("issues", []) if i.get("severity") == "error"]
            elif r.kind == "security":
                items = [i for i in d.get("findings", []) if i.get("severity") in ("critical", "high")]
            elif r.kind == "review":
                items = []
                for i in d.get("issues", []):
                    if not i.get("file") or i.get("fingerprint") in addressed:
                        continue  # don't chase the same review comment twice
                    if i.get("severity") == "blocker" or (i.get("severity") == "major" and not late):
                        items.append(i)
            else:
                items = []
            for i in items:
                blocking.setdefault(i.get("fingerprint") or Issue.from_dict(i).fingerprint, i)
        return list(blocking.values()), gates

    async def _evaluate(self, project: Project, verification: list[Task]) -> Outcome:
        it = project.iteration
        issues, gates = self._collect_issues(verification)
        self._record_iteration_score(it, gates, len(issues))
        if not issues:
            self._decide(
                f"All quality gates passed in iteration {it}",
                "; ".join(f"{k}: {v['summary']}" for k, v in gates.items()),
            )
            return self._start_final_review(project, gates)

        cycle_start = int(self.memory.get(MemoryKind.STATE, "cycle_start", 1) or 1)
        used = it - cycle_start
        if used < self._max_fix_iterations(project):
            self._assign_fixes(project, issues, reason=f"{len(issues)} blocking issue(s) found in iteration {it}")
            return "continue"

        await self._rollback_to_best_if_better(project)
        return self.escalate(
            f"{len(issues)} blocking issue(s) remain after {used} fix iteration(s). "
            "You can approve the release anyway, grant more fix iterations, or give feedback."
        )

    def _record_iteration_score(self, it: int, gates: dict[str, Any], blocking: int) -> None:
        scores = dict(self.memory.get(MemoryKind.STATE, "iteration_scores", {}) or {})
        combined = sum(g["score"] for g in gates.values()) / max(1, len(gates))
        scores[str(it)] = {"score": round(combined, 1), "blocking": blocking, "commit": GitRepo(self._workspace()).head()}
        self.memory.set(MemoryKind.STATE, "iteration_scores", scores, "ceo")

    def _workspace(self):  # noqa: ANN202
        from pathlib import Path

        return Path(self._project().workspace_path)

    async def _rollback_to_best_if_better(self, project: Project) -> None:
        scores = self.memory.get(MemoryKind.STATE, "iteration_scores", {}) or {}
        current = scores.get(str(project.iteration))
        if not current or len(scores) < 2:
            return
        best_it, best = min(scores.items(), key=lambda kv: (kv[1]["blocking"], -kv[1]["score"]))
        if best_it == str(project.iteration) or not best.get("commit"):
            return
        if (best["blocking"], -best["score"]) >= (current["blocking"], -current["score"]):
            return
        repo = GitRepo(self._workspace())
        sha = await asyncio.to_thread(
            repo.restore_to, best["commit"], f"revert: roll back to iteration {best_it} (best verified result)"
        )
        self._decide(
            f"Rolled back the code to iteration {best_it}",
            f"Iteration {best_it} had {best['blocking']} blocking issue(s) (score {best['score']}) vs "
            f"{current['blocking']} now (score {current['score']}). New commit {str(sha)[:8]} restores it.",
            level="warning",
        )

    # ---- fixes -------------------------------------------------------------------------------
    def _primary_files(self) -> dict[str, str]:
        arch = self.memory.architecture
        files = {f["path"]: f.get("owner_role") or role_for_path(f["path"]) for f in arch.get("files", [])}
        return files

    def _assign_fixes(self, project: Project, issues: list[dict[str, Any]], reason: str) -> None:
        owners = self._primary_files()
        main_js = next((p for p in owners if p.endswith("app.js")), next(iter(owners), ""))
        by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for i in issues:
            f = i.get("file") or ""
            if f not in owners:
                f = next((p for p in owners if PurePosixPath(p).name == PurePosixPath(f).name), "") if f else ""
            by_file[f or main_js].append({**i, "file": f or main_js})

        new_it = project.iteration + 1
        order = build_order(list(by_file))
        specs = []
        for path, file_issues in by_file.items():
            role = owners.get(path, role_for_path(path))
            specs.append(
                TaskSpec(
                    key=path,
                    title=f"Fix {len(file_issues)} issue(s) in {path}",
                    role=role,
                    kind=TaskKind.FIX,
                    description="; ".join(i.get("message", "")[:120] for i in file_issues[:4]),
                    priority=1,
                    input={"files": [path], "issues": file_issues[:10]},
                    depends_on_keys=order.get(path, []),
                )
            )
        self._create(specs, iteration=new_it)
        self.s.store.update_project(self.pid, iteration=new_it, phase=Phase.FIXING)
        review_fps = [i.get("fingerprint") for i in issues if i.get("source") == "review" and i.get("fingerprint")]
        if review_fps:
            addressed = list(self.memory.get(MemoryKind.STATE, "addressed_review", []) or []) + review_fps
            self.memory.set(MemoryKind.STATE, "addressed_review", addressed[-200:], "ceo")
        assignment = ", ".join(
            f"{ROLE_TITLES.get(s.role, self.s.registry.title(s.role))} → {s.input['files'][0]} ({len(s.input['issues'])})"
            for s in specs
        )
        self._decide(f"Assigned {len(specs)} fix task(s) for iteration {new_it}: {assignment}", reason)

    # ---- release ----------------------------------------------------------------------------
    def _status_text(self, gates: dict[str, Any]) -> str:
        lines = [f"- {kind}: {'PASSED' if g['passed'] else 'FAILED'} — {g['summary']}" for kind, g in gates.items()]
        tests = self.s.store.list_reports(self.pid, "test")
        scenarios = (tests[-1].details or {}).get("scenarios", []) if tests else []
        verified = [s for s in scenarios if s.get("defect") != "test"]
        if verified:
            lines.append("Acceptance criteria exercised in a real browser:")
            lines += [f"  - [{'x' if s.get('passed') else ' '}] {s.get('criterion') or s.get('name')}" for s in verified[:10]]
        unverified = len(scenarios) - len(verified)
        if unverified or not scenarios:
            lines.append(f"Criteria NOT verified by browser tests: {unverified if scenarios else 'all (no browser tests ran)'}")
        open_bugs = [b for b in self.memory.values(MemoryKind.BUG) if b.get("status") == "open"]
        lines.append(f"Open bugs: {len(open_bugs)}")
        return "\n".join(lines)

    def _start_final_review(self, project: Project, gates: dict[str, Any]) -> Outcome:
        spec = TaskSpec(
            "final", f"Final release review (iteration {project.iteration})", "ceo", TaskKind.FINAL_REVIEW,
            "CEO reviews evidence from QA, security and code review and decides on release.", 1,
            input={"status_text": self._status_text(gates)},
        )  # fmt: skip
        self._create([spec], iteration=project.iteration)
        self._set_phase(Phase.APPROVAL)
        return "continue"

    def _after_final_review(self, project: Project, final: Task) -> Outcome:
        out = final.output or {}
        cycle_start = int(self.memory.get(MemoryKind.STATE, "cycle_start", 1) or 1)
        budget_left = (project.iteration - cycle_start) < self._max_fix_iterations(project)
        revise_used = bool(self.memory.get(MemoryKind.STATE, "ceo_revise_used", False))
        unmet = [c for c in out.get("unmet_criteria", []) if c.strip()]
        if out.get("decision") == "revise" and unmet and budget_left and not revise_used:
            self.memory.set(MemoryKind.STATE, "ceo_revise_used", True, "ceo")
            owners = self._primary_files()
            target = next((p for p in owners if p.endswith("app.js")), next(iter(owners)))
            issues = [
                {"severity": "error", "category": "acceptance", "source": "ceo", "file": target,
                 "message": f"CEO final review: acceptance criterion not met — {c}"}
                for c in unmet[:5]
            ]  # fmt: skip
            self._assign_fixes(project, issues, reason=f"CEO final review found unmet criteria: {unmet}")
            return "continue"
        if out.get("decision") == "revise":
            self._decide(
                "Proceeding to release despite final-review concerns",
                f"Concerns: {unmet or out.get('summary')}. Revision budget exhausted or already used.",
                level="warning",
            )
        self.s.store.update_project(self.pid, summary=out.get("release_notes", ""))
        if self._requires_approval(project):
            self.s.store.update_project(
                self.pid,
                status=ProjectStatus.AWAITING_APPROVAL,
                phase=Phase.APPROVAL,
                status_reason="All quality gates passed. Approve to deploy, or reject with feedback.",
            )
            self._emit("CEO recommends release — awaiting your approval", type="approval_requested")
            return "stop"
        self._decide("Approved the release", out.get("summary", "Quality gates passed"))
        self.create_deploy(project)
        return "continue"

    def create_deploy(self, project: Project) -> None:
        spec = TaskSpec("deploy", f"Deploy release (iteration {project.iteration})", "devops", TaskKind.DEPLOY,
                        "Package, merge to main, tag, archive and start the live preview.", 1)  # fmt: skip
        self._create([spec], iteration=project.iteration)
        self.s.store.update_project(
            self.pid, status=ProjectStatus.RUNNING, phase=Phase.DEPLOYMENT, status_reason=""
        )

    def _finish(self, project: Project, current: list[Task]) -> Outcome:
        deploy = [t for t in current if t.kind == TaskKind.DEPLOY][-1]
        if deploy.status != TaskStatus.COMPLETED:
            return self.escalate("Deployment did not complete.")
        url = (deploy.output or {}).get("preview_url")
        self.s.store.update_project(
            self.pid, status=ProjectStatus.COMPLETED, phase=Phase.DONE, progress=100.0, preview_url=url, status_reason=""
        )
        self._emit(f"Project delivered: {project.name} is live at {url}", type="project_completed", data={"url": url})
        return "stop"

    # ---- human feedback → new work ------------------------------------------------------------
    def plan_change_request(self, project: Project, feedback: str) -> None:
        """Turn client feedback (rejection or change request) into a new fix iteration."""
        owners = self._primary_files()
        text = feedback.lower()
        targets = [p for p in owners if p.endswith(("index.html", "app.js"))]
        if any(w in text for w in _VISUAL_WORDS):
            targets += [p for p in owners if p.endswith(".css")]
        if any(w in text for w in _BACKEND_WORDS):
            targets += [p for p in owners if p.endswith((".py", ".sql"))]
        targets = list(dict.fromkeys(targets)) or list(owners)
        issues = [
            {"severity": "error", "category": "change_request", "source": "client", "file": p,
             "message": f"Client feedback to implement: {feedback}"}
            for p in targets
        ]  # fmt: skip
        self.memory.set(MemoryKind.STATE, "cycle_start", project.iteration + 1, "ceo")
        self.memory.set(MemoryKind.STATE, "ceo_revise_used", False, "ceo")
        self._assign_fixes(project, issues, reason=f"Client feedback: {feedback}")
        self.s.store.update_project(self.pid, status=ProjectStatus.RUNNING, status_reason="")
