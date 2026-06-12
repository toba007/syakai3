@echo off
setlocal
set "APP_BAT="
for /d %%D in ("%~dp0SS_tobatti\tobatti\*") do (
  if exist "%%~fD\run_kaiwa_app.bat" set "APP_BAT=%%~fD\run_kaiwa_app.bat"
)
if "%APP_BAT%"=="" (
  echo [ERROR] Conversation app launcher was not found.
  pause
  exit /b 1
)
call "%APP_BAT%"
endlocal
