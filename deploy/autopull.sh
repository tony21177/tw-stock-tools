#!/bin/bash
# 常駐主機端(可選):每 10 分自動 pull,有更新就重啟網站。
# 裝法:crontab 加 →  */10 * * * * /home/USER/project/tw_stock_tools/deploy/autopull.sh >> /tmp/autopull.log 2>&1
cd "$(dirname "$0")/.."
BEFORE=$(git rev-parse HEAD)
git pull --ff-only origin main -q || exit 0
AFTER=$(git rev-parse HEAD)
if [ "$BEFORE" != "$AFTER" ]; then
  echo "$(date '+%F %T') updated $BEFORE -> $AFTER, restarting"
  systemctl --user restart concept-dashboard
fi
