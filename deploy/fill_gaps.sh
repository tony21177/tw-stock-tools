#!/bin/bash
# 筆電端補洞:把「筆電關機期間漏掉的逐日快取」從主機補進來。
# --ignore-existing = 只補缺的日子,絕不覆蓋筆電自己抓的(兩邊資料因此收斂一致)。
# 裝法(筆電 crontab):@reboot sleep 240 && .../fill_gaps.sh ; 0 23 * * * .../fill_gaps.sh
set -e
HOST="${1:-${PROD_HOST:-ubuntu@ORACLE_IP}}"
SRC="$HOST:~/project/tw_stock_tools/concept_momentum/cache"
DST=~/project/tw_stock_tools/concept_momentum/cache
SSH="ssh -i ~/.ssh/oracle_arm -o ConnectTimeout=10"
for d in year_prices margin_hist sbl_day inst_day vol_day season_limitup kline \
         bsr_cache broker_radar_history turnaround_relay_history \
         second_wave_history short_retreat_history lending_radar_history \
         market_overnight_history warrant_flow results; do
  rsync -az --ignore-existing -e "$SSH" "$SRC/$d/" "$DST/$d/" 2>/dev/null || true
done
echo "$(date '+%F %T') gaps filled from $HOST"
