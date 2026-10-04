"""Developer agents: Frontend, Backend, Database and AI/ML engineers.

All share one implementation: generate (or fix) one file per LLM call with
the files it depends on in context, then self-check the result before
handing it back. A failed self-check raises a retryable error so the
orchestrator re-runs the task with the error fed back to the model; on the
final attempt the file is accepted with a warning and QA takes over.
"""

from __future__ import annotations

import ast
import sys
from pathlib import PurePosixPath
from typing import Any

from ..llm.parsing import ParseError, extract_code
from ..memory import MemoryKind
from ..states import TaskKind
from ..verification.static_checks import (
    ALLOWED_PY_THIRD_PARTY,
    browser_compat_problems,
    check_js_syntax,
    node_available,
)
from ..workspace.analysis import parse_html, parse_js
from .base import Agent, AgentContext, AgentError, AgentResult
from .conventions import ROLE_TITLES, fence_lang, file_rules, related_paths


def _design_text(design: dict[str, Any]) -> str:
    if not design:
        return ""
    p = design.get("palette", {})
    comps = ", ".join(c.get("name", "") for c in design.get("components", [])[:8])
    return (
        f"DESIGN (from the UI/UX agent): style '{design.get('style_name', '')}'. "
        f"Palette: primary {p.get('primary')}, secondary {p.get('secondary')}, background {p.get('background')}, "
        f"surface {p.get('surface')}, text {p.get('text')}, accent {p.get('accent')}. "
        f"Font: {design.get('font_family', 'system-ui')}. Layout: {design.get('layout', '')} "
        f"Components: {comps}."
    )


def _format_issues(issues: list[dict[str, Any]]) -> str:
    lines = []
    for i in issues[:10]:
        loc = f"{i.get('file', '')}{':' + str(i['line']) if i.get('line') else ''}"
        line = f"- [{i.get('severity', 'error')}] {loc} {i.get('message', '')}".strip()
        if i.get("evidence"):
            line += f"\n  evidence: {str(i['evidence'])[:600]}"
        if i.get("suggestion"):
            line += f"\n  suggestion: {str(i['suggestion'])[:300]}"
        lines.append(line)
    return "\n".join(lines) or "- (no details)"


