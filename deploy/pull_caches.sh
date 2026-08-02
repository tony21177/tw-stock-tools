#!/bin/bash
# 筆電端:從常駐主機拉快取回來(開發測試用)。預設拉輕量必要組;--all 全拉。
# 用法:./deploy/pull_caches.sh user@prod-host [--all]
set -e
HOST="${1:?用法: pull_caches.sh user@host [--all]}"
DST=~/project/tw_stock_tools/concept_momentum/cache
SRC="$HOST:~/project/tw_stock_tools/concept_momentum/cache"
if [ "$2" = "--all" ]; then
  rsync -az --info=progress2 "$SRC/" "$DST/"
else
  for d in year_prices margin_hist sbl_day inst_day vol_day season_limitup kline; do
    rsync -az "$SRC/$d/" "$DST/$d/" 2>/dev/null || true
  done
  rsync -az "$SRC/"*.json "$DST/" 2>/dev/null || true
fi
echo "✅ caches pulled from $HOST"
