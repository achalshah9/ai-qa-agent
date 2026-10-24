@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_and_run.bat once first to create the virtual environment.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m unittest discover -s tests -v
pause
