"""End-to-end orchestration with the deterministic mock provider."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ai_ceo.llm.mock_provider import MockProvider
from ai_ceo.memory import MemoryKind, ProjectMemory
from ai_ceo.orchestrator import ControlError
from ai_ceo.states import ProjectStatus, TaskKind, TaskStatus
from ai_ceo.workspace import GitRepo
from tests.conftest import run_to_rest

NO_BROWSER = {"browser_channel": "none"}


def kinds(engine, pid):
    return [(t.kind, t.status, t.iteration) for t in engine.s.store.list_tasks(pid)]


@pytest.mark.browser
async def test_autonomous_cycle_catches_and_fixes_injected_bug(make_engine):
    engine = make_engine()
    p = engine.create_project("Build a task tracker web app")
    await engine.start(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.COMPLETED

    store = engine.s.store
    tests = store.list_reports(p.id, "test")
    assert [r.passed for r in tests] == [False, True], "iteration 1 must fail on the injected bug, iteration 2 must pass"
    assert any("acceptance test failed" in i["message"] for i in tests[0].details["issues"])
    fix = [t for t in store.list_tasks(p.id) if t.kind == TaskKind.FIX]
    assert len(fix) == 1 and fix[0].role == "frontend" and fix[0].input["files"] == ["app.js"]

    project = store.get_project(p.id)
    assert project.iteration == 2 and project.progress == 100.0 and project.preview_url
    repo = GitRepo(Path(project.workspace_path))
    assert "v1.0.0" in repo.tags() and repo.current_branch() == "develop"
    assert list(engine.s.settings.releases_dir.glob(f"*{p.id}*.zip"))

    mem = ProjectMemory(store, p.id)
    assert mem.requirements["acceptance_criteria"] and mem.architecture["files"]
    bugs = mem.values(MemoryKind.BUG)
    assert bugs and all(b["status"] == "fixed" for b in bugs)
    assert any("fix task" in d["decision"] for d in mem.values(MemoryKind.DECISION))


@pytest.mark.browser
async def test_backend_project_runs_api_tests(make_engine):
    engine = make_engine()
    p = engine.create_project("Notes app with a REST API and database", settings={"app_type": "web_with_backend"})
    await engine.start(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.COMPLETED
    test = engine.s.store.list_reports(p.id, "test")[-1]
    assert test.passed and len(test.details["api"]) == 6 and all(a["passed"] for a in test.details["api"])
    assert {f["path"] for f in ProjectMemory(engine.s.store, p.id).architecture["files"]} >= {"backend/main.py", "backend/schema.sql"}
    await engine.stop_preview(p.id)


async def test_failure_recovery_reassigns_then_escalates_then_human_retry(make_engine):
    provider = MockProvider(delay_s=0.0, fail_tags={"write index.html": 2})
    engine = make_engine(provider, **NO_BROWSER)
    p = engine.create_project("Build a task tracker web app")
    await engine.start(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.NEEDS_ATTENTION

    task = next(t for t in engine.s.store.list_tasks(p.id) if t.title == "Build index.html")
    assert task.status == TaskStatus.FAILED and task.role == "aiml", "CEO must reassign to the escalation engineer"
    decisions = [d["decision"] for d in ProjectMemory(engine.s.store, p.id).values(MemoryKind.DECISION)]
    assert any("Reassigned 'Build index.html'" in d for d in decisions)
    assert "still failed" in engine.s.store.get_project(p.id).status_reason

    await engine.retry_task(task.id)  # mock failures are exhausted now
    assert await run_to_rest(engine, p.id) == ProjectStatus.COMPLETED


async def test_task_timeout_is_handled(make_engine):
    provider = MockProvider(delay_s=0.5)
    engine = make_engine(provider, task_timeout_s=0.2, **NO_BROWSER)
    p = engine.create_project("Build a task tracker web app")
    await engine.start(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.NEEDS_ATTENTION
    intake = engine.s.store.list_tasks(p.id)[0]
    assert intake.status == TaskStatus.FAILED and "timed out" in intake.error


async def test_pause_resume_stop(make_engine):
    engine = make_engine(MockProvider(delay_s=0.15), **NO_BROWSER)
    p = engine.create_project("Build a task tracker web app")
    await engine.start(p.id)
    await asyncio.sleep(0.05)
    await engine.pause(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.PAUSED
    done_while_paused = sum(t.status == TaskStatus.COMPLETED for t in engine.s.store.list_tasks(p.id))
    await asyncio.sleep(0.4)
    assert sum(t.status == TaskStatus.COMPLETED for t in engine.s.store.list_tasks(p.id)) == done_while_paused

    await engine.resume(p.id)
    await asyncio.sleep(0.2)
    await engine.stop(p.id)
    assert engine.s.store.get_project(p.id).status == ProjectStatus.STOPPED
    assert not [t for t in engine.s.store.list_tasks(p.id) if t.status in (TaskStatus.IN_PROGRESS, TaskStatus.PLANNED)]
    with pytest.raises(ControlError):
        await engine.pause(p.id)

    await engine.resume(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.COMPLETED


async def test_approval_gate_reject_feedback_and_change_request(make_engine):
    engine = make_engine(**NO_BROWSER)
    p = engine.create_project("Build a task tracker web app", settings={"require_approval": True})
    await engine.start(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.AWAITING_APPROVAL
    assert not [t for t in engine.s.store.list_tasks(p.id) if t.kind == TaskKind.DEPLOY]

    await engine.reject(p.id, "Use a dark colour theme")
    assert await run_to_rest(engine, p.id) == ProjectStatus.AWAITING_APPROVAL
    fixes = [t for t in engine.s.store.list_tasks(p.id) if t.kind == TaskKind.FIX]
    assert {t.input["files"][0] for t in fixes} >= {"style.css", "app.js", "index.html"}, "visual feedback must reach the stylesheet"
    assert "dark colour theme" in ProjectMemory(engine.s.store, p.id).brief()

    await engine.approve(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.COMPLETED

    await engine.feedback(p.id, "Add a clear-all button")
    assert await run_to_rest(engine, p.id) == ProjectStatus.AWAITING_APPROVAL
    assert engine.s.store.get_project(p.id).iteration == 3


async def test_reassign_skip_and_validation(make_engine):
    engine = make_engine(MockProvider(delay_s=0.0, fail_tags={"write style.css": 5}), **NO_BROWSER)
    p = engine.create_project("Build a task tracker web app")
    await engine.start(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.NEEDS_ATTENTION
    css = next(t for t in engine.s.store.list_tasks(p.id) if t.title == "Build style.css")
    with pytest.raises(ControlError):
        await engine.reassign_task(css.id, "security")  # cannot write code
    await engine.cancel_task(css.id)  # skip it; the rest of the pipeline continues
    assert await run_to_rest(engine, p.id) in (ProjectStatus.COMPLETED, ProjectStatus.NEEDS_ATTENTION)
    assert engine.s.store.get_task(css.id).status == TaskStatus.CANCELLED


async def test_rollback_requires_pause_and_creates_commit(make_engine):
    engine = make_engine(**NO_BROWSER)
    p = engine.create_project("Build a task tracker web app")
    await engine.start(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.COMPLETED
    repo = GitRepo(Path(engine.s.store.get_project(p.id).workspace_path))
    first_feature = next(c for c in reversed(repo.log()) if c.message.startswith("feat"))
    result = await engine.rollback(p.id, first_feature.sha)
    assert result["commit"] and repo.log()[0].message.startswith("revert:")
    await engine.stop_preview(p.id)


async def test_recover_after_restart(make_engine):
    engine = make_engine(**NO_BROWSER)
    p = engine.create_project("Build a task tracker web app")
    store = engine.s.store
    first = store.list_tasks(p.id)[0]
    store.update_project(p.id, status=ProjectStatus.RUNNING)
    store.update_task(first.id, status=TaskStatus.IN_PROGRESS, attempts=1)
    engine.recover()
    assert store.get_project(p.id).status == ProjectStatus.PAUSED
    assert store.get_task(first.id).status == TaskStatus.PLANNED
    await engine.resume(p.id)
    assert await run_to_rest(engine, p.id) == ProjectStatus.COMPLETED


async def test_create_project_validation(make_engine):
    engine = make_engine(**NO_BROWSER)
    with pytest.raises(ControlError):
        engine.create_project("   ")
    p = engine.create_project("x" * 10_000 + " app", name="\x00Evil\x07Name", settings={"max_fix_iterations": 99, "evil": 1})
    assert len(p.objective) <= 4000 and "\x00" not in p.name
    assert p.settings == {"max_fix_iterations": 10}
