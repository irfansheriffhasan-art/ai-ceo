"""Logging setup: readable console output plus a rotating JSON-lines file."""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("project_id", "task_id", "agent"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def setup_logging(logs_dir: Path, level: str = "INFO", console: bool = True) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("ai_ceo")
    root.setLevel(level)
    root.propagate = False

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "aiceo.jsonl", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
        root.addHandler(stream)

    # Third-party HTTP clients are noisy at INFO.
    for noisy in ("httpx", "httpcore", "anthropic", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ai_ceo.{name}")
