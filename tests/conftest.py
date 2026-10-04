from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ai_ceo.config import Settings
from ai_ceo.llm.mock_provider import MockProvider
from ai_ceo.orchestrator import Engine
from ai_ceo.services import Services
from ai_ceo.verification.browser import browser_available

_browser = None


def has_browser() -> bool:
    global _browser
    if _browser is None:
        _browser = browser_available("auto")[0]
    return _browser


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(reason="no Chromium-family browser available for Playwright")
    for item in items:
        if "browser" in item.keywords and not has_browser():
            item.add_marker(skip)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(
        data_dir=tmp_path / "data",
        llm_provider="mock",
        auth_token="test-token-0123456789abcdef",
        task_max_attempts=2,
        max_parallel_tasks=3,
        _env_file=None,
    )
    s.ensure_dirs()
    return s


@pytest.fixture
async def make_engine(settings: Settings):
    created: list[Engine] = []

    def _make(provider: MockProvider | None = None, **overrides: object) -> Engine:
        s = settings.model_copy(update=overrides) if overrides else settings
        engine = Engine(Services(s, provider or MockProvider(delay_s=0.0)))
        created.append(engine)
        return engine

    yield _make
    for e in created:
        await e.shutdown()


async def run_to_rest(engine: Engine, pid: str, timeout: float = 180) -> str:
    """Wait until the project's runner goes idle; return the project status."""
    await asyncio.wait_for(engine.wait(pid), timeout=timeout)
    p = engine.s.store.get_project(pid)
    assert p is not None
    return p.status
