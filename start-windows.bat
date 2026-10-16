@echo off
setlocal
cd /d "%~dp0"
title Hop
rem Runs Hop from source on Windows (the packaged app is Hop.exe; see README.md).
rem Usage: start-windows.bat [--pin 123456] [--port 8765] [--name NAME] [--short NAME] [--headless] ...
rem Opens the Hop window; this console shows the log.

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python 3.10 or newer was not found.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

rem An older checkout may have a .venv made with Python 3.9: rebuild it.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if errorlevel 1 (
    echo Upgrading the virtual environment...
    rmdir /s /q .venv
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv
    pause
    exit /b 1
  )
)

rem Reinstall when requirements.txt changed since the last successful install.
rem The app window (pywebview) and internet access (aiortc) are optional: if they fail, retry without.
set "NEEDS_INSTALL=1"
if exist ".venv\.installed" (
  fc /b requirements.txt ".venv\.installed" >nul 2>&1 && set "NEEDS_INSTALL="
)
if defined NEEDS_INSTALL (
  echo Installing dependencies ^(first run only^)...
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
  if errorlevel 1 (
    echo Retrying without the optional packages ^(app window, internet access^)...
    findstr /v /i /b /c:"pywebview" /c:"aiortc" requirements.txt > ".venv\requirements-core.txt"
    ".venv\Scripts\python.exe" -m pip install -q -r ".venv\requirements-core.txt"
    if errorlevel 1 (
      echo Dependency installation failed. Check your internet connection and retry.
      pause
      exit /b 1
    )
    echo Installed without the app window and internet access; Hop will run in this console.
  )
  copy /y requirements.txt ".venv\.installed" >nul
)

echo.
echo NOTE: Windows Firewall will ask for access the first time.
echo Choose "Private networks" and click Allow access.
echo.

".venv\Scripts\python.exe" host.py %*
if errorlevel 1 pause
