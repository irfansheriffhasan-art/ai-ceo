# AI-CEO — Autonomous Multi-Agent Software Company

Describe an app. An AI CEO turns it into a charter. A team of 14 specialist agents then plans, designs,
builds, tests, reviews, fixes and deploys it. The team verifies its own work in a real headless browser
and fixes what fails. When it can't converge, it escalates to you. You watch and steer everything from a
live command-center dashboard, or from the terminal.

```
USER ──▶ AI CEO ──▶ Strategic Planner ──▶ Project Manager ──▶ Orchestrator
                                                                   │
   ┌───────────────────────────────────────────────────────────────┤
   │ Product · Architect · UI/UX · Frontend · Backend · Database · AI/ML
   │ Security · Testing · Code Review · DevOps
   └───────────────────────────────────────────────────────────────┤
                                                                   ▼
        Verification (static + browser + API + security + review) ──▶ CEO decision
                 ▲                                                 │
                 └──────── fix tasks routed to file owners ◀───────┤ (bounded retries)
                                                                   ▼
                                            Approval ──▶ Deploy (git tag, zip, live preview)
```

---

## Quick start

Prerequisites: Python 3.11+, Git, Node 18+. For local models you also need
[Ollama](https://ollama.com) with a model pulled. A Chromium-family browser is needed for
browser tests; Edge or Chrome is detected automatically.

```powershell
# 1. Python environment
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. A local model (default) — or set ANTHROPIC_API_KEY / OPENAI_API_KEY, see Configuration
ollama pull llama3.1:8b

# 3. Check the environment
python main.py doctor

# 4a. Terminal: describe an idea and watch the company build it
python main.py

# 4b. Dashboard: build the UI once, then serve it
cd web; npm install; npm run build; cd ..
python main.py serve              # prints the URL and your access token
```

To try everything offline in about a minute, with deterministic output from the mock provider:

```powershell
python main.py --provider mock run "Build a task tracker web app" --yes
```

The mock build deliberately ships a bug in its first `app.js`, so you can watch the
QA → CEO → fix → regression-test loop catch and repair it.

---

## Command reference

| Command | What it does |
|---|---|
| `python main.py` | Interactive: enter an idea, watch the live agent view, approve the release |
| `python main.py run "<idea>" [--backend] [--approve] [--max-fix N] [--yes]` | Build an idea; `--backend` forces a FastAPI + SQLite app |
| `python main.py resume <project-id> [--more-fixes N] [--approve-release]` | Continue an interrupted, paused, stopped or escalated project from where it left off |
| `python main.py serve [--host H] [--port P]` | API + dashboard (default http://localhost:8000) |
| `python main.py list` | List projects |
| `python main.py doctor` | Check LLM, model, git, node and browser |
| Global: `--provider ollama\|anthropic\|openai\|mock`, `--model NAME` | Override the configured LLM |

---

## The development loop

| Phase | Who | What actually happens |
|---|---|---|
| Requirements | CEO, Product | Charter (static vs backend app, constraints); user stories, prioritised features, **testable acceptance criteria** |
| Plan | Strategic Planner, PM | Milestones, risks, definition of done; deterministic work breakdown into a dependency graph |
| Architect | Architect, UI/UX | Stack, file plan with owners, data model, API, decisions; palette, typography, components, accessibility |
| Implement | Frontend / Backend / Database / AI-ML | One file per model call with dependent files in context; **self-check** (syntax via `node --check` / `ast`, element-id cross-references, browser-only APIs, import policy) before hand-off |
| Test | Testing | Static analysis; app served locally and driven by **Playwright** (load, console errors, screenshot); acceptance scenarios generated from the criteria; **API tests against the running backend**; regression tracking |
| Review | Security, Code Review | Rule-based security scan; LLM code review against the requirements |
| Fix | CEO → file owners | Blocking issues are grouped per file and assigned to the file's owner, then the full suite runs again |
| Approve | CEO (+ you) | Gate check plus an LLM release review; optional human approval |
| Deploy | DevOps | README, Dockerfile, run scripts; merge `develop`→`main`, tag, `git archive` zip, live preview |

### Self-correction and failure handling

- **Task failure:** the task is retried (default 3 attempts) with the previous error fed back to the
  agent. After that, the CEO reassigns it to an escalation engineer with a simplified brief. If it
  still fails, the CEO escalates to you, and you can retry, reassign, skip or stop.
- **Quality failure:** correction tasks go to the owner of each failing file, and the whole suite runs
  again. This repeats for up to `max_fix_iterations`.
- **No convergence:** the CEO rolls back to the best-scoring iteration (a new commit, so history is
  kept) and escalates to you. You can approve anyway, grant more iterations or give feedback.
- **Invalid tests:** when a scenario references elements that exist nowhere in the code, it is
  classified as a *test* defect and rewritten. No developer is sent to "fix" working code.
- **Timeouts** apply to every model call and every task.
- **Restarts:** interrupted tasks are re-queued and the project is parked as paused. Continue it with
  `resume` or the dashboard.
- **Loop protection:** retry limits, iteration budgets, de-duplicated review comments and a
  no-progress detector make sure the loop always terminates.

The loop is driven by deterministic CEO *policy* code (`orchestrator/policy.py`) rather than by a
model. A weak model therefore cannot derail it, and every decision is logged with its reason.

---

## Dashboard (command center)

- **Overview:**
  - status, phase stepper and iteration
  - KPIs: progress, active agents, completed/failed tasks, open bugs, LLM usage
- **Agent monitor:** all 14 agents with role, status, current task, elapsed time, live token count,
  per-project progress and last activity.
- **Task board:** Backlog · Planned · In Progress · Testing · Review · Completed · Failed. Click a task
  for its details, output, model calls and log, plus **Retry / Skip / Reassign**.
- **Activity feed:** real-time stream over SSE, filterable to decisions or problems.
- **Project workspace:**
  - requirements, architecture and design, decision log, agent outputs
  - code browser with search and dependency graph
  - git history with diffs and **roll back to any commit**
  - test runs with the browser screenshot and bug tracker
  - security findings, code review
  - quality-score chart per iteration (with a table view)
  - every LLM prompt and response, raw project memory
- **Controls:** Pause (graceful) · Resume · Stop · Approve · Reject with feedback · Keep fixing ·
  Approve anyway · change requests after delivery · start/stop preview · download the release zip.

Agents show concise decisions, actions, reasons and outputs. No hidden chain-of-thought is collected
or displayed.

---

## Configuration

Copy `.env.example` to `.env`. Every setting can also be set as an environment variable.

| Setting | Default | Notes |
|---|---|---|
| `AICEO_LLM_PROVIDER` | `ollama` | `ollama`, `anthropic`, `openai`, `mock` |
| `AICEO_LLM_MODEL` | `llama3.1:8b` | With `anthropic` and a local model name configured, `claude-opus-5-5` is used |
| `AICEO_LLM_ROLE_MODELS` | `{}` | Per-agent model, e.g. a coder model for developers |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | — | Read only from env/`.env`; never logged |
| `AICEO_LLM_MAX_CONCURRENCY` | `1` | Raise for cloud providers |
| `AICEO_MAX_PARALLEL_TASKS` | `3` | Independent tasks run concurrently |
| `AICEO_MAX_FIX_ITERATIONS` | `3` | Per release cycle; overridable per project |
| `AICEO_REQUIRE_HUMAN_APPROVAL` | `false` | Also selectable per project |
| `AICEO_BROWSER_CHANNEL` | `auto` | Bundled Chromium → Edge → Chrome; `none` disables browser tests |
| `AICEO_RUN_GENERATED_BACKENDS` | `true` | Generated FastAPI apps are executed for API tests and previews |

Runtime data lives in `data/` (gitignored): `aiceo.db` (SQLite), `workspaces/` (one git repository
per generated project), `releases/`, `artifacts/` (screenshots, logs), `logs/aiceo.jsonl`.

### Model choice and speed

The default local model is `llama3.1:8b`. On a 6 GB laptop GPU it generates about 13–15 tokens/s
with part of the model on the CPU, so one build takes **10–25 minutes and 15–25 model calls**. Small
models make many mistakes, which is why the platform leans on fixed project layouts, file-by-file
generation, self-checks and real tests. With `AICEO_LLM_PROVIDER=anthropic` (Claude) the same
pipeline is much faster per iteration and needs far fewer fix iterations.

---

## Security model

- **Dashboard and API:**
  - one access token (generated on first run, stored in `data/auth_token`), exchanged for an
    HttpOnly, SameSite=Strict session cookie that does not contain the token
  - Bearer tokens for scripts
  - login throttling
  - state-changing requests need the `X-AICEO-Request` header and an allowed Origin (CSRF protection)
  - CSP, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`
  - binds to `127.0.0.1` by default
  - input validation on every endpoint
- **Generated code is untrusted:**
  - model-proposed paths are validated (relative paths only, no traversal, no dotfiles such as
    `.git`/`.env`, an extension allow-list, size limits)
  - preview and test servers refuse dot-paths and listen on localhost only
  - generated backends run in a subprocess whose environment is stripped of keys, tokens and
    passwords, with a throwaway database and timeouts
  - this is process isolation, not a container sandbox. Set `AICEO_RUN_GENERATED_BACKENDS=false` on
    machines where running model-written Python is not acceptable.
- **Security agent:** checks for
  - secrets (with redaction in reports)
  - `eval`/`Function`, XSS sinks
  - insecure randomness for passwords and tokens
  - SQL injection, shell execution, unsafe deserialization
  - unvalidated FastAPI bodies, unauthenticated mutating endpoints
  - permissive CORS, debug mode, unpinned or unvetted dependencies, root containers

  No CVE database is bundled; run `pip-audit` / `npm audit` in CI for that.

---

## Testing the platform

```powershell
python -m pytest            # 58 tests, about 1–2 minutes (uses a real headless browser when available)
cd web; npm run typecheck   # dashboard type check
```

The suite covers:
- parsing (including the exact reply format that broke the prototype)
- path safety, git operations, code analysis
- static checks, the security scanner and browser-harness semantics
- full autonomous cycles: static app, backend app with API tests, injected-bug fix loop
- failure recovery (reassign → escalate → human retry), timeouts, pause/resume/stop, approval and
  rejection, change requests, rollback, restart recovery
- API authentication, CSRF and Origin checks, throttling, validation, data endpoints, and a live
  SSE stream over real HTTP

---

## Project structure

```
main.py                 entry point (CLI)
ai_ceo/
  config.py             typed settings (.env / environment)
  llm/                  providers (ollama, anthropic, openai, mock), client, parsing
  agents/               the 14 agents + shared engineering conventions
  orchestrator/         engine (controls), runner (scheduler), policy (CEO decisions), tracker
  verification/         static checks, browser tests, API tests, security scanner, local servers
  workspace/            sandboxed files, git, code intelligence
  prompts/              editable prompt templates (*.md)
  db.py memory.py events.py services.py deploy.py
  api/                  FastAPI app, auth, routes (REST + SSE)
web/                    React + TypeScript command center (Vite)
tests/                  pytest suite
legacy/prototype_v1/    the original prototype (archived, unused)
generated_sites/        output of the original prototype (kept as-is)
```

## Docker

`Dockerfile` builds the dashboard and runs the platform on the Playwright Python image, which ships
with a browser. It expects Ollama on the host (`host.docker.internal:11434`):

```bash
docker build -t ai-ceo .
docker run -p 8000:8000 -v ai-ceo-data:/data ai-ceo
```

Docker was not available on the development machine, so this image has not been built or tested yet.

## Known limitations

- Generated apps follow fixed layouts (a static 3-file app, or FastAPI + SQLite with a vanilla
  frontend). This trades flexibility for reliability on small models.
- An 8B local model can still miss requirements or write weak tests. The loop catches most of these,
  but expect escalations; the decision is then yours.
- Single-operator authentication; there are no user accounts or roles.
- The orchestrator runs in-process. Running several projects concurrently is supported, but they share
  one GPU.
