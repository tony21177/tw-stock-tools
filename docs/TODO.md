# 📋 待辦:常駐主機搬遷(2026-08-02 暫緩)

**目標**:開發在筆電(想關就關),網站/cron/推播 24/7 在常駐主機;
兩邊資料雙軌+雙向補洞(聯集,都最完整);推播/ngrok 只在 primary。
**基礎設施已全部就緒**,只差一台主機:

- [ ] **取得常駐主機**(擇一):
  - [ ] 方案 A:Oracle Cloud 免費 ARM——首次註冊被風控拒。重試 checklist:
        關 VPN/家用網路/乾淨瀏覽器、資料英文拼音與信用卡一致、換不同銀行實體卡、
        失敗 2 次停 24-48h 換新 email 再試。**兩天內搞不定就放棄轉 B**
  - [ ] 方案 B:二手迷你主機——蝦皮搜「**M720q i5-8500T**」16G/256G NVMe
        約 NT$3,000(評價 4.9+ 店家;要含變壓器、問風扇異音、7 天測試)。
        到貨裝 Ubuntu Server 24.04 → 插網路線 → 給 Claude SSH
  - [ ] 方案 C:年付 VPS(RackNerd 促銷 ~$17-25/年,2GB)刷卡即開
- [ ] 主機到手後:照 `docs/MIGRATION.md` §1-4 安裝(Claude 執行,~1 小時)
      — crontab.primary + systemd + ngrok(同域名)+ rsync 494MB 快取
- [ ] 筆電轉 standby:`crontab.standby.txt` 裝入 + fill_gaps/pull_backup 兩條
      cron + 腳本內 `ORACLE_IP` 佔位符換真 IP
- [ ] 驗收:22 頁 200、推播只來一份、手機 ngrok 網址正常、雙向補洞跑通
- [ ] (可選)主機每日快照 cron `backup_caches.sh` + 筆電 `pull_backup.sh` 確認輪替

**已備好的資產**:SSH 金鑰 `~/.ssh/oracle_arm`(公鑰在 MIGRATION 流程)、
`deploy/` 全套腳本(crontab 兩角色版/deploy/autopull/fill_gaps/pull_backup/backup_caches)、
`claude/` memory+skills 版控。
