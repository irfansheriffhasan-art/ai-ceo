"""Code intelligence for generated projects.

Repository analysis, a file dependency graph, symbol extraction (Python via
``ast``, JS/HTML via targeted parsing), DOM cross-references and code search.
Used by the testing, review and security agents and by the dashboard.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any

LANG_BY_EXT = {
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".js": "javascript",
    ".mjs": "javascript",
    ".py": "python",
    ".sql": "sql",
    ".json": "json",
    ".md": "markdown",
}


# ---- HTML ----------------------------------------------------------------------
@dataclass
class HtmlInfo:
    ids: list[str] = field(default_factory=list)
    classes: set[str] = field(default_factory=set)
    scripts: list[str] = field(default_factory=list)
    inline_script_count: int = 0
    stylesheets: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    has_doctype: bool = False
    has_title: bool = False
    has_viewport: bool = False
    has_lang: bool = False
    tags: list[str] = field(default_factory=list)
    inputs_without_label: int = 0
    inline_handlers: list[str] = field(default_factory=list)
    blank_targets_without_noopener: int = 0
    unclosed: list[str] = field(default_factory=list)


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.info = HtmlInfo()
        self._stack: list[str] = []
        self._in_title = False
        self._in_script_inline = False
        self._labels_for: set[str] = set()
        self._input_ids: list[str | None] = []

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.info.has_doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        self.info.tags.append(tag)
        if tag not in _VOID:
            self._stack.append(tag)
        if "id" in a and a["id"]:
            self.info.ids.append(a["id"])
        if a.get("class"):
            self.info.classes.update(a["class"].split())
        for k in a:
            if k.startswith("on"):
                self.info.inline_handlers.append(f"{tag}[{k}]")
        if tag == "html" and a.get("lang"):
            self.info.has_lang = True
        if tag == "title":
            self._in_title = True
        if tag == "script":
            if a.get("src"):
                self.info.scripts.append(a["src"])
            else:
                self.info.inline_script_count += 1
        if tag == "link" and "stylesheet" in a.get("rel", "").lower() and a.get("href"):
            self.info.stylesheets.append(a["href"])
        if tag == "img" and a.get("src"):
            self.info.images.append(a["src"])
        if tag == "meta" and a.get("name", "").lower() == "viewport":
            self.info.has_viewport = True
        if tag == "label" and a.get("for"):
            self._labels_for.add(a["for"])
        if tag in ("input", "textarea", "select") and a.get("type", "") not in ("hidden", "submit", "button"):
            has_aria = any(k in a for k in ("aria-label", "aria-labelledby", "title", "placeholder"))
            self._input_ids.append(None if has_aria else a.get("id", ""))
        if tag == "a" and a.get("target") == "_blank" and "noopener" not in a.get("rel", ""):
            self.info.blank_targets_without_noopener += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self._stack:
            while self._stack:
                top = self._stack.pop()
                if top == tag:
                    break
                if top not in ("p", "li", "td", "tr", "th", "option", "dt", "dd"):
                    self.info.unclosed.append(top)

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.info.has_title = True

    def finish(self) -> HtmlInfo:
        self.info.unclosed.extend(t for t in self._stack if t not in ("html", "body", "head", "p", "li"))
        self.info.inputs_without_label = sum(
            1 for i in self._input_ids if i is not None and (not i or i not in self._labels_for)
        )
        return self.info


def parse_html(source: str) -> HtmlInfo:
    c = _Collector()
    c.feed(source)
    c.close()
    return c.finish()


# ---- JavaScript ----------------------------------------------------------------
_JS_ID_REFS = [
    re.compile(r"getElementById\(\s*['\"]([\w\-:]+)['\"]\s*\)"),
    re.compile(r"querySelector(?:All)?\(\s*['\"]#([\w\-]+)['\"]\s*\)"),
]
_JS_CREATED_IDS = [
    re.compile(r"\.id\s*=\s*['\"]([\w\-]+)['\"]"),
    re.compile(r"id=\\?['\"]([\w\-]+)\\?['\"]"),
    re.compile(r"setAttribute\(\s*['\"]id['\"]\s*,\s*['\"]([\w\-]+)['\"]"),
]
_JS_FUNCS = re.compile(
    r"(?:function\s+([A-Za-z_$][\w$]*)\s*\(|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)|class\s+([A-Za-z_$][\w$]*))"
)
_JS_IMPORTS = re.compile(r"""import\s+(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]""")
_JS_FETCH = re.compile(r"""fetch\(\s*[`'"]([^`'"]+)[`'"]""")


@dataclass
class JsInfo:
    id_refs: list[tuple[str, int]] = field(default_factory=list)  # (id, line)
    created_ids: set[str] = field(default_factory=set)
    functions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    fetch_urls: list[str] = field(default_factory=list)


def parse_js(source: str) -> JsInfo:
    info = JsInfo()
    for lineno, line in enumerate(source.splitlines(), start=1):
        for rx in _JS_ID_REFS:
            for m in rx.finditer(line):
                info.id_refs.append((m.group(1), lineno))
    for rx in _JS_CREATED_IDS:
        info.created_ids.update(rx.findall(source))
    for m in _JS_FUNCS.finditer(source):
        name = next((g for g in m.groups() if g), None)
        if name:
            info.functions.append(name)
    info.imports = _JS_IMPORTS.findall(source)
    info.fetch_urls = _JS_FETCH.findall(source)
    return info


# ---- Python --------------------------------------------------------------------
@dataclass
class PyInfo:
    syntax_error: str | None = None
    imports: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    routes: list[tuple[str, str]] = field(default_factory=list)  # (METHOD, path)


def parse_python(source: str, filename: str = "<file>") -> PyInfo:
    info = PyInfo()
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        info.syntax_error = f"line {e.lineno}: {e.msg}"
        return info
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            info.imports.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            info.imports.append(node.module.split(".")[0])
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            info.functions.append(node.name)
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in ("get", "post", "put", "patch", "delete")
                    and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)
                ):
                    info.routes.append((dec.func.attr.upper(), dec.args[0].value))
        elif isinstance(node, ast.ClassDef):
            info.classes.append(node.name)
    info.imports = sorted(set(info.imports))
    return info


