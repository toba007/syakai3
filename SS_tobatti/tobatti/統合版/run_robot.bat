@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo  Denden Robot - Integrated App
echo ========================================
echo.

set "PYTHON_CMD=py"
set "PYTHONUTF8=1"

echo Checking Python packages...
%PYTHON_CMD% -c "import cv2, numpy, PIL, sounddevice, speech_recognition, pyttsx3, requests, serial; from google import genai" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages. This may take a few minutes...
  %PYTHON_CMD% -m pip install --disable-pip-version-check --timeout 60 -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Package install failed.
    pause
    exit /b 1
  )
)

echo Starting robot...
echo Press Esc on the face window to leave fullscreen.
echo Press Ctrl+C in this window to stop.
echo.
%PYTHON_CMD% main.py

if errorlevel 1 pause
endlocal
