"""Thin FinMind v4 API client.

Each function takes (data_id, start_date, end_date, token) and returns the
parsed `data` list in FinMind's native schema. No schema translation, no
caching — callers stay in control of their own data shapes.

Built-in retry: HTTP 429 → sleep 60s, retry once.
"""

from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.finmindtrade.com/api/v4/data"


def _call(dataset: str, params: dict, token: str, _retried: bool = False) -> list[dict]:
    """Generic FinMind call. Raises RuntimeError on non-200 status."""
    full_params = {"dataset": dataset, "token": token, **params}
    url = f"{BASE_URL}?{urllib.parse.urlencode(full_params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429 and not _retried:
            time.sleep(60)
            return _call(dataset, params, token, _retried=True)
        body = e.read().decode() if hasattr(e, "read") else str(e)
        raise RuntimeError(f"FinMind {dataset} HTTP {e.code}: {body[:200]}")
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset} error: {payload.get('msg', '')}")
    return payload.get("data", [])


def fetch_securities_lending(stock_id: str, start_date: str, end_date: str,
                              token: str) -> list[dict]:
    """Fetch 借券交易 (借入 events) for a stock.

    Returns rows with shape:
      {date, stock_id, transaction_type, volume (張), fee_rate (%),
       close, original_return_date, original_lending_period}
    """
    return _call("TaiwanStockSecuritiesLending", {
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }, token)


def fetch_short_sale_balances(stock_id: str, start_date: str, end_date: str,
                               token: str) -> list[dict]:
    """Fetch 信用交易+借券賣出餘額 for a stock.

    Returns rows with shape (values in 股):
      {date, stock_id,
       MarginShortSalesPreviousDayBalance, MarginShortSalesShortSales,
       MarginShortSalesShortCovering, ..., MarginShortSalesCurrentDayBalance,
       SBLShortSalesPreviousDayBalance, SBLShortSalesShortSales,
       SBLShortSalesReturns, SBLShortSalesAdjustments, SBLShortSalesCurrentDayBalance,
       SBLShortSalesQuota, SBLShortSalesShortCovering}
    """
    return _call("TaiwanDailyShortSaleBalances", {
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }, token)


def fetch_stock_price(stock_id: str, start_date: str, end_date: str,
                      token: str) -> list[dict]:
    """Fetch 個股日線價格.

    Returns rows with shape:
      {date, stock_id, Trading_Volume, Trading_money, open, max, min, close,
       spread, Trading_turnover}
    """
    return _call("TaiwanStockPrice", {
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }, token)


def fetch_short_sale_balances_market(date: str, token: str) -> list[dict]:
    """Fetch 全市場一日 借券賣出餘額 (for daily SBL monitor sweeps)."""
    return _call("TaiwanDailyShortSaleBalances", {
        "start_date": date,
        "end_date": date,
    }, token)


def fetch_stock_price_tick(stock_id: str, date: str,
                           token: str) -> list[dict]:
    """Fetch tick-by-tick 成交資料 for one stock on one date.

    Returns rows with shape:
      {date, stock_id, deal_price (float), volume (股),
       Time ('HH:MM:SS.ffffff'), TickType (int)}
    Single-day only; FinMind sponsor tier required.
    """
    return _call("TaiwanStockPriceTick", {
        "data_id": stock_id,
        "start_date": date,
        "end_date": date,
    }, token)
