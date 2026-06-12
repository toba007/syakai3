@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py main.py %*
    goto end
)

where python >nul 2>nul
if not errorlevel 1 (
    python main.py %*
    goto end
)

echo Python was not found.
echo Install Python from https://www.python.org/downloads/windows/

:end
echo.
pause
