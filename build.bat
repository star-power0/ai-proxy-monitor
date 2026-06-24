@echo off
title AI Proxy Monitor Builder
cd /d "%~dp0"

echo [1/3] Preparing environment...
.venv\Scripts\pip.exe install pyinstaller pywebview

echo.
echo [2/3] Packing application into desktop EXE...
echo (Including FastAPI service, Webview2 layout, and static pages)
.venv\Scripts\pyinstaller.exe --noconfirm --onedir --windowed --add-data "frontend;frontend" --add-data "backend;backend" --add-data "logo.ico;." --icon="logo.ico" --name "AI中转站监控大屏" run_app.py

echo.
echo [3/3] Package complete!
echo ====================================================
echo The standalone EXE has been compiled at:
echo dist\AI中转站监控大屏\AI中转站监控大屏.exe
echo ====================================================
pause
