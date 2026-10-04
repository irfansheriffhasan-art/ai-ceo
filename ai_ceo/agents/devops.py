"""DevOps agent: release packaging, git release flow and local deployment."""

from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from ..memory import MemoryKind
from ..states import TaskKind
from .base import Agent, AgentContext, AgentResult

STATIC_DOCKERFILE = """# Static site served by an unprivileged nginx (listens on 8080)
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --chown=nginx:nginx index.html style.css app.js /usr/share/nginx/html/
USER nginx
EXPOSE 8080
"""

BACKEND_DOCKERFILE = """FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_DB_PATH=/data/app.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY frontend/ frontend/
RUN useradd --create-home appuser && mkdir -p /data && chown appuser /data
USER appuser
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

DOCKERIGNORE = ".git\n__pycache__\n*.db\ndocs\n"


def _pinned(pkg: str, fallback: str) -> str:
    try:
        return f"{pkg}=={version(pkg)}"
    except PackageNotFoundError:
        return f"{pkg}=={fallback}"


class DevOpsAgent(Agent):
    role = "devops"
    title = "DevOps Agent"
    description = "Packages releases (README, Dockerfile, run scripts), merges to main, tags, archives and deploys a live preview."
    kinds = frozenset({TaskKind.DEPLOY})
    uses_llm = False

    async def run(self, ctx: AgentContext) -> AgentResult:
        arch = ctx.memory.architecture
        backend = bool(arch.get("needs_backend"))
        release = int(ctx.memory.get(MemoryKind.STATE, "release", 0) or 0) + 1
        tag = f"v1.{release - 1}.0"

        files = {
            "README.md": self._readme(ctx, backend, tag),
            "Dockerfile": BACKEND_DOCKERFILE if backend else STATIC_DOCKERFILE,
            ".dockerignore": DOCKERIGNORE,
        }
        if backend:
            files["requirements.txt"] = "\n".join(
                [_pinned("fastapi", "0.115.0"), _pinned("uvicorn", "0.30.0"), _pinned("pydantic", "2.9.0")]
            ) + "\n"
            files["run.ps1"] = "pip install -r requirements.txt\npython -m uvicorn backend.main:app --port 8000\n"
            files["run.sh"] = "#!/usr/bin/env sh\npip install -r requirements.txt\npython -m uvicorn backend.main:app --port 8000\n"
        else:
            files["run.ps1"] = "python -m http.server 8080\n"
            files["run.sh"] = "#!/usr/bin/env sh\npython3 -m http.server 8080\n"

        sha = await ctx.commit_files(files, f"chore(devops): release packaging for {tag}")
        zip_path = ctx.settings.releases_dir / f"{ctx.project.slug}-{ctx.project.id}-{tag}.zip"
        async with ctx.git_lock:
            await asyncio.to_thread(self._release, ctx, tag, zip_path)
        ctx.note(f"DevOps Agent merged develop into main, tagged {tag} and packaged {zip_path.name}")

        url = await ctx.services.previews.start(ctx.project.id, ctx.workspace.root, backend)
        ctx.memory.set(MemoryKind.STATE, "release", release, self.role)
        details: dict[str, Any] = {
            "tag": tag,
            "commit": sha or ctx.git.head(),
            "package": str(zip_path),
            "preview_url": url,
            "target": "uvicorn (local)" if backend else "static server (local)",
        }
        summary = f"Released {tag}; live preview at {url}"
        return AgentResult(
            summary=summary,
            output=details,
            report={"kind": "deploy", "passed": True, "score": 100.0, "summary": summary, "details": details},
        )

    @staticmethod
    def _release(ctx: AgentContext, tag: str, zip_path: Any) -> None:
        git = ctx.git
        git.checkout("main")
        try:
            git.merge("develop", f"release: {tag}")
            git.tag(tag, f"Release {tag} of {ctx.project.name}")
            git.archive(tag, zip_path)
        finally:
            git.checkout("develop")

    def _readme(self, ctx: AgentContext, backend: bool, tag: str) -> str:
        mem = ctx.memory
        obj = mem.get(MemoryKind.OBJECTIVE, "main", {}) or {}
        req = mem.requirements
        arch = mem.architecture
        lines = [
            f"# {ctx.project.name}",
            "",
            obj.get("objective", ctx.project.objective),
            "",
            f"Release **{tag}** — built autonomously by the AI-CEO multi-agent software company.",
            "",
            "## Features",
            *[f"- **{f['name']}** — {f['description']}" for f in req.get("features", [])],
            "",
            "## Run it",
            "",
        ]
        if backend:
            lines += [
                "```bash",
                "pip install -r requirements.txt",
                "python -m uvicorn backend.main:app --port 8000",
                "# open http://127.0.0.1:8000",
                "```",
                "",
                "Data is stored in SQLite (`APP_DB_PATH`, default `app.db`).",
            ]
        else:
            lines += [
                "Open `index.html` in a browser, or serve the folder:",
                "",
                "```bash",
                "python -m http.server 8080",
                "# open http://127.0.0.1:8080",
                "```",
            ]
        lines += [
            "",
            "### Docker",
            "",
            "```bash",
            f"docker build -t {ctx.project.slug} .",
            f"docker run -p {'8000:8000' if backend else '8080:8080'} {ctx.project.slug}",
            "```",
            "",
            "## Project structure",
            "",
            *[f"- `{f['path']}` — {f['purpose']}" for f in arch.get("files", [])],
            "",
            "## Quality",
            "",
        ]
        for kind in ("test", "security", "review"):
            reports = ctx.services.store.list_reports(ctx.project.id, kind)
            if reports:
                lines.append(f"- {kind.title()}: {reports[-1].summary}")
        lines += [
            "",
            "See `docs/` for requirements, architecture and design documents.",
            "",
        ]
        return "\n".join(lines)
