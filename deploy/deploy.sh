#!/bin/bash
# 筆電端一鍵部署:push → 常駐主機 pull + 重啟網站
# 用法:./deploy/deploy.sh user@prod-host
set -e
HOST="${1:?用法: deploy.sh user@host}"
git push origin main
ssh "$HOST" 'cd ~/project/tw_stock_tools && git pull --ff-only origin main \
  && systemctl --user restart concept-dashboard \
  && sleep 2 && curl -s -o /dev/null -w "dashboard: %{http_code}\n" http://localhost:5000/'
echo "✅ deployed to $HOST"
