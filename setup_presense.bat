@echo off
setlocal
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
echo Setup failed. Install Python 3.11 x64 and inspect the error above.
pause
exit /b 1
