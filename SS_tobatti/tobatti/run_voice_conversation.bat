@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ========================================
echo  Tobatti Voice Conversation Only
echo ========================================
echo.

if exist "%~dp0config.txt" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0config.txt") do (
    if not "%%A"=="" set "%%A=%%B"
  )
) else (
  echo [WARN] config.txt was not found.
  echo        Copy config.example.txt to config.txt and set GEMINI_API_KEY.
  echo.
)

set "PYTHON_CMD=py"
set "PYTHONUTF8=1"

echo.
echo Select mode:
echo   1. Realtime voice conversation
echo   2. Text conversation test
echo   3. List microphone devices
echo   4. Show conversation history
if "%VOICE_MODE%"=="" set /p VOICE_MODE=Enter 1, 2, 3, or 4: 
if "%VOICE_MODE%"=="" set "VOICE_MODE=1"

if "%VOICE_MODE%"=="3" (
  echo Checking microphone package...
  %PYTHON_CMD% -c "import sounddevice" >nul 2>nul
  if errorlevel 1 %PYTHON_CMD% -m pip install --disable-pip-version-check --timeout 20 sounddevice
  %PYTHON_CMD% voice_conversation.py --list-devices
  pause
  exit /b 0
)

if "%VOICE_MODE%"=="4" (
  %PYTHON_CMD% voice_conversation.py --show-history
  pause
  exit /b 0
)

if "%GEMINI_API_KEY%"=="" (
  echo [ERROR] GEMINI_API_KEY is not set.
  echo.
  echo Add this line to config.txt:
  echo   GEMINI_API_KEY=your_key_here
  echo.
  pause
  exit /b 1
)

echo Checking Python packages...
%PYTHON_CMD% -c "import google.generativeai, numpy, sounddevice, pyttsx3" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages...
  %PYTHON_CMD% -m pip install --disable-pip-version-check --timeout 20 google-generativeai numpy sounddevice pyttsx3
  if errorlevel 1 (
    echo [ERROR] Package install failed.
    pause
    exit /b 1
  )
)

if "%VOICE_MODE%"=="2" (
  %PYTHON_CMD% voice_conversation.py --text
) else (
  %PYTHON_CMD% voice_conversation.py
)

if errorlevel 1 pause
endlocal
