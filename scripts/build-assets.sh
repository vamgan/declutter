#!/usr/bin/env bash
# Render site/assets/banner.html to PNG in both themes with headless Chrome.
# The PNGs are build output. Edit banner.html, never the images.
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[ -x "$CHROME" ] || { echo "Chrome not found. Set CHROME=/path/to/chrome" >&2; exit 1; }

for theme in light dark; do
  tmp="$(mktemp -d)"
  if [ "$theme" = dark ]; then
    sed 's|<html>|<html data-theme="dark">|' site/assets/banner.html > "$tmp/b.html"
  else
    cp site/assets/banner.html "$tmp/b.html"
  fi
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --window-size=1600,400 \
    --screenshot="site/assets/banner-$theme.png" "file://$tmp/b.html" >/dev/null 2>&1
  rm -rf "$tmp"
  echo "rendered site/assets/banner-$theme.png"
done
