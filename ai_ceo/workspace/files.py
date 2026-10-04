"""Sandboxed file access for generated projects.

Every path that comes from a model is validated before touching the disk:
relative POSIX paths only, no traversal, no hidden segments (so ``.git`` and
``.env`` can never be written), an extension allow-list and size limits.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

ALLOWED_EXTENSIONS = {
    ".html",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".py",
    ".sql",
    ".md",
    ".txt",
    ".svg",
    ".toml",
    ".ps1",
    ".sh",
    ".gitignore",
    ".dockerignore",
}
ALLOWED_BARE_NAMES = {"Dockerfile", ".gitignore", ".dockerignore"}
MAX_FILE_BYTES = 400_000
MAX_DEPTH = 4
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_\-][A-Za-z0-9_.\-]*$")


class UnsafePathError(ValueError):
    pass


def validate_rel_path(path: str) -> str:
    """Return a normalised relative POSIX path or raise ``UnsafePathError``."""
    if not path or len(path) > 160:
        raise UnsafePathError(f"invalid path length: {path!r}")
    if "\\" in path or ":" in path or path.startswith("/") or "\x00" in path:
        raise UnsafePathError(f"path must be relative POSIX: {path!r}")
    norm = PurePosixPath(path)
    parts = norm.parts
    if not parts or len(parts) > MAX_DEPTH:
        raise UnsafePathError(f"path too deep: {path!r}")
    for i, seg in enumerate(parts):
        is_last = i == len(parts) - 1
        if seg in (".", ".."):
            raise UnsafePathError(f"path traversal: {path!r}")
        if is_last and seg in ALLOWED_BARE_NAMES:
            continue
        if seg.startswith(".") or not _SEGMENT_RE.match(seg):
            raise UnsafePathError(f"illegal path segment {seg!r} in {path!r}")
    name = parts[-1]
    if name not in ALLOWED_BARE_NAMES and norm.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UnsafePathError(f"file type not allowed: {path!r}")
    return norm.as_posix()


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _abs(self, rel: str) -> Path:
        safe = validate_rel_path(rel)
        target = (self.root / safe).resolve()
        if self.root not in target.parents:
            raise UnsafePathError(f"path escapes workspace: {rel!r}")
        return target

    def write(self, rel: str, content: str) -> str:
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise UnsafePathError(f"{rel} exceeds {MAX_FILE_BYTES} bytes")
        target = self._abs(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.replace(b"\r\n", b"\n"))
        return validate_rel_path(rel)

    def read(self, rel: str) -> str:
        return self._abs(rel).read_text(encoding="utf-8", errors="replace")

    def exists(self, rel: str) -> bool:
        try:
            return self._abs(rel).is_file()
        except UnsafePathError:
            return False

    def list_files(self) -> list[str]:
        files = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(self.root).as_posix()
            if any(seg.startswith(".") and seg not in ALLOWED_BARE_NAMES for seg in rel.split("/")):
                continue
            if "__pycache__" in rel or rel.endswith((".db", ".pyc")):
                continue
            files.append(rel)
        return files

    def read_all(self, max_chars_per_file: int = 50_000) -> dict[str, str]:
        out = {}
        for rel in self.list_files():
            try:
                out[rel] = self.read(rel)[:max_chars_per_file]
            except (UnsafePathError, OSError):
                continue
        return out

    def tree(self) -> list[dict[str, object]]:
        return [{"path": rel, "bytes": (self.root / rel).stat().st_size} for rel in self.list_files()]
