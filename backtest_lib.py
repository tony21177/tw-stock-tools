#!/usr/bin/env python3
"""backtest_lib — 回測共用工具：成本模型、統計顯著性、episode 去重。

所有回測腳本 (second_wave / broker_radar / concept / turnaround / lending)
共用此模組，統一：
  - 成本假設：手續費 0.1425%×2×折扣 + 證交稅 0.3% + 滑價
  - 顯著性：percentile bootstrap CI、t-stat、moving-block bootstrap（重疊序列用）
  - episode 去重：cooldown 法（觸發後 N 根 K 棒內不再進場）
"""
import statistics

import numpy as np

FEE_PCT = 0.1425   # 券商手續費 % (單邊, 未折扣)
TAX_PCT = 0.30     # 證交稅 % (賣出)


def cost_roundtrip_pct(discount: float = 0.6, slippage_bp: float = 0.0) -> float:
    """買+賣一趟總成本 (%)。預設 6 折手續費、零滑價 → 0.471%。"""
    return FEE_PCT * discount * 2 + TAX_PCT + slippage_bp * 2 / 100.0


def t_stat(xs: list) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    sd = statistics.stdev(xs)
    return statistics.mean(xs) / (sd / n ** 0.5) if sd > 0 else 0.0


def bootstrap_ci(xs, n_boot: int = 5000, alpha: float = 0.05, seed: int = 7):
    """均值的 percentile bootstrap 信賴區間。回 (lo, hi)。"""
    if not xs:
        return (0.0, 0.0)
    a = np.asarray(xs, dtype=np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    means = a[idx].mean(axis=1)
    return (float(np.percentile(means, alpha / 2 * 100)),
            float(np.percentile(means, (1 - alpha / 2) * 100)))


def block_bootstrap_ci(xs, block: int, n_boot: int = 5000,
                       alpha: float = 0.05, seed: int = 7):
    """Moving-block bootstrap — 給重疊期間序列 (自相關) 的均值 CI。"""
    n = len(xs)
    if n == 0:
        return (0.0, 0.0)
    block = max(1, min(block, n))
    a = np.asarray(xs, dtype=np.float64)
    rng = np.random.default_rng(seed)
    nblk = -(-n // block)  # ceil(n/block)
    starts = rng.integers(0, n - block + 1, size=(n_boot, nblk))
    means = np.empty(n_boot)
    for b in range(n_boot):
        seq = np.concatenate([a[s:s + block] for s in starts[b]])[:n]
        means[b] = seq.mean()
    return (float(np.percentile(means, alpha / 2 * 100)),
            float(np.percentile(means, (1 - alpha / 2) * 100)))


def dedup_cooldown(fires: list, cooldown: int) -> list:
    """fires = 同一檔股票已排序的觸發索引。觸發後 cooldown 根內不再進場。"""
    out, last = [], None
    for i in fires:
        if last is None or i - last > cooldown:
            out.append(i)
            last = i
    return out


def split_by_window(events, windows):
    """events = [(..., date_yyyymmdd, ...)]，date 在 tuple index 1。
    windows = {label: (from, to)} 含兩端。回 {label: [events]}。"""
    out = {k: [] for k in windows}
    for ev in events:
        d = ev[1]
        for label, (lo, hi) in windows.items():
            if lo <= d <= hi:
                out[label].append(ev)
    return out


def summarize_events(abs_rets, exc_rets, cost, edge_samples=None) -> dict:
    """事件研究摘要。edge_samples = 每事件 (超額 − 同日隨機基準)，可選。"""
    n = len(exc_rets)
    if n == 0:
        return {"n": 0}
    lo, hi = bootstrap_ci(exc_rets)
    out = {
        "n": n,
        "abs_mean": round(statistics.mean(abs_rets), 2),
        "exc_mean": round(statistics.mean(exc_rets), 2),
        "exc_med": round(statistics.median(exc_rets), 2),
        "exc_ci": [round(lo, 2), round(hi, 2)],
        "t": round(t_stat(exc_rets), 2),
        "net": round(statistics.mean(exc_rets) - cost, 2),
        "win": round(sum(1 for x in abs_rets if x > 0) / n * 100, 0),
        "beat": round(sum(1 for x in exc_rets if x > 0) / n * 100, 0),
        "cost": cost,
    }
    if edge_samples:
        elo, ehi = bootstrap_ci(edge_samples)
        out["edge_mean"] = round(statistics.mean(edge_samples) - cost, 2)
        out["edge_ci"] = [round(elo - cost, 2), round(ehi - cost, 2)]
    return out
