#!/bin/bash
# Pre-market chip-price for a fixed watchlist.
#
# Runs at 08:50 weekdays (cron) — fetches each stock's most recent BSR
# (published ~17:30 the previous day) and pushes the chip-price analysis
# to Telegram.
#
# Stocks run sequentially because 3491 is TPEx (上櫃) which uses Playwright
# + Xvfb headed mode — parallel runs would race over display :99.
#
# Env vars expected: TG_BOT_TOKEN, FINMIND_TOKEN (set in cron line).

set -u
cd "$(dirname "$0")"

STOCKS=(3491 2313 6282)

for code in "${STOCKS[@]}"; do
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') chip-price $code ==="
    /usr/bin/python3 tw_chip_price.py "$code" --telegram
    sleep 2
done

echo "=== $(date '+%Y-%m-%d %H:%M:%S') daily chip-price done ==="
