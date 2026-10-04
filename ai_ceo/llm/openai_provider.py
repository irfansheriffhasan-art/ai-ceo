"""OpenAI (or any OpenAI-compatible server via AICEO_OPENAI_BASE_URL). Optional."""

from __future__ import annotations

import time
from typing import Any

import openai

from .base import LLMError, LLMProvider, LLMRequest, LLMResponse


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None, base_url: str | None, timeout_s: float):
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=1)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.prompt},
            ],
            "max_completion_tokens": req.max_tokens,
        }
        if req.json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": req.json_schema, "strict": True},
            }
        started = time.monotonic()
        try:
            resp = await self.client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as e:
            raise LLMError("OpenAI authentication failed", retryable=False, hint="check OPENAI_API_KEY") from e
        except openai.NotFoundError as e:
            raise LLMError(f"OpenAI model '{req.model}' not found", retryable=False) from e
        except openai.BadRequestError as e:
            raise LLMError(f"OpenAI rejected the request: {e.message}", retryable=False) from e
        except openai.RateLimitError as e:
            raise LLMError("OpenAI rate limit", retryable=True) from e
        except openai.APIStatusError as e:
            raise LLMError(f"OpenAI API error {e.status_code}", retryable=e.status_code >= 500) from e
        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            raise LLMError("Cannot reach the OpenAI API", retryable=True) from e

        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=resp.model,
            provider=self.name,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_s=time.monotonic() - started,
            truncated=choice.finish_reason == "length",
        )

    async def health(self) -> dict[str, Any]:
        try:
            await self.client.models.list()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"OpenAI API unavailable: {type(e).__name__}"}
        return {"ok": True, "detail": "OpenAI API reachable"}

    async def aclose(self) -> None:
        await self.client.close()
