#!/bin/bash
# Builds "dist/Hop.app" and dist/Hop-<version>-mac-<arch>.zip.
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
APP="dist/Hop.app"

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
ZIP="dist/Hop-$VERSION-mac-$ARCH.zip"

# 3. Icon
echo "==> Generating icon.icns"
bash packaging/make-icns.sh

# 4. PyInstaller
echo "==> Building $APP ($ARCH, version $VERSION)"
rm -rf "build/hop" "dist/Hop" "$APP" "$ZIP"
"$VPY" -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath dist --workpath build/hop packaging/hop.spec \
  || fail "PyInstaller failed"
[ -d "$APP" ] || fail "$APP was not produced"
rm -rf "dist/Hop"   # the intermediate onedir folder; the .app contains everything

# 5. Signature. With MACOS_SIGN_P12 (base64 .p12) + MACOS_SIGN_PASSWORD set (GitHub Actions secrets), sign
#    with that fixed self-signed certificate: macOS then sees every release as the same app, so updates keep
#    their Screen Recording and Accessibility permissions. Without it (local builds), sign ad hoc.
xattr -cr "$APP"
if [ -n "${MACOS_SIGN_P12:-}" ] && [ -n "${MACOS_SIGN_PASSWORD:-}" ]; then
  echo "==> Signing with the Hop certificate"
  KC="$ROOT/build/hop-sign.keychain-db"; KPW="$(openssl rand -hex 16)"
  mkdir -p build; rm -f "$KC"
  security create-keychain -p "$KPW" "$KC" || fail "couldn't create the signing keychain"
  security set-keychain-settings -lut 3600 "$KC"
  security unlock-keychain -p "$KPW" "$KC"
  printf '%s' "$MACOS_SIGN_P12" | base64 --decode > build/hop-sign.p12
  security import build/hop-sign.p12 -k "$KC" -P "$MACOS_SIGN_PASSWORD" -T /usr/bin/codesign >/dev/null || fail "couldn't import the certificate"
  rm -f build/hop-sign.p12
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KPW" "$KC" >/dev/null
  # codesign looks up identities through the search list
  security list-keychains -d user -s "$KC" $(security list-keychains -d user | tr -d '"')
  codesign --force --deep --keychain "$KC" -s "Hop Self-Signed" "$APP" || fail "codesign failed"
  security delete-keychain "$KC" || true
else
  echo "==> Signing (ad hoc)"
  codesign --force --deep -s - "$APP" || fail "codesign failed"
fi
codesign --verify --deep "$APP" || fail "signature verification failed"
codesign -dv "$APP" 2>&1 | grep -E "^(Authority|Signature)=" || true

# 6. Zip
echo "==> Zipping"
ditto -c -k --keepParent "$APP" "$ZIP" || fail "zip failed"

echo
echo "Built:  $ROOT/$APP"
echo "Zip:    $ROOT/$ZIP"
echo
echo "First launch on another Mac: move Hop to Applications, then right-click it > Open"
echo "(or System Settings > Privacy & Security > Open Anyway). The app is ad hoc signed, not notarized."
echo "Then grant Screen Recording and Accessibility to \"Hop\" in Privacy & Security."
