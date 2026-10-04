"""The CEO agent: project charter (intake) and the final release review.

The CEO's *policy* decisions during the run (fix assignment, escalation,
rollback, approval gating) live in ``orchestrator.policy`` and are logged
as CEO decisions; this module holds the CEO's LLM-backed judgement calls.
"""

from __future__ import annotations

from ..memory import MemoryKind
from ..schemas import FinalReviewOutput, IntakeOutput
from ..states import TaskKind
from .base import Agent, AgentContext, AgentError, AgentResult
from .conventions import PLATFORM_CONSTRAINTS


class CEOAgent(Agent):
    role = "ceo"
    title = "AI CEO"
    description = "Understands the objective, sets the charter, decides on fixes and escalations, approves releases."
    kinds = frozenset({TaskKind.INTAKE, TaskKind.FINAL_REVIEW})

    async def run(self, ctx: AgentContext) -> AgentResult:
        if ctx.task.kind == TaskKind.INTAKE:
            return await self._intake(ctx)
        if ctx.task.kind == TaskKind.FINAL_REVIEW:
            return await self._final_review(ctx)
        raise AgentError(f"CEO cannot handle {ctx.task.kind}", retryable=False)

    async def _intake(self, ctx: AgentContext) -> AgentResult:
        prefs = ctx.memory.values(MemoryKind.PREFERENCE)
        feedback = ("CLIENT PREFERENCES:\n" + "\n".join(f"- {p}" for p in prefs)) if prefs else ""
        out = await ctx.structured(
            IntakeOutput, "ceo_intake", "project charter", max_tokens=700, request=ctx.project.objective, feedback=feedback
        )
        forced = (ctx.project.settings or {}).get("app_type")
        if forced in ("static_web", "web_with_backend") and forced != out.app_type:
            ctx.memory.record_decision(f"App type set to {forced}", "Chosen explicitly by the client", "ceo")
            out.app_type = forced
        ctx.memory.set(
            MemoryKind.OBJECTIVE,
            "main",
            {
                "request": ctx.project.objective,
                "objective": out.objective,
                "project_name": out.project_name,
                "app_type": out.app_type,
                "target_users": out.target_users,
            },
            self.role,
        )
        for c in PLATFORM_CONSTRAINTS[out.app_type] + out.constraints[:5]:
            ctx.memory.add_constraint(c, self.role)
        ctx.memory.record_decision(f"Build a {out.app_type.replace('_', ' ')} app: {out.objective}", out.summary, self.role)
        return AgentResult(summary=f"Charter set: {out.project_name} ({out.app_type}). {out.summary}", output=out.model_dump())

    async def _final_review(self, ctx: AgentContext) -> AgentResult:
        status = ctx.task.input.get("status_text", "")
        out = await ctx.structured(
            FinalReviewOutput,
            "ceo_final_review",
            "release decision",
            max_tokens=700,
            brief=ctx.memory.brief(2500),
            iteration=ctx.project.iteration,
            status=status,
        )
        ctx.memory.record_decision(
            f"Release decision: {out.decision}", out.summary + (f" Unmet: {out.unmet_criteria}" if out.unmet_criteria else ""), self.role
        )
        return AgentResult(
            summary=f"Decision: {out.decision.upper()} — {out.summary}",
            output=out.model_dump(),
            report={
                "kind": "final_review",
                "passed": out.decision == "approve",
                "score": 100.0 if out.decision == "approve" else 50.0,
                "summary": out.summary,
                "details": out.model_dump(),
            },
        )
