@echo off
title AI Proxy Monitor Server
cd /d "%~dp0"

echo [1/2] Launching debug Chrome browser...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="A:\ChromeDevToolsProfile" "http://127.0.0.1:8084"

echo [2/2] Starting Python monitor server...
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8084
pause
