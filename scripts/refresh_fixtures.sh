#!/usr/bin/env bash
# Usage: bash scripts/refresh_fixtures.sh <gallery_id>
# Saves live DC pages as parser fixtures. Uses DC_COOKIES if set.
set -euo pipefail
GALLERY="${1:?usage: refresh_fixtures.sh <gallery_id>}"
OUT="$(dirname "$0")/../tests/fixtures/dc"
mkdir -p "$OUT"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
CURL_OPTS=(-sS -A "$UA")
if [[ -n "${DC_COOKIES:-}" ]]; then CURL_OPTS+=(-H "Cookie: $DC_COOKIES"); fi
curl "${CURL_OPTS[@]}" "https://gall.dcinside.com/board/lists/?id=${GALLERY}&page=1" -o "$OUT/list_page.html"
NO=$(grep -o 'no=[0-9]\+' "$OUT/list_page.html" | head -1 | cut -d= -f2)
if [[ -n "$NO" ]]; then
  curl "${CURL_OPTS[@]}" "https://gall.dcinside.com/board/view/?id=${GALLERY}&no=${NO}" -o "$OUT/post_page.html"
fi
echo "fixtures refreshed in $OUT"
