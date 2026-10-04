"""REST + SSE endpoints for the command-center dashboard."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..memory import ProjectMemory
from ..orchestrator import Engine
from ..services import Services
from ..workspace import GitRepo, Workspace
from ..workspace.analysis import analyze_repository, search
from .auth import SESSION_COOKIE, AuthManager

public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api")

_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9_\-]+\.(png|log)$")


# ---- dependencies ------------------------------------------------------------------------
def get_auth(request: Request) -> AuthManager:
    return request.app.state.auth


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def require_auth(request: Request) -> None:
    auth: AuthManager = request.app.state.auth
    method = auth.authenticate(request)
    auth.check_csrf(request, method)


# ---- request bodies -----------------------------------------------------------------------
class LoginIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ProjectIn(BaseModel):
    objective: str = Field(min_length=5, max_length=4000)
    name: str | None = Field(default=None, max_length=80)
    require_approval: bool = False
    max_fix_iterations: int | None = Field(default=None, ge=0, le=10)
    app_type: Literal["auto", "static_web", "web_with_backend"] = "auto"
    auto_start: bool = True


class FeedbackIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class RollbackIn(BaseModel):
    commit: str = Field(min_length=4, max_length=40, pattern=r"^[0-9a-fA-F]+$")


class ReassignIn(BaseModel):
    role: str = Field(min_length=2, max_length=32)


class ContinueIn(BaseModel):
    extra_iterations: int = Field(default=2, ge=1, le=5)


# ---- public ----------------------------------------------------------------------------------
@public.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


@public.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, auth: AuthManager = Depends(get_auth)) -> dict[str, Any]:
    client = request.client.host if request.client else "unknown"
    if auth.throttled(client):
        raise HTTPException(429, "too many failed attempts; try again later")
    if not auth.check_token(body.token.strip()):
        auth.record_failure(client)
        raise HTTPException(401, "invalid access token")
    auth.clear_failures(client)
    response.set_cookie(
        SESSION_COOKIE,
        auth.session_value,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=7 * 24 * 3600,
        path="/",
    )
    return {"authenticated": True}


@public.post("/auth/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}


@public.get("/auth/session")
def session(request: Request, auth: AuthManager = Depends(get_auth)) -> dict[str, Any]:
    try:
        auth.authenticate(request)
        return {"authenticated": True}
    except HTTPException:
        return {"authenticated": False}


# ---- system & agents -------------------------------------------------------------------------
@router.get("/system")
async def system(services: Services = Depends(get_services)) -> dict[str, Any]:
    return {"version": __version__, **(await services.system_status())}


@router.get("/agents")
def agents(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    return services.tracker.snapshot()


# ---- projects ----------------------------------------------------------------------------------
@router.get("/projects")
def list_projects(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    out = []
    for p in services.store.list_projects():
        d = p.to_dict()
        d["preview_url"] = services.previews.url(p.id)
        out.append(d)
    return out


@router.post("/projects", status_code=201)
async def create_project(body: ProjectIn, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    settings: dict[str, Any] = {"require_approval": body.require_approval}
    if body.max_fix_iterations is not None:
        settings["max_fix_iterations"] = body.max_fix_iterations
    if body.app_type != "auto":
        settings["app_type"] = body.app_type
    project = engine.create_project(body.objective, body.name, settings)
    if body.auto_start:
        await engine.start(project.id)
    return engine.snapshot(project.id)


@router.get("/projects/{pid}")
def get_project(pid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    return engine.snapshot(pid)


@router.post("/projects/{pid}/start")
async def start(pid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.start(pid)
    return engine.snapshot(pid)


@router.post("/projects/{pid}/pause")
async def pause(pid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.pause(pid)
    return engine.snapshot(pid)


@router.post("/projects/{pid}/resume")
async def resume(pid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.resume(pid)
    return engine.snapshot(pid)


@router.post("/projects/{pid}/stop")
async def stop(pid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.stop(pid)
    return engine.snapshot(pid)


@router.post("/projects/{pid}/approve")
async def approve(pid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.approve(pid)
    return engine.snapshot(pid)


@router.post("/projects/{pid}/reject")
async def reject(pid: str, body: FeedbackIn, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.reject(pid, body.message)
    return engine.snapshot(pid)


@router.post("/projects/{pid}/feedback")
async def feedback(pid: str, body: FeedbackIn, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.feedback(pid, body.message)
    return engine.snapshot(pid)


@router.post("/projects/{pid}/continue")
async def continue_fixing(pid: str, body: ContinueIn, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.continue_fixing(pid, body.extra_iterations)
    return engine.snapshot(pid)


@router.post("/projects/{pid}/rollback")
async def rollback(pid: str, body: RollbackIn, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    result = await engine.rollback(pid, body.commit.lower())
    return {**engine.snapshot(pid), "rollback": result}


@router.post("/projects/{pid}/preview")
async def start_preview(pid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.start_preview(pid)
    return engine.snapshot(pid)


@router.delete("/projects/{pid}/preview")
async def stop_preview(pid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    await engine.stop_preview(pid)
    return engine.snapshot(pid)


# ---- project data -----------------------------------------------------------------------------
def _project_paths(services: Services, pid: str) -> tuple[Workspace, GitRepo]:
    p = services.store.get_project(pid)
    if p is None:
        raise KeyError(pid)
    root = Path(p.workspace_path)
    return Workspace(root), GitRepo(root)


@router.get("/projects/{pid}/events")
def events(
    pid: str,
    after: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    return [e.to_dict() for e in services.store.list_events(pid, after_id=after, limit=limit)]


@router.get("/projects/{pid}/memory")
def memory(pid: str, services: Services = Depends(get_services)) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in ProjectMemory(services.store, pid).all():
        grouped.setdefault(item["kind"], []).append(item)
    return grouped


@router.get("/projects/{pid}/reports")
def reports(pid: str, kind: str | None = None, services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    return [r.to_dict() for r in services.store.list_reports(pid, kind)]


@router.get("/projects/{pid}/llm-calls")
def llm_calls(pid: str, services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    return [c.to_dict() for c in services.store.list_llm_calls(pid)]


@router.get("/llm-calls/{call_id}")
def llm_call(call_id: int, services: Services = Depends(get_services)) -> dict[str, Any]:
    c = services.store.get_llm_call(call_id)
    if c is None:
        raise KeyError(call_id)
    return c.to_dict(include_response=True)


@router.get("/projects/{pid}/files")
async def files(pid: str, services: Services = Depends(get_services)) -> list[dict[str, Any]]:
    ws, _ = _project_paths(services, pid)
    return await asyncio.to_thread(ws.tree)


@router.get("/projects/{pid}/files/content")
async def file_content(pid: str, path: str = Query(min_length=1, max_length=200), services: Services = Depends(get_services)) -> dict[str, Any]:
    ws, _ = _project_paths(services, pid)
    if not ws.exists(path):
        raise KeyError(path)
    return {"path": path, "content": await asyncio.to_thread(ws.read, path)}


@router.get("/projects/{pid}/commits")
async def commits(pid: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    _, repo = _project_paths(services, pid)
    log = await asyncio.to_thread(repo.log, 100)
    branch = await asyncio.to_thread(repo.current_branch)
    tags = await asyncio.to_thread(repo.tags)
    return {"branch": branch, "tags": tags, "commits": [c.to_dict() for c in log]}


@router.get("/projects/{pid}/commits/{sha}")
async def commit_diff(pid: str, sha: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    _, repo = _project_paths(services, pid)
    return {"sha": sha, "diff": await asyncio.to_thread(repo.show, sha)}


@router.get("/projects/{pid}/analysis")
async def analysis(pid: str, services: Services = Depends(get_services)) -> dict[str, Any]:
    ws, _ = _project_paths(services, pid)
    return analyze_repository(await asyncio.to_thread(ws.read_all))


@router.get("/projects/{pid}/search")
async def code_search(
    pid: str,
    q: str = Query(min_length=1, max_length=200),
    regex: bool = False,
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    ws, _ = _project_paths(services, pid)
    return search(await asyncio.to_thread(ws.read_all), q, regex=regex)


@router.get("/projects/{pid}/artifacts/{name}")
def artifact(pid: str, name: str, services: Services = Depends(get_services)) -> FileResponse:
    if not _ARTIFACT_NAME.match(name) or not re.match(r"^[a-f0-9]{12}$", pid):
        raise HTTPException(400, "invalid artifact name")
    path = services.settings.artifacts_dir / pid / name
    if not path.is_file():
        raise KeyError(name)
    return FileResponse(path)


@router.get("/projects/{pid}/download")
def download(pid: str, services: Services = Depends(get_services)) -> FileResponse:
    p = services.store.get_project(pid)
    if p is None:
        raise KeyError(pid)
    zips = sorted(services.settings.releases_dir.glob(f"*-{pid}-*.zip"), key=lambda f: f.stat().st_mtime)
    if not zips:
        raise HTTPException(404, "no release has been packaged yet")
    return FileResponse(zips[-1], filename=zips[-1].name, media_type="application/zip")


# ---- tasks ----------------------------------------------------------------------------------------
@router.get("/tasks/{tid}")
def task_detail(tid: str, services: Services = Depends(get_services), engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    t = services.store.get_task(tid)
    if t is None:
        raise KeyError(tid)
    calls = [c.to_dict() for c in services.store.list_llm_calls(t.project_id, limit=500) if c.task_id == tid]
    evts = [e.to_dict() for e in services.store.list_events(t.project_id, limit=1000) if e.task_id == tid]
    return {**t.to_dict(), "llm_calls": calls, "events": evts, "reassign_options": engine.task_kinds_for_reassign(tid)}


@router.post("/tasks/{tid}/retry")
async def retry_task(tid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    return (await engine.retry_task(tid)).to_dict()


@router.post("/tasks/{tid}/cancel")
async def cancel_task(tid: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    return (await engine.cancel_task(tid)).to_dict()


@router.post("/tasks/{tid}/reassign")
async def reassign_task(tid: str, body: ReassignIn, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
    return (await engine.reassign_task(tid, body.role)).to_dict()


# ---- live stream ----------------------------------------------------------------------------------
@router.get("/stream")
async def stream(request: Request, project_id: str | None = None, services: Services = Depends(get_services)) -> StreamingResponse:
    queue = services.events.subscribe()

    async def gen() -> AsyncIterator[str]:
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if project_id and ev.get("project_id") not in (project_id, None):
                    continue
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        finally:
            services.events.unsubscribe(queue)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
