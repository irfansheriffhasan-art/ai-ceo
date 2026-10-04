"""Planning agents: Product, Strategic Planner, Architect, UI/UX and Project Manager."""

from __future__ import annotations

import json

from ..memory import MemoryKind
from ..schemas import ArchitectureOutput, DesignOutput, RequirementsOutput, StrategyOutput
from ..states import TaskKind
from .base import Agent, AgentContext, AgentError, AgentResult, TaskSpec
from .conventions import ROLE_TITLES, build_order, layout_for, normalize_architecture


class ProductAgent(Agent):
    role = "product"
    title = "Product Agent"
    description = "Writes user stories, prioritised features and testable acceptance criteria."
    kinds = frozenset({TaskKind.REQUIREMENTS})

    async def run(self, ctx: AgentContext) -> AgentResult:
        app_type = ctx.memory.get(MemoryKind.OBJECTIVE, "main", {}).get("app_type", "static_web")
        out = await ctx.structured(
            RequirementsOutput,
            "product_requirements",
            "requirements",
            max_tokens=1400,
            brief=ctx.memory.brief(2000),
            file_budget=len(layout_for(app_type)),
        )
        if not out.acceptance_criteria:
            raise AgentError("requirements have no acceptance criteria")
        ctx.memory.set(MemoryKind.REQUIREMENTS, "spec", out.model_dump(), self.role)
        doc = ["# Requirements", "", out.summary, "", "## User stories", *[f"- {s}" for s in out.user_stories], ""]
        doc += ["## Features", *[f"- **{f.name}** ({f.priority}): {f.description}" for f in out.features], ""]
        doc += ["## Acceptance criteria", *[f"- [ ] {c}" for c in out.acceptance_criteria], ""]
        doc += ["## Out of scope", *[f"- {o}" for o in out.out_of_scope], ""]
        musts = sum(1 for f in out.features if f.priority == "must")
        return AgentResult(
            summary=f"{len(out.features)} features ({musts} must-have), {len(out.acceptance_criteria)} acceptance criteria",
            output=out.model_dump(),
            files={"docs/REQUIREMENTS.md": "\n".join(doc)},
            commit_message="docs(product): add requirements and acceptance criteria",
        )


class PlannerAgent(Agent):
    role = "planner"
    title = "Strategic Planner"
    description = "Turns requirements into milestones, priorities, risks and a definition of done."
    kinds = frozenset({TaskKind.STRATEGY})

    async def run(self, ctx: AgentContext) -> AgentResult:
        out = await ctx.structured(
            StrategyOutput, "planner_strategy", "delivery strategy", max_tokens=900, brief=ctx.memory.brief(2500)
        )
        # Risks stay advisory (stored in the strategy, shown in the dashboard). They are NOT promoted to
        # constraints: constraints reach every developer prompt, and a planner's suggestion such as
        # "use library X" would then override the platform rules (observed in a real run: crypto-js).
        ctx.memory.set(MemoryKind.STRATEGY, "plan", out.model_dump(), self.role)
        return AgentResult(
            summary=f"{len(out.milestones)} milestones; DoD has {len(out.definition_of_done)} checks",
            output=out.model_dump(),
        )


class ArchitectAgent(Agent):
    role = "architect"
    title = "Architect Agent"
    description = "Chooses the stack, file structure, data model, API and records architecture decisions."
    kinds = frozenset({TaskKind.ARCHITECTURE})

    async def run(self, ctx: AgentContext) -> AgentResult:
        app_type = ctx.memory.get(MemoryKind.OBJECTIVE, "main", {}).get("app_type", "static_web")
        backend = app_type == "web_with_backend"
        layout = layout_for(app_type)
        if backend:
            layout_rules = (
                "- This app has a Python backend. Use exactly these files: "
                + ", ".join(p for p, _, _ in layout)
                + ". backend/main.py serves the JSON API under /api and also serves the frontend folder."
            )
            api_rule = "every JSON endpoint the frontend needs, all under /api/, including GET /api/health."
        else:
            layout_rules = (
                "- This is a static web app that runs entirely in the browser. Use exactly these files at the project root: "
                + ", ".join(p for p, _, _ in layout)
                + ". Persist user data in localStorage."
            )
            api_rule = "empty list (there is no backend)."
        out = await ctx.structured(
            ArchitectureOutput,
            "architect",
            "architecture",
            max_tokens=1400,
            brief=ctx.memory.brief(2500),
            layout_rules=layout_rules,
            needs_backend="true" if backend else "false",
            api_rule=api_rule,
        )
        arch, notes = normalize_architecture(out, app_type)
        if _wants_ai(ctx):
            for f in arch["files"]:
                if f["path"].endswith("app.js"):
                    f["owner_role"] = "aiml"
            notes.append("AI/data-driven features requested: the AI/ML Agent owns the application logic (app.js).")
        ctx.memory.set(MemoryKind.ARCHITECTURE, "spec", arch, self.role)
        for d in arch["decisions"][:4]:
            ctx.memory.record_decision(d["decision"], d["rationale"], self.role)
        for n in notes:
            ctx.memory.record_decision("Architecture normalised to platform conventions", n, "ceo")
        for f in arch["files"]:
            ctx.memory.set(MemoryKind.FILE, f["path"], {"purpose": f["purpose"], "owner": f["owner_role"]}, self.role)

        doc = ["# Architecture", "", arch["summary"], "", "## Stack"]
        doc += [f"- {k}: {v}" for k, v in arch["stack"].items()]
        doc += ["", "## Files", *[f"- `{f['path']}` ({f['owner_role']}): {f['purpose']}" for f in arch["files"]]]
        if arch["data_model"]:
            doc += ["", "## Data model", *[f"- {e['name']}: {', '.join(e['fields'])}" for e in arch["data_model"]]]
        if arch["api_endpoints"]:
            doc += ["", "## API", *[f"- `{e['method']} {e['path']}` — {e['description']}" for e in arch["api_endpoints"]]]
        doc += ["", "## Decisions", *[f"- **{d['decision']}** — {d['rationale']}" for d in arch["decisions"]], ""]
        return AgentResult(
            summary=f"{len(arch['files'])} files, backend={'yes' if backend else 'no'}, {len(arch['api_endpoints'])} endpoints",
            output=arch,
            files={"docs/ARCHITECTURE.md": "\n".join(doc)},
            commit_message="docs(architecture): add architecture and file plan",
        )


