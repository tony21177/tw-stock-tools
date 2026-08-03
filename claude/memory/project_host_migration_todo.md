---
name: project-host-migration-todo
description: 常駐主機搬遷暫緩中 — TODO 在 repo docs/TODO.md;基礎設施(deploy/腳本+MIGRATION.md)已全就緒只差主機
metadata:
  type: project
---

**常駐主機搬遷(2026-08-02 暫緩,用戶「先寫成 todo」)**:目標=筆電開發+主機 24/7 服務、資料雙軌雙向補洞聯集、推播單邊。
- 完整 TODO:repo `docs/TODO.md`;流程:`docs/MIGRATION.md`;腳本:`deploy/`(crontab 兩角色/deploy/autopull/fill_gaps 雙向/pull_backup/backup_caches)。
- 卡點:Oracle 免費 ARM 註冊被風控拒(重試 checklist 在 TODO);備選=二手 M720q(~NT$3,000)或年付 VPS。
- SSH 金鑰已生成 `~/.ssh/oracle_arm`。用戶拿到主機 IP 後:照 MIGRATION §1-4 裝到驗收,筆電轉 standby(crontab.standby + fill_gaps/pull_backup cron + ORACLE_IP 佔位符換真值)。
- ⚠ 在此之前筆電仍是唯一生產機(30 條 cron + ngrok 照舊),勿誤裝 standby 版 crontab。
