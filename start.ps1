# Start AI-CEO and open the Studio in your browser (Windows PowerShell).
#   .\start.ps1          use the configured model (local Ollama by default)
#   .\start.ps1 -Demo    offline demo mode - no AI model needed
param([switch]$Demo, [int]$Port = 8000)
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) { Write-Host "Run .\setup.ps1 first." -ForegroundColor Yellow; exit 1 }
if ($Demo) {
    & .\.venv\Scripts\python.exe main.py --provider mock serve --port $Port
} else {
    & .\.venv\Scripts\python.exe main.py serve --port $Port
}
