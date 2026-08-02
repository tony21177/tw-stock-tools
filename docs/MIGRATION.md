# 🚚 搬機指南 — 讓另一台機器的 Claude Code 無縫接續

目標:在新機器(建議 WSL2 Ubuntu / Linux)上重建完整環境
——網站、排程、推播、快取,以及 **Claude Code 的記憶與技能**。

## 0. 這個 repo 帶了什麼

| 目錄 | 內容 |
|---|---|
| `claude/memory/` | Claude Code 長期記憶(44 份:策略口徑/教訓/慣例)——**接續開發的關鍵** |
| `claude/skills/` | 自製 skills:chip / chip-price / contract-liabilities / taiwan-stock-data-scraping |
| `claude/CLAUDE.md` | 使用者層指示(放 `~/CLAUDE.md`) |
| `deploy/crontab.sanitized.txt` | 完整排程(token 為 `${VAR}` 佔位符) |
| `deploy/systemd/` | 網站 + ngrok 的 systemd user units |
| `deploy/secrets.env.example` | 需要的密鑰清單(真實值不進 git) |
| `deploy/sync_claude_assets.sh` | 舊機:把本機 Claude 資產同步進 repo(commit 前跑) |
| `docs/` | 全部策略文件;`README.md` 是索引 |

## 1. 系統需求

```bash
sudo apt install python3 python3-pip rsync curl gettext-base   # envsubst 在 gettext-base
pip3 install flask matplotlib plotly requests                   # 依 docs/infra.md 部署需求節
# 中文字型(matplotlib 圖表用):
sudo apt install fonts-wqy-microhei
# ngrok:https://ngrok.com 下載,ngrok config add-authtoken <token>
#   靜態域名在 ngrok dashboard 申請後改 deploy/systemd/ngrok-tunnel.service 的域名參數
```

## 2. 還原步驟

```bash
git clone https://github.com/tony21177/tw-stock-tools.git ~/project/tw_stock_tools
cd ~/project/tw_stock_tools

# ── Claude Code 資產 ──
mkdir -p ~/.claude/projects/-home-kun ~/.claude/skills
rsync -a claude/memory/ ~/.claude/projects/-home-kun/memory/
rsync -a claude/skills/ ~/.claude/skills/
cp claude/CLAUDE.md ~/CLAUDE.md
# ⚠ memory 路徑含 "-home-kun"(由家目錄 /home/kun 而來);若新機使用者不同,
#   對應改為 ~/.claude/projects/<你的家目錄轉 dash>/memory/

# ── 密鑰 ──
cp deploy/secrets.env.example deploy/secrets.env && nano deploy/secrets.env

# ── crontab(佔位符代入真實值)──
set -a && source deploy/secrets.env && set +a
envsubst < deploy/crontab.sanitized.txt | crontab -
crontab -l | head   # 確認 token 已代入

# ── 網站 + ngrok(systemd user units)──
mkdir -p ~/.config/systemd/user
cp deploy/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now concept-dashboard ngrok-tunnel
loginctl enable-linger $USER          # WSL/伺服器:登出後 unit 續跑
```

## 3. 歷史快取資料(重要,git 不含)

`concept_momentum/cache/` 多數在 .gitignore。分兩類(詳 memory `cron 補跑分類規則`):

- **可重建**(FinMind 指定日期乾淨補):year_prices / margin_hist / sbl_day /
  inst_day / vol_day / season_limitup / kline —— 各工具 `--backfill` 或首跑自建
- **不可重建的歷史累積**(datetime.now() 綁定):`bsr_cache/`、
  `broker_radar_history/`、各策略 `*_history/` —— **必須從舊機 rsync**:

```bash
rsync -az 舊機:/home/kun/project/tw_stock_tools/concept_momentum/cache/ \
      ~/project/tw_stock_tools/concept_momentum/cache/
```

嫌大就整包搬(最省事,快取全保留、免 backfill)。

## 3.5 資料備份(三層)

1. **主機每日快照**:crontab 加 `30 23 * * * ~/project/tw_stock_tools/deploy/backup_caches.sh`
   (tar 輪替留 7 份,~/backups/,約 2-3GB)
2. **筆電自動異地備份**:筆電 crontab 掛 `deploy/pull_backup.sh`
   (`@reboot` 每次開機拉 + 開機期間每 4 小時確認)→ 主機的 7 份 tar 快照
   自動同步到筆電 `~/backups_oracle/`;rsync 增量,每次只傳新的那份。
   另 `pull_caches.sh --all` 是拉「解開的原始快取」供開發測試,兩者用途不同
