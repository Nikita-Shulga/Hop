#!/bin/bash
# Builds "dist/Local View.app" and dist/LocalView-<version>-mac-<arch>.zip.
# Usage: packaging/build-mac.sh        (run on a Mac; builds for this Python's architecture)
# Env:   VENV=path   virtual environment to use (default: .venv in the project)
#        PYTHON=path Python 3.10+ used to create the venv if it doesn't exist yet
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

fail() { echo "error: $*" >&2; exit 1; }
[ "$(uname -s)" = "Darwin" ] || fail "build-mac.sh must run on macOS."

VERSION="$(tr -d '[:space:]' < packaging/VERSION)"
VENV="${VENV:-$ROOT/.venv}"
APP="dist/Local View.app"

# 1. Virtual environment
if [ ! -x "$VENV/bin/python" ]; then
  PY="${PYTHON:-}"
  if [ -z "$PY" ]; then
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
      c="$(command -v "$c" 2>/dev/null || true)"
      [ -n "$c" ] || continue
      if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        PY="$c"; break
      fi
    done
  fi
  [ -n "$PY" ] || fail "Python 3.10 or newer not found. Install it from https://www.python.org/downloads/"
  echo "==> Creating $VENV with $PY"
  "$PY" -m venv "$VENV" || fail "could not create the virtual environment"
fi
VPY="$VENV/bin/python"
"$VPY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "$VPY is older than Python 3.10; delete $VENV and run again."

# 2. Dependencies
echo "==> Installing dependencies"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r requirements.txt -r requirements-build.txt \
  || fail "pip install failed (check your internet connection)"
"$VPY" -c "import aiohttp, mss, PIL, pynput, qrcode, webview, zeroconf, pyperclip, aiortc, av" \
  || fail "a runtime dependency is missing (requirements.txt must list zeroconf and pyperclip)"

ARCH="$("$VPY" -c 'import platform; print(platform.machine())')"
case "$ARCH" in
  x86_64) ARCH=x64 ;;
  arm64|aarch64) ARCH=arm64 ;;
esac
ZIP="dist/LocalView-$VERSION-mac-$ARCH.zip"

# 3. Icon
echo "==> Generating icon.icns"
bash packaging/make-icns.sh

# 4. PyInstaller
echo "==> Building $APP ($ARCH, version $VERSION)"
rm -rf "build/localview" "dist/Local View" "$APP" "$ZIP"
"$VPY" -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath dist --workpath build/localview packaging/localview.spec \
  || fail "PyInstaller failed"
[ -d "$APP" ] || fail "$APP was not produced"
rm -rf "dist/Local View"   # the intermediate onedir folder; the .app contains everything

# 5. Ad hoc signature (no Developer ID; lets the app run and keeps its identity stable per build)
echo "==> Signing (ad hoc)"
xattr -cr "$APP"
codesign --force --deep -s - "$APP" || fail "codesign failed"
codesign --verify --deep --strict "$APP" || fail "signature verification failed"

# 6. Zip
echo "==> Zipping"
ditto -c -k --keepParent "$APP" "$ZIP" || fail "zip failed"

echo
echo "Built:  $ROOT/$APP"
echo "Zip:    $ROOT/$ZIP"
echo
echo "First launch on another Mac: move Local View to Applications, then right-click it > Open"
echo "(or System Settings > Privacy & Security > Open Anyway). The app is ad hoc signed, not notarized."
echo "Then grant Screen Recording and Accessibility to \"Local View\" in Privacy & Security."
