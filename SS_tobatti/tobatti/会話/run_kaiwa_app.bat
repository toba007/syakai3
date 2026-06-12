@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo  Tobatti Conversation App
echo ========================================
echo.

set "PYTHON_CMD=py"
set "PYTHONUTF8=1"
set "APP_SCRIPT=launch_kaiwa_app.py"

if not exist "%APP_SCRIPT%" (
  echo [ERROR] %APP_SCRIPT% was not found.
  pause
  exit /b 1
)

if exist "..\config.txt" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("..\config.txt") do (
    if not "%%A"=="" if "!%%A!"=="" set "%%A=%%B"
  )
)

if not exist ".env" (
  echo [WARN] .env was not found in this folder.
  if "%GEMINI_API_KEY%"=="" (
    echo [ERROR] GEMINI_API_KEY is not set.
    echo        Create .env or set GEMINI_API_KEY in ..\config.txt.
    pause
    exit /b 1
  )
)

if "%START_FACE%"=="" set "START_FACE=1"
if "%FACE_WINDOWED%"=="" set "FACE_WINDOWED=0"
if "%START_FACE%"=="1" (
  if exist "..\face-ui\face_app.py" (
    echo Starting face UI...
    if "%FACE_WINDOWED%"=="1" (
      start "Robot Face" /D "%~dp0..\face-ui" %PYTHON_CMD% face_app.py --windowed
    ) else (
      start "Robot Face" /D "%~dp0..\face-ui" %PYTHON_CMD% face_app.py
    )
  ) else (
    echo [WARN] face-ui was not found.
  )
)

echo Checking Python packages...
%PYTHON_CMD% -c "import sounddevice, speech_recognition, pyttsx3, numpy, dotenv, requests, serial; from google import genai" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages. This may take a few minutes...
  %PYTHON_CMD% -m pip install --disable-pip-version-check --timeout 30 sounddevice SpeechRecognition pyttsx3 numpy python-dotenv google-genai requests pyserial
  if errorlevel 1 (
    echo [ERROR] Package install failed.
    pause
    exit /b 1
  )
)

echo Starting conversation app ...
echo Press Ctrl+C in this window to stop.
echo.
%PYTHON_CMD% "%APP_SCRIPT%"

if errorlevel 1 pause
endlocal
