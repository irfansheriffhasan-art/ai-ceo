"""Testing agent: static analysis, browser tests, API tests and regression tracking."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any

from ..memory import MemoryKind
from ..schemas import ApiTestPlanOutput, TestPlanOutput
from ..states import TaskKind
from ..verification.api_tests import run_api_cases
from ..verification.browser import BrowserUnavailable, run_browser_suite
from ..verification.issues import Issue
from ..verification.servers import BackendProcess, BackendStartError, StaticServer
from ..verification.static_checks import run_static_checks
from ..workspace.analysis import parse_python
from .base import Agent, AgentContext, AgentResult

_CLASS_RE = re.compile(r"""(?:className\s*=\s*|classList\.(?:add|toggle)\(\s*)['"`]([\w\- ]+)['"`]""")


SOURCE_EXTENSIONS = (".html", ".css", ".js", ".py", ".sql")


def _code_files(files: dict[str, str]) -> dict[str, str]:
    """Everything except documentation (used for security scanning, which also covers config)."""
    return {p: s for p, s in files.items() if not p.startswith("docs/") and not p.endswith(".md")}


def _source_files(files: dict[str, str]) -> dict[str, str]:
    """Application source only (used for static analysis and tests)."""
    return {p: s for p, s in files.items() if p.endswith(SOURCE_EXTENSIONS) and not p.startswith("docs/")}


class TestingAgent(Agent):
    role = "testing"
    title = "Testing Agent"
    description = "Runs static analysis, headless-browser acceptance tests, API tests and regression checks."
    kinds = frozenset({TaskKind.TEST})

    async def run(self, ctx: AgentContext) -> AgentResult:
        settings = ctx.settings
        arch = ctx.memory.architecture
        backend = bool(arch.get("needs_backend"))
        files = _source_files(ctx.workspace.read_all())
        expected = [f["path"] for f in arch.get("files", [])]
        html_path = "frontend/index.html" if backend else "index.html"
        js_path = "frontend/app.js" if backend else "app.js"

        static = await asyncio.to_thread(run_static_checks, files, expected, settings.node_path)
        errors = sum(1 for i in static if i.severity == "error")
        ctx.note(f"Testing Agent ran static analysis on {len(files)} files: {errors} error(s), {len(static) - errors} warning(s)")
        issues: list[Issue] = list(static)
        details: dict[str, Any] = {"static": [i.to_dict() for i in static], "load": None, "scenarios": [], "api": []}
        checks_total = len(files)
        checks_passed = len(files) - len({i.file for i in static if i.severity == "error"})

        browser_ok, browser_detail = await ctx.services.browser_status()
        details["browser"] = browser_detail
        if html_path not in files:
            ctx.note("Testing Agent skipped runtime tests: no HTML entry point", level="warning")
        elif not browser_ok:
            ctx.note(f"Browser tests unavailable ({browser_detail}); relying on static analysis", level="warning")
            details["browser_skipped"] = browser_detail
        else:
            scenarios = await self._browser_plan(ctx, files, html_path, js_path)
            api_cases = await self._api_plan(ctx, files) if backend else []
            shot = settings.artifacts_dir / ctx.project.id / f"screenshot-i{ctx.project.iteration}-{ctx.task.id}.png"
            source_text = "\n".join(files.values())
            try:
                runtime = await asyncio.to_thread(
                    self._run_runtime, ctx, backend, scenarios, api_cases, shot, source_text, settings.browser_channel
                )
                invalid = [sc for sc in runtime.get("scenarios", []) if sc.get("defect") == "test"]
                if invalid:
                    # Self-correction: the tests were wrong, not the app. Rewrite them once and re-run.
                    ctx.note(f"Testing Agent found {len(invalid)} invalid test scenario(s); rewriting the test plan", level="warning")
                    feedback = "PREVIOUS TEST PLAN WAS INVALID — these scenarios referenced elements that do not exist:\n" + "\n".join(
                        f"- '{sc['name']}': {sc['error'][:200]}" for sc in invalid
                    )
                    scenarios = await self._browser_plan(ctx, files, html_path, js_path, feedback=feedback)
                    runtime = await asyncio.to_thread(
                        self._run_runtime, ctx, backend, scenarios, api_cases, shot, source_text, settings.browser_channel
                    )
            except BrowserUnavailable as e:
                ctx.services.mark_browser_unavailable(str(e))
                runtime = {"error": str(e)}
            r_issues, r_total, r_passed = self._classify(runtime, html_path, js_path, ctx)
            issues += r_issues
            checks_total += r_total
            checks_passed += r_passed
            details.update(
                load=runtime.get("load"),
                scenarios=runtime.get("scenarios", []),
                api=runtime.get("api", []),
                backend_log=runtime.get("backend_log", ""),
                channel=runtime.get("channel"),
            )
            if runtime.get("screenshot"):
                details["screenshot"] = Path(runtime["screenshot"]).name
        checks_total = max(checks_total, len(files))

        blocking = [i for i in issues if i.severity == "error"]
        passed = not blocking
        score = round(100.0 * checks_passed / checks_total, 1) if checks_total else 0.0
        details["issues"] = [i.to_dict() for i in issues]
        self._update_memory(ctx, issues, passed, score, details)
        valid = [s for s in details["scenarios"] if s.get("defect") != "test"]
        invalid = len(details["scenarios"]) - len(valid)
        sc_pass = sum(1 for s in valid if s.get("passed"))
        api_valid = [a for a in details["api"] if a.get("defect") != "test"]
        api_pass = sum(1 for a in api_valid if a.get("passed"))
        parts = [f"{len(blocking)} failure(s)"]
        if valid:
            parts.append(f"{sc_pass}/{len(valid)} acceptance scenarios passed")
        if invalid:
            parts.append(f"{invalid} invalid test(s) skipped — criteria unverified")
        if api_valid:
            parts.append(f"{api_pass}/{len(api_valid)} API tests passed")
        if details.get("browser_skipped"):
            parts.append("browser tests unavailable")
        details["unverified_scenarios"] = invalid
        summary = ("PASSED: " if passed else "FAILED: ") + ", ".join(parts)
        return AgentResult(
            summary=summary,
            output={"passed": passed, "score": score, "failures": len(blocking)},
            report={"kind": "test", "passed": passed, "score": score, "summary": summary, "details": details},
        )

    # ---- test planning ---------------------------------------------------------------
    async def _browser_plan(
        self, ctx: AgentContext, files: dict[str, str], html_path: str, js_path: str, feedback: str = ""
    ) -> list[dict[str, Any]]:
        html = files.get(html_path, "")
        js = files.get(js_path, "")
        # Keyed on the HTML only: fixes to app.js re-run the SAME scenarios (true regression testing)
        # instead of moving the goalposts with a freshly generated plan every iteration.
        digest = hashlib.sha1(html.encode("utf-8")).hexdigest()[:12]
        cached = ctx.memory.get(MemoryKind.TEST_PLAN, "browser")
        if not feedback and cached and cached.get("hash") == digest and not cached.get("needs_revision"):
            return cached["scenarios"]
        criteria = ctx.memory.acceptance_criteria()
        if not criteria:
            return []
        dynamic = sorted({c for m in _CLASS_RE.findall(js) for c in m.split()})
        plan = await ctx.structured(
            TestPlanOutput,
            "testing_plan",
            "browser test plan",
            max_tokens=2000,
            criteria="\n".join(f"- {c}" for c in criteria[:8]),
            html=html[:6000],
            js=js[:5000],
            dynamic_classes=", ".join(dynamic) or "(none)",
            feedback=feedback,
        )
        scenarios = [s.model_dump() for s in plan.scenarios if s.steps][:8]
        version = (cached or {}).get("version", 0) + 1
        ctx.memory.set(MemoryKind.TEST_PLAN, "browser", {"hash": digest, "scenarios": scenarios, "version": version}, self.role)
        ctx.note(f"Testing Agent wrote {len(scenarios)} acceptance scenarios (test plan v{version})")
        return scenarios

    async def _api_plan(self, ctx: AgentContext, files: dict[str, str]) -> list[dict[str, Any]]:
        code = files.get("backend/main.py", "")
        if not code:
            return []
        routes = parse_python(code).routes
        digest = hashlib.sha1(repr(sorted(routes)).encode("utf-8")).hexdigest()[:12]
        cached = ctx.memory.get(MemoryKind.TEST_PLAN, "api")
        if cached and cached.get("hash") == digest and not cached.get("needs_revision"):
            return cached["cases"]
        endpoints = "\n".join(
            f"- {e['method']} {e['path']}: {e.get('description', '')}" for e in ctx.memory.architecture.get("api_endpoints", [])
        )
        plan = await ctx.structured(
            ApiTestPlanOutput,
            "testing_api_plan",
            "API test plan",
            max_tokens=1500,
            endpoints=endpoints,
            routes=", ".join(f"{m} {p}" for m, p in routes) or "(none found)",
            code=code[:7000],
        )
        cases = [c.model_dump() for c in plan.cases][:10]
        ctx.memory.set(MemoryKind.TEST_PLAN, "api", {"hash": digest, "cases": cases}, self.role)
        return cases

    # ---- execution (worker thread) --------------------------------------------------------
    def _run_runtime(
        self,
        ctx: AgentContext,
        backend: bool,
        scenarios: list[dict[str, Any]],
        api_cases: list[dict[str, Any]],
        shot: Path,
        source_text: str,
        channel: str,
    ) -> dict[str, Any]:
        root = ctx.workspace.root
        if not backend:
            with StaticServer(root) as srv:
                return run_browser_suite(
                    srv.url, "index.html", scenarios, channel=channel, screenshot_path=shot, source_text=source_text
                )
        if not ctx.settings.run_generated_backends:
            return {"error": "running generated backends is disabled (AICEO_RUN_GENERATED_BACKENDS=false)"}
        log_path = ctx.settings.artifacts_dir / ctx.project.id / f"backend-test-{ctx.task.id}.log"
        proc = BackendProcess(root, log_path)
        try:
            base = proc.start()
        except BackendStartError as e:
            return {"backend_error": str(e), "backend_log": e.log_tail}
        try:
            api = run_api_cases(base, api_cases)
            result = run_browser_suite(base, "", scenarios, channel=channel, screenshot_path=shot, source_text=source_text)
            result["api"] = api
            result["backend_log"] = proc.log_tail(2000)
            return result
        finally:
            proc.stop()

    # ---- classification ------------------------------------------------------------------
    def _classify(
        self, runtime: dict[str, Any], html_path: str, js_path: str, ctx: AgentContext
    ) -> tuple[list[Issue], int, int]:
        issues: list[Issue] = []
        total = passed = 0
        if runtime.get("error"):
            issues.append(Issue("warning", "test_infrastructure", runtime["error"], source="runtime"))
            return issues, 0, 0
        if runtime.get("backend_error"):
            issues.append(
                Issue(
                    "error",
                    "backend_start",
                    f"backend failed to start: {runtime['backend_error']}",
                    file="backend/main.py",
                    source="runtime",
                    evidence=runtime.get("backend_log", "")[-1500:],
                )
            )
            return issues, 1, 0

        load = runtime.get("load") or {}
        total += 1
        load_ok = load.get("status") == 200 and not load.get("page_errors")
        if load.get("status") != 200:
            issues.append(Issue("error", "load", f"app failed to load (HTTP {load.get('status')})", file=html_path, source="runtime"))
        for err in load.get("page_errors", []):
            issues.append(Issue("error", "runtime_exception", f"uncaught JavaScript error on page load: {err}", file=js_path, source="runtime"))
        for req in load.get("failed_requests", []):
            issues.append(Issue("error", "failed_request", f"request failed while loading: {req}", file=html_path, source="runtime"))
            load_ok = False
        for msg in load.get("console_errors", []):
            issues.append(Issue("warning", "console_error", f"console error: {msg}", file=js_path, source="runtime"))
        if load.get("status") == 200 and not load.get("text_length") and not load.get("interactive_elements"):
            issues.append(Issue("error", "blank_page", "page renders blank (no text, no controls)", file=html_path, source="runtime"))
            load_ok = False
        passed += 1 if load_ok else 0

        previous = ctx.memory.get(MemoryKind.TEST_RESULT, "scenario_status", {}) or {}
        current_status: dict[str, bool] = {}
        test_defects = 0
        for sc in runtime.get("scenarios", []):
            key = sc.get("criterion") or sc.get("name", "")
            if sc.get("passed"):
                total += 1
                passed += 1
                current_status[key] = True
                continue
            if sc.get("defect") == "test":
                test_defects += 1
                issues.append(
                    Issue(
                        "warning",
                        "test_defect",
                        f"scenario '{sc['name']}' could not run (test references something that does not exist): {sc['error']}",
                        source="scenario",
                    )
                )
                continue
            total += 1
            current_status[key] = False
            regression = previous.get(key) is True
            issues.append(
                Issue(
                    "error",
                    "regression" if regression else "acceptance",
                    ("REGRESSION — previously passing. " if regression else "")
                    + f"acceptance test failed: '{sc.get('criterion') or sc['name']}' — {sc['error']}",
                    file=js_path,
                    source="scenario",
                )
            )
        if test_defects:
            plan = ctx.memory.get(MemoryKind.TEST_PLAN, "browser")
            if plan:
                plan["needs_revision"] = True
                ctx.memory.set(MemoryKind.TEST_PLAN, "browser", plan, self.role)
        ctx.memory.set(MemoryKind.TEST_RESULT, "scenario_status", {**previous, **current_status}, self.role)

        for case in runtime.get("api", []):
            if case.get("defect") == "test":
                issues.append(Issue("warning", "test_defect", f"API test '{case['name']}' is invalid: {case['error']}", source="api"))
                continue
            total += 1
            if case.get("passed"):
                passed += 1
            else:
                issues.append(
                    Issue(
                        "error",
                        "api",
                        f"API test '{case['name']}' failed: {case['method']} {case['path']} — {case['error']}",
                        file="backend/main.py",
                        source="api",
                    )
                )
        return issues, total, passed

    def _update_memory(self, ctx: AgentContext, issues: list[Issue], passed: bool, score: float, details: dict[str, Any]) -> None:
        open_now = {i.fingerprint: i for i in issues if i.severity == "error"}
        for item in ctx.memory.items(MemoryKind.BUG):
            bug = item["value"]
            if bug.get("status") == "open" and bug.get("source") != "security" and item["key"] not in open_now:
                bug["status"] = "fixed"
                bug["fixed_in_iteration"] = ctx.project.iteration
                ctx.memory.set(MemoryKind.BUG, item["key"], bug, self.role)
        for fp, issue in open_now.items():
            ctx.memory.set(
                MemoryKind.BUG,
                fp,
                {"status": "open", "message": issue.message[:300], "file": issue.file, "source": issue.source, "iteration": ctx.project.iteration},
                self.role,
            )
        ctx.memory.set(
            MemoryKind.TEST_RESULT,
            f"iteration-{ctx.project.iteration}",
            {"passed": passed, "score": score, "errors": len(open_now), "scenarios": len(details.get("scenarios", []))},
            self.role,
        )
