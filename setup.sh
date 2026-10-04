#!/usr/bin/env bash
# AI-CEO one-time setup (macOS / Linux).  Usage:  ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

step "Checking prerequisites"
command -v python3 >/dev/null || { echo "Python 3.11+ is required"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Python 3.11+ is required"; exit 1; }
command -v node >/dev/null || { echo "Node.js 18+ is required: https://nodejs.org"; exit 1; }
command -v git >/dev/null || { echo "Git is required"; exit 1; }
echo "$(python3 --version), Node $(node --version), $(git --version)"

step "Creating Python virtual environment (.venv)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet

step "Building the web UI"
(cd web && npm ci --no-audit --no-fund && npm run build)

step "Checking a browser for automated QA"
if ! .venv/bin/python -c "from ai_ceo.verification.browser import browser_available as b; ok, d = b('auto'); print('browser:', d); raise SystemExit(0 if ok else 1)"; then
  echo "No Chrome/Edge found for Playwright - installing Chromium..."
  .venv/bin/python -m playwright install --with-deps chromium || .venv/bin/python -m playwright install chromium
fi

step "Checking the AI model"
if command -v ollama >/dev/null; then
  echo "Ollama found. Pulling llama3.1:8b (Ctrl+C to skip if you use Claude/OpenAI)..."
  ollama pull llama3.1:8b || true
else
  echo "Ollama not found. Install it from https://ollama.com, set ANTHROPIC_API_KEY in .env, or run the demo: ./start.sh --demo"
fi

step "Environment check"
.venv/bin/python main.py doctor || true
printf '\n\033[32mSetup complete. Start with: ./start.sh   (or ./start.sh --demo)\033[0m\n'
