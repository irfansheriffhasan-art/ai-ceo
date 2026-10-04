"""Local servers used for testing and previews of generated apps.

- ``StaticServer`` serves a directory on 127.0.0.1, refusing dot-paths so
  ``.git`` and similar can never be fetched.
- ``BackendProcess`` runs a generated FastAPI backend in a subprocess with a
  scrubbed environment (no API keys/tokens are inherited), bound to
  localhost, with its own throwaway database.
"""

from __future__ import annotations

import functools
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

_SENSITIVE_ENV = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _SafeHandler(SimpleHTTPRequestHandler):
    def send_head(self):  # type: ignore[override]
        path = unquote(urlsplit(self.path).path)
        if any(seg.startswith(".") for seg in path.split("/") if seg) or "__pycache__" in path:
            self.send_error(404)
            return None
        return super().send_head()

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


class StaticServer:
    def __init__(self, root: Path, port: int = 0):
        handler = functools.partial(_SafeHandler, directory=str(root))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def start(self) -> StaticServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self) -> StaticServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


class BackendStartError(RuntimeError):
    def __init__(self, message: str, log_tail: str):
        super().__init__(message)
        self.log_tail = log_tail


def scrubbed_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in _SENSITIVE_ENV)}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
    env.update(extra or {})
    return env


class BackendProcess:
    """Runs ``uvicorn backend.main:app`` from a generated project's root."""

    def __init__(
        self, root: Path, log_path: Path, port: int | None = None, db_path: Path | None = None, fresh_db: bool = True
    ):
        self.root = root
        self.port = port or free_port()
        self.log_path = log_path
        self.db_path = db_path or (log_path.parent / f"app-{self.port}.db")
        self.fresh_db = fresh_db
        self.proc: subprocess.Popen[bytes] | None = None
        self._log_file = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout_s: float = 25.0) -> str:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.fresh_db and self.db_path.exists():
            self.db_path.unlink()
        self._log_file = open(self.log_path, "wb")  # noqa: SIM115 - closed in stop()
        cmd = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(self.port)]
        self.proc = subprocess.Popen(
            cmd,
            cwd=self.root,
            env=scrubbed_env({"APP_DB_PATH": str(self.db_path), "PYTHONPATH": str(self.root)}),
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.stop()
                raise BackendStartError(f"backend exited with code {self.proc.returncode}", self.log_tail())
            try:
                r = httpx.get(self.url + "/", timeout=1.5)
                if r.status_code < 500:
                    return self.url
            except httpx.HTTPError:
                pass
            time.sleep(0.4)
        self.stop()
        raise BackendStartError(f"backend did not respond within {timeout_s:.0f}s", self.log_tail())

    def log_tail(self, max_chars: int = 3000) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
        except OSError:
            return ""

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    def __enter__(self) -> BackendProcess:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
