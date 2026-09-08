@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe bootstrap.py
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r vendor\realtime-caption\requirements.txt
if errorlevel 1 goto fail
echo Setup complete. Run start_presense.bat --demo first.
pause
exit /b 0
:fail
echo Setup failed. Inspect the error above; Python does not necessarily need reinstalling.
pause
exit /b 1
