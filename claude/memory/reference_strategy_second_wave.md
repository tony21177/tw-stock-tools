---
name: 強勢股第二波策略 (Second Wave)
description: tw_second_wave.py — 抓「強勢上漲數月 → 1-2 週無法突破 → 急殺 15-25% → 開始反彈」搶第二波發動的入場點
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
「**強勢股第二波**」(Second Wave) — `tw_second_wave.py` CLI 工具，搜尋主力洗籌碼後再啟動的高勝率 setup。

## Pattern 四階段
1. **Phase 1 強勢底盤**：峰前 6 個月已大漲 30%+
2. **Phase 2 高點停滯**：峰值前後 1-2 週無法再突破
3. **Phase 3 急跌洗盤**：1-2 週內急跌 15-25% (恐慌爆量)
4. **Phase 4 第二波啟動**：低點後 1-10 td 反彈，量能轉強

## 七項量化過濾 (預設值)
| 條件 | 預設 | 說明 |
|------|------|------|
| F1 強勢底盤 | rally ≥ 30% | 峰前 6m 累積漲幅 |
| F2 高點在近 | peak ≤ 60 td 內 | 峰值落在最近 3 個月 |
| F3 急跌幅度 | 15% ≤ drop ≤ 25% | peak → trough 跌幅 |
| F4 急跌時長 | 5-15 td | peak → trough 持續天數 |
| F5 反彈進行 | trough 1-10 td 前，bounce ≥ +5% | 已反彈但不老 |
| F6 量能甦醒 | 近 3d 均量 / 急跌期 ≥ 0.7 | 急跌期常爆恐慌量，反彈期不需爆量但不能萎縮 |
| F7 還沒新高 | 今 < 0.98 × peak | 避免太晚進場 |

## Cron
```
40 7 * * 1-5 ... tw_second_wave.py --quiet --telegram --line-to Ca0735be…
```
盤前 07:40 跑 (Mon-Fri)，與「轉機接力」(07:30) 錯開 10 分鐘。
2026-07-19 起同步推 **LINE 田尾三人幫群組**（`--line-to`，共用 `line_push.py`，cron env `LINE_CHANNEL_ID`+`LINE_CHANNEL_SECRET` 自動換發 token；cron_catchup 也掛了）。LINE bot=@cyb6894h (tony21177)，籌碼敘事推 睏霸數錢 群、第二波推 田尾三人幫 群。

## 使用範例
```bash
# 全市場掃描
python3 ~/project/tw_stock_tools/tw_second_wave.py

# Telegram 推送
TG_BOT_TOKEN=xxx FINMIND_TOKEN=yyy \
  python3 ~/project/tw_stock_tools/tw_second_wave.py --telegram

# 個股驗證
python3 ~/project/tw_stock_tools/tw_second_wave.py --universe 2313
```

## 設計動機
2313 華通近期典型走勢：
- 6m 漲 299% (71 → 286) ← Phase 1
- 4/10 高點 286
- 4/10-4/24 急跌 25% 至 214.5 (10 td) ← Phase 3
- 4/24-4/30 反彈 +14% 至 244.5 ← Phase 4 啟動

主力洗籌碼後發動的高勝率入場點：
- 急跌把短線散戶洗出，籌碼鎖定
- 反彈量能甦醒 → 確認轉強
- 還沒破前高 → 進場空間夠

## 使用者怎麼跟我提到這個策略
- 「強勢股第二波」/ 「第二波」/ 「Second Wave」 都指這套
- 跟「轉機接力」是不同策略 (轉機接力是基本面+ABCD 接力，第二波是純技術面 pattern)

## 全市場實證 (2026-04-30 收盤資料)
9 檔候選，跑完 1 分鐘 (6 workers, Yahoo cold cache):
- 4991 環宇-KY 漲 457% / 跌 21% / 反彈 19% / 量比 5.2x ⭐ 最強
- 3163 波若威 漲 551% / 跌 20% / 反彈 10%
- 6588 東典光電 漲 474% / 跌 22% / 反彈 16%
- 2313 華通 漲 299% / 跌 25% / 反彈 14% (參考案例)
- 3234 光環、3437 榮創、1528 恩德、5243 乙盛-KY、4760 勤凱
