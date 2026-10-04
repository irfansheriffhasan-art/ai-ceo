"""Authentication for the dashboard API.

Single-operator model: one access token (generated on first run, stored in
``data/auth_token``). Browsers exchange it for an HttpOnly, SameSite=Strict
session cookie; scripts can send ``Authorization: Bearer <token>``.

Cookie-authenticated state-changing requests must carry the
``X-AICEO-Request`` header and, when an Origin is sent, come from an
allowed origin. A custom header can't be added cross-site without a CORS
preflight, which this server refuses for unknown origins — so generated
apps running on other localhost ports can't drive the API with the
operator's cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

SESSION_COOKIE = "aiceo_session"
CSRF_HEADER = "x-aiceo-request"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class AuthManager:
    def __init__(self, token: str, allowed_origins: list[str], max_failures: int = 10, window_s: int = 300):
        if len(token) < 16:
            raise ValueError("auth token must be at least 16 characters")
        self._token = token.encode("utf-8")
        self.session_value = hmac.new(self._token, b"aiceo-session-v1", hashlib.sha256).hexdigest()
        self.allowed_origins = set(allowed_origins)
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def check_token(self, candidate: str) -> bool:
        return hmac.compare_digest(candidate.encode("utf-8"), self._token)

    # ---- login throttling --------------------------------------------------------------
    def _recent(self, client: str) -> deque[float]:
        q = self._failures[client]
        cutoff = time.monotonic() - self.window_s
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def throttled(self, client: str) -> bool:
        return len(self._recent(client)) >= self.max_failures

    def record_failure(self, client: str) -> None:
        self._recent(client).append(time.monotonic())

    def clear_failures(self, client: str) -> None:
        self._failures.pop(client, None)

    # ---- request checks --------------------------------------------------------------------
    def authenticate(self, request: Request) -> str:
        """Return the auth method ('bearer' | 'cookie') or raise 401."""
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer ") and self.check_token(header[7:].strip()):
            return "bearer"
        cookie = request.cookies.get(SESSION_COOKIE, "")
        if cookie and hmac.compare_digest(cookie, self.session_value):
            return "cookie"
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")

    def check_csrf(self, request: Request, method: str) -> None:
        if request.method in SAFE_METHODS or method == "bearer":
            return
        if request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "missing X-AICEO-Request header")
        origin = request.headers.get("origin")
        if origin and not self._origin_allowed(origin, request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-origin request rejected")

    def _origin_allowed(self, origin: str, request: Request) -> bool:
        if origin in self.allowed_origins:
            return True
        host = request.headers.get("host", "")
        return origin in (f"http://{host}", f"https://{host}")
