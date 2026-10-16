@echo off
rem Builds dist\Hop\Hop.exe and dist\Hop-<version>-win-<arch>.zip.
rem Usage: double-click, or run  packaging\build-windows.bat  from a Command Prompt.
rem Needs Python 3.10+ from python.org (tick "Add python.exe to PATH") and an internet connection.
setlocal EnableExtensions
cd /d "%~dp0.."
title Building Hop

set "VENV=.venv"
set "VERSION="
for /f "usebackq delims=" %%v in ("packaging\VERSION") do if not defined VERSION set "VERSION=%%v"
if not defined VERSION (
  echo ERROR: could not read packaging\VERSION
  goto :fail
)

rem 1. Find Python 3.10+
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo ERROR: Python 3.10 or newer was not found.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  goto :fail
)

rem 2. Virtual environment
if not exist "%VENV%\Scripts\python.exe" (
  echo =^> Creating %VENV% with %PY%
  %PY% -m venv "%VENV%"
  if errorlevel 1 (
    echo ERROR: could not create the virtual environment.
    goto :fail
  )
)
set "VPY=%VENV%\Scripts\python.exe"
"%VPY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: %VENV% uses Python older than 3.10. Delete the %VENV% folder and run again.
  goto :fail
)

rem 3. Dependencies
echo =^> Installing dependencies
"%VPY%" -m pip install -q --upgrade pip
"%VPY%" -m pip install -q -r requirements.txt -r requirements-build.txt
if errorlevel 1 (
  echo ERROR: pip install failed. Check your internet connection and try again.
  goto :fail
)

"%VPY%" -c "import aiohttp, mss, PIL, pynput, qrcode, webview, zeroconf, pyperclip, aiortc, av"
if errorlevel 1 (
  echo ERROR: a runtime dependency is missing ^(requirements.txt must list zeroconf and pyperclip^).
  goto :fail
)

set "ARCH="
if not exist build mkdir build
"%VPY%" -c "import platform; m=platform.machine().lower(); print('arm64' if m in ('arm64','aarch64') else 'x64')" > build\arch.txt 2>nul
set /p ARCH=<build\arch.txt
if not defined ARCH set "ARCH=x64"
set "ZIP=dist\Hop-%VERSION%-win-%ARCH%.zip"

rem 4. PyInstaller
echo =^> Building dist\Hop\Hop.exe (%ARCH%, version %VERSION%)
if exist "build\hop" rmdir /s /q "build\hop"
if exist "dist\Hop" rmdir /s /q "dist\Hop"
if exist "%ZIP%" del /q "%ZIP%"
"%VPY%" -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build\hop packaging\hop.spec
if errorlevel 1 (
  echo ERROR: PyInstaller failed. See the messages above.
  goto :fail
)
if not exist "dist\Hop\Hop.exe" (
  echo ERROR: dist\Hop\Hop.exe was not produced.
  goto :fail
)

rem 5. Zip (the Hop folder itself goes in the zip)
echo =^> Zipping
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\Hop' -DestinationPath '%ZIP%' -Force"
if errorlevel 1 (
  echo ERROR: could not create %ZIP%
  goto :fail
)

echo.
echo Built:  %CD%\dist\Hop\Hop.exe
echo Zip:    %CD%\%ZIP%
echo.
echo Keep Hop.exe inside its folder (it needs the files next to it).
echo First run: allow Windows Firewall on Private networks. The exe isn't code-signed, so
echo SmartScreen may say "Windows protected your PC": click More info, then Run anyway.
if not defined CI pause
endlocal
exit /b 0

:fail
echo.
echo Build failed.
if not defined CI pause
endlocal
exit /b 1
