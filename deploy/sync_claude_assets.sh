#!/bin/bash
# 把本機 Claude Code 資產同步進 repo(commit 前跑,讓 memory/skills 有版本控制)
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$REPO/claude/memory" "$REPO/claude/skills"
rsync -a --delete ~/.claude/projects/-home-kun/memory/ "$REPO/claude/memory/"
for s in chip chip-price contract-liabilities taiwan-stock-data-scraping; do
  rsync -a --delete ~/.claude/skills/$s/ "$REPO/claude/skills/$s/"
done
cp ~/CLAUDE.md "$REPO/claude/CLAUDE.md"
mkdir -p "$REPO/deploy/systemd"
cp ~/.config/systemd/user/concept-dashboard.service \
   ~/.config/systemd/user/ngrok-tunnel.service "$REPO/deploy/systemd/" 2>/dev/null || true
# crontab 去敏匯出(token → 佔位符)
crontab -l | sed -E \
  -e 's/FINMIND_TOKEN=[^ ]+/FINMIND_TOKEN=${FINMIND_TOKEN}/g' \
  -e 's/TG_BOT_TOKEN=[^ ]+/TG_BOT_TOKEN=${TG_BOT_TOKEN}/g' \
  -e 's/LINE_CHANNEL_ID=[^ ]+/LINE_CHANNEL_ID=${LINE_CHANNEL_ID}/g' \
  -e 's/LINE_CHANNEL_SECRET=[^ ]+/LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET}/g' \
  > "$REPO/deploy/crontab.sanitized.txt"
echo "synced: memory $(ls "$REPO/claude/memory" | wc -l) files, skills 4, CLAUDE.md, systemd, crontab(sanitized)"