class DeveloperAgent(Agent):
    kinds = frozenset({TaskKind.IMPLEMENT, TaskKind.FIX})

    async def run(self, ctx: AgentContext) -> AgentResult:
        paths: list[str] = ctx.task.input.get("files") or []
        if not paths:
            raise AgentError("task has no target files", retryable=False)
        fixing = ctx.task.kind == TaskKind.FIX
        out_files: dict[str, str] = {}
        warnings: list[str] = []
        for path in paths:
            content, warning = await self._produce(ctx, path, fixing)
            out_files[path] = content
            if warning:
                warnings.append(warning)
        lines = sum(c.count("\n") for c in out_files.values())
        verb = "Fixed" if fixing else "Wrote"
        summary = f"{verb} {', '.join(out_files)} ({lines} lines)"
        if fixing:
            summary += f", addressing {len(ctx.task.input.get('issues', []))} issue(s)"
        if warnings:
            summary += ". Accepted with warnings: " + "; ".join(warnings)
        prefix = "fix" if fixing else "feat"
        return AgentResult(
            summary=summary,
            output={"files": list(out_files), "warnings": warnings},
            files=out_files,
            commit_message=f"{prefix}({self.role}): {ctx.task.title}",
        )

    async def _produce(self, ctx: AgentContext, path: str, fixing: bool) -> tuple[str, str]:
        arch = ctx.memory.architecture
        rel_paths = list(related_paths(path))
        if fixing and PurePosixPath(path).name == "index.html":
            sibling = str(PurePosixPath(path).with_name("app.js"))
            rel_paths.append(sibling)
        related = {r: ctx.workspace.read(r) for r in rel_paths if ctx.workspace.exists(r)}
        html_src = next((src for p, src in related.items() if p.endswith("index.html")), "")
        html_ids = parse_html(html_src).ids if html_src else []

        related_text = "\n\n".join(
            f"EXISTING FILE `{p}` (keep consistent with it):\n```{fence_lang(p)}\n{src[:7000]}\n```" for p, src in related.items()
        )
        extra = []
        if ctx.task.input.get("simplify"):
            extra.append("IMPORTANT: previous attempts failed. Write a simpler, shorter version that still delivers every must-have feature.")
        if ctx.previous_error:
            extra.append(f"A previous attempt was rejected: {ctx.previous_error[:500]}. Do not repeat that mistake.")
        common = {
            "role_title": ROLE_TITLES.get(self.role, self.title),
            "brief": ctx.memory.brief(1600, include=("objective", "constraints", "preferences", "requirements", "architecture")),
            "path": path,
            "file_rules": file_rules(path, arch, html_ids),
            "related_files": related_text,
            "extra": "\n".join(extra),
        }
        if fixing:
            current = ctx.workspace.read(path) if ctx.workspace.exists(path) else ""
            issues = [i for i in ctx.task.input.get("issues", []) if i.get("file") in (path, "")] or ctx.task.input.get("issues", [])
            text, truncated = await ctx.text(
                "dev_fix",
                f"fix {path}",
                issues=_format_issues(issues),
                current=current[:9000],
                lang=fence_lang(path),
                **common,
            )
        else:
            purpose = next((f["purpose"] for f in arch.get("files", []) if f["path"] == path), "")
            text, truncated = await ctx.text(
                "dev_implement",
                f"write {path}",
                design=_design_text(ctx.memory.design) if self.role in ("frontend", "aiml") else "",
                task_title=ctx.task.title,
                task_description=ctx.task.description,
                file_purpose=purpose,
                **common,
            )
        try:
            code = extract_code(text, path)
        except ParseError as e:
            raise AgentError(f"could not extract {path} from model output: {e}") from e

        problem = "output was cut off before the end (too long) — write more compact code" if truncated else None
        problem = problem or self._self_check(ctx, path, code, html_ids)
        if problem:
            final_attempt = ctx.task.attempts >= ctx.task.max_attempts
            if not final_attempt:
                raise AgentError(f"self-check failed for {path}: {problem}")
            ctx.note(f"{self.title} accepted {path} despite self-check warning: {problem}", level="warning")
            return code, f"{path}: {problem}"
        return code, ""

    def _self_check(self, ctx: AgentContext, path: str, code: str, html_ids: list[str]) -> str | None:
        ext = PurePosixPath(path).suffix.lower()
        lowered = code.lower()
        if ext == ".html":
            if "<html" not in lowered or "</html>" not in lowered:
                return "not a complete HTML document (missing <html> or </html>)"
            if "app.js" not in code or "style.css" not in code:
                return "index.html must link style.css and load app.js"
            broken = parse_html(code).malformed_attrs
            if broken:
                tag, attr = broken[0]
                return f'<{tag}> attribute "{attr}" is missing its closing quote, which swallows the elements after it'
        elif ext == ".js":
            compat = browser_compat_problems(code)
            if compat:
                msg, line = compat[0]
                return f"line {line}: {msg}. Use only browser APIs (e.g. crypto.getRandomValues for randomness)"
            if node_available(ctx.settings.node_path):
                err = check_js_syntax(code, ctx.settings.node_path)
                if err:
                    return f"JavaScript syntax error, {err}"
            if html_ids:
                info = parse_js(code)
                missing = sorted({i for i, _ in info.id_refs if i not in html_ids and i not in info.created_ids})
                if missing:
                    return f"uses element ids not present in index.html: {', '.join(missing)} (available: {', '.join(html_ids)})"
        elif ext == ".py":
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return f"Python syntax error at line {e.lineno}: {e.msg}"
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods.add(node.module.split(".")[0])
            bad = sorted(m for m in mods if m not in sys.stdlib_module_names and m not in ALLOWED_PY_THIRD_PARTY)
            if bad:
                return f"imports unavailable packages: {', '.join(bad)}"
            if "app" not in code or "FastAPI(" not in code:
                return "must define `app = FastAPI()`"
        elif ext == ".css" and code.count("{") != code.count("}"):
            return "unbalanced braces in CSS"
        elif ext == ".sql" and "create table" not in lowered:
            return "schema has no CREATE TABLE statements"
        if any(m in lowered for m in ("your code here", "todo: implement", "rest of the code")):
            return "contains placeholder text instead of real code"
        if PurePosixPath(path).name == "app.js":
            ctx.memory.set(MemoryKind.FILE, path, {"functions": parse_js(code).functions[:30]}, self.role)
        return None


class FrontendDeveloper(DeveloperAgent):
    role = "frontend"
    title = "Frontend Developer"
    description = "Builds the HTML structure, CSS styling and JavaScript behaviour of the app."


class BackendDeveloper(DeveloperAgent):
    role = "backend"
    title = "Backend Developer"
    description = "Implements the FastAPI service, endpoints, validation and persistence."


class DatabaseAgent(DeveloperAgent):
    role = "database"
    title = "Database Agent"
    description = "Designs the SQLite schema, constraints and data model."


class AIMLAgent(DeveloperAgent):
    role = "aiml"
    title = "AI/ML Agent"
    description = (
        "Implements AI/data-driven behaviour (smart search, scoring, categorisation, insights) and acts as the "
        "escalation engineer when another developer's task keeps failing."
    )
