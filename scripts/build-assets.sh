#!/usr/bin/env bash
# Render the image assets with headless Chrome.
#   banner.html  -> banner-light.png / banner-dark.png   (1600x400, README header)
#   social.html  -> social-card.png                      (1280x640, link previews)
# The PNGs are build output. Edit the HTML, never the images.
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

# Social card. Link previews are 2:1 and crop toward the centre, so this is a
# different composition rather than a resize of the wide banner.
"$CHROME" --headless --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=1 --window-size=1280,640 \
  --screenshot="site/assets/social-card.png" "file://$PWD/site/assets/social.html" >/dev/null 2>&1
echo "rendered site/assets/social-card.png"
