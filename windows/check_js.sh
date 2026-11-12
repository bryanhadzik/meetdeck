#!/bin/sh
# Syntax-check the inline <script> blocks of every page before a release (a stray brace once broke meet setup).
set -e
cd "$(dirname "$0")/.."
T=$(mktemp -d)
for f in app/static/*.html; do
  python3 -c "import re,sys; open(sys.argv[2],'w').write('\n'.join(re.findall(r'<script>(.*?)</script>', open(sys.argv[1]).read(), re.S)))" "$f" "$T/$(basename "$f").js"
done
docker run --rm -v "$T:/js:ro" node:20-alpine sh -c 'ok=0; for f in /js/*.js; do node --check "$f" || { echo "JavaScript error in ${f#/js/}"; ok=1; }; done; exit $ok'
rm -rf "$T"
