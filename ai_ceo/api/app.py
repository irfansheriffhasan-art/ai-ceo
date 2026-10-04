"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import Settings, get_settings
from ..llm import LLMProvider
from ..log import get_logger, setup_logging
from ..orchestrator import ControlError, Engine
from ..services import Services
from ..workspace import GitError, UnsafePathError
from .auth import AuthManager
from .routes import public, require_auth, router

log = get_logger("api")

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

DASHBOARD_MISSING = """<!doctype html><meta charset="utf-8"><title>AI-CEO</title>
<body style="font-family:system-ui;max-width:640px;margin:4rem auto;line-height:1.5">
<h1>AI-CEO API is running</h1>
<p>The dashboard has not been built yet. Build it once with:</p>
<pre>cd web
npm install
npm run build</pre>
<p>then reload this page. The API is available under <code>/api</code>.</p></body>"""


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(settings.logs_dir)
        services = Services(settings, provider)
        engine = Engine(services)
        engine.recover()
        app.state.services = services
        app.state.engine = engine
        log.info("AI-CEO API ready (provider=%s, model=%s)", services.llm.provider_name, services.llm.model_for("frontend"))
        yield
        await engine.shutdown()

    app = FastAPI(title="AI-CEO", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.auth = AuthManager(settings.resolve_auth_token(), settings.cors_origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-AICEO-Request"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # noqa: ANN001, ANN202
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    @app.exception_handler(KeyError)
    async def not_found(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": f"not found: {exc.args[0] if exc.args else ''}"}, status_code=404)

    @app.exception_handler(ControlError)
    async def conflict(_: Request, exc: ControlError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(GitError)
    @app.exception_handler(UnsafePathError)
    @app.exception_handler(ValueError)
    async def bad_request(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    app.include_router(public)
    app.include_router(router, dependencies=[Depends(require_auth)])

    dist = settings.web_dist_dir
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "not found")
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        async def placeholder() -> HTMLResponse:
            return HTMLResponse(DASHBOARD_MISSING)

    return app
