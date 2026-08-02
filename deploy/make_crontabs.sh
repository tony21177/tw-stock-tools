#!/bin/bash
# 從去敏 master 產生兩種角色的 crontab:
#   crontab.primary.txt  = 原樣(推播 + 全部工作)
#   crontab.standby.txt  = 去掉推播旗標(--telegram/--line-to/--tg-*),
#                          並拿掉會寫 git 追蹤檔的富台 OI 記錄行(避免 pull 衝突)
set -e
cd "$(dirname "$0")"
cp crontab.sanitized.txt crontab.primary.txt
sed -E \
  -e 's/ --telegram//g' \
  -e 's/ --line-to [^ ]+//g' \
  -e '/remind-twn-oi/d' \
  crontab.sanitized.txt > crontab.standby.txt
echo "generated: crontab.primary.txt / crontab.standby.txt"
