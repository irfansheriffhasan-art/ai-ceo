"""Dependency container wiring the platform together."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from .agents import AgentRegistry
from .config import Settings, get_settings
from .db import Store
from .deploy import PreviewManager
from .events import EventBus
from .llm import LLMClient, LLMProvider, build_provider
from .log import get_logger
from .orchestrator.tracker import AgentTracker
from .verification.browser import browser_available
from .workspace import GitRepo

log = get_logger("services")


class Services:
    def __init__(self, settings: Settings, provider: LLMProvider | None = None, store: Store | None = None):
        self.settings = settings
        self.store = store or Store(settings.db_path)
        self.events = EventBus(self.store)
        self.llm = LLMClient(settings, provider or build_provider(settings), self.store)
        self.registry = AgentRegistry()
        self.tracker = AgentTracker(self.registry, self.events)
        self.previews = PreviewManager(settings)
        self._browser: tuple[bool, str] | None = None
        self._browser_lock = asyncio.Lock()

    @classmethod
    def create(cls, settings: Settings | None = None, provider: LLMProvider | None = None) -> Services:
        return cls(settings or get_settings(), provider)

    async def browser_status(self) -> tuple[bool, str]:
        """Probe once (launching a browser takes a few seconds), then cache."""
        if self._browser is None:
            async with self._browser_lock:
                if self._browser is None:
                    self._browser = await asyncio.to_thread(browser_available, self.settings.browser_channel)
                    log.info("browser testing: %s", self._browser)
        return self._browser

    def mark_browser_unavailable(self, detail: str) -> None:
        self._browser = (False, detail)

    async def system_status(self) -> dict[str, Any]:
        provider = await self.llm.provider.health()
        model = self.llm.model_for("frontend")
        if self.llm.provider_name == "ollama" and provider.get("ok"):
            from .llm.ollama_provider import OllamaProvider

            provider["model_installed"] = OllamaProvider.has_model(provider.get("models", []), model)
            if not provider["model_installed"]:
                provider["ok"] = False
                provider["detail"] = f"model '{model}' is not installed — run: ollama pull {model}"
        browser_ok, browser_detail = await self.browser_status()
        return {
            "llm": {"provider": self.llm.provider_name, "model": model, **provider},
            "node": {"ok": shutil.which(self.settings.node_path) is not None},
            "git": {"ok": GitRepo.available()},
            "browser": {"ok": browser_ok, "detail": browser_detail},
            "settings": {
                "max_parallel_tasks": self.settings.max_parallel_tasks,
                "max_fix_iterations": self.settings.max_fix_iterations,
                "task_max_attempts": self.settings.task_max_attempts,
                "require_human_approval": self.settings.require_human_approval,
                "llm_max_concurrency": self.settings.llm_max_concurrency,
                "run_generated_backends": self.settings.run_generated_backends,
            },
        }

    async def aclose(self) -> None:
        await self.previews.stop_all()
        await self.llm.provider.aclose()