_AI_KEYWORDS = (
    " ai ",
    "artificial intelligence",
    "machine learning",
    "recommend",
    "predict",
    "classif",
    "sentiment",
    "smart ",
    "categoriz",
    "categoris",
    "chatbot",
    "insight",
)


def _wants_ai(ctx: AgentContext) -> bool:
    req = ctx.memory.requirements
    text = " ".join(
        [ctx.project.objective]
        + [f.get("name", "") + " " + f.get("description", "") for f in req.get("features", [])]
    ).lower()
    return any(k in f" {text} " for k in _AI_KEYWORDS)


class UIUXAgent(Agent):
    role = "uiux"
    title = "UI/UX Agent"
    description = "Defines the visual language: palette, typography, layout, components and accessibility rules."
    kinds = frozenset({TaskKind.DESIGN})

    async def run(self, ctx: AgentContext) -> AgentResult:
        out = await ctx.structured(
            DesignOutput,
            "uiux_design",
            "visual design",
            max_tokens=1000,
            brief=ctx.memory.brief(2000, include=("objective", "requirements", "preferences")),
        )
        ctx.memory.set(MemoryKind.DESIGN, "spec", out.model_dump(), self.role)
        p = out.palette
        doc = [
            f"# Design — {out.style_name}",
            "",
            out.summary,
            "",
            "## Palette",
            *[f"- {k}: `{v}`" for k, v in p.model_dump().items()],
            "",
            f"## Typography\n\n`{out.font_family}`",
            "",
            f"## Layout\n\n{out.layout}",
            "",
            "## Components",
            *[f"- **{c.name}**: {c.description}" for c in out.components],
            "",
            "## Accessibility",
            *[f"- {a}" for a in out.accessibility],
            "",
        ]
        return AgentResult(
            summary=f"'{out.style_name}' style, {len(out.components)} components",
            output=out.model_dump(),
            files={"docs/DESIGN.md": "\n".join(doc)},
            commit_message="docs(design): add UI/UX design spec",
        )


class ProjectManagerAgent(Agent):
    """Deterministic work breakdown: turns the file plan into an ordered task graph."""

    role = "pm"
    title = "Project Manager"
    description = "Breaks the architecture into implementation tasks with owners, priorities and dependencies; tracks progress."
    kinds = frozenset({TaskKind.BREAKDOWN})
    uses_llm = False

    async def run(self, ctx: AgentContext) -> AgentResult:
        arch = ctx.memory.architecture
        files = arch.get("files", [])
        if not files:
            raise AgentError("no architecture file plan to break down", retryable=False)
        features = ctx.memory.requirements.get("features", [])
        must = [f["name"] for f in features if f.get("priority") == "must"]
        deps = build_order([f["path"] for f in files])
        specs: list[TaskSpec] = []
        for f in files:
            path, role = f["path"], f["owner_role"]
            verb = {"frontend": "Build", "backend": "Implement", "database": "Design"}.get(role, "Build")
            description = f"{f['purpose']}."
            if must and path.endswith((".js", ".html", "main.py")):
                description += f" Must support: {', '.join(must[:6])}."
            specs.append(
                TaskSpec(
                    key=path,
                    title=f"{verb} {path}",
                    role=role,
                    kind=TaskKind.IMPLEMENT,
                    description=description,
                    priority=1 if not deps[path] else 2,
                    input={"files": [path]},
                    depends_on_keys=deps[path],
                )
            )
        plan = [
            {"task": s.title, "owner": ROLE_TITLES.get(s.role, s.role), "after": s.depends_on_keys} for s in specs
        ]
        ctx.memory.set(MemoryKind.PLAN, "work_breakdown", plan, self.role)
        return AgentResult(
            summary=f"Created {len(specs)} implementation tasks: " + "; ".join(s.title for s in specs),
            output={"tasks": plan, "dependency_graph": json.loads(json.dumps(deps))},
            new_tasks=specs,
        )
