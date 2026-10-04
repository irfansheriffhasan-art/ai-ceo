"""Local models through Ollama (default provider)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import ollama

from .base import LLMError, LLMProvider, LLMRequest, LLMResponse


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, host: str, num_ctx: int, timeout_s: float):
        self.host = host
        self.num_ctx = num_ctx
        self.client = ollama.AsyncClient(host=host, timeout=timeout_s)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        messages = [
            {"role": "system", "content": req.system},
            {"role": "user", "content": req.prompt},
        ]
        options = {
            "num_ctx": self.num_ctx,
            "temperature": req.temperature,
            "num_predict": req.max_tokens,
        }
        started = time.monotonic()
        text_parts: list[str] = []
        chunks = 0
        final: Any = None
        try:
            stream = await self.client.chat(
                model=req.model,
                messages=messages,
                format=req.json_schema,
                options=options,
                stream=True,
            )
            async for part in stream:
                text_parts.append(part.message.content or "")
                chunks += 1
                if req.on_progress and chunks % 25 == 0:
                    req.on_progress(chunks)
                if part.done:
                    final = part
        except ollama.ResponseError as e:
            if e.status_code == 404:
                raise LLMError(
                    f"Ollama model '{req.model}' is not installed",
                    retryable=False,
                    hint=f"run: ollama pull {req.model}",
                ) from e
            raise LLMError(f"Ollama error {e.status_code}: {e.error}", retryable=e.status_code >= 500) from e
        except (ConnectionError, httpx.ConnectError) as e:
            raise LLMError(
                f"Cannot reach Ollama at {self.host}", retryable=True, hint="is `ollama serve` running?"
            ) from e
        except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError) as e:
            raise LLMError(f"Ollama transport error: {type(e).__name__}", retryable=True) from e

        text = "".join(text_parts)
        return LLMResponse(
            text=text,
            model=req.model,
            provider=self.name,
            input_tokens=getattr(final, "prompt_eval_count", 0) or 0,
            output_tokens=getattr(final, "eval_count", 0) or chunks,
            latency_s=time.monotonic() - started,
            truncated=getattr(final, "done_reason", "") == "length",
        )

    async def health(self) -> dict[str, Any]:
        try:
            listing = await self.client.list()
        except Exception as e:  # noqa: BLE001 - health must never raise
            return {"ok": False, "detail": f"Cannot reach Ollama at {self.host}: {type(e).__name__}", "models": []}
        models = [m.model for m in listing.models if m.model]
        return {"ok": True, "detail": f"{len(models)} local models", "models": models}

    @staticmethod
    def has_model(models: list[str], wanted: str) -> bool:
        if ":" not in wanted:
            wanted = f"{wanted}:latest"
        return wanted in models
