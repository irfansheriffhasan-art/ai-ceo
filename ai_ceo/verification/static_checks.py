"""Deterministic static checks: syntax, structure and cross-file consistency.

These catch the failure modes small models produce most often: JS syntax
errors, truncated files, HTML pointing at assets that don't exist, and JS
that references element ids the HTML never defines.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath

from ..workspace.analysis import _resolve_ref, parse_html, parse_js, parse_python
from .issues import Issue

ALLOWED_PY_THIRD_PARTY = {"fastapi", "pydantic", "uvicorn", "starlette"}
PLACEHOLDER_MARKERS = ("your code here", "todo: implement", "implementation goes here", "...rest of")

# Node.js-only constructs that crash in a browser (small models emit these often).
_NODE_ONLY = [
    (re.compile(r"(?<![\w.$])require\s*\(\s*['\"]"), "require() is Node.js-only (ReferenceError: require is not defined in browsers)"),
    (re.compile(r"\bmodule\.exports\b|(?<![\w.])exports\.\w+\s*="), "module.exports is Node.js-only"),
    (re.compile(r"\bprocess\.(env|argv|exit)\b"), "process.* is Node.js-only"),
    (re.compile(r"^\s*import\s[^;]*?from\s+['\"](?![./])[^'\"]+['\"]", re.M), "bare package import cannot load in a browser without a bundler"),
]


def browser_compat_problems(source: str) -> list[tuple[str, int]]:
    """Node-only constructs in browser JavaScript: (message, line)."""
    found = []
    for rx, msg in _NODE_ONLY:
        m = rx.search(source)
        if m:
            found.append((msg, source.count("\n", 0, m.start()) + 1))
    return found


def node_available(node_path: str = "node") -> bool:
    return shutil.which(node_path) is not None


def check_js_syntax(source: str, node_path: str = "node") -> str | None:
    """Return a syntax error message, or None if the file parses."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "check.js"
        f.write_text(source, encoding="utf-8")
        try:
            proc = subprocess.run(
                [node_path, "--check", str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
            )
        except (OSError, subprocess.SubprocessError) as e:
            return f"could not run node: {e}"
        if proc.returncode == 0:
            return None
        lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
        location = next((ln for ln in lines if "check.js:" in ln), "")
        message = next((ln for ln in lines if "Error" in ln), lines[-1] if lines else "syntax error")
        line_no = location.rsplit(":", 1)[-1] if location else "?"
        return f"line {line_no}: {message.strip()}"


def run_static_checks(files: dict[str, str], expected_files: list[str], node_path: str = "node") -> list[Issue]:
    issues: list[Issue] = []
    have_node = node_available(node_path)
    html_ids: set[str] = set()
    js_created_ids: set[str] = set()
    js_infos = {}

    for path in expected_files:
        if path not in files:
            issues.append(Issue("error", "missing_file", f"planned file {path} was not created", file=path, source="static"))

    for path, src in files.items():
        ext = PurePosixPath(path).suffix.lower()
        stripped = src.strip()
        if ext in (".html", ".css", ".js", ".py") and len(stripped) < 8:
            issues.append(Issue("error", "empty_file", f"{path} is empty or a placeholder", file=path, source="static"))
            continue
        lowered = src.lower()
        for marker in PLACEHOLDER_MARKERS:
            if marker in lowered:
                issues.append(
                    Issue("error", "placeholder", f"{path} contains placeholder text '{marker}'", file=path, source="static")
                )
                break

        if ext in (".html", ".htm"):
            h = parse_html(src)
            html_ids.update(h.ids)
            if "</html>" not in lowered:
                issues.append(Issue("error", "truncated", f"{path} has no closing </html> tag (truncated output?)", file=path, source="static"))
            if not h.has_doctype:
                issues.append(Issue("warning", "html_structure", "missing <!DOCTYPE html>", file=path, source="static"))
            if not h.has_title:
                issues.append(Issue("warning", "html_structure", "missing or empty <title>", file=path, source="static"))
            if not h.has_viewport:
                issues.append(Issue("warning", "responsive", "missing viewport meta tag", file=path, source="static"))
            for tag, attr in h.malformed_attrs[:5]:
                issues.append(
                    Issue(
                        "error",
                        "html_syntax",
                        f'<{tag}> attribute "{attr}" swallows the following markup — a closing quote is missing, '
                        "so elements after it never appear on the page",
                        file=path,
                        source="static",
                        suggestion='Close every attribute value with a quote, e.g. type="button".',
                    )
                )
            for dup, n in Counter(h.ids).items():
                if n > 1:
                    issues.append(Issue("warning", "html_structure", f"duplicate id '{dup}' ({n}x)", file=path, source="static"))
            for tag in sorted(set(h.unclosed))[:5]:
                issues.append(Issue("warning", "html_structure", f"unclosed <{tag}> element", file=path, source="static"))
            for ref in h.scripts + h.stylesheets + h.images:
                target = _resolve_ref(path, ref)
                if target and target not in files and not _served_by_backend(target, files):
                    issues.append(
                        Issue(
                            "error",
                            "broken_reference",
                            f"{path} references '{ref}' but no such file exists",
                            file=path,
                            source="static",
                            suggestion=f"existing files: {', '.join(sorted(files))}",
                        )
                    )
        elif ext in (".js", ".mjs"):
            if have_node:
                err = check_js_syntax(src, node_path)
                if err:
                    issues.append(Issue("error", "syntax", f"JavaScript syntax error, {err}", file=path, source="static"))
            if not path.startswith("backend/"):
                for msg, line in browser_compat_problems(src):
                    issues.append(Issue("error", "browser_compat", msg, file=path, line=line, source="static"))
            info = parse_js(src)
            js_infos[path] = info
            js_created_ids.update(info.created_ids)
        elif ext == ".css":
            if src.count("{") != src.count("}"):
                issues.append(
                    Issue("error", "syntax", f"unbalanced braces ({src.count('{')} open, {src.count('}')} close)", file=path, source="static")
                )
        elif ext == ".py":
            p = parse_python(src, path)
            if p.syntax_error:
                issues.append(Issue("error", "syntax", f"Python syntax error at {p.syntax_error}", file=path, source="static"))
                continue
            local = {PurePosixPath(f).stem for f in files if f.endswith(".py")} | {"backend"}
            for mod in p.imports:
                if mod in sys.stdlib_module_names or mod in local or mod in ALLOWED_PY_THIRD_PARTY:
                    continue
                issues.append(
                    Issue(
                        "error",
                        "dependency",
                        f"imports '{mod}', which is not available (allowed: stdlib, {', '.join(sorted(ALLOWED_PY_THIRD_PARTY))})",
                        file=path,
                        source="static",
                    )
                )

    # Cross-file: element ids used by JS must exist in HTML (or be created by JS).
    if html_ids or any(f.endswith(".html") for f in files):
        for path, info in js_infos.items():
            missing = {}
            for el_id, line in info.id_refs:
                if el_id not in html_ids and el_id not in js_created_ids and el_id not in missing:
                    missing[el_id] = line
            for el_id, line in missing.items():
                issues.append(
                    Issue(
                        "error",
                        "dom_reference",
                        f"{path} looks up element id '{el_id}' but no HTML element has that id",
                        file=path,
                        line=line,
                        source="static",
                        suggestion=f"ids available in HTML: {', '.join(sorted(html_ids)) or '(none)'}",
                    )
                )
    return issues


def _served_by_backend(target: str, files: dict[str, str]) -> bool:
    """Backend apps serve ``frontend/`` at the site root, so '/app.js' maps to 'frontend/app.js'."""
    return f"frontend/{target}" in files
