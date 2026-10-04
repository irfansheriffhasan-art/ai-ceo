"""Deterministic offline provider for tests, CI and demos (AICEO_LLM_PROVIDER=mock).

It answers each agent with realistic, working output for one of two apps:
a localStorage task tracker (static) or a notes app with a FastAPI backend
(when the request mentions an API/server/database). With ``inject_bug`` the
first app.js has a logic bug (the task counter never updates) that passes
syntax and id checks but fails a browser acceptance test, so the full
QA -> CEO -> fix -> regression-test loop is exercised.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from .base import LLMError, LLMProvider, LLMRequest, LLMResponse

_BACKEND_HINT = re.compile(r"\b(api|backend|server|database|multi-?user|rest)\b", re.I)


# ---------------------------------------------------------------------------------------
# Static app: task tracker
# ---------------------------------------------------------------------------------------
STATIC_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Task Tracker</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="app-header">
    <h1>Task Tracker</h1>
    <p id="task-count" class="task-count">0 tasks remaining</p>
  </header>
  <main class="container">
    <form id="task-form" class="task-form">
      <label for="task-input" class="visually-hidden">New task</label>
      <input id="task-input" type="text" placeholder="What needs to be done?" autocomplete="off">
      <button id="add-btn" type="submit">Add</button>
    </form>
    <section class="filters" aria-label="Filter tasks">
      <button id="filter-all" class="filter active" type="button">All</button>
      <button id="filter-active" class="filter" type="button">Active</button>
      <button id="filter-done" class="filter" type="button">Done</button>
    </section>
    <ul id="task-list" class="task-list"></ul>
    <p id="empty-state" class="empty-state">No tasks yet. Add your first one above.</p>
  </main>
  <script src="app.js" defer></script>
</body>
</html>
"""

STATIC_CSS = """:root {
  --primary: #4f46e5;
  --primary-dark: #4338ca;
  --background: #f5f7fb;
  --surface: #ffffff;
  --text: #1f2937;
  --muted: #6b7280;
  --accent: #10b981;
  --danger: #ef4444;
  --radius: 12px;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--background);
  color: var(--text);
}
.app-header { background: var(--primary); color: #fff; padding: 2rem 1rem; text-align: center; }
.app-header h1 { margin: 0 0 .25rem; }
.task-count { margin: 0; opacity: .9; }
.container { max-width: 640px; margin: -1.5rem auto 2rem; padding: 0 1rem; }
.task-form { display: flex; gap: .5rem; background: var(--surface); padding: .75rem; border-radius: var(--radius); box-shadow: 0 4px 16px rgba(0,0,0,.08); }
.task-form input { flex: 1; padding: .75rem; border: 1px solid #d1d5db; border-radius: 8px; font-size: 1rem; }
button { cursor: pointer; border: none; border-radius: 8px; padding: .75rem 1rem; font-size: 1rem; }
#add-btn { background: var(--primary); color: #fff; }
#add-btn:hover { background: var(--primary-dark); }
button:focus-visible, input:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
.filters { display: flex; gap: .5rem; margin: 1rem 0; }
.filter { background: var(--surface); color: var(--muted); }
.filter.active { background: var(--primary); color: #fff; }
.task-list { list-style: none; padding: 0; margin: 0; }
.task-item { display: flex; align-items: center; gap: .75rem; background: var(--surface); padding: .75rem 1rem; border-radius: var(--radius); margin-bottom: .5rem; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.task-item.done .task-text { text-decoration: line-through; color: var(--muted); }
.task-text { flex: 1; }
.delete-btn { background: transparent; color: var(--danger); padding: .25rem .5rem; }
.empty-state { text-align: center; color: var(--muted); }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
@media (max-width: 480px) { .task-form { flex-direction: column; } }
"""

