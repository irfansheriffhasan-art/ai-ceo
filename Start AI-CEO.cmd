@echo off
title AI-CEO
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
