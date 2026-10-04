"""Engineering conventions shared by the architect, PM, developers and DevOps.

Small local models produce far more reliable code when the project layout
and the contracts between files are fixed up front. The architect decides
*what* the app does; these conventions decide *where* things live and how
files reference each other.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from ..schemas import ArchitectureOutput

STATIC_LAYOUT: list[tuple[str, str, str]] = [
    ("index.html", "page structure, content and element ids", "frontend"),
    ("style.css", "visual design and responsive layout", "frontend"),
    ("app.js", "application behaviour, state and persistence", "frontend"),
]

BACKEND_LAYOUT: list[tuple[str, str, str]] = [
    ("backend/schema.sql", "SQLite database schema", "database"),
    ("backend/main.py", "FastAPI app: JSON API under /api, serves the frontend", "backend"),
    ("frontend/index.html", "page structure, content and element ids", "frontend"),
    ("frontend/style.css", "visual design and responsive layout", "frontend"),
    ("frontend/app.js", "UI behaviour; talks to the JSON API with fetch()", "frontend"),
]

PLATFORM_CONSTRAINTS = {
    "static_web": [
        "Plain HTML, CSS and vanilla JavaScript only: no frameworks, build tools or CDN dependencies",
        "Runs by opening index.html; user data persists in localStorage",
    ],
    "web_with_backend": [
        "Backend: Python FastAPI with the stdlib sqlite3 module; only fastapi, pydantic and the standard library",
        "Frontend: plain HTML, CSS and vanilla JavaScript served by the backend",
    ],
}

ROLE_TITLES = {
    "frontend": "Frontend Developer",
    "backend": "Backend Developer",
    "database": "Database Engineer",
    "aiml": "AI/ML Engineer",
}


def layout_for(app_type: str) -> list[tuple[str, str, str]]:
    return BACKEND_LAYOUT if app_type == "web_with_backend" else STATIC_LAYOUT


def role_for_path(path: str) -> str:
    ext = PurePosixPath(path).suffix.lower()
    return {".py": "backend", ".sql": "database"}.get(ext, "frontend")


def normalize_architecture(arch: ArchitectureOutput, app_type: str) -> tuple[dict[str, Any], list[str]]:
    """Map the architect's proposal onto the canonical layout.

    Returns the normalised architecture dict and a list of adjustments made
    (recorded as decisions so the dashboard shows why).
    """
    notes: list[str] = []
    needs_backend = app_type == "web_with_backend"
    if arch.needs_backend != needs_backend:
        notes.append(
            f"Architect proposed needs_backend={arch.needs_backend}; kept CEO's app type '{app_type}'."
        )
    proposed_by_ext: dict[str, str] = {}
    for f in arch.files:
        proposed_by_ext.setdefault(PurePosixPath(f.path).suffix.lower(), f.purpose)
    files = []
    for path, default_purpose, owner in layout_for(app_type):
        purpose = proposed_by_ext.get(PurePosixPath(path).suffix.lower()) or default_purpose
        files.append({"path": path, "purpose": purpose[:200], "owner_role": owner})
    canonical = {f["path"] for f in files}
    dropped = [f.path for f in arch.files if f.path not in canonical]
    if dropped:
        notes.append(f"Consolidated proposed files {dropped} into the canonical layout {sorted(canonical)}.")

    endpoints = []
    if needs_backend:
        seen = set()
        for e in arch.api_endpoints:
            path = e.path if e.path.startswith("/api/") else "/api/" + e.path.lstrip("/")
            key = (e.method, path)
            if key not in seen:
                seen.add(key)
                endpoints.append({"method": e.method, "path": path, "description": e.description})
        if ("GET", "/api/health") not in seen:
            endpoints.insert(0, {"method": "GET", "path": "/api/health", "description": "Health check"})

    stack = arch.stack.model_dump()
    if not needs_backend:
        stack.update(backend="none", storage=stack.get("storage") if "local" in stack.get("storage", "").lower() else "localStorage")
    normalized = {
        "needs_backend": needs_backend,
        "app_type": app_type,
        "stack": stack,
        "files": files,
        "data_model": [e.model_dump() for e in arch.data_model],
        "api_endpoints": endpoints,
        "decisions": [d.model_dump() for d in arch.decisions],
        "summary": arch.summary,
    }
    return normalized, notes


# ---- per-file rules handed to developers ------------------------------------------------
def file_rules(path: str, arch: dict[str, Any], html_ids: list[str] | None = None) -> str:
    name = PurePosixPath(path).name
    backend = bool(arch.get("needs_backend"))
    endpoints = "\n".join(
        f"  - {e['method']} {e['path']}: {e.get('description', '')}" for e in arch.get("api_endpoints", [])
    )
    entities = "\n".join(f"  - {e['name']}: {', '.join(e.get('fields', []))}" for e in arch.get("data_model", []))

    if name == "index.html":
        return "\n".join(
            [
                '- A complete HTML5 document: <!DOCTYPE html>, <html lang="en">, <meta charset="UTF-8">, a viewport meta tag and a <title>.',
                '- Link the stylesheet exactly as <link rel="stylesheet" href="style.css"> and load the script exactly as <script src="app.js" defer></script> at the end of <body>.',
                '- Give every input, button and every container that JavaScript updates a unique, descriptive id (e.g. id="task-input", id="task-list").',
                "- Use semantic elements (header, main, section, form, ul) and a <label> for every input.",
                "- No inline JavaScript (no onclick=...) and no inline styles.",
                "- Include all static UI needed for every feature; dynamic list items will be created by app.js.",
            ]
        )
    if name == "style.css":
        return "\n".join(
            [
                "- Style the ids and classes used in index.html (shown below) plus the dynamic classes app.js will create.",
                "- Define the palette as CSS custom properties in :root and use them throughout.",
                "- Modern, clean look: spacing, rounded corners, subtle shadows, clear hover and :focus-visible states.",
                "- Responsive: must look good from 375px to 1440px wide.",
                "- Plain CSS only (no @import of external fonts or frameworks).",
            ]
        )
    if name == "app.js":
        rules = [
            "- Vanilla browser JavaScript only: no frameworks, no import/export, no external libraries. Never use require(), module.exports or process — they do not exist in browsers.",
            "- For randomness that must be secure (passwords, tokens, ids) use crypto.getRandomValues(); never Math.random().",
            "- Form fields are read and written with .value (not textContent).",
            f"- Use ONLY these element ids from index.html: {', '.join(html_ids or []) or '(see HTML below)'}. Never invent ids.",
            "- The script is loaded with `defer`, so the DOM is ready when it runs.",
            "- Insert user-provided text with textContent (never innerHTML with user data).",
            "- Create dynamic elements with document.createElement and give them meaningful class names.",
            "- Validate input: ignore empty or whitespace-only submissions.",
            "- Support pressing Enter in text inputs where it makes sense.",
        ]
        if backend:
            rules += [
                "- Load and save data through the backend JSON API using fetch() with relative URLs and JSON bodies:",
                endpoints,
                "- Handle failed requests gracefully (show a message, do not crash).",
            ]
        else:
            rules.append(
                "- Persist user data in localStorage under one key; wrap JSON.parse in try/catch and fall back to an empty state."
            )
        return "\n".join(rules)
    if name == "schema.sql":
        return "\n".join(
            [
                "- SQLite DDL only. Use CREATE TABLE IF NOT EXISTS for every table.",
                "- Every table has `id INTEGER PRIMARY KEY AUTOINCREMENT` and sensible NOT NULL constraints.",
                "- Tables for this data model:",
                entities or "  - (derive from the requirements)",
            ]
        )
    if name == "main.py":
        return "\n".join(
            [
                "- A FastAPI application object named `app`.",
                "- Database: sqlite3 with path os.environ.get('APP_DB_PATH', 'app.db'). Use a helper that opens a connection with row_factory = sqlite3.Row.",
                "- Define init_db() that runs the SQL in Path(__file__).parent / 'schema.sql' with executescript(), and call init_db() at module level right after creating `app` (do not use @app.on_event).",
                "- Use parameterized queries (?) only — never build SQL with f-strings or string formatting.",
                "- Request bodies are pydantic BaseModel classes; return JSON (dicts / lists of dicts).",
                "- Return 404 with HTTPException when an item does not exist.",
                "- Implement exactly these endpoints:",
                endpoints,
                "- LAST line before the end of the module: app.mount('/', StaticFiles(directory=Path(__file__).parent.parent / 'frontend', html=True), name='frontend')",
                "- Imports allowed: the Python standard library, fastapi, fastapi.staticfiles, pydantic. Nothing else.",
            ]
        )
    return "- Write clean, complete, working code."


def related_paths(path: str) -> list[str]:
    """Files a developer must see to keep cross-file contracts consistent."""
    name = PurePosixPath(path).name
    parent = str(PurePosixPath(path).parent)
    prefix = "" if parent == "." else parent + "/"
    if name in ("style.css", "app.js"):
        return [f"{prefix}index.html"]
    if name == "main.py":
        return ["backend/schema.sql"]
    return []


def build_order(paths: list[str]) -> dict[str, list[str]]:
    """Dependencies between files: each file maps to the files it must wait for."""
    deps: dict[str, list[str]] = {p: [] for p in paths}
    for p in paths:
        for r in related_paths(p):
            if r in deps and r != p:
                deps[p].append(r)
    if "frontend/app.js" in deps and "backend/main.py" in deps:
        deps["frontend/app.js"].append("backend/main.py")
    return deps


def fence_lang(path: str) -> str:
    return {
        ".html": "html",
        ".css": "css",
        ".js": "javascript",
        ".py": "python",
        ".sql": "sql",
        ".md": "markdown",
    }.get(PurePosixPath(path).suffix.lower(), "")
