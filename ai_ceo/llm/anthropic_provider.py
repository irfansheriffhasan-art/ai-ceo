"""Claude through the Anthropic API (optional; enabled with ANTHROPIC_API_KEY).

Uses streaming so long code generations never hit HTTP timeouts, structured
outputs (``output_config.format``) for JSON tasks, and server-side refusal
fallbacks. Thinking is adaptive by default on current models; depth is
controlled with ``effort``.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from .base import LLMError, LLMProvider, LLMRequest, LLMResponse

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, effort: str, timeout_s: float, max_retries: int = 1):
        # api_key=None lets the SDK resolve credentials itself (env var or `ant auth login` profile).
        self.client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_s, max_retries=max_retries)
        self.effort = effort

    async def complete(self, req: LLMRequest) -> LLMResponse:
        output_config: dict[str, Any] = {"effort": self.effort}
        if req.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": req.json_schema}
        started = time.monotonic()
        try:
            async with self.client.beta.messages.stream(
                model=req.model,
                # Adaptive thinking shares this budget, so leave generous headroom over the visible output.
                max_tokens=max(req.max_tokens * 4, 16000),
                system=req.system,
                messages=[{"role": "user", "content": req.prompt}],
                output_config=output_config,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                produced = 0
                async for chunk in stream.text_stream:
                    produced += max(1, len(chunk) // 4)
                    if req.on_progress:
                        req.on_progress(produced)
                message = await stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMError("Anthropic authentication failed", retryable=False, hint="check ANTHROPIC_API_KEY") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError("Anthropic API key lacks permission", retryable=False) from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Anthropic model '{req.model}' not found", retryable=False) from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Anthropic rejected the request: {e.message}", retryable=False) from e
        except anthropic.RateLimitError as e:
            raise LLMError("Anthropic rate limit", retryable=True) from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}", retryable=e.status_code >= 500) from e
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            raise LLMError("Cannot reach the Anthropic API", retryable=True) from e

        if message.stop_reason == "refusal":
            raise LLMError("Claude declined this request", retryable=False)
        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=message.model,
            provider=self.name,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_s=time.monotonic() - started,
            truncated=message.stop_reason == "max_tokens",
        )

    async def health(self) -> dict[str, Any]:
        try:
            await self.client.models.retrieve(DEFAULT_MODEL)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"Anthropic API unavailable: {type(e).__name__}"}
        return {"ok": True, "detail": "Anthropic API reachable"}

    async def aclose(self) -> None:
        await self.client.close()
