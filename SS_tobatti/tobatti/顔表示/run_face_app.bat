@echo off
cd /d "%~dp0"
py face_app.py
if errorlevel 1 pause
