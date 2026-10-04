"""Quality gate agents: Security and Code Review."""

from __future__ import annotations

import asyncio

from ..memory import MemoryKind
from ..schemas import ReviewOutput
from ..states import TaskKind
from ..verification import security as sec
from ..verification.issues import Issue
from ..verification.static_checks import run_static_checks
from .base import Agent, AgentContext, AgentResult
from .conventions import fence_lang
from .testing import _code_files, _source_files


class SecurityAgent(Agent):
    role = "security"
    title = "Security Agent"
    description = "Scans for secrets, injection/XSS sinks, unsafe APIs, weak randomness, missing validation/auth and risky config."
    kinds = frozenset({TaskKind.SECURITY})
    uses_llm = False

    async def run(self, ctx: AgentContext) -> AgentResult:
        files = _code_files(ctx.workspace.read_all())
        findings = await asyncio.to_thread(sec.scan_files, files)
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        blocking = [f for f in findings if f.severity in ("critical", "high")]
        passed = not blocking
        score = float(sec.score(findings))
        for f in blocking:
            ctx.memory.set(
                MemoryKind.BUG,
                f.fingerprint,
                {"status": "open", "message": f.message, "file": f.file, "source": "security", "iteration": ctx.project.iteration},
                self.role,
            )
        # Security bugs from earlier iterations that are no longer present are resolved.
        current = {f.fingerprint for f in blocking}
        for item in ctx.memory.items(MemoryKind.BUG):
            bug = item["value"]
            if bug.get("source") == "security" and bug.get("status") == "open" and item["key"] not in current:
                bug["status"] = "fixed"
                ctx.memory.set(MemoryKind.BUG, item["key"], bug, self.role)
        breakdown = ", ".join(f"{n} {s}" for s, n in sorted(counts.items(), key=lambda kv: -sec.SEVERITY_WEIGHT.get(kv[0], 0)))
        summary = ("PASSED" if passed else "FAILED") + f": security score {score:.0f}/100" + (f" ({breakdown})" if breakdown else ", no findings")
        return AgentResult(
            summary=summary,
            output={"passed": passed, "counts": counts},
            report={
                "kind": "security",
                "passed": passed,
                "score": score,
                "summary": summary,
                "details": {"findings": [f.to_dict() for f in findings], "counts": counts, "files_scanned": len(files)},
            },
        )


class ReviewerAgent(Agent):
    role = "reviewer"
    title = "Code Review Agent"
    description = "Reviews the code against requirements for correctness, completeness, robustness and security."
    kinds = frozenset({TaskKind.REVIEW})

    async def run(self, ctx: AgentContext) -> AgentResult:
        files = _source_files(ctx.workspace.read_all())
        expected = [f["path"] for f in ctx.memory.architecture.get("files", [])]
        static = await asyncio.to_thread(run_static_checks, files, expected, ctx.settings.node_path)
        checks = "\n".join(f"- [{i.severity}] {i.file}: {i.message}" for i in static[:12]) or "- static analysis: no problems found"

        budget = 15000
        blocks = []
        for path in expected or sorted(files):
            if path not in files:
                continue
            chunk = files[path][: max(1500, budget // max(1, len(expected)))]
            blocks.append(f"`{path}`:\n```{fence_lang(path)}\n{chunk}\n```")
        out = await ctx.structured(
            ReviewOutput,
            "reviewer",
            "code review",
            max_tokens=1500,
            brief=ctx.memory.brief(1800, include=("objective", "requirements", "architecture", "preferences")),
            checks=checks,
            files="\n\n".join(blocks),
        )
        issues = []
        for i in out.issues[:6]:
            file = i.file.strip("`./ ")
            if file not in files:
                match = next((p for p in files if p.endswith(file)), "")
                file = match
            issues.append(
                Issue(i.severity, "review", i.description, file=file, source="review", suggestion=i.suggestion)
            )
        blocking = [i for i in issues if i.severity in ("blocker", "major") and i.file]
        passed = not blocking
        summary = (
            ("APPROVED" if passed else "CHANGES REQUESTED")
            + f": score {out.score}/10, {len(blocking)} blocking issue(s), {len(issues) - len(blocking)} minor"
        )
        return AgentResult(
            summary=summary,
            output={"approved": passed, "score": out.score},
            report={
                "kind": "review",
                "passed": passed,
                "score": float(out.score * 10),
                "summary": summary + (f" — {out.summary}" if out.summary else ""),
                "details": {
                    "issues": [i.to_dict() for i in issues],
                    "strengths": out.strengths,
                    "model_said_approved": out.approved,
                    "review_summary": out.summary,
                },
            },
        )
