@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer and enable "Add Python to PATH".
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating local virtual environment...
  python -m venv .venv
  if errorlevel 1 goto failed
)
echo Installing or updating required packages...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Starting AI QA Engineering Agent...
.venv\Scripts\python.exe -m streamlit run app.py
if errorlevel 1 goto failed
goto end
:failed
echo Setup or launch failed. Review the error above.
pause
exit /b 1
:end
endlocal
