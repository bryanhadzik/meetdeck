#!/bin/sh
# Publish a MeetDeck update to GitHub (bryanhadzik/meetdeck). Windows copies see it under
# Setup -> Updates and install it with one click.
#   windows/release.sh "What changed, one line per item"
set -e
cd "$(dirname "$0")/.."
NOTES="${1:?say what changed: windows/release.sh \"Fixed ...\"}"
TODAY=$(date +%Y.%m.%d)
CUR=$(cat app/VERSION 2>/dev/null || echo 0)
case "$CUR" in
  "$TODAY".*) N=$(( ${CUR##*.} + 1 )) ;;
  *) N=1 ;;
esac
V="$TODAY.$N"
echo "$V" > app/VERSION
windows/build.sh --with-meets          # also refreshes the server's Windows download
git add -A
if [ -n "$COMMIT_TRAILER" ]; then git commit -q -m "MeetDeck $V" -m "$NOTES" -m "$COMMIT_TRAILER"
else git commit -q -m "MeetDeck $V" -m "$NOTES"; fi
git push -q origin HEAD
gh release create "v$V" "windows/dist/meetdeck-app-$V.zip" --title "MeetDeck $V" --notes "$NOTES"
echo "Released MeetDeck $V"