_STATIC_JS = """const STORAGE_KEY = 'task-tracker.tasks';
const form = document.getElementById('task-form');
const input = document.getElementById('task-input');
const list = document.getElementById('task-list');
const count = document.getElementById('task-count');
const emptyState = document.getElementById('empty-state');
const filterButtons = {
  all: document.getElementById('filter-all'),
  active: document.getElementById('filter-active'),
  done: document.getElementById('filter-done'),
};
let filter = 'all';

function loadTasks() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

let tasks = loadTasks();

function saveTasks() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
}

function updateCount() {
  const remaining = tasks.filter((t) => !t.done).length;
  count.textContent = `${remaining} ${remaining === 1 ? 'task' : 'tasks'} remaining`;
}

function render() {
  list.textContent = '';
  const visible = tasks.filter((t) => filter === 'all' || (filter === 'done' ? t.done : !t.done));
  for (const task of visible) {
    const li = document.createElement('li');
    li.className = 'task-item' + (task.done ? ' done' : '');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'task-toggle';
    checkbox.checked = task.done;
    checkbox.setAttribute('aria-label', 'Mark task as done');
    checkbox.addEventListener('change', () => {
      task.done = checkbox.checked;
      saveTasks();
      render();
    });
    const text = document.createElement('span');
    text.className = 'task-text';
    text.textContent = task.text;
    const del = document.createElement('button');
    del.className = 'delete-btn';
    del.type = 'button';
    del.textContent = 'Delete';
    del.addEventListener('click', () => {
      tasks = tasks.filter((t) => t.id !== task.id);
      saveTasks();
      render();
    });
    li.append(checkbox, text, del);
    list.appendChild(li);
  }
  emptyState.hidden = tasks.length > 0;
  /*COUNT*/
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const value = input.value.trim();
  if (!value) return;
  tasks.push({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), text: value, done: false });
  input.value = '';
  saveTasks();
  render();
});

for (const [name, button] of Object.entries(filterButtons)) {
  button.addEventListener('click', () => {
    filter = name;
    Object.values(filterButtons).forEach((b) => b.classList.remove('active'));
    button.classList.add('active');
    render();
  });
}

render();
"""

STATIC_JS_GOOD = _STATIC_JS.replace("/*COUNT*/", "updateCount();")
STATIC_JS_BUGGY = _STATIC_JS.replace("  /*COUNT*/\n", "")

STATIC_SCENARIOS = {
    "scenarios": [
        {
            "name": "Add a task",
            "criterion": "After typing a task and clicking Add, the task appears in the list",
            "steps": [
                {"action": "fill", "selector": "#task-input", "value": "Buy milk"},
                {"action": "click", "selector": "#add-btn", "value": ""},
                {"action": "expect_text", "selector": "#task-list", "value": "Buy milk"},
                {"action": "expect_count", "selector": ".task-item", "value": "1"},
            ],
        },
        {
            "name": "Remaining counter",
            "criterion": "The header shows how many tasks remain",
            "steps": [
                {"action": "fill", "selector": "#task-input", "value": "Write report"},
                {"action": "press", "selector": "#task-input", "value": "Enter"},
                {"action": "expect_text", "selector": "#task-count", "value": "1 task remaining"},
            ],
        },
        {
            "name": "Complete and filter",
            "criterion": "Completed tasks can be filtered",
            "steps": [
                {"action": "fill", "selector": "#task-input", "value": "Call mom"},
                {"action": "click", "selector": "#add-btn", "value": ""},
                {"action": "check", "selector": ".task-toggle", "value": ""},
                {"action": "click", "selector": "#filter-active", "value": ""},
                {"action": "expect_count", "selector": ".task-item", "value": "0"},
                {"action": "click", "selector": "#filter-done", "value": ""},
                {"action": "expect_count", "selector": ".task-item", "value": "1"},
            ],
        },
        {
            "name": "Delete a task",
            "criterion": "A task can be deleted",
            "steps": [
                {"action": "fill", "selector": "#task-input", "value": "Temporary"},
                {"action": "click", "selector": "#add-btn", "value": ""},
                {"action": "click", "selector": ".delete-btn", "value": ""},
                {"action": "expect_count", "selector": ".task-item", "value": "0"},
                {"action": "expect_visible", "selector": "#empty-state", "value": ""},
            ],
        },
    ]
}

