"""Headless-browser testing of generated web apps (Playwright, sync API).

Runs in a worker thread (``asyncio.to_thread``). Each call:
1. loads the app, capturing console errors, uncaught exceptions and failed
   requests, and takes a screenshot (shown in the dashboard);
2. executes scenario tests derived from the acceptance criteria, each in a
   fresh browser context so localStorage doesn't leak between scenarios.

Scenario failures are classified as *app* defects (send to a developer) or
*test* defects (the test referenced something that doesn't exist anywhere
in the code — regenerate the test instead of "fixing" working code).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

_launch_cache: dict[str, str] = {}


class BrowserUnavailable(RuntimeError):
    pass


def _launch(p: Any, preference: str) -> tuple[Any, str]:
    order = {
        "auto": ["chromium", "msedge", "chrome"],
        "chromium": ["chromium"],
        "msedge": ["msedge"],
        "chrome": ["chrome"],
    }[preference]
    if preference == "auto" and "auto" in _launch_cache:
        order = [_launch_cache["auto"]]
    errors = []
    for channel in order:
        try:
            if channel == "chromium":
                browser = p.chromium.launch(headless=True)
            else:
                browser = p.chromium.launch(headless=True, channel=channel)
            _launch_cache["auto"] = channel
            return browser, channel
        except Exception as e:  # noqa: BLE001 - try the next channel
            errors.append(f"{channel}: {str(e).splitlines()[0][:160]}")
    raise BrowserUnavailable("no usable browser (" + "; ".join(errors) + ")")


def browser_available(preference: str = "auto") -> tuple[bool, str]:
    if preference == "none":
        return False, "disabled"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright not installed"
    try:
        with sync_playwright() as p:
            browser, channel = _launch(p, preference)
            browser.close()
            return True, channel
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


_TOKEN_RE = re.compile(r"[#.]([A-Za-z_][\w\-]*)")


def _selector_tokens(selector: str) -> list[str]:
    return _TOKEN_RE.findall(selector)


def _classify_missing(selector: str, source_text: str) -> str:
    """A selector naming ids/classes that appear nowhere in the code is a test defect."""
    tokens = _selector_tokens(selector)
    if tokens and any(tok not in source_text for tok in tokens):
        return "test"
    return "app"


def run_browser_suite(
    base_url: str,
    entry: str,
    scenarios: list[dict[str, Any]],
    *,
    channel: str,
    screenshot_path: Path | None,
    source_text: str,
    step_timeout_ms: int = 4000,
) -> dict[str, Any]:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import sync_playwright

    url = f"{base_url.rstrip('/')}/{entry.lstrip('/')}" if entry else base_url
    result: dict[str, Any] = {"url": url, "channel": None, "load": {}, "scenarios": [], "screenshot": None}

    with sync_playwright() as p:
        browser, used = _launch(p, channel)
        result["channel"] = used
        try:
            # ---- smoke load ----------------------------------------------------------
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            ctx.route("**/favicon.ico", lambda route: route.fulfill(status=204, body=""))
            page = ctx.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            failed: list[str] = []
            page.on("console", lambda m: console_errors.append(m.text[:300]) if m.type == "error" else None)
            page.on("pageerror", lambda e: page_errors.append(str(e)[:300]))
            page.on("requestfailed", lambda r: failed.append(f"{r.method} {r.url} ({r.failure})"))
            page.on(
                "response",
                lambda r: failed.append(f"HTTP {r.status} {r.url}")
                if r.status >= 400 and r.url.startswith(base_url)
                else None,
            )
            page.on("dialog", lambda d: d.accept())
            status = None
            try:
                resp = page.goto(url, wait_until="load", timeout=15000)
                status = resp.status if resp else None
                page.wait_for_timeout(600)
            except PWError as e:
                page_errors.append(f"navigation failed: {str(e).splitlines()[0][:200]}")
            title = page.title() if status else ""
            body_text = page.inner_text("body") if status else ""
            interactive = page.locator("button, input, textarea, select, a[href]").count() if status else 0
            if screenshot_path and status:
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot_path), full_page=False)
                result["screenshot"] = str(screenshot_path)
            result["load"] = {
                "status": status,
                "title": title,
                "console_errors": console_errors[:10],
                "page_errors": page_errors[:10],
                "failed_requests": [f for f in failed if "favicon" not in f][:10],
                "text_length": len(body_text.strip()),
                "interactive_elements": interactive,
            }
            ctx.close()

            # ---- scenarios -------------------------------------------------------------
            for sc in scenarios[:8]:
                result["scenarios"].append(
                    _run_scenario(browser, url, sc, step_timeout_ms, source_text, PWError)
                )
        finally:
            browser.close()
    return result


def _run_scenario(
    browser: Any, url: str, sc: dict[str, Any], timeout: int, source_text: str, PWError: type[Exception]
) -> dict[str, Any]:
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.route("**/favicon.ico", lambda route: route.fulfill(status=204, body=""))
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.on("dialog", lambda d: d.accept())
    out: dict[str, Any] = {
        "name": sc.get("name", "scenario"),
        "criterion": sc.get("criterion", ""),
        "steps": sc.get("steps", [])[:15],
        "passed": False,
        "steps_run": 0,
        "failed_step": None,
        "error": "",
        "defect": None,
    }
    try:
        page.goto(url, wait_until="load", timeout=15000)
        page.wait_for_timeout(300)
        for i, step in enumerate(sc.get("steps", [])[:15]):
            action, selector, value = step.get("action"), (step.get("selector") or "").strip(), step.get("value") or ""
            try:
                _do_step(page, action, selector, value, timeout)
            except AssertionError as e:
                out.update(failed_step=i, error=f"step {i + 1} {action} '{selector}': {e}", defect="app")
                break
            except PWError as e:
                msg = str(e).splitlines()[0][:240]
                if "selector" in msg.lower() and ("valid" in msg.lower() or "unexpected" in msg.lower()):
                    defect = "test"
                elif selector and page.locator(selector).count() == 0:
                    defect = _classify_missing(selector, source_text)
                else:
                    defect = "app"
                out.update(failed_step=i, error=f"step {i + 1} {action} '{selector}': {msg}", defect=defect)
                break
            out["steps_run"] = i + 1
        else:
            out["passed"] = not errors
            if errors:
                out.update(error=f"uncaught exception: {errors[0]}", defect="app")
        if errors and not out["error"]:
            out["error"] = f"uncaught exception: {errors[0]}"
    except PWError as e:
        out.update(error=f"page failed to load: {str(e).splitlines()[0][:200]}", defect="app")
    finally:
        ctx.close()
    return out


def _poll(fn: Any, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        if fn():
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)


_TEXTS_JS = """els => els.map(e => ['INPUT', 'TEXTAREA', 'SELECT', 'OUTPUT'].includes(e.tagName)
    ? (e.value ?? '') : (e.innerText ?? ''))"""


_REGEX_HINT = re.compile(r"\.\*|\.\+|\\[dws]|\[[^\]]+\]|^\^|\$$|\{\d+(,\d*)?\}")


def _as_regex(value: str) -> re.Pattern[str] | None:
    """Models often write regex expectations (e.g. '.*[A-Z].*'); honour them when unambiguous."""
    if not _REGEX_HINT.search(value):
        return None
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error:
        return None


def _texts(loc: Any) -> list[str]:
    """Visible text of each match; form fields contribute their current value."""
    try:
        return list(loc.evaluate_all(_TEXTS_JS))
    except Exception:  # noqa: BLE001 - element detached mid-poll
        return []


def _do_step(page: Any, action: str, selector: str, value: str, timeout: int) -> None:
    loc = page.locator(selector or "body")
    if action == "fill":
        loc.first.fill(value, timeout=timeout)
    elif action == "click":
        loc.first.click(timeout=timeout)
    elif action == "press":
        loc.first.press(value or "Enter", timeout=timeout)
    elif action == "select":
        loc.first.select_option(value, timeout=timeout)
    elif action == "check":
        loc.first.check(timeout=timeout)
    elif action == "wait":
        page.wait_for_timeout(min(int(value) if value.isdigit() else 300, 3000))
    elif action == "expect_visible":
        loc.first.wait_for(state="visible", timeout=timeout)
    elif action == "expect_hidden":
        loc.first.wait_for(state="hidden", timeout=timeout)
    elif action == "expect_text":
        needle = value.strip().lower()
        if not needle:  # "has some text": an empty expectation would otherwise pass vacuously
            if not _poll(lambda: any(t.strip() for t in _texts(loc)), timeout):
                raise AssertionError("expected non-empty text, found nothing")
        else:
            pattern = _as_regex(value.strip())

            def matches(t: str) -> bool:
                return bool(pattern.search(t)) if pattern else needle in t.lower()

            if not _poll(lambda: any(matches(t) for t in _texts(loc)), timeout):
                texts = " | ".join(t.strip()[:60] for t in _texts(loc)[:3])
                kind = "matching /" if pattern else "containing '"
                raise AssertionError(f"expected text {kind}{value}{'/' if pattern else chr(39)}, found: {texts or '(nothing)'}")
    elif action == "expect_length":
        m = re.match(r"\s*(>=|<=|>|<)?\s*(\d+)", value or "1")
        op, n = (m.group(1) or "=="), int(m.group(2)) if m else 1
        ops = {"==": lambda c: c == n, ">=": lambda c: c >= n, "<=": lambda c: c <= n, ">": lambda c: c > n, "<": lambda c: c < n}
        if not _poll(lambda: any(ops[op](len(t.strip())) for t in _texts(loc)), timeout):
            lengths = [len(t.strip()) for t in _texts(loc)[:3]]
            raise AssertionError(f"expected text length {op} {n}, found lengths {lengths or '(no element)'}")
    elif action == "expect_count":
        m = re.match(r"\s*(>=|<=|>|<)?\s*(\d+)", value or "1")
        op, n = (m.group(1) or "=="), int(m.group(2)) if m else 1
        ops = {"==": lambda c: c == n, ">=": lambda c: c >= n, "<=": lambda c: c <= n, ">": lambda c: c > n, "<": lambda c: c < n}
        if not _poll(lambda: ops[op](loc.count()), timeout):
            raise AssertionError(f"expected count {op} {n}, found {loc.count()}")
    elif action == "expect_value":
        if not _poll(lambda: loc.first.input_value(timeout=timeout) == value, timeout):
            raise AssertionError(f"expected value '{value}', found '{loc.first.input_value(timeout=timeout)}'")
    else:
        raise AssertionError(f"unknown action {action}")
