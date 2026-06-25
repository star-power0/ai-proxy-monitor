@echo off
title AI Proxy Monitor Builder
cd /d "%~dp0"

setlocal

echo [1/3] Preparing environment...
call .venv\Scripts\pip.exe install -r backend\requirements.txt pyinstaller pywebview
if errorlevel 1 exit /b 1

echo.
echo [2/3] Packing application into desktop EXE...
call .venv\Scripts\pyinstaller.exe --noconfirm --clean --distpath dist --workpath build "AI中转站监控大屏.spec"
if errorlevel 1 exit /b 1

echo.
echo [3/3] Package complete!
echo ====================================================
echo The standalone EXE has been compiled at:
echo dist\AI中转站监控大屏\AI中转站监控大屏.exe
echo ====================================================
exit /b 0
