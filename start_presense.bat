@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_presense.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe run_presense.py %*
if errorlevel 1 pause
