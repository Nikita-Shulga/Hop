#!/bin/bash
# Builds packaging/icon.icns from static/icon.png (macOS only: uses sips + iconutil).
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="static/icon.png"
SET="packaging/icon.iconset"
OUT="packaging/icon.icns"
[ -f "$SRC" ] || { echo "error: $SRC not found" >&2; exit 1; }
rm -rf "$SET"
mkdir -p "$SET"
for s in 16 32 128 256 512; do
  sips -s format png -z "$s" "$s" "$SRC" --out "$SET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -s format png -z "$d" "$d" "$SRC" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$OUT"
rm -rf "$SET"
echo "Wrote $OUT"
