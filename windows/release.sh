#!/bin/sh
# Publish a MeetDeck update to GitHub (bryanhadzik/meetdeck). Windows copies see it under
# Setup -> Updates and install it with one click.
#   windows/release.sh "What changed, one line per item"
set -e
cd "$(dirname "$0")/.."
NOTES="${1:?say what changed: windows/release.sh \"Fixed ...\"}"
# Version: MEETDECK_VERSION=1.1 windows/release.sh "..." sets it; otherwise the last number goes up
# (1.0 -> 1.0.1 -> 1.0.2). Old dated builds (2026.11.10.6) sort before 1.0 in the updater.
CUR=$(cat app/VERSION 2>/dev/null || echo 0)
if [ -n "$MEETDECK_VERSION" ]; then V="$MEETDECK_VERSION"
else
  case "$CUR" in
    20[0-9][0-9].*) TODAY=$(date +%Y.%m.%d)
      case "$CUR" in "$TODAY".*) V="$TODAY.$(( ${CUR##*.} + 1 ))" ;; *) V="$TODAY.1" ;; esac ;;
    *.*.*) V="${CUR%.*}.$(( ${CUR##*.} + 1 ))" ;;
    *) V="$CUR.1" ;;
  esac
fi
echo "$V" > app/VERSION
windows/build.sh --with-meets          # also refreshes the server's Windows download
git add -A
if [ -n "$COMMIT_TRAILER" ]; then git commit -q -m "MeetDeck $V" -m "$NOTES" -m "$COMMIT_TRAILER"
else git commit -q -m "MeetDeck $V" -m "$NOTES"; fi
git push -q origin HEAD
python3 windows/public_zip.py windows/dist/MeetDeck-Windows.zip windows/dist/public/MeetDeck-Windows.zip 2>/dev/null || { mkdir -p windows/dist/public && python3 windows/public_zip.py windows/dist/MeetDeck-Windows.zip windows/dist/public/MeetDeck-Windows.zip; }
gh release create "v$V" "windows/dist/meetdeck-app-$V.zip" "windows/dist/public/MeetDeck-Windows.zip" --title "MeetDeck $V" --notes "$NOTES"
echo "Released MeetDeck $V"
