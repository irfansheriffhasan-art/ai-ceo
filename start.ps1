# Start AI-CEO and open the Studio in your browser (Windows PowerShell).
#   .\start.ps1             use the configured model (local Ollama by default)
#   .\start.ps1 -Demo       offline demo mode - no AI model needed, builds a sample app in ~1 minute
#   .\start.ps1 -NoBrowser  don't open a browser tab
param([switch]$Demo, [switch]$NoBrowser, [int]$Port = 8000)
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) { Write-Host "Run setup.ps1 first." -ForegroundColor Yellow; exit 1 }
$serveArgs = @("serve", "--port", $Port)
if ($NoBrowser) { $serveArgs += "--no-browser" }
if ($Demo) {
    & .\.venv\Scripts\python.exe main.py --provider mock @serveArgs
} else {
    & .\.venv\Scripts\python.exe main.py @serveArgs
}