# ---------------------------------------------------------------------------------------
# Backend app: notes
# ---------------------------------------------------------------------------------------
NOTES_SCHEMA = """CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

NOTES_MAIN = '''import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("APP_DB_PATH", "app.db")
BASE_DIR = Path(__file__).parent

app = FastAPI(title="Notes API")


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=10000)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8"))


init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/notes")
def list_notes() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, title, body, created_at FROM notes ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/notes", status_code=201)
def create_note(note: NoteIn) -> dict:
    with connect() as conn:
        cur = conn.execute("INSERT INTO notes (title, body) VALUES (?, ?)", (note.title.strip(), note.body))
        row = conn.execute("SELECT id, title, body, created_at FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int) -> dict:
    with connect() as conn:
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": note_id}


app.mount("/", StaticFiles(directory=BASE_DIR.parent / "frontend", html=True), name="frontend")
'''

NOTES_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Quick Notes</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="app-header"><h1>Quick Notes</h1></header>
  <main class="container">
    <form id="note-form" class="note-form">
      <label for="note-title">Title</label>
      <input id="note-title" type="text" placeholder="Note title" autocomplete="off">
      <label for="note-body">Note</label>
      <textarea id="note-body" rows="3" placeholder="Write something..."></textarea>
      <button id="save-btn" type="submit">Save note</button>
    </form>
    <p id="status" class="status" role="status"></p>
    <ul id="notes-list" class="notes-list"></ul>
  </main>
  <script src="app.js" defer></script>
</body>
</html>
"""

NOTES_CSS = """:root { --primary: #0f766e; --background: #f0fdfa; --surface: #ffffff; --text: #134e4a; --muted: #5f7f7a; --danger: #dc2626; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background: var(--background); color: var(--text); }
.app-header { background: var(--primary); color: #fff; padding: 1.5rem; text-align: center; }
.container { max-width: 680px; margin: 1.5rem auto; padding: 0 1rem; }
.note-form { display: grid; gap: .5rem; background: var(--surface); padding: 1rem; border-radius: 12px; box-shadow: 0 4px 14px rgba(0,0,0,.07); }
input, textarea { padding: .6rem; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }
button { cursor: pointer; border: none; border-radius: 8px; padding: .6rem 1rem; font: inherit; }
#save-btn { background: var(--primary); color: #fff; }
button:focus-visible, input:focus-visible, textarea:focus-visible { outline: 3px solid #f59e0b; outline-offset: 2px; }
.status { color: var(--muted); min-height: 1.2em; }
.notes-list { list-style: none; padding: 0; }
.note-item { background: var(--surface); border-radius: 12px; padding: 1rem; margin-bottom: .75rem; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.note-title { margin: 0 0 .25rem; }
.note-body { margin: 0 0 .5rem; white-space: pre-wrap; }
.delete-btn { background: transparent; color: var(--danger); padding: .25rem 0; }
"""

NOTES_JS = """const form = document.getElementById('note-form');
const titleInput = document.getElementById('note-title');
const bodyInput = document.getElementById('note-body');
const list = document.getElementById('notes-list');
const statusEl = document.getElementById('status');

function setStatus(message) {
  statusEl.textContent = message;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

function renderNotes(notes) {
  list.textContent = '';
  for (const note of notes) {
    const li = document.createElement('li');
    li.className = 'note-item';
    const title = document.createElement('h3');
    title.className = 'note-title';
    title.textContent = note.title;
    const body = document.createElement('p');
    body.className = 'note-body';
    body.textContent = note.body;
    const del = document.createElement('button');
    del.className = 'delete-btn';
    del.type = 'button';
    del.textContent = 'Delete';
    del.addEventListener('click', async () => {
      try {
        await api(`/api/notes/${note.id}`, { method: 'DELETE' });
        await loadNotes();
      } catch (e) {
        setStatus('Could not delete note.');
      }
    });
    li.append(title, body, del);
    list.appendChild(li);
  }
  setStatus(notes.length ? `${notes.length} note(s)` : 'No notes yet.');
}

async function loadNotes() {
  try {
    renderNotes(await api('/api/notes'));
  } catch (e) {
    setStatus('Could not load notes.');
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const title = titleInput.value.trim();
  if (!title) {
    setStatus('Please enter a title.');
    return;
  }
  try {
    await api('/api/notes', { method: 'POST', body: JSON.stringify({ title, body: bodyInput.value }) });
    titleInput.value = '';
    bodyInput.value = '';
    await loadNotes();
  } catch (e) {
    setStatus('Could not save note.');
  }
});

loadNotes();
"""

