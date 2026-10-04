"""Git integration for generated projects: commits, branches, diffs, tags, rollback.

All operations are synchronous subprocess calls with argument lists (no
shell). Call them through ``asyncio.to_thread`` from async code. Nothing
here rewrites history: rollback creates a *new* commit that restores an
earlier tree, so every previous state stays reachable.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..util import truncate

GIT_IDENTITY = ("AI-CEO", "ai-ceo@localhost")
GITIGNORE = "__pycache__/\n*.pyc\n*.db\n*.sqlite3\n.env\nnode_modules/\n"


class GitError(RuntimeError):
    pass


@dataclass
class CommitInfo:
    sha: str
    short: str
    message: str
    author: str
    date: str
    files: list[str]

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


class GitRepo:
    def __init__(self, path: Path):
        self.path = path

    def _run(self, *args: str, check: bool = True) -> str:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
        cmd = [
            "git",
            "-c", f"user.name={GIT_IDENTITY[0]}",
            "-c", f"user.email={GIT_IDENTITY[1]}",
            "-c", "core.autocrlf=false",
            "-c", "commit.gpgsign=false",
            *args,
        ]  # fmt: skip
        proc = subprocess.run(
            cmd, cwd=self.path, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=60
        )
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout

    @staticmethod
    def available() -> bool:
        try:
            return subprocess.run(["git", "--version"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def is_repo(self) -> bool:
        return (self.path / ".git").exists()

    def init(self) -> str | None:
        self.path.mkdir(parents=True, exist_ok=True)
        if not self.is_repo():
            self._run("init", "-q", "-b", "main")
        gi = self.path / ".gitignore"
        if not gi.exists():
            gi.write_text(GITIGNORE, encoding="utf-8")
        return self.commit_all("chore: initialize project workspace", author="CEO")

    def commit_all(self, message: str, author: str = "AI-CEO") -> str | None:
        """Stage everything and commit. Returns the new sha, or None if nothing changed."""
        self._run("add", "-A")
        if not self._run("status", "--porcelain").strip():
            return None
        author_id = f"{author} <{author.lower().replace(' ', '-')}@ai-ceo.local>"
        self._run("commit", "-q", "-m", message, f"--author={author_id}")
        return self.head()

    def head(self) -> str | None:
        out = self._run("rev-parse", "HEAD", check=False).strip()
        return out if len(out) == 40 else None

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def checkout(self, branch: str, create: bool = False) -> None:
        if create:
            self._run("checkout", "-q", "-B", branch)
        else:
            self._run("checkout", "-q", branch)

    def merge(self, branch: str, message: str) -> None:
        self._run("merge", "-q", "--no-ff", "-m", message, branch)

    def tag(self, name: str, message: str) -> None:
        self._run("tag", "-f", "-a", name, "-m", message)

    def archive(self, ref: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._run("archive", "--format=zip", "-o", str(out_path), ref)
        return out_path

    def branches(self) -> list[str]:
        return [b.strip().lstrip("* ").strip() for b in self._run("branch", "--list").splitlines() if b.strip()]

    def tags(self) -> list[str]:
        return [t for t in self._run("tag", "--list").splitlines() if t]

    def log(self, limit: int = 50) -> list[CommitInfo]:
        if self.head() is None:
            return []
        sep = "\x1f"
        out = self._run(
            "log", "--all", "--topo-order", f"-n{limit}", "--date=iso-strict", f"--format=%H{sep}%h{sep}%s{sep}%an{sep}%ad", "--name-only"
        )
        commits: list[CommitInfo] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            if sep in line:
                sha, short, subject, author, date = line.split(sep)
                commits.append(CommitInfo(sha, short, subject, author, date, []))
            elif commits:
                commits[-1].files.append(line.strip())
        return commits

    def show(self, sha: str, max_chars: int = 200_000) -> str:
        self._validate_sha(sha)
        # Merge commits (releases) are diffed against their first parent so they show what the release brought in.
        return truncate(
            self._run("show", "--diff-merges=first-parent", "--format=%H%n%an%n%ad%n%n%B", "--patch", "--stat", sha), max_chars
        )

    def diff_since(self, sha: str, max_chars: int = 100_000) -> str:
        self._validate_sha(sha)
        return truncate(self._run("diff", sha, "HEAD"), max_chars)

    def restore_to(self, sha: str, message: str) -> str | None:
        """Make the working tree equal to ``sha`` and record that as a new commit."""
        self._validate_sha(sha)
        self._run("restore", f"--source={sha}", "--staged", "--worktree", "--", ".")
        return self.commit_all(message, author="CEO")

    def _validate_sha(self, sha: str) -> None:
        if not sha or not all(c in "0123456789abcdef" for c in sha.lower()) or not 4 <= len(sha) <= 40:
            raise GitError(f"invalid commit id: {sha!r}")
        if self._run("cat-file", "-t", sha, check=False).strip() != "commit":
            raise GitError(f"unknown commit: {sha}")
