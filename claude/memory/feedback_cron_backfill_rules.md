---
name: feedback_cron_backfill_rules
description: 補跑漏掉的累積數據 cron 時，哪些可重建、哪些工具是 datetime.now() 綁定不能硬補
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---

WSL2 掛起會讓當天 cron 整批被跳過（非排隊），事後補跑 `~/project/tw_stock_tools` 的累積數據序列時，**先分類再補**，不要每個都直接跑：

**可乾淨補（從 FinMind 歷史重建，內部 date 正確）：**
- 借券雷達 / 空頭撤退：`tw_lending_monitor.py --mode lending|sbl --date YYYYMMDD --json-out-... .../YYYYMMDD.json`（有 `--date`）
- 大盤寬度：直接呼叫 `market_breadth.run_today('YYYYMMDD', token)`（吃明確日期）。但它靠 `cache/taiex.json` 判定交易日，taiex 常缺日 → 先 `data_fetcher.fetch_taiex(force=True)` 補滿再跑。

**不能硬補（工具用 `datetime.now()` 綁定，硬跑會污染）：**
- 主力雷達 `tw_broker_monitor.py`：分點 BSR 來源 TWSE/TPEx **只有當日、無歷史 API**；BSR scraper 用 `datetime.now()` 當 cache 檔名。事後跑會把「最新 session」資料貼上**今天日期**標籤存進 `bsr_cache/*_<today>.json`（200 檔），且內部 date 欄位也是今天。後果：當天傍晚真正的 cron 會讀到髒 cache → 產出錯的雷達。**永久缺，別補**；若已誤跑，立刻 `rm bsr_cache/*_<today>.json` + 刪掉錯誤的 history 檔。
- 轉機接力 `tw_daily_screen.py` / 強勢股第二波 `tw_second_wave.py`：盤前 07:30/07:40 篩選，用前一日收盤。事後跑會抓到目標日收盤＝產出「下一個交易日盤前」，無法重現那一刻。盤前訊號前瞻性、單日缺漏對回測影響小，留缺口即可。

**Why:** 區分「EOD 可重建數據」vs「當下快照/盤前訊號」。前者 FinMind 有歷史可指定日期；後者工具沒有 as-of 參數，硬跑只會用最新資料貼舊日期 → 污染。

**How to apply:** 補跑前先 `grep '"--date"' <tool>.py` 看有沒有 as-of 參數；沒有就別用今天的執行去填過去的檔名。相關：[[reference_all_strategies]] [[feedback_cron_finmind_token]]

**臨時休市日反向污染（2026-07-10 事件，07-17 清理）：** FinMind `TaiwanStockTradingDate` 日曆**不含臨時停市**（颱風假）— 2026-07-10 實際休市但日曆至今仍列為交易日 → `is_trading_day.py` 誤放行 → 全部盤後 cron 照跑：TWSE BSR 回傳前一日資料被錯標成 0710（bsr_cache 219 檔 + chip_price_history 1 檔，內容 100% 重複 07/09）；主力雷達/借券/盤前篩選等 7 個 strategy history 檔也寫入假交易日紀錄。全部已驗證後刪除。判定某日是否真交易日的黃金標準：**FinMind 抓 2330 該日有無成交列**（money_flow/taiex 也可交叉）。`tw_chip_price.py build_behavior_series` 已加自動防禦（整日 (buy,sell) 簽名與前日重複即剔除）。**2026-07-17 起 `is_trading_day.py` 加第二層守門**（過去日期或今天過 15:00 時查 2330 有無實際成交，臨時休市 exit 1，FinMind 異常 fail-open）→ 盤後 cron 不會再於颱風假誤跑；但盤前 cron（07:30/08:50）無法驗證當日，颱風假當天盤前工具仍會跑（前瞻訊號、影響小）。cron_catchup 同日也加了 pgrep 長工防雙跑。