NOTES_SCENARIOS = {
    "scenarios": [
        {
            "name": "Create a note",
            "criterion": "After entering a title and clicking Save note, the note appears in the list",
            "steps": [
                {"action": "fill", "selector": "#note-title", "value": "Groceries"},
                {"action": "fill", "selector": "#note-body", "value": "Eggs and bread"},
                {"action": "click", "selector": "#save-btn", "value": ""},
                {"action": "expect_text", "selector": "#notes-list", "value": "Groceries"},
            ],
        },
        {
            "name": "Empty title is rejected",
            "criterion": "Saving without a title shows a message",
            "steps": [
                {"action": "click", "selector": "#save-btn", "value": ""},
                {"action": "expect_text", "selector": "#status", "value": "title"},
            ],
        },
    ]
}

NOTES_API_CASES = {
    "cases": [
        {"name": "health", "method": "GET", "path": "/api/health", "body_json": "", "expect_status": 200, "expect_contains": "ok"},
        {"name": "create note", "method": "POST", "path": "/api/notes", "body_json": '{"title": "First", "body": "hello"}', "expect_status": 201, "expect_contains": "First"},
        {"name": "list notes", "method": "GET", "path": "/api/notes", "body_json": "", "expect_status": 200, "expect_contains": "First"},
        {"name": "reject empty title", "method": "POST", "path": "/api/notes", "body_json": '{"title": ""}', "expect_status": 422, "expect_contains": ""},
        {"name": "delete note", "method": "DELETE", "path": "/api/notes/1", "body_json": "", "expect_status": 200, "expect_contains": "deleted"},
        {"name": "delete missing", "method": "DELETE", "path": "/api/notes/999", "body_json": "", "expect_status": 404, "expect_contains": ""},
    ]
}