# ---- repository level ------------------------------------------------------------
def _resolve_ref(from_path: str, ref: str) -> str | None:
    if ref.startswith(("http://", "https://", "//", "data:", "#", "mailto:")):
        return None
    ref = ref.split("?")[0].split("#")[0]
    if ref.startswith("/"):
        return ref.lstrip("/")
    base = PurePosixPath(from_path).parent
    parts: list[str] = []
    for seg in (base / ref).parts:
        if seg == "..":
            if parts:
                parts.pop()
        elif seg != ".":
            parts.append(seg)
    return "/".join(parts)


def analyze_repository(files: dict[str, str]) -> dict[str, Any]:
    """Build a structural summary of a project from its file contents."""
    file_rows = []
    languages: dict[str, int] = {}
    edges: list[dict[str, str]] = []
    symbols: dict[str, list[str]] = {}
    html_ids: set[str] = set()
    routes: list[dict[str, str]] = []

    for path, src in files.items():
        lang = LANG_BY_EXT.get(PurePosixPath(path).suffix.lower(), "other")
        lines = src.count("\n") + 1
        languages[lang] = languages.get(lang, 0) + lines
        file_rows.append({"path": path, "language": lang, "lines": lines, "bytes": len(src.encode("utf-8"))})

        if lang == "html":
            h = parse_html(src)
            html_ids.update(h.ids)
            for ref, kind in [(s, "script") for s in h.scripts] + [(s, "stylesheet") for s in h.stylesheets]:
                target = _resolve_ref(path, ref)
                if target:
                    edges.append({"from": path, "to": target, "kind": kind})
        elif lang == "javascript":
            j = parse_js(src)
            symbols[path] = j.functions[:50]
            for imp in j.imports:
                target = _resolve_ref(path, imp)
                if target:
                    edges.append({"from": path, "to": target, "kind": "import"})
            for url in j.fetch_urls:
                edges.append({"from": path, "to": url, "kind": "http"})
        elif lang == "python":
            p = parse_python(src, path)
            symbols[path] = p.functions[:50] + p.classes[:20]
            local_modules = {PurePosixPath(f).stem: f for f in files if f.endswith(".py")}
            for imp in p.imports:
                if imp in local_modules and local_modules[imp] != path:
                    edges.append({"from": path, "to": local_modules[imp], "kind": "import"})
            routes.extend({"method": m, "path": r, "file": path} for m, r in p.routes)

    return {
        "files": sorted(file_rows, key=lambda r: r["path"]),
        "languages": languages,
        "total_lines": sum(languages.values()),
        "dependencies": edges,
        "symbols": symbols,
        "dom_ids": sorted(html_ids),
        "routes": routes,
    }


def search(files: dict[str, str], query: str, regex: bool = False, limit: int = 200) -> list[dict[str, Any]]:
    try:
        rx = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"invalid regex: {e}") from e
    hits: list[dict[str, Any]] = []
    for path, src in files.items():
        for lineno, line in enumerate(src.splitlines(), start=1):
            if rx.search(line):
                hits.append({"path": path, "line": lineno, "text": line.strip()[:240]})
                if len(hits) >= limit:
                    return hits
    return hits
