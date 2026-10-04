"""Robust extraction of JSON and code from model output.

The original prototype required the literal markers ``HTML:``/``CSS:``/``JS:``,
which real models never produce, so every run silently fell back to a stub.
These parsers accept the formats models actually emit: fenced blocks with or
without a language tag, filename headings (``**index.html**``, ``### app.js``),
info strings with filenames (```` ```html index.html ````), unterminated
fences from truncated output, and bare code.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel

_FENCE_RE = re.compile(r"```[ \t]*([^\n`]*)\n(.*?)(?:\n```|```|\Z)", re.DOTALL)

_LANG_BY_EXT = {
    ".html": {"html", "htm", "xml"},
    ".htm": {"html", "htm"},
    ".css": {"css"},
    ".js": {"js", "javascript", "jsx", "mjs"},
    ".mjs": {"js", "javascript"},
    ".py": {"py", "python", "python3"},
    ".sql": {"sql", "sqlite"},
    ".json": {"json"},
    ".md": {"md", "markdown"},
    ".txt": {"text", "txt"},
}

_FILENAME_RE = re.compile(r"([\w\-./]+\.(?:html?|css|m?js|jsx|py|sql|json|md|txt|toml|ya?ml))", re.IGNORECASE)


class ParseError(ValueError):
    pass


# ---- JSON ----------------------------------------------------------------------
def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in ``text``."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    for info, body in _FENCE_RE.findall(text):
        if info.strip().lower() in ("", "json"):
            try:
                return json.loads(body.strip())
            except json.JSONDecodeError:
                continue
    candidate = _balanced_slice(text)
    if candidate is not None:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            raise ParseError(f"invalid JSON: {e}") from e
    raise ParseError("no JSON object found in model output")


def _balanced_slice(text: str) -> str | None:
    start = next((i for i, ch in enumerate(text) if ch in "{["), None)
    if start is None:
        return None
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# ---- code ------------------------------------------------------------------------
def _fenced_blocks(text: str) -> list[tuple[str, str, str]]:
    """Return (info_string, body, preceding_context) for every fenced block."""
    blocks = []
    for m in _FENCE_RE.finditer(text):
        preceding = text[max(0, m.start() - 160) : m.start()]
        context_lines = [ln for ln in preceding.splitlines() if ln.strip()][-2:]
        blocks.append((m.group(1).strip(), m.group(2), "\n".join(context_lines)))
    return blocks


def extract_code(text: str, filename: str) -> str:
    """Extract the content of ``filename`` from a model reply."""
    blocks = _fenced_blocks(text)
    if not blocks:
        body = _strip_prose(text)
        if not body.strip():
            raise ParseError(f"model returned no content for {filename}")
        return body.strip() + "\n"

    name = PurePosixPath(filename).name.lower()
    ext = PurePosixPath(filename).suffix.lower()
    langs = _LANG_BY_EXT.get(ext, set())

    def mentions(block: tuple[str, str, str]) -> bool:
        info, _, ctx = block
        return name in info.lower() or name in ctx.lower()

    def lang_matches(block: tuple[str, str, str]) -> bool:
        info = block[0].lower().split()
        return bool(info) and info[0] in langs

    for predicate in (mentions, lang_matches):
        matches = [b for b in blocks if predicate(b)]
        if matches:
            return max(matches, key=lambda b: len(b[1]))[1].strip() + "\n"
    return max(blocks, key=lambda b: len(b[1]))[1].strip() + "\n"


def extract_files(text: str, allowed: set[str] | None = None) -> dict[str, str]:
    """Extract several files from one reply; keys are relative paths."""
    files: dict[str, str] = {}
    for info, body, ctx in _fenced_blocks(text):
        path = None
        for source in (info, ctx):
            found = _FILENAME_RE.findall(source)
            if found:
                path = found[-1].strip("./") if found[-1].startswith("./") else found[-1]
                break
        if path is None:
            first = body.splitlines()[0] if body.strip() else ""
            found = _FILENAME_RE.findall(first) if re.match(r"\s*(//|#|<!--|/\*)", first) else []
            if found:
                path = found[0]
        if path is None:
            continue
        if allowed is not None and path not in allowed:
            continue
        files[path] = body.strip() + "\n"
    return files


_PROSE_PREFIX = re.compile(r"^(here(?:'s| is)|sure|below|certainly|the following)[^\n]*\n", re.IGNORECASE)


def _strip_prose(text: str) -> str:
    return _PROSE_PREFIX.sub("", text.strip(), count=1)


# ---- JSON schema ---------------------------------------------------------------
_UNSUPPORTED_KEYS = {
    "title",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "format",
    "examples",
}


def to_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic model -> self-contained strict JSON schema.

    Inlines ``$defs``, marks every property required, forbids extra
    properties and drops keywords some providers reject. The same schema
    works for Ollama ``format``, Anthropic ``output_config`` and OpenAI
    ``response_format``.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"].split("/")[-1]
                return resolve(copy.deepcopy(defs[ref]))
            out = {k: resolve(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS}
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [resolve(n) for n in node]
        return node

    return resolve(raw)