def _fence(lang: str, code: str) -> str:
    return f"Here is the file:\n\n```{lang}\n{code}```\n"


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, inject_bug: bool = True, delay_s: float = 0.05, fail_tags: dict[str, int] | None = None):
        self.inject_bug = inject_bug
        self.delay_s = delay_s
        # tag substring -> number of times to fail first (for failure-recovery tests)
        self.fail_tags = dict(fail_tags or {})
        self.calls: list[str] = []
        self._served_buggy = False

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "detail": "mock provider (deterministic, offline)", "models": ["mock"]}

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req.tag)
        started = time.monotonic()
        for key, remaining in list(self.fail_tags.items()):
            if key in req.tag and remaining > 0:
                self.fail_tags[key] = remaining - 1
                raise LLMError(f"mock failure for {req.tag}", retryable=False)
        await asyncio.sleep(self.delay_s)
        if req.on_progress:
            req.on_progress(50)
        text = self._answer(req)
        return LLMResponse(
            text=text,
            model="mock",
            provider=self.name,
            input_tokens=len(req.prompt) // 4,
            output_tokens=len(text) // 4,
            latency_s=time.monotonic() - started,
        )

    def _answer(self, req: LLMRequest) -> str:
        tag = req.tag
        role, _, purpose = tag.partition(":")
        if purpose == "project charter":
            request = req.prompt.split('"""')[1] if req.prompt.count('"""') >= 2 else req.prompt
            backend = bool(_BACKEND_HINT.search(request))
        else:
            backend = any(m in req.prompt for m in ("APP TYPE: web_with_backend", "backend/main.py", 'id="note-title"'))
        if purpose == "project charter":
            return json.dumps(self._charter(backend))
        if purpose == "requirements":
            return json.dumps(self._requirements(backend))
        if purpose == "delivery strategy":
            return json.dumps(
                {
                    "milestones": [
                        {"name": "Core experience", "goal": "Create, list and delete items"},
                        {"name": "Polish", "goal": "Responsive design, empty states and accessibility"},
                    ],
                    "priorities": ["Working core flow", "Data persistence", "Accessible, responsive UI"],
                    "risks": ["Scope creep — keep to must-have features", "Data loss — validate and persist on every change"],
                    "definition_of_done": ["All acceptance tests pass", "No high-severity security findings", "Code review approved"],
                    "summary": "Ship the core flow first, then polish.",
                }
            )
        if purpose == "architecture":
            return json.dumps(self._architecture(backend))
        if purpose == "visual design":
            return json.dumps(
                {
                    "style_name": "Calm Indigo",
                    "palette": {
                        "primary": "#4f46e5",
                        "secondary": "#6366f1",
                        "background": "#f5f7fb",
                        "surface": "#ffffff",
                        "text": "#1f2937",
                        "accent": "#10b981",
                    },
                    "font_family": "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
                    "layout": "A coloured header with the title and counter, then a centred card with the input form and the list.",
                    "components": [
                        {"name": "header", "description": "title and live counter"},
                        {"name": "input form", "description": "text input with an Add button"},
                        {"name": "item list", "description": "cards with checkbox and delete"},
                    ],
                    "accessibility": ["Every input has a label", "Visible focus outlines", "WCAG AA contrast"],
                    "summary": "Clean, friendly and accessible.",
                }
            )
        if purpose.startswith(("write ", "fix ")):
            return self._code(role, purpose)
        if purpose == "browser test plan":
            return json.dumps(NOTES_SCENARIOS if backend else STATIC_SCENARIOS)
        if purpose == "API test plan":
            return json.dumps(NOTES_API_CASES)
        if purpose == "code review":
            return json.dumps(
                {
                    "approved": True,
                    "score": 8,
                    "issues": [
                        {
                            "severity": "minor",
                            "file": "frontend/app.js" if backend else "app.js",
                            "description": "Consider debouncing re-renders for very long lists.",
                            "suggestion": "Only re-render the changed item.",
                        }
                    ],
                    "strengths": ["User input is inserted with textContent", "Clear separation of state and rendering"],
                    "summary": "Solid, readable implementation that meets the requirements.",
                }
            )
        if purpose == "release decision":
            return json.dumps(
                {
                    "decision": "approve",
                    "unmet_criteria": [],
                    "release_notes": "A responsive app covering every must-have feature, checked by the automated test suite.",
                    "summary": "All quality gates passed.",
                }
            )
        raise LLMError(f"mock provider has no answer for '{tag}'", retryable=False)

    # ---- canned content ---------------------------------------------------------------
    @staticmethod
    def _charter(backend: bool) -> dict[str, Any]:
        if backend:
            return {
                "project_name": "Quick Notes",
                "objective": "A notes web app with a REST API and SQLite storage where users create, list and delete notes.",
                "app_type": "web_with_backend",
                "target_users": "People who want to capture quick notes",
                "constraints": ["Notes persist on the server", "Simple, fast UI"],
                "summary": "The request needs server-side persistence, so we build a FastAPI backend.",
            }
        return {
            "project_name": "Task Tracker",
            "objective": "A browser-based task tracker to add, complete, filter and delete tasks, saved in localStorage.",
            "app_type": "static_web",
            "target_users": "Individuals managing personal to-dos",
            "constraints": ["Works offline", "Mobile friendly"],
            "summary": "Everything can run in the browser, so a static app is simplest and most reliable.",
        }

    @staticmethod
    def _requirements(backend: bool) -> dict[str, Any]:
        if backend:
            return {
                "user_stories": ["As a user, I want to save a note with a title so that I remember it later."],
                "features": [
                    {"name": "Create note", "description": "Title and body saved via the API", "priority": "must"},
                    {"name": "List notes", "description": "Newest first", "priority": "must"},
                    {"name": "Delete note", "description": "Remove a note", "priority": "must"},
                ],
                "acceptance_criteria": [
                    "After entering a title and clicking Save note, the note appears in the list",
                    "Saving without a title shows a message",
                ],
                "out_of_scope": ["User accounts", "Rich text"],
                "summary": "A minimal notes app backed by an API.",
            }
        return {
            "user_stories": [
                "As a user, I want to add tasks so that I can track my work.",
                "As a user, I want to mark tasks done so that I see progress.",
            ],
            "features": [
                {"name": "Add task", "description": "Type a task and add it with the button or Enter", "priority": "must"},
                {"name": "Complete task", "description": "Toggle a task as done", "priority": "must"},
                {"name": "Delete task", "description": "Remove a task", "priority": "must"},
                {"name": "Filter", "description": "Show all, active or done tasks", "priority": "should"},
                {"name": "Counter", "description": "Show remaining tasks", "priority": "must"},
            ],
            "acceptance_criteria": [
                "After typing a task and clicking Add, the task appears in the list",
                "The header shows how many tasks remain",
                "Completed tasks can be filtered",
                "A task can be deleted",
            ],
            "out_of_scope": ["Accounts", "Sync across devices"],
            "summary": "A focused personal task tracker.",
        }

    @staticmethod
    def _architecture(backend: bool) -> dict[str, Any]:
        if backend:
            return {
                "needs_backend": True,
                "stack": {"frontend": "HTML/CSS/vanilla JS", "backend": "FastAPI", "storage": "SQLite"},
                "files": [
                    {"path": "backend/schema.sql", "purpose": "notes table", "owner_role": "database"},
                    {"path": "backend/main.py", "purpose": "REST API for notes and static hosting", "owner_role": "backend"},
                    {"path": "frontend/index.html", "purpose": "note form and list", "owner_role": "frontend"},
                    {"path": "frontend/style.css", "purpose": "styling", "owner_role": "frontend"},
                    {"path": "frontend/app.js", "purpose": "calls the API and renders notes", "owner_role": "frontend"},
                ],
                "data_model": [{"name": "notes", "fields": ["id", "title", "body", "created_at"]}],
                "api_endpoints": [
                    {"method": "GET", "path": "/api/health", "description": "health check"},
                    {"method": "GET", "path": "/api/notes", "description": "list notes"},
                    {"method": "POST", "path": "/api/notes", "description": "create a note"},
                    {"method": "DELETE", "path": "/api/notes/{id}", "description": "delete a note"},
                ],
                "decisions": [{"decision": "SQLite via stdlib", "rationale": "Zero setup, enough for a single server"}],
                "summary": "FastAPI + SQLite backend serving a vanilla JS frontend.",
            }
        return {
            "needs_backend": False,
            "stack": {"frontend": "HTML/CSS/vanilla JS", "backend": "none", "storage": "localStorage"},
            "files": [
                {"path": "index.html", "purpose": "page structure", "owner_role": "frontend"},
                {"path": "style.css", "purpose": "styling", "owner_role": "frontend"},
                {"path": "app.js", "purpose": "task state, rendering and persistence", "owner_role": "frontend"},
            ],
            "data_model": [{"name": "task", "fields": ["id", "text", "done"]}],
            "api_endpoints": [],
            "decisions": [
                {"decision": "localStorage persistence", "rationale": "No server needed; works offline"},
                {"decision": "Re-render the list from state", "rationale": "Simple and predictable"},
            ],
            "summary": "A static single-page app with state persisted in localStorage.",
        }

    def _code(self, role: str, purpose: str) -> str:
        verb, _, path = purpose.partition(" ")
        if path == "backend/schema.sql":
            return _fence("sql", NOTES_SCHEMA)
        if path == "backend/main.py":
            return _fence("python", NOTES_MAIN)
        if path == "frontend/index.html":
            return _fence("html", NOTES_HTML)
        if path == "frontend/style.css":
            return _fence("css", NOTES_CSS)
        if path == "frontend/app.js":
            return _fence("javascript", NOTES_JS)
        if path == "index.html":
            return _fence("html", STATIC_HTML)
        if path == "style.css":
            return _fence("css", STATIC_CSS)
        if path == "app.js":
            if verb == "write" and self.inject_bug and not self._served_buggy:
                self._served_buggy = True
                return _fence("javascript", STATIC_JS_BUGGY)
            return _fence("javascript", STATIC_JS_GOOD)
        raise LLMError(f"mock provider cannot write {path}", retryable=False)
