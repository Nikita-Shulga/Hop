#!/bin/bash
# Runs Hop from source on macOS (the packaged app is "Hop.app"; see README.md).
# Usage: ./start-mac.command [--pin 123456] [--port 8765] [--name NAME] [--short NAME] [--headless] ...
# Opens the Hop window; keep this Terminal window open (it shows the log).
# Grant Screen Recording + Accessibility to Terminal (not Hop) when running from source.
cd "$(dirname "$0")" || exit 1

# Python 3.10+ is needed (the internet video stack, aiortc/PyAV, has no wheels for 3.9 — the version
# Apple's Command Line Tools ship). Prefer the newest one installed.
NEW_ENOUGH='import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
PY=""
for v in 3.13 3.12 3.11 3.10; do
  for c in "$(command -v python$v 2>/dev/null)" /opt/homebrew/bin/python$v /usr/local/bin/python$v \
           /Library/Frameworks/Python.framework/Versions/$v/bin/python$v /opt/homebrew/opt/python@$v/bin/python$v; do
    [ -n "$c" ] && [ -x "$c" ] && "$c" -c "$NEW_ENOUGH" 2>/dev/null && { PY="$c"; break 2; }
  done
done
if [ -z "$PY" ]; then
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null)"; do
    [ -n "$c" ] && [ -x "$c" ] && "$c" -c "$NEW_ENOUGH" 2>/dev/null && { PY="$c"; break; }
  done
fi

if [ -z "$PY" ]; then
  echo "Python 3.10 or newer was not found."
  echo "Install Python 3.12 from https://www.python.org/downloads/ and run this again."
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

# An older checkout may have a .venv made with Python 3.9: rebuild it.
if [ -x .venv/bin/python ] && ! .venv/bin/python -c "$NEW_ENOUGH" 2>/dev/null; then
  echo "Upgrading the virtual environment to $PY ..."
  rm -rf .venv
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment with $PY ..."
  rm -rf .venv
  "$PY" -m venv .venv || { echo "Failed to create .venv"; read -n 1 -s -r -p "Press any key to close..."; exit 1; }
fi

if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Installing dependencies (first run only) ..."
  .venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
  if .venv/bin/python -m pip install -q -r requirements.txt; then
    touch .venv/.installed
  else
    # The app window (pywebview) and internet access (aiortc) are optional: retry without them.
    echo "Retrying without the optional packages (app window, internet access) ..."
    if grep -viE '^(pywebview|aiortc)' requirements.txt > .venv/requirements-core.txt &&
       .venv/bin/python -m pip install -q -r .venv/requirements-core.txt; then
      echo "Installed without the app window and internet access; Hop will run in this Terminal."
      touch .venv/.installed
    else
      echo "Dependency installation failed. Check your internet connection and retry."
      read -n 1 -s -r -p "Press any key to close..."
      exit 1
    fi
  fi
fi

exec .venv/bin/python host.py "$@"
