"""API: authentication, CSRF/origin protection, controls, data endpoints and the live SSE stream."""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from ai_ceo.api import create_app
from ai_ceo.llm.mock_provider import MockProvider
from ai_ceo.verification.servers import free_port

TOKEN = "test-token-0123456789abcdef"
H = {"X-AICEO-Request": "1"}


@pytest.fixture
def client(settings):
    app = create_app(settings.model_copy(update={"browser_channel": "none"}), provider=MockProvider(delay_s=0.0))
    with TestClient(app) as c:
        yield c


def login(c):
    assert c.post("/api/auth/login", json={"token": TOKEN}).status_code == 200


def wait_status(c, pid, statuses, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = c.get(f"/api/projects/{pid}").json()
        if snap["project"]["status"] in statuses:
            return snap
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {statuses}")


def test_auth_required_and_login(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/auth/login", json={"token": "wrong"}).status_code == 401
    login(client)
    assert client.get("/api/projects").status_code == 200
    cookie = client.cookies.get("aiceo_session")
    assert cookie and TOKEN not in cookie, "the session cookie must not contain the raw token"
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/projects").status_code == 401


def test_bearer_token_and_login_throttle(client):
    assert client.get("/api/agents", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    for _ in range(10):
        client.post("/api/auth/login", json={"token": "nope"})
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 429


def test_csrf_and_origin_protection(client):
    login(client)
    body = {"objective": "Build a todo app", "auto_start": False}
    assert client.post("/api/projects", json=body).status_code == 403, "cookie auth without CSRF header"
    assert client.post("/api/projects", json=body, headers={**H, "Origin": "http://127.0.0.1:5555"}).status_code == 403
    assert client.post("/api/projects", json=body, headers={**H, "Origin": "http://testserver"}).status_code == 201
    # Bearer clients (scripts) are not CSRF-prone and don't need the header.
    assert client.post("/api/projects", json=body, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 201


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_input_validation(client):
    login(client)
    assert client.post("/api/projects", json={"objective": "hi"}, headers=H).status_code == 422
    assert client.post("/api/projects", json={"objective": "x" * 5000}, headers=H).status_code == 422
    assert client.post("/api/projects", json={"objective": "ok app", "max_fix_iterations": 50}, headers=H).status_code == 422


def test_lifecycle_and_data_endpoints(client):
    login(client)
    r = client.post("/api/projects", json={"objective": "Build a todo app", "require_approval": True}, headers=H)
    assert r.status_code == 201
    pid = r.json()["project"]["id"]
    snap = wait_status(client, pid, {"awaiting_approval"})
    assert snap["counts"]["completed"] >= 10 and len(snap["agents"]) == 14

    assert client.post(f"/api/projects/{pid}/pause", headers=H).status_code == 409, "cannot pause while awaiting approval"
    assert client.post(f"/api/projects/{pid}/approve", headers=H).status_code == 200
    snap = wait_status(client, pid, {"completed"})
    assert snap["project"]["preview_url"]

    files = [f["path"] for f in client.get(f"/api/projects/{pid}/files").json()]
    assert {"index.html", "app.js", "style.css", "README.md", "Dockerfile"} <= set(files)
    assert "localStorage" in client.get(f"/api/projects/{pid}/files/content", params={"path": "app.js"}).json()["content"]
    for bad in ("../../aiceo.db", ".git/config", "C:/Windows/win.ini"):
        assert client.get(f"/api/projects/{pid}/files/content", params={"path": bad}).status_code in (400, 404)

    commits = client.get(f"/api/projects/{pid}/commits").json()
    assert commits["tags"] == ["v1.0.0"] and len(commits["commits"]) >= 8
    assert "diff --git" in client.get(f"/api/projects/{pid}/commits/{commits['commits'][1]['sha']}").json()["diff"]
    assert client.get(f"/api/projects/{pid}/analysis").json()["dependencies"]
    assert client.get(f"/api/projects/{pid}/search", params={"q": "localStorage"}).json()
    mem = client.get(f"/api/projects/{pid}/memory").json()
    assert {"requirements", "architecture", "decision", "design"} <= set(mem)
    assert {r["kind"] for r in client.get(f"/api/projects/{pid}/reports").json()} >= {"test", "security", "review", "deploy"}
    calls = client.get(f"/api/projects/{pid}/llm-calls").json()
    assert calls and "response_text" in client.get(f"/api/llm-calls/{calls[0]['id']}").json()
    assert client.get(f"/api/projects/{pid}/download").headers["content-type"] == "application/zip"
    assert client.get(f"/api/projects/{pid}/artifacts/..%2Faiceo.db").status_code in (400, 404)

    task = snap["tasks"][0]
    detail = client.get(f"/api/tasks/{task['id']}").json()
    assert detail["reassign_options"] == ["ceo"] and detail["llm_calls"]
    assert client.post(f"/api/tasks/{task['id']}/retry", headers=H).status_code == 409
    assert client.delete(f"/api/projects/{pid}/preview", headers=H).status_code == 200


def test_live_event_stream_over_real_http(settings):
    """Run the real server and read Server-Sent Events while a project executes."""
    app = create_app(settings.model_copy(update={"browser_channel": "none"}), provider=MockProvider(delay_s=0.02))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(base + "/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        auth = {"Authorization": f"Bearer {TOKEN}"}
        seen: list[dict] = []
        with httpx.Client(base_url=base, headers=auth, timeout=30) as c:
            pid = c.post("/api/projects", json={"objective": "Build a todo app"}).json()["project"]["id"]
            with c.stream("GET", f"/api/stream?project_id={pid}") as stream:
                for line in stream.iter_lines():
                    if line.startswith("data: "):
                        seen.append(json.loads(line[6:]))
                        if any(e["type"] == "project_completed" for e in seen):
                            break
        types = {e["type"] for e in seen}
        assert {"task_started", "task_completed", "ceo_decision", "project_completed"} <= types
        assert all(e["project_id"] in (pid, None) for e in seen)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
