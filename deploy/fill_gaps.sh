#!/bin/bash
# 雙向補洞同步(筆電端執行):兩邊的逐日快取互補缺口 → 收斂成聯集,
# 兩邊都擁有最完整資料。--ignore-existing = 只補對方沒有的日子、絕不覆蓋。
#   拉:主機有、筆電沒有(筆電關機期間的日子)
#   推:筆電有、主機沒有(主機當機/API 失敗漏抓、或搬遷前的歷史)
# 裝法(筆電 crontab):
#   @reboot sleep 240 && ~/project/tw_stock_tools/deploy/fill_gaps.sh >> /tmp/fill_gaps.log 2>&1
#   0 23 * * * ~/project/tw_stock_tools/deploy/fill_gaps.sh >> /tmp/fill_gaps.log 2>&1
set -e
HOST="${1:-${PROD_HOST:-ubuntu@ORACLE_IP}}"
BASE=~/project/tw_stock_tools/concept_momentum/cache
RBASE="~/project/tw_stock_tools/concept_momentum/cache"
SSH="ssh -i ~/.ssh/oracle_arm -o ConnectTimeout=10"
# 僅同步「逐日檔」目錄(一天一檔,聯集語意安全;latest/彙總類各自 cron 重建,不同步)
DIRS="year_prices margin_hist sbl_day inst_day vol_day season_limitup kline \
      bsr_cache broker_radar_history turnaround_relay_history \
      second_wave_history short_retreat_history lending_radar_history \
      market_overnight_history warrant_flow results"
for d in $DIRS; do
  rsync -az --ignore-existing -e "$SSH" "$HOST:$RBASE/$d/" "$BASE/$d/" 2>/dev/null || true   # 拉
  rsync -az --ignore-existing -e "$SSH" "$BASE/$d/" "$HOST:$RBASE/$d/" 2>/dev/null || true   # 推
done
echo "$(date '+%F %T') 雙向補洞完成(聯集收斂)from/to $HOST"
