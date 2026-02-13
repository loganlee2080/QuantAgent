#!/usr/bin/env python3
"""
Query Binance USD-M funding history APIs and optionally write CSV.

1) Funding rate history (market data, no auth)
   GET /fapi/v1/fundingRate
   Params: symbol (e.g. BTCUSDT), startTime, endTime, limit (max 1000)
   Returns: symbol, fundingRate, fundingTime, markPrice

2) Funding fee income history (account, requires API key)
   GET /fapi/v1/income with incomeType=FUNDING_FEE
   Params: symbol, startTime, endTime, limit (max 1000)
   Returns: symbol, income, asset, time, tradeId, etc.

Usage:
  # Funding rate history for BTC (public; no .env needed)
  python scripts/fetch_binance_funding_history.py --rate --symbol BTCUSDT [--limit 500] [--out data/binance/funding_rate_history.csv]

  # Your funding fee income history (signed; needs BINANCE_API_KEY/SECRET)
  python scripts/fetch_binance_funding_history.py --income [--limit 1000] [--out data/binance/funding_fee_income.csv]

  # Both
  python scripts/fetch_binance_funding_history.py --rate --income --symbol BTCUSDT

  # Funding rate history for all coins in positions.csv (per-symbol CSVs in data/binance/funding/)
  python scripts/fetch_binance_funding_history.py --rate --all-from-positions [--append]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from env_manager import (
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_PUBLIC_BASE,
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    DATA_BINANCE,
)


def _binance_signed_get(api_key: str, api_secret: str, path: str, params: dict | None = None) -> list | dict:
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{BINANCE_FUTURES_BASE}{path}?{qs}&signature={sig}"
    r = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_funding_rate_history(
    symbol: str,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 1000,
) -> list[dict]:
    """
    GET /fapi/v1/fundingRate (public).
    Returns list of { symbol, fundingRate, fundingTime, markPrice }.
    """
    if not requests:
        raise RuntimeError("requests package required")
    params = {"symbol": symbol.upper() if not symbol.endswith("USDT") else symbol, "limit": min(limit, 1000)}
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time
    # Basic retry with backoff to be gentle on rate limits / transient errors
    backoff = 1.0
    max_backoff = 16.0
    for attempt in range(5):
        try:
            r = requests.get(f"{BINANCE_FUTURES_PUBLIC_BASE}/fapi/v1/fundingRate", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            # If it's a 403 (forbidden / temporary ban / geo-block), don't hammer – log once and give up for this symbol.
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 403:
                print(
                    f"Warning: fundingRate request forbidden (403) for {symbol}; "
                    f"skipping symbol to avoid further rate-limit/ban issues: {e}",
                    file=sys.stderr,
                )
                return []
            # Last attempt: re-raise
            if attempt == 4:
                raise
            # Log and sleep with backoff, then retry
            print(f"Warning: fundingRate request failed for {symbol} (attempt {attempt+1}/5): {e}", file=sys.stderr)
            time.sleep(backoff)
            backoff = min(backoff * 2.0, max_backoff)
    # Should not reach here
    return []


def fetch_funding_fee_income_history(
    api_key: str,
    api_secret: str,
    symbol: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 1000,
) -> list[dict]:
    """
    GET /fapi/v1/income with incomeType=FUNDING_FEE (signed).
    Returns list of income records (time, symbol, income, asset, tradeId, etc.).
    """
    params = {"incomeType": "FUNDING_FEE", "limit": min(limit, 1000)}
    if symbol:
        params["symbol"] = symbol.upper() if not symbol.endswith("USDT") else symbol
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time
    return _binance_signed_get(api_key, api_secret, "/fapi/v1/income", params)


def write_funding_rate_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sort by fundingTime descending so newest records appear first
    def _key(row: dict) -> int:
        try:
            return int(row.get("fundingTime") or 0)
        except (TypeError, ValueError):
            return 0
    ordered = sorted(rows, key=_key, reverse=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "fundingRate", "fundingTime", "markPrice"])
        w.writeheader()
        for r in ordered:
            w.writerow({
                "symbol": r.get("symbol", ""),
                "fundingRate": r.get("fundingRate", ""),
                "fundingTime": r.get("fundingTime", ""),
                "markPrice": r.get("markPrice", ""),
            })
    print(f"Wrote {len(rows)} rows to {path}")


def write_funding_fee_income_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["time", "time_iso", "symbol", "income", "asset", "tradeId", "info"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            t_ms = int(r.get("time") or 0)
            from datetime import datetime
            time_iso = datetime.utcfromtimestamp(t_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S") if t_ms else ""
            w.writerow({
                "time": t_ms,
                "time_iso": time_iso,
                "symbol": r.get("symbol", ""),
                "income": r.get("income", ""),
                "asset": r.get("asset", ""),
                "tradeId": r.get("tradeId", ""),
                "info": r.get("info", ""),
            })
    print(f"Wrote {len(rows)} rows to {path}")


def _read_existing_funding_rate_csv(path: Path) -> list[dict]:
    """
    Read an existing per-symbol funding rate CSV (if any).

    Returns a list of dicts sorted by fundingTime (ascending).
    """
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(dict(r))
    except Exception as e:
        print(f"Warning: failed to read existing funding rate CSV {path}: {e}", file=sys.stderr)
        return []
    def _key(row: dict) -> int:
        try:
            return int(row.get("fundingTime") or 0)
        except (TypeError, ValueError):
            return 0
    rows.sort(key=_key)
    return rows


def _append_funding_rate_rows(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    """
    Merge new funding rate rows into existing, de-duplicating by fundingTime.
    """
    if not existing:
        base = []
        last_ts = None
    else:
        base = list(existing)
        try:
            last_ts = int(base[-1].get("fundingTime") or 0)
        except (TypeError, ValueError):
            last_ts = None
    for r in new_rows:
        try:
            ts = int(r.get("fundingTime") or 0)
        except (TypeError, ValueError):
            ts = None
        if ts is None:
            continue
        if last_ts is not None and ts <= last_ts:
            continue
        base.append({
            "symbol": r.get("symbol", ""),
            "fundingRate": r.get("fundingRate", ""),
            "fundingTime": r.get("fundingTime", ""),
            "markPrice": r.get("markPrice", ""),
        })
        last_ts = ts if last_ts is None or ts > last_ts else last_ts
    return base


def _process_symbol_funding_rate(
    symbol: str,
    days: int | None,
    limit: int,
    out_dir: Path,
    append: bool,
) -> None:
    """
    Fetch funding rate history for a single symbol and write/append its CSV.

    - When append=False, fetch last N days (if days is set) or up to `limit` rows and overwrite.
    - When append=True and CSV exists, only fetch rows strictly after the last fundingTime.
    """
    from datetime import datetime, timedelta

    symbol = symbol.upper() if not symbol.upper().endswith("USDT") else symbol.upper()
    out_path = out_dir / f"funding_rate_history_{symbol}.csv"
    out_dir.mkdir(parents=True, exist_ok=True)

    existing_rows: list[dict] = []
    start_ms: int | None = None
    end_ms: int | None = None

    now_ms = int(datetime.utcnow().timestamp() * 1000)
    end_ms = now_ms

    if append and out_path.exists():
        existing_rows = _read_existing_funding_rate_csv(out_path)
        if existing_rows:
            try:
                last_ts = int(existing_rows[-1].get("fundingTime") or 0)
            except (TypeError, ValueError):
                last_ts = None
            if last_ts:
                start_ms = last_ts + 1
    if start_ms is None and days is not None:
        start_ms = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)

    # Fetch from Binance with basic rate-limit handling
    try:
        rows = fetch_funding_rate_history(
            symbol,
            start_time=start_ms,
            end_time=end_ms,
            limit=limit,
        )
    except Exception as e:
        print(f"Funding rate fetch failed for {symbol}: {e}", file=sys.stderr)
        return

    merged_rows: list[dict]
    if append and existing_rows:
        merged_rows = _append_funding_rate_rows(existing_rows, rows)
    else:
        merged_rows = []
        for r in rows:
            merged_rows.append({
                "symbol": r.get("symbol", ""),
                "fundingRate": r.get("fundingRate", ""),
                "fundingTime": r.get("fundingTime", ""),
                "markPrice": r.get("markPrice", ""),
            })

    write_funding_rate_csv(merged_rows, out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Query Binance USD-M funding history APIs")
    ap.add_argument("--rate", action="store_true", help="Fetch funding rate history (public)")
    ap.add_argument("--income", action="store_true", help="Fetch funding fee income history (signed)")
    ap.add_argument("--symbol", default="BTCUSDT", help="Symbol for rate history (default: BTCUSDT)")
    ap.add_argument(
        "--all-from-market-data",
        action="store_true",
        help="When set with --rate, fetch funding rate history for all currencies from data/binance/market_data.csv",
    )
    ap.add_argument(
        "--all-from-positions",
        action="store_true",
        help="When set with --rate, fetch funding rate history for all coins in data/binance/positions.csv",
    )
    ap.add_argument("--limit", type=int, default=500, help="Max records (default 500, max 1000)")
    ap.add_argument("--days", type=int, default=None, help="Last N days (sets start time; overrides --start)")
    ap.add_argument("--start", type=int, default=None, help="Start time (ms)")
    ap.add_argument("--end", type=int, default=None, help="End time (ms)")
    ap.add_argument("--out-rate", default=None, help="Output CSV for funding rate (default: data/binance/funding_rate_history.csv)")
    ap.add_argument("--out-income", default=None, help="Output CSV for funding fee income (default: data/binance/funding_fee_income.csv)")
    ap.add_argument(
        "--per-symbol-out-dir",
        default=None,
        help="Directory for per-symbol funding rate CSVs when using --all-from-positions or --all-from-market-data "
             "(default: data/binance/funding/)",
    )
    ap.add_argument(
        "--append",
        action="store_true",
        help="Append to per-symbol funding history (skip existing fundingTime values) instead of overwriting",
    )
    ap.add_argument(
        "--per-symbol-sleep",
        type=float,
        default=0.5,
        help="Sleep seconds between symbols when using --all-from-market-data (default: 0.5s)",
    )
    args = ap.parse_args()

    if not args.rate and not args.income:
        ap.print_help()
        print("\nUse --rate and/or --income to fetch.", file=sys.stderr)
        return 1

    if not requests:
        print("Install requests: pip install requests", file=sys.stderr)
        return 1

    # 1) Funding rate history (public)
    if args.rate:
        if args.all_from_positions or args.all_from_market_data:
            # Multi-symbol mode: read symbols from positions.csv or market_data.csv and write per-symbol CSVs.
            symbols: list[str] = []
            if args.all_from_positions:
                positions_path = DATA_BINANCE / "positions.csv"
                if not positions_path.exists():
                    print(f"positions.csv not found at {positions_path}", file=sys.stderr)
                    return 1
                try:
                    with open(positions_path, newline="") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            coin = (row.get("coin") or "").strip()
                            if not coin:
                                continue
                            sym = coin.upper()
                            if not sym.endswith("USDT"):
                                sym = sym + "USDT"
                            symbols.append(sym)
                except Exception as e:
                    print(f"Failed to read positions.csv: {e}", file=sys.stderr)
                    return 1
                symbols = sorted(set(symbols))
                label = "positions"
            else:
                market_data_path = DATA_BINANCE / "market_data.csv"
                if not market_data_path.exists():
                    print(f"market_data.csv not found at {market_data_path}", file=sys.stderr)
                    return 1
                try:
                    with open(market_data_path, newline="") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            cur = (row.get("currency") or "").strip()
                            if not cur:
                                continue
                            sym = cur.upper()
                            if not sym.endswith("USDT"):
                                sym = sym + "USDT"
                            symbols.append(sym)
                except Exception as e:
                    print(f"Failed to read market_data.csv: {e}", file=sys.stderr)
                    return 1
                symbols = sorted(set(symbols))
                label = "market_data"
            out_dir = Path(args.per_symbol_out_dir) if args.per_symbol_out_dir else DATA_BINANCE / "funding"
            print(f"Fetching funding rate history for {len(symbols)} symbols (from {label}) into {out_dir} ...")
            for i, sym in enumerate(symbols, 1):
                print(f"[{i}/{len(symbols)}] {sym}")
                _process_symbol_funding_rate(
                    sym,
                    days=args.days,
                    limit=args.limit,
                    out_dir=out_dir,
                    append=bool(args.append),
                )
                # Simple pacing to be gentle with rate limits
                if args.per_symbol_sleep > 0:
                    time.sleep(args.per_symbol_sleep)
        else:
            # Single-symbol mode (backwards compatible with previous behavior).
            start_ms = args.start
            end_ms = args.end
            if args.days is not None:
                end_ms = end_ms or int(datetime.utcnow().timestamp() * 1000)
                start_ms = int((datetime.utcnow() - timedelta(days=args.days)).timestamp() * 1000)
            try:
                rate_rows = fetch_funding_rate_history(
                    args.symbol,
                    start_time=start_ms,
                    end_time=end_ms,
                    limit=args.limit,
                )
                print(f"Funding rate history ({args.symbol}): {len(rate_rows)} records")
                if rate_rows:
                    print(f"  Latest: fundingRate={rate_rows[-1].get('fundingRate')} fundingTime={rate_rows[-1].get('fundingTime')}")
                out = Path(args.out_rate) if args.out_rate else DATA_BINANCE / "funding_rate_history.csv"
                write_funding_rate_csv(rate_rows, out)
            except Exception as e:
                print(f"Funding rate fetch failed: {e}", file=sys.stderr)
                return 1

    # 2) Funding fee income history (signed)
    if args.income:
        api_key = BINANCE_API_KEY
        api_secret = BINANCE_API_SECRET
        if not api_key or not api_secret:
            print("Set BINANCE_API_KEY and BINANCE_API_SECRET for --income.", file=sys.stderr)
            return 1
        try:
            income_rows = fetch_funding_fee_income_history(
                api_key, api_secret,
                symbol=args.symbol if args.rate else None,
                start_time=start_ms,
                end_time=end_ms,
                limit=args.limit,
            )
            print(f"Funding fee income history: {len(income_rows)} records")
            if income_rows:
                last = income_rows[0]
                print(f"  Latest: time={last.get('time')} symbol={last.get('symbol')} income={last.get('income')}")
            out = Path(args.out_income) if args.out_income else DATA_BINANCE / "funding_fee_income.csv"
            write_funding_fee_income_csv(income_rows, out)
        except Exception as e:
            print(f"Funding fee income fetch failed: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
