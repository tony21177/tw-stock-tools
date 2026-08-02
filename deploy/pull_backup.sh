#!/bin/bash
# 筆電端:從常駐主機拉「每日快照備份」回筆電(異地備份)。
# 拉的是主機 ~/backups/ 的 tar 快照(輪替 7 份)— rsync 已有的檔案會跳過,
# 每次實際只傳最新一兩份,快又省。
#
# 裝法(筆電 crontab,搬遷完成後):
#   @reboot sleep 180 && ~/project/tw_stock_tools/deploy/pull_backup.sh >> /tmp/pull_backup.log 2>&1
#   0 */4 * * * ~/project/tw_stock_tools/deploy/pull_backup.sh >> /tmp/pull_backup.log 2>&1
# (@reboot=每次開 WSL 就拉一次;*/4=開著的時候每 4 小時再確認)
set -e
HOST="${1:-${PROD_HOST:-ubuntu@ORACLE_IP}}"        # 搬遷後把 ORACLE_IP 換成真 IP,或 export PROD_HOST
DST=~/backups_oracle
mkdir -p "$DST"
rsync -az -e "ssh -i ~/.ssh/oracle_arm -o ConnectTimeout=10" \
      "$HOST:~/backups/" "$DST/"
# 筆電端也輪替,只留 7 份
ls -t "$DST"/cache_*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm
echo "$(date '+%F %T') pulled: $(ls "$DST" | wc -l) 份快照, 最新 $(ls -t "$DST" | head -1)"
