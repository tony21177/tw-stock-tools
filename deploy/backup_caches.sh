#!/bin/bash
# 常駐主機端:每日快取快照(tar 輪替留 7 份)。
# 裝法(主機 crontab):30 23 * * * ~/project/tw_stock_tools/deploy/backup_caches.sh >> /tmp/backup.log 2>&1
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DST=~/backups
mkdir -p "$DST"
tar czf "$DST/cache_$(date +%Y%m%d).tar.gz" -C "$REPO/concept_momentum" cache
ls -t "$DST"/cache_*.tar.gz | tail -n +8 | xargs -r rm    # 留最新 7 份
echo "$(date '+%F %T') backup ok: $(ls -lh "$DST" | tail -1)"
