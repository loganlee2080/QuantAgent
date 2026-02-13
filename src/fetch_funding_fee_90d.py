#!/usr/bin/env python3
"""
Fetch Binance USD-M funding fee income and write to funding_fee_history.csv.

Uses GET /fapi/v1/income with incomeType=FUNDING_FEE in 24h windows (Binance requires
startTime–endTime ≤ 24h). Rate-limited to avoid Binance API limits (default 1.5s between
requests; income endpoint weight is high).

Usage (from project root, with venv activated):
  python scripts/fetch_funding_fee_90d.py [--days 7] [--delay 1.5]

Requires: BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) in .env or environment.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None


from env_manager import (
    BINANCE_FUTURES_BASE,
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    DATA_BINANCE,
)

FUNDING_FEE_HISTORY_PATH = DATA_BINANCE / "funding_fee_history.csv"

CSV_FIELDS = ["time", "time_iso", "symbol", "income", "asset", "tradeId", "info"]


def _signed_get(api_key: str, api_secret: str, path: str, params: dict) -> list | dict:
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{BINANCE_FUTURES_BASE}{path}?{qs}&signature={sig}"
    r = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=30)
    r.raise_for_status()
    return r.json()


def _item_to_row(item: dict) -> dict:
    t_ms = int(item.get("time") or 0)
    time_iso = datetime.utcfromtimestamp(t_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S") if t_ms else ""
    income = item.get("income") or "0"
    if isinstance(income, (int, float)):
        income = f"{income:.8f}".rstrip("0").rstrip(".")
    else:
        income = str(income).strip()
    return {
        "time": str(t_ms),
        "time_iso": time_iso,
        "symbol": str(item.get("symbol") or ""),
        "income": income,
        "asset": str(item.get("asset") or "USDT"),
        "tradeId": str(item.get("tradeId") or ""),
        "info": str(item.get("info") or ""),
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Fetch 90 days funding fee income -> funding_fee_history.csv")
    ap.add_argument("--days", type=int, default=7, help="Days to fetch (default 7)")
    ap.add_argument("--delay", type=float, default=1.5, help="Seconds between API requests (default 1.5 for rate limit)")
    ap.add_argument("--out", default=None, help=f"Output CSV (default {FUNDING_FEE_HISTORY_PATH})")
    args = ap.parse_args()

    if not requests:
        print("Install requests: pip install requests", file=sys.stderr)
        return 1

    api_key = BINANCE_API_KEY
    api_secret = BINANCE_API_SECRET
    if not api_key or not api_secret:
        print("Set BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) in .env or environment.", file=sys.stderr)
        return 1

    days = max(1, min(args.days, 90))  # Binance keeps ~90d; cap at 90
    delay = max(0.5, args.delay)
    out_path = Path(args.out) if args.out else FUNDING_FEE_HISTORY_PATH

    now_ms = int(time.time() * 1000)
    window_ms = 24 * 60 * 60 * 1000
    start_ms = now_ms - days * window_ms
    all_rows: list[dict] = []

    print(f"Fetching {days} days of funding fee income (24h windows, {delay}s between requests)...", file=sys.stderr)
    for i in range(days):
        win_start = start_ms + i * window_ms
        win_end = min(win_start + window_ms - 1, now_ms)
        try:
            data = _signed_get(
                api_key,
                api_secret,
                "/fapi/v1/income",
                {"incomeType": "FUNDING_FEE", "startTime": win_start, "endTime": win_end, "limit": 1000},
            )
        except Exception as e:
            print(f"Day {i}: {e}", file=sys.stderr)
            time.sleep(delay)
            continue
        if not isinstance(data, list):
            time.sleep(delay)
            continue
        for item in data:
            all_rows.append(_item_to_row(item))
        if (i + 1) % 15 == 0:
            print(f"  {i + 1}/{days} days, {len(all_rows)} rows so far", file=sys.stderr)
        time.sleep(delay)

    all_rows.sort(key=lambda r: int(r["time"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(all_rows)
    print(f"Wrote {len(all_rows)} rows to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
