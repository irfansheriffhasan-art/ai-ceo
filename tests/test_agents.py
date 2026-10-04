"""Agent-level behaviour that is easiest to verify in isolation."""

from types import SimpleNamespace

from ai_ceo.agents.conventions import build_order, file_rules
from ai_ceo.agents.testing import TestingAgent, _repro
from ai_ceo.db import Store
from ai_ceo.memory import MemoryKind, ProjectMemory


def _ctx(tmp_path):
    store = Store(tmp_path / "t.db")
    project = store.create_project(name="p", slug="p", objective="o")
    notes: list[str] = []
    return SimpleNamespace(memory=ProjectMemory(store, project.id), note=lambda msg, **_: notes.append(msg)), notes


def test_stubborn_identical_failures_are_disputed_once(tmp_path):
    ctx, notes = _ctx(tmp_path)
    ctx.memory.set(MemoryKind.TEST_PLAN, "browser", {"hash": "h", "scenarios": [], "version": 1})
    failing = [{"name": "random", "criterion": "c1", "passed": False, "defect": "app", "failed_step": 3, "error": "expected 'A1!'"}]
    agent = TestingAgent()

    agent._dispute_stubborn_failures(ctx, failing)
    assert not ctx.memory.get(MemoryKind.TEST_PLAN, "browser").get("needs_revision"), "one failure is not a dispute"

    agent._dispute_stubborn_failures(ctx, failing)
    plan = ctx.memory.get(MemoryKind.TEST_PLAN, "browser")
    assert plan["needs_revision"] and "random" in plan["revision_feedback"]
    assert notes and "disputes 1" in notes[0]


def test_changing_failures_are_not_disputed(tmp_path):
    ctx, _ = _ctx(tmp_path)
    ctx.memory.set(MemoryKind.TEST_PLAN, "browser", {"hash": "h", "scenarios": [], "version": 1})
    agent = TestingAgent()
    for step in (1, 2, 3):  # the developer is making progress: the failure point moves
        agent._dispute_stubborn_failures(ctx, [{"name": "s", "criterion": "c", "passed": False, "failed_step": step, "error": f"e{step}"}])
    assert not ctx.memory.get(MemoryKind.TEST_PLAN, "browser").get("needs_revision")


def test_repro_steps_are_readable():
    text = _repro({"steps": [{"action": "click", "selector": "#go", "value": ""}, {"action": "expect_text", "selector": "#out", "value": "hi"}], "failed_step": 1})
    assert text.startswith("Fresh page load") and "click #go" in text and "expect_text #out 'hi'" in text and "step 2" in text


def test_conventions_order_and_rules():
    order = build_order(["frontend/app.js", "frontend/index.html", "backend/main.py", "backend/schema.sql"])
    assert order["backend/main.py"] == ["backend/schema.sql"]
    assert set(order["frontend/app.js"]) == {"frontend/index.html", "backend/main.py"}
    rules = file_rules("app.js", {"needs_backend": False}, ["a", "b"])
    assert "a, b" in rules and "getRandomValues" in rules and "require()" in rules
