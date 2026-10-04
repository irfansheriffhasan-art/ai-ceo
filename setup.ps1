# AI-CEO one-time setup (Windows PowerShell).  Usage:  .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Step "Checking prerequisites"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw "Python 3.11+ is required: https://www.python.org/downloads/" }
$ver = python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]"3.11") { throw "Python 3.11+ is required (found $ver)" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js 18+ is required: https://nodejs.org" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is required: https://git-scm.com" }
Write-Host "Python $ver, Node $(node --version), $(git --version)"

Step "Creating Python virtual environment (.venv)"
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet

Step "Building the web UI"
Push-Location web
npm ci --no-audit --no-fund
npm run build
Pop-Location

Step "Checking a browser for automated QA"
& .\.venv\Scripts\python.exe -c "from ai_ceo.verification.browser import browser_available as b; ok, d = b('auto'); print('browser:', d); raise SystemExit(0 if ok else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "No Edge/Chrome found for Playwright - installing Chromium..." -ForegroundColor Yellow
    & .\.venv\Scripts\python.exe -m playwright install chromium
}

Step "Checking the AI model"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Ollama found. Pulling llama3.1:8b (skip with Ctrl+C if you use Claude/OpenAI)..."
    ollama pull llama3.1:8b
} else {
    Write-Host "Ollama not found. Install it from https://ollama.com for local models," -ForegroundColor Yellow
    Write-Host "set ANTHROPIC_API_KEY in .env to use Claude, or start in demo mode: .\start.ps1 -Demo" -ForegroundColor Yellow
}

Step "Environment check"
& .\.venv\Scripts\python.exe main.py doctor
Write-Host "`nSetup complete. Start the app with:  .\start.ps1   (or .\start.ps1 -Demo for the offline demo)" -ForegroundColor Green
