"""Command-line interface.

    python main.py                       interactive: describe an idea, watch the company build it
    python main.py run "idea" [options]  build an idea non-interactively
    python main.py serve                 start the API + command-center dashboard
    python main.py doctor                check LLM, git, node and browser setup
    python main.py list                  list projects
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import webbrowser
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import Settings
from .log import setup_logging
from .states import ProjectStatus

console = Console()

BANNER = """[bold cyan]
████████████████████████████████████████
  AI-CEO  AUTONOMOUS DEV PLATFORM  v{v}
  Multi-Agent Software Company
████████████████████████████████████████[/bold cyan]
"""

STATUS_STYLE = {"working": "bold green", "retrying": "bold yellow", "error": "bold red", "idle": "dim"}
LEVEL_STYLE = {"error": "red", "warning": "yellow", "info": ""}


def _settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    if getattr(args, "provider", None):
        overrides["llm_provider"] = args.provider
    if getattr(args, "model", None):
        overrides["llm_model"] = args.model
    if getattr(args, "approve", False):
        overrides["require_human_approval"] = True
    if getattr(args, "no_bug", False):
        overrides["mock_inject_bug"] = False
    settings = Settings(**overrides)
    settings.ensure_dirs()
    return settings


# ---- live view ------------------------------------------------------------------------
def _render(snapshot: dict[str, Any], events: list[dict[str, Any]]) -> Group:
    p = snapshot["project"]
    head = Text.assemble(
        (f"{p['name']}", "bold"),
        f"  ·  status: ",
        (p["status"], "bold green" if p["status"] in ("running", "completed") else "bold yellow"),
        f"  ·  phase: {p['phase']}  ·  iteration {p['iteration']}  ·  {p['progress']:.0f}%",
    )
    agents = Table(expand=True, show_edge=False, header_style="bold")
    agents.add_column("Agent")
    agents.add_column("Status")
    agents.add_column("Current task", ratio=2)
    agents.add_column("Done", justify="right")
    for a in snapshot["agents"]:
        cur = a.get("current_task")
        task_text = ""
        if cur:
            task_text = f"{cur['title']} ({cur['elapsed_s']:.0f}s" + (f", {cur['tokens']} tok" if cur.get("tokens") else "") + ")"
        agents.add_row(a["title"], Text(a["status"], STATUS_STYLE.get(a["status"], "")), task_text, str(a["completed"]))
    feed = Table.grid(padding=(0, 1))
    for e in events[-14:]:
        feed.add_row(Text(e["ts"][11:19], "dim"), Text(e["message"][:160], LEVEL_STYLE.get(e["level"], "")))
    c = snapshot["counts"]
    board = "  ".join(f"{k}: {v}" for k, v in sorted(c.items()))
    return Group(
        Panel(head, title="AI-CEO", border_style="cyan"),
        Panel(agents, title="Agent monitor", border_style="blue"),
        Panel(Text(board), title="Task board", border_style="magenta"),
        Panel(feed, title="Activity", border_style="green"),
    )


async def _watch(engine: Any, pid: str) -> Any:
    services = engine.s
    queue = services.events.subscribe()
    events = [e.to_dict() for e in services.store.list_events(pid, limit=20)]
    runner_done = asyncio.create_task(engine.wait(pid))
    try:
        with Live(_render(engine.snapshot(pid), events), console=console, refresh_per_second=2, transient=False) as live:
            while not runner_done.done():
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=1.0)
                    if ev.get("project_id") == pid and ev.get("id") is not None:
                        events.append(ev)
                except TimeoutError:
                    pass
                live.update(_render(engine.snapshot(pid), events))
            live.update(_render(engine.snapshot(pid), events))
        return await runner_done
    finally:
        services.events.unsubscribe(queue)


async def _build(args: argparse.Namespace, idea: str, interactive: bool) -> int:
    from .orchestrator import Engine
    from .services import Services

    settings = _settings(args)
    setup_logging(settings.logs_dir, console=False)
    services = Services(settings)
    engine = Engine(services)
    engine.recover()
    status = await services.system_status()
    if not status["llm"]["ok"]:
        console.print(f"[red]LLM not ready:[/red] {status['llm']['detail']}")
        return 2
    console.print(
        f"LLM: [bold]{status['llm']['provider']}[/bold] / {status['llm']['model']}  ·  "
        f"browser tests: {'on (' + status['browser']['detail'] + ')' if status['browser']['ok'] else 'off'}"
    )
    project_settings: dict[str, Any] = {}
    if getattr(args, "backend", False):
        project_settings["app_type"] = "web_with_backend"
    if getattr(args, "max_fix", None) is not None:
        project_settings["max_fix_iterations"] = args.max_fix
    if getattr(args, "approve", False):
        project_settings["require_approval"] = True
    project = engine.create_project(idea, getattr(args, "name", None), project_settings)
    console.print(f"Project [bold]{project.id}[/bold] → {project.workspace_path}")
    try:
        await engine.start(project.id)
        while True:
            project = await _watch(engine, project.id)
            if project.status == ProjectStatus.AWAITING_APPROVAL and interactive:
                answer = console.input("[bold]Approve release?[/bold] [Y]es / or type feedback to revise: ").strip()
                if answer.lower() in ("", "y", "yes"):
                    await engine.approve(project.id)
                else:
                    await engine.reject(project.id, answer)
                continue
            break
        _summary(engine, project.id)
        if project.status == ProjectStatus.COMPLETED and project.preview_url:
            console.print(f"\n[bold green]Live preview:[/bold green] {project.preview_url}")
            if interactive:
                webbrowser.open(project.preview_url)
                console.input("Press Enter to stop the preview and exit...")
        return 0 if project.status == ProjectStatus.COMPLETED else 1
    finally:
        await engine.shutdown()


def _summary(engine: Any, pid: str) -> None:
    store = engine.s.store
    p = store.get_project(pid)
    table = Table(title=f"{p.name} — {p.status}", show_lines=False)
    table.add_column("Gate")
    table.add_column("Result")
    for kind in ("test", "security", "review", "final_review", "deploy"):
        reports = store.list_reports(pid, kind)
        if reports:
            r = reports[-1]
            table.add_row(kind, Text(r.summary[:150], "green" if r.passed else "red"))
    console.print(table)
    usage = store.llm_usage(pid)
    console.print(
        f"LLM calls: {usage['calls']}  ·  tokens in/out: {usage['input_tokens']}/{usage['output_tokens']}  ·  "
        f"model time: {usage['latency_ms'] / 1000:.0f}s"
    )
    if p.status_reason:
        console.print(f"[yellow]{p.status_reason}[/yellow]")
    console.print(f"Workspace (git repo): {p.workspace_path}")


async def _doctor(args: argparse.Namespace) -> int:
    from .services import Services

    settings = _settings(args)
    services = Services(settings)
    status = await services.system_status()
    ok = True
    for name in ("llm", "git", "node", "browser"):
        item = status[name]
        ok &= bool(item["ok"]) or name == "browser"
        detail = item.get("detail", "")
        if name == "llm":
            detail = f"{item['provider']} / {item['model']} — {detail}"
        console.print(f"{'[green]✔[/green]' if item['ok'] else '[red]✘[/red]'} {name:8} {detail}")
    await services.aclose()
    return 0 if ok else 1


def _list(args: argparse.Namespace) -> int:
    from .db import Store

    settings = _settings(args)
    store = Store(settings.db_path)
    table = Table("id", "name", "status", "phase", "iter", "progress", "created")
    for p in store.list_projects():
        table.add_row(p.id, p.name[:40], p.status, p.phase, str(p.iteration), f"{p.progress:.0f}%", str(p.created_at)[:16])
    console.print(table)
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api.app import create_app

    settings = _settings(args)
    host = args.host or settings.host
    port = args.port or settings.port
    token = settings.resolve_auth_token()
    app = create_app(settings)
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    console.print(BANNER.format(v=__version__))
    console.print(f"Dashboard: [bold]{url}[/bold]")
    console.print(f"Access token: [bold]{token}[/bold]  (stored in {settings.data_dir / 'auth_token'})")
    if host not in ("127.0.0.1", "localhost"):
        console.print("[yellow]Warning: listening on a non-local interface. Anyone who can reach it needs the token.[/yellow]")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-ceo", description="AI-CEO autonomous multi-agent software company")
    parser.add_argument("--provider", choices=["ollama", "anthropic", "openai", "mock"], help="LLM provider override")
    parser.add_argument("--model", help="LLM model override")
    sub = parser.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="build an idea")
    run.add_argument("idea")
    run.add_argument("--name")
    run.add_argument("--backend", action="store_true", help="force an app with a FastAPI backend")
    run.add_argument("--approve", action="store_true", help="require human approval before deploy")
    run.add_argument("--max-fix", type=int, dest="max_fix")
    run.add_argument("--no-bug", action="store_true", help="mock provider: don't inject the demo bug")
    run.add_argument("--yes", action="store_true", help="non-interactive")

    serve = sub.add_parser("serve", help="start the dashboard server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--no-browser", action="store_true")

    sub.add_parser("doctor", help="check the environment")
    sub.add_parser("list", help="list projects")

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        return _serve(args)
    if args.cmd == "doctor":
        return asyncio.run(_doctor(args))
    if args.cmd == "list":
        return _list(args)
    if args.cmd == "run":
        return asyncio.run(_build(args, args.idea, interactive=not args.yes))

    console.print(BANNER.format(v=__version__))
    idea = console.input("[bold]Enter project idea:[/bold] ").strip()
    if not idea:
        return 0
    return asyncio.run(_build(args, idea, interactive=True))


if __name__ == "__main__":
    sys.exit(main())
