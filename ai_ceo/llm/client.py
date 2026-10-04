"""LLMClient: the single entry point agents use to talk to a model.

Adds, on top of any provider:
- a global concurrency limit (local GPUs run one generation at a time)
- per-call timeouts and retry with exponential backoff for transient errors
- structured output: strict JSON schema + pydantic validation + a repair round
- tracing of every call (tokens, latency, errors) into the database
- live token-progress events for the dashboard
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..db import Store
from ..log import get_logger
from ..util import truncate
from .base import LLMError, LLMProvider, LLMRequest, LLMResponse
from .parsing import ParseError, extract_json, to_strict_schema

T = TypeVar("T", bound=BaseModel)
log = get_logger("llm")


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(settings.ollama_host, settings.ollama_num_ctx, settings.llm_timeout_s)
    if settings.llm_provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        return AnthropicProvider(key, settings.anthropic_effort, settings.llm_timeout_s)
    if settings.llm_provider == "openai":
        from .openai_provider import OpenAIProvider

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIProvider(key, settings.openai_base_url, settings.llm_timeout_s)
    from .mock_provider import MockProvider

    return MockProvider(inject_bug=settings.mock_inject_bug)


class CallContext:
    """Who is calling: used for tracing and progress events."""

    def __init__(
        self,
        role: str,
        project_id: str | None = None,
        task_id: str | None = None,
        on_progress: Callable[[str, int], None] | None = None,
    ):
        self.role = role
        self.project_id = project_id
        self.task_id = task_id
        self.on_progress = on_progress


class LLMClient:
    def __init__(self, settings: Settings, provider: LLMProvider, store: Store | None = None):
        self.settings = settings
        self.provider = provider
        self.store = store
        self._semaphore = asyncio.Semaphore(max(1, settings.llm_max_concurrency))

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def model_for(self, role: str) -> str:
        if self.provider.name == "mock":
            return "mock"
        if self.provider.name == "anthropic" and self.settings.llm_model.startswith(("llama", "gemma", "qwen")):
            from .anthropic_provider import DEFAULT_MODEL

            return self.settings.llm_role_models.get(role, DEFAULT_MODEL)
        return self.settings.model_for(role)

    async def text(
        self,
        ctx: CallContext,
        *,
        system: str,
        prompt: str,
        purpose: str,
        max_tokens: int = 2048,
        temperature: float | None = None,
    ) -> LLMResponse:
        req = self._request(ctx, system, prompt, purpose, max_tokens, temperature, schema=None)
        return await self._call_with_retries(ctx, req)

    async def structured(
        self,
        ctx: CallContext,
        schema: type[T],
        *,
        system: str,
        prompt: str,
        purpose: str,
        max_tokens: int = 1500,
        temperature: float | None = None,
        repair_attempts: int = 1,
    ) -> tuple[T, LLMResponse]:
        json_schema = to_strict_schema(schema)
        current_prompt = prompt
        last_error = ""
        for attempt in range(repair_attempts + 1):
            req = self._request(ctx, system, current_prompt, purpose, max_tokens, temperature, schema=json_schema)
            resp = await self._call_with_retries(ctx, req)
            try:
                data = extract_json(resp.text)
                return schema.model_validate(data), resp
            except (ParseError, ValidationError) as e:
                last_error = truncate(str(e), 600)
                log.warning(
                    "invalid structured output (attempt %d): %s",
                    attempt + 1,
                    last_error,
                    extra={"project_id": ctx.project_id, "task_id": ctx.task_id, "agent": ctx.role},
                )
                current_prompt = (
                    f"{prompt}\n\nIMPORTANT: your previous reply was rejected because it was not valid "
                    f"for the required JSON schema ({last_error}). Reply again with ONLY one JSON object "
                    "that matches the schema exactly."
                )
        raise LLMError(f"model did not return valid {schema.__name__} JSON: {last_error}", retryable=True)

    # ---- internals ---------------------------------------------------------------
    def _request(
        self,
        ctx: CallContext,
        system: str,
        prompt: str,
        purpose: str,
        max_tokens: int,
        temperature: float | None,
        schema: dict[str, Any] | None,
    ) -> LLMRequest:
        def progress(tokens: int) -> None:
            if ctx.on_progress:
                ctx.on_progress(purpose, tokens)

        return LLMRequest(
            system=system,
            prompt=prompt,
            model=self.model_for(ctx.role),
            json_schema=schema,
            max_tokens=max_tokens,
            temperature=self.settings.llm_temperature if temperature is None else temperature,
            purpose=purpose,
            tag=f"{ctx.role}:{purpose}",
            on_progress=progress,
        )

    async def _call_with_retries(self, ctx: CallContext, req: LLMRequest) -> LLMResponse:
        max_retries = max(0, self.settings.llm_max_retries)
        for attempt in range(max_retries + 1):
            try:
                return await self._call_once(ctx, req)
            except LLMError as e:
                if not e.retryable or attempt == max_retries:
                    raise
                delay = min(2**attempt * 2 + random.uniform(0, 1), 30)
                log.warning("LLM call failed (%s); retrying in %.1fs", e, delay, extra={"agent": ctx.role})
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _call_once(self, ctx: CallContext, req: LLMRequest) -> LLMResponse:
        async with self._semaphore:
            started = time.monotonic()
            try:
                resp = await asyncio.wait_for(self.provider.complete(req), timeout=self.settings.llm_timeout_s)
            except TimeoutError as e:
                self._trace(ctx, req, None, started, f"timeout after {self.settings.llm_timeout_s:.0f}s")
                raise LLMError(f"model call timed out after {self.settings.llm_timeout_s:.0f}s", retryable=True) from e
            except LLMError as e:
                self._trace(ctx, req, None, started, str(e))
                raise
            self._trace(ctx, req, resp, started, "")
            if not resp.text.strip():
                raise LLMError("model returned an empty response", retryable=True)
            return resp

    def _trace(
        self, ctx: CallContext, req: LLMRequest, resp: LLMResponse | None, started: float, error: str
    ) -> None:
        if self.store is None:
            return
        try:
            self.store.add_llm_call(
                project_id=ctx.project_id,
                task_id=ctx.task_id,
                role=ctx.role,
                provider=self.provider.name,
                model=resp.model if resp else req.model,
                purpose=req.purpose,
                input_tokens=resp.input_tokens if resp else 0,
                output_tokens=resp.output_tokens if resp else 0,
                latency_ms=int((time.monotonic() - started) * 1000),
                ok=resp is not None and not error,
                error=error,
                prompt_preview=truncate(req.prompt, 4000),
                response_text=resp.text if resp else "",
            )
        except Exception:  # noqa: BLE001 - tracing must never break a run
            log.exception("failed to record LLM trace")