3. (可選)Oracle Object Storage 免費 20GB 再放一份週備份

資料流動單向:**主機是唯一寫入者,筆電只讀副本** — 不會再發生本機誤跑污染歷史檔。

## 4. 驗收清單(常駐主機)

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/          # 200
for p in margin-scan ftd vcp utility-screen foreign-cost option-flow; do
  curl -s -o /dev/null -w "$p:%{http_code} " http://localhost:5000/$p; done; echo
crontab -l | wc -l        # ~30 條
```
手機開 ngrok 網址 → 首頁深色 + 點任一代號出 K 線彈窗 = 成功。

## 5. 筆電開發 + 常駐主機服務(分離架構,2026-08-02 定案)

**開發在筆電(想關就關),服務在常駐主機(24/7)**:

**模式(2026-08-02 定案):Active-Active 資料 / Single-Push 通知**

- 兩邊都跑同一套 cron(資料雙軌累積,互為備援);
  **推播與 ngrok 只在 primary**(避免通知×2 與域名衝突)。
- 角色 crontab 由 `deploy/make_crontabs.sh` 產生:
  - 主機(primary):`envsubst < crontab.primary.txt | crontab -`
  - 筆電(standby):`envsubst < crontab.standby.txt | crontab -`
    (已去推播旗標;另加 fill_gaps/pull_backup 兩條,見下)
- 筆電關機期間的資料洞:`deploy/fill_gaps.sh`(@reboot + 每晚 23:00)
  從主機 `--ignore-existing` 補缺日、不覆蓋本機 → 兩邊收斂一致。
- **故障切換(1 分鐘)**:主機掛了 → 筆電 `envsubst < crontab.primary.txt | crontab -`
  並 `systemctl --user start ngrok-tunnel`(靜態域名自動跟過來);修復後換回。
- 日常流程:
  1. 筆電開發 → `./deploy/deploy.sh user@prod`(push + 遠端 pull + 重啟 + 健檢)
  2. 或懶人法:常駐主機掛 `deploy/autopull.sh`(每 10 分自動 pull+重啟)
  3. 筆電要測試資料 → `./deploy/pull_caches.sh user@prod`(拉共用快取;--all 全拉)
  4. memory 有更新 → commit 前跑 `deploy/sync_claude_assets.sh`
- ⚠ 只在常駐主機跑 cron;筆電手動測工具時**不要帶 --telegram/--line-to**(免重複推播)。

## 6. 新機上的 Claude Code 開始工作前

1. 確認 memory 已就位(session 會自動載入 `MEMORY.md` 索引)
2. 讀 `README.md`(策略索引)+ 該次要動的 `docs/` 策略文件
3. 鐵律都在 memory:紅漲綠跌、★ 標記、術語白話、改動全檢查、
   新頁 checklist(`reference-site-nav`)、commit 規範(明確 stage、勿 `git add -A`)
4. **舊機持續開發時**:commit 前跑 `deploy/sync_claude_assets.sh` 讓 memory/skills 同步進版控

## 7. 回遷:關掉雲端、改回本地跑

整套架構可逆,回遷 ≈ 30 分鐘:

```bash
# ① 最後一次全量同步(雲 → 筆電)
./deploy/pull_caches.sh ubuntu@ORACLE_IP --all     # 原始快取全量
./deploy/pull_backup.sh                             # 最後的 tar 快照

# ② 雲端停服務(先停,避免雙跑)
ssh -i ~/.ssh/oracle_arm ubuntu@ORACLE_IP \
  'crontab -r; systemctl --user disable --now concept-dashboard ngrok-tunnel'

# ③ 筆電恢復生產身分
set -a && source deploy/secrets.env && set +a
envsubst < deploy/crontab.sanitized.txt | crontab -   # 排程裝回
systemctl --user enable --now concept-dashboard ngrok-tunnel
# ngrok 靜態域名綁帳號不綁機器 → 雲端 agent 停掉後,筆電啟動即接手同一網址

# ④ 驗收(同 §4)後,Oracle console 終止 instance(免費層,無違約金)
```

**可逆的關鍵設計**:code/文件/Claude 資產在 git;crontab/systemd 是去敏設定檔
(secrets 分離);ngrok 域名跟帳號走;資料靠每日快照+筆電自動異地備份,
任何時點筆電手上都有 ≤24 小時新的完整資料。

⚠ 回遷後記得把筆電 crontab 裡的兩條 pull_backup 拿掉(自己拉自己無意義),
並恢復 cron_catchup(WSL 掛機補跑又需要了)。
