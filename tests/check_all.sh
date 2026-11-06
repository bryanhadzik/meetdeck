#!/bin/sh
# Every saved Meet Manager meet: our .cl2/.hy3 must match Meet Manager's line for line (headers aside).
cd "$(dirname "$0")/.."
docker cp tests/check_mm_any.py swimmeet:/tmp/check_mm_any.py
for d in tests/fixtures/mm-*/; do
  n=$(basename "$d"); docker exec swimmeet rm -rf "/tmp/fx-$n"; docker cp "$d." "swimmeet:/tmp/fx-$n"
  echo "== $n"; docker exec swimmeet python3 /tmp/check_mm_any.py "/tmp/fx-$n" 3
done
