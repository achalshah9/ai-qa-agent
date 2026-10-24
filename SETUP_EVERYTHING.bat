@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title AI QA Engineering Agent - Setup and Launch

echo ============================================================
echo  AI QA Engineering Agent - One-click setup for Windows
echo ============================================================
echo.
echo This script can install Python for the current Windows user,
echo create a project-specific virtual environment, install the
 echo required Python packages, and launch the demo.
echo It does not need administrator rights in a normal setup.
echo Internet access is required for downloads.
echo.

set "PYTHON_EXE="

REM Prefer a compatible installed Python via the Python Launcher.
for %%V in (3.13 3.12 3.11) do (
  py -%%V -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
    if defined PYTHON_EXE goto :python_found
  )
)

REM Try the python command if the launcher isn't available.
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
  if defined PYTHON_EXE goto :python_found
)

echo No Python 3.11+ was found. Downloading the official Python 3.13.17 installer...
echo.

for /f "delims=" %%A in ('powershell -NoProfile -Command "[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()" 2^>nul') do set "OSARCH=%%A"
if /I "%OSARCH%"=="X64" set "PYURL=https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe"
if /I "%OSARCH%"=="X86" set "PYURL=https://www.python.org/ftp/python/3.13.17/python-3.13.17.exe"
if /I "%OSARCH%"=="Arm64" set "PYURL=https://www.python.org/ftp/python/3.13.17/python-3.13.17-arm64.exe"
if not defined PYURL (
  echo ERROR: Could not determine Windows architecture.
  echo Please install Python from https://www.python.org/downloads/windows/ and rerun this file.
  goto :failed
)

set "INSTALLER=%TEMP%\python-3.13.17-installer.exe"
echo Download source: python.org
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%INSTALLER%'"
if errorlevel 1 (
  echo ERROR: Python download failed. Check your internet connection and try again.
  goto :failed
)
if not exist "%INSTALLER%" (
  echo ERROR: Installer file was not downloaded.
  goto :failed
)

echo Installing Python for this Windows user. No admin install is requested...
start /wait "" "%INSTALLER%" /quiet InstallAllUsers=0 Include_test=0 Include_pip=1 Include_doc=0 Include_tcltk=0 Include_launcher=0 PrependPath=0 TargetDir="%LOCALAPPDATA%\Programs\Python\Python313"
if errorlevel 1 (
  echo WARNING: Python installer returned a non-zero exit code. Checking whether Python is available...
)
set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not exist "%PYTHON_EXE%" (
  echo ERROR: Python was not found at the expected installation path.
  echo The installation may have been blocked by Windows or device policy.
  goto :failed
)

goto :python_found

:python_found
echo.
echo Using Python:
"%PYTHON_EXE%" --version
if errorlevel 1 goto :failed

echo.
if not exist ".venv\Scripts\python.exe" (
  echo Creating the project's virtual environment...
  "%PYTHON_EXE%" -m venv .venv
  if errorlevel 1 goto :failed
) else (
  echo Existing project virtual environment found; reusing it.
)

echo.
echo Installing required packages from requirements.txt...
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :failed

echo.
echo Running core checks...
"%~dp0.venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 (
  echo WARNING: One or more tests failed. You can still inspect the output above; do not claim the checks passed.
  pause
)

echo.
echo Starting the app. Keep this terminal window open while using it.
echo The browser address is usually http://localhost:8501
"%~dp0.venv\Scripts\python.exe" -m streamlit run "%~dp0app.py"
if errorlevel 1 goto :failed

goto :end

:failed
echo.
echo Setup did not complete. Read the error above.
echo If installation was blocked, try installing Python from the official site:
echo https://www.python.org/downloads/windows/
echo Then run SETUP_EVERYTHING.bat again.
pause
exit /b 1

:end
endlocal
