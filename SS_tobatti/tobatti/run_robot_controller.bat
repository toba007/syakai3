@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ========================================
echo  Communication Robot Controller
echo ========================================
echo.

if exist "%~dp0config.txt" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0config.txt") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

if "%GEMINI_API_KEY%"=="" echo [WARN] GEMINI_API_KEY is not set.
if "%OPENWEATHER_API_KEY%"=="" echo [WARN] OPENWEATHER_API_KEY is not set.
if "%NEWS_API_KEY%"=="" echo [INFO] NEWS_API_KEY is not set. NHK RSS fallback will be used.
echo.

if "%ESP32_PORT%"=="" (
  set /p ESP32_PORT=ESP32 port, for example COM3. Leave blank for no ESP32: 
)

echo.
echo Select run mode:
echo   1. Normal mode with RealSense D435
echo   2. Text chat test mode without RealSense
echo   3. No RealSense, idle speech only
echo   4. List microphone devices
if "%RUN_MODE%"=="" set /p RUN_MODE=Enter 1, 2, 3, or 4: 
if "%RUN_MODE%"=="" set "RUN_MODE=1"

echo.
if "%FACE_WINDOWED%"=="" set /p FACE_WINDOWED=Start face in windowed mode for now? y/N: 
if "%DEBUG_REALSENSE%"=="" set /p DEBUG_REALSENSE=Show RealSense debug window? y/N: 
echo.

set "PYTHON_CMD=py"
set "HAS_PY311=0"

if "%RUN_MODE%"=="1" (
  py -3.11 -c "import sys" >nul 2>nul
  if errorlevel 1 (
    echo [WARN] Python 3.11 was not found.
    echo [WARN] RealSense D435 needs pyrealsense2, and pyrealsense2 usually does not work on Python 3.14.
    set /p INSTALL_PY311=Install Python 3.11 now with winget? y/N: 
    if /i "!INSTALL_PY311!"=="y" (
      winget install -e --id Python.Python.3.11
      py -3.11 -c "import sys" >nul 2>nul
      if errorlevel 1 (
        echo [WARN] Python 3.11 still was not found. Restart this bat after installation finishes.
      ) else (
        set "PYTHON_CMD=py -3.11"
        set "HAS_PY311=1"
      )
    )
  ) else (
    set "PYTHON_CMD=py -3.11"
    set "HAS_PY311=1"
  )
)

echo Checking basic Python packages...
%PYTHON_CMD% -c "import google.generativeai, numpy, cv2, PIL, serial, pyttsx3, requests, sounddevice" >nul 2>nul
if errorlevel 1 (
  echo Installing basic packages. This may take a few minutes...
  %PYTHON_CMD% -m pip install --disable-pip-version-check --timeout 20 -r requirements-base.txt
  if errorlevel 1 (
    echo [WARN] Basic package install failed or was incomplete.
    echo [WARN] Continuing anyway. If the program errors, run:
    echo        %PYTHON_CMD% -m pip install -r requirements-base.txt
    echo.
  )
)

if "%RUN_MODE%"=="4" (
  %PYTHON_CMD% list_audio_devices.py
  pause
  exit /b 0
)

if "%RUN_MODE%"=="1" (
  if "%HAS_PY311%"=="1" (
    %PYTHON_CMD% -c "import pyrealsense2" >nul 2>nul
    if errorlevel 1 (
      echo Installing RealSense package pyrealsense2...
      %PYTHON_CMD% -m pip install --disable-pip-version-check --timeout 20 -r requirements-realsense.txt
      if errorlevel 1 (
        echo [WARN] pyrealsense2 could not be installed automatically.
        echo [WARN] RealSense mode may not work until pyrealsense2 is installed.
        echo.
      )
    )
  ) else (
    echo [WARN] Running RealSense mode without Python 3.11. It will probably fall back to no detection.
    echo.
  )
)

if "%SKIP_FACE%"=="1" (
  echo [TEST] Skipping face UI because SKIP_FACE=1.
) else (
  echo Starting face UI...
  if /i "%FACE_WINDOWED%"=="y" (
    start "Robot Face" /D "%~dp0face-ui" %PYTHON_CMD% face_app.py --windowed
  ) else (
    start "Robot Face" /D "%~dp0face-ui" %PYTHON_CMD% face_app.py
  )
)

if not "%SKIP_FACE%"=="1" timeout /t 2 /nobreak >nul

set "DEBUG_ARG="
if /i "%DEBUG_REALSENSE%"=="y" set "DEBUG_ARG=--debug-realsense"

echo Starting robot controller...
if "%RUN_MODE%"=="2" (
  %PYTHON_CMD% robot_controller.py --esp32-port "%ESP32_PORT%" --text-chat
) else if "%RUN_MODE%"=="3" (
  %PYTHON_CMD% robot_controller.py --esp32-port "%ESP32_PORT%" --no-realsense
) else (
  %PYTHON_CMD% robot_controller.py --esp32-port "%ESP32_PORT%" %DEBUG_ARG%
)

if errorlevel 1 pause
endlocal
