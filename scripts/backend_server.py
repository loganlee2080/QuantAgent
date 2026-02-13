#!/usr/bin/env python3
"""
Simple local backend for the CryptoQuant frontend.

- Serves Binance positions and account summary from CSV files.
- Accepts order submissions from the UI and appends them to a CSV for auditing,
  which can then be executed via binance_trade_api.py.

Run (from project root, with venv activated):

    python scripts/backend_server.py

Then point the React app at http://localhost:8000 (default).
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import math
import re
import subprocess
import sys
import threading
import time as time_module
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, TypedDict

from flask import Flask, Response, jsonify, request, send_from_directory

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

try:
    # Optional: only needed if you want Claude integration.
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment]

# Optional: LangChain-based server-side chat memory
try:
    from langchain.memory import FileChatMessageHistory
    from langchain_core.messages import HumanMessage, AIMessage
except Exception:  # pragma: no cover - optional dependency
    FileChatMessageHistory = None  # type: ignore[assignment]
    HumanMessage = None  # type: ignore[assignment]
    AIMessage = None  # type: ignore[assignment]

from env_manager import (
    ROOT,
    DATA_BINANCE,
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_PUBLIC_BASE,
    BINANCE_SPOT_BASE,
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    COINGLASS_BASE,
    COINGLASS_API_KEY,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    BACKEND_PORT,
    RUN_FETCH_LOOPS,
    CRAWL_POSITIONS_INTERVAL_SECONDS,
    ORDER_HISTORY_REFRESH_SECONDS,
    FUNDING_ESTIMATE_INTERVAL_SECONDS,
    MARKET_DATA_INTERVAL_SECONDS,
    FUNDING_RATE_HISTORY_INTERVAL_SECONDS,
    FUNDING_MARKET_DATA_INTERVAL_SECONDS,
    FUNDING_FEE_HISTORY_INTERVAL_SECONDS,
    FUNDING_FEE_HISTORY_FIRST_DAYS,
)

POSITIONS_PATH = DATA_BINANCE / "positions.csv"
SUMMARY_PATH = DATA_BINANCE / "summary.csv"
UI_ORDERS_PATH = DATA_BINANCE / "orders" / "ui_orders.csv"
ORDER_CLOSE_TEMPLATE_PATH = DATA_BINANCE / "orders" / "order_close_template.csv"
ORDER_META_PATH = DATA_BINANCE / "orders" / "order_meta.csv"  # Global order config (order_meta) used when placing orders
ORDER_TEMPLATE_PATH = DATA_BINANCE / "orders" / "order_template.csv"
AI_SUGGESTIONS_PATH = DATA_BINANCE / "orders" / "ai_suggestions.jsonl"
ORDER_HISTORY_PATH = DATA_BINANCE / "orders" / "order_history.csv"
BINANCE_ORDER_HISTORY_CSV = DATA_BINANCE / "orders" / "binance-order-history.csv"
ORDER_STATUS_AUDIT_PATH = DATA_BINANCE / "orders" / "order_status_audit.csv"
CLAUDE_CONFIG_PATH = DATA_BINANCE / "orders" / "claude_config.json"
MARKET_DATA_PATH = DATA_BINANCE / "market_data.csv"
MARKET_DATA_LABELED_PATH = DATA_BINANCE / "backup" / "market_data_labeled.csv"
FUNDING_FEE_HISTORY_PATH = DATA_BINANCE / "funding_fee_history.csv"

# Claude API model IDs: Opus 4.6, Sonnet 4.5, Haiku 4.5 (https://platform.claude.com/docs/en/about-claude/models/overview).
# Default is Haiku 4.5.
CLAUDE_MODELS = [
    "claude-opus-4-6",              # Claude Opus 4.6
    "claude-sonnet-4-5-20250929",   # Claude Sonnet 4.5
    "claude-haiku-4-5-20251001",    # Claude Haiku 4.5 (default)
]
CLAUDE_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _claude_model_or_default(model: str) -> str:
    """Return model if it's in CLAUDE_MODELS, else CLAUDE_DEFAULT_MODEL."""
    return model if model in CLAUDE_MODELS else CLAUDE_DEFAULT_MODEL

_positions_crawler_thread: Optional[threading.Thread] = None
_positions_crawler_stop = threading.Event()
_order_history_refresh_thread: Optional[threading.Thread] = None
_order_history_refresh_stop = threading.Event()
_funding_estimate_thread: Optional[threading.Thread] = None
_funding_estimate_stop = threading.Event()
_market_data_thread: Optional[threading.Thread] = None
_market_data_stop = threading.Event()
# symbol -> { "fundingRate72hAvgDay", "fundingRateLatestDay" } (decimal strings, per-day rate)
_funding_rate_estimates: dict = {}
_funding_rate_estimates_lock = threading.Lock()

_funding_rate_history_thread: Optional[threading.Thread] = None
_funding_rate_history_stop = threading.Event()


def _positions_crawler_loop() -> None:
    """
    Background loop that runs crawl_binance_usdm_positions.py every N seconds.
    Uses the same Python interpreter as this backend.
    """
    script_path = ROOT / "scripts" / "crawl_binance_usdm_positions.py"
    while not _positions_crawler_stop.is_set():
        try:
            sys.stderr.write("[backend_server] Running crawl_binance_usdm_positions.py\n")
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                sys.stderr.write(
                    f"[backend_server] crawler exited with {proc.returncode}:\n"
                    f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n"
                )
        except Exception:
            sys.stderr.write("[backend_server] Exception in positions crawler loop:\n")
            traceback.print_exc()
        # Wait with stop-checks
        if _positions_crawler_stop.wait(CRAWL_POSITIONS_INTERVAL_SECONDS):
            break


def _get_funding_symbols() -> List[str]:
    """Symbols to fetch funding rate for (e.g. BTCUSDT). From positions.csv coins or fallback."""
    if POSITIONS_PATH.exists():
        try:
            with open(POSITIONS_PATH, newline="") as f:
                reader = csv.DictReader(f)
                coins = [(r.get("coin") or "").strip() for r in reader if (r.get("coin") or "").strip()]
            if coins:
                # Deduplicate while preserving order
                seen = set()
                symbols: List[str] = []
                for c in coins:
                    sym = c + "USDT" if not c.endswith("USDT") else c
                    if sym not in seen:
                        seen.add(sym)
                        symbols.append(sym)
                return symbols
        except Exception:
            pass
    return ["BTCUSDT", "ETHUSDT"]


def _load_local_funding_rates(symbol: str, max_rows: int = 12) -> List[float]:
    """
    Load recent fundingRate values for a symbol from local CSV history.

    - Reads data/binance/funding/funding_rate_history_<symbol>.csv
    - Returns up to `max_rows` most recent fundingRate values as floats (newest first).
    """
    csv_path = DATA_BINANCE / "funding" / f"funding_rate_history_{symbol}.csv"
    if not csv_path.exists():
        return []
    rows: List[dict] = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(dict(r))
    except Exception as e:
        sys.stderr.write(f"[backend_server] Failed to read local funding history {csv_path}: {e}\n")
        return []

    def _key(row: dict) -> int:
        try:
            return int(row.get("fundingTime") or 0)
        except (TypeError, ValueError):
            return 0

    rows.sort(key=_key, reverse=True)  # newest first
    rates: List[float] = []
    for r in rows[:max_rows]:
        try:
            rate = float(r.get("fundingRate") or 0)
        except (TypeError, ValueError):
            continue
        rates.append(rate)
    return rates


def _fetch_funding_rate_estimates() -> None:
    """
    Compute funding rate estimates from local CSV history instead of live API.

    For each symbol from positions.csv:
      - Read recent funding rates from data/binance/funding/funding_rate_history_<symbol>.csv
      - Compute:
          fundingRate72hAvgDay: average of last 9 (72h) funding rates * 3 (day rate)
          fundingRateLatestDay: most recent funding rate * 3 (day rate)
      - If no local data is available for a symbol, it is skipped.
    """
    symbols = _get_funding_symbols()
    if not symbols:
        return

    new_estimates: dict = {}
    for symbol in symbols:
        rates = _load_local_funding_rates(symbol, max_rows=12)
        if not rates:
            # No local history yet (e.g. user never opened funding chart); skip quietly.
            continue

        # Latest (first element) -> day rate = * 3
        latest_day = rates[0] * 3.0
        # 72h average: use last 9 if available, else all
        n = min(9, len(rates))
        window = rates[:n] if n else rates
        avg_8h = sum(window) / len(window) if window else 0.0
        avg_day = avg_8h * 3.0
        new_estimates[symbol] = {
            "fundingRate72hAvgDay": f"{avg_day:.8f}".rstrip("0").rstrip("."),
            "fundingRateLatestDay": f"{latest_day:.8f}".rstrip("0").rstrip("."),
        }

    with _funding_rate_estimates_lock:
        _funding_rate_estimates.clear()
        _funding_rate_estimates.update(new_estimates)
    if new_estimates:
        sys.stderr.write(
            f"[backend_server] Funding rate estimates updated from local CSV for {len(new_estimates)} symbols\n"
        )


def _update_funding_rate_history_for_symbol(
    symbol: str,
    out_dir: Path,
    days_if_empty: int = 7,
) -> None:
    """
    Fetch funding rate history for a single symbol and write/append its CSV.

    - If the CSV already exists, only fetch rows strictly after the last fundingTime and append.
    - If the CSV does not exist yet, fetch roughly the last `days_if_empty` days.
    """
    if not requests:
        return
    base = BINANCE_FUTURES_PUBLIC_BASE
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"funding_rate_history_{symbol}.csv"

    existing_rows: list[dict] = []
    start_ms: Optional[int] = None
    end_ms: int = int(time_module.time() * 1000)

    # If we already have a CSV, append only new rows (fundingTime strictly greater than last one)
    if out_path.exists():
        try:
            with open(out_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    existing_rows.append(dict(r))
        except Exception as e:
            sys.stderr.write(f"[backend_server] Failed to read existing funding history {out_path}: {e}\n")
            existing_rows = []
        if existing_rows:
            try:
                last_ts = int(existing_rows[0].get("fundingTime") or 0)
            except (TypeError, ValueError):
                last_ts = 0
            # CSVs produced by our scripts are sorted desc; ensure we really have latest.
            for r in existing_rows:
                try:
                    ts = int(r.get("fundingTime") or 0)
                except (TypeError, ValueError):
                    continue
                if ts > last_ts:
                    last_ts = ts
            if last_ts > 0:
                start_ms = last_ts + 1

    # If no existing data, pull roughly the last N days
    if start_ms is None and days_if_empty > 0:
        start_ms = int((datetime.utcnow() - timedelta(days=days_if_empty)).timestamp() * 1000)

    params = {"symbol": symbol, "limit": 1000}
    if start_ms is not None:
        params["startTime"] = start_ms
    params["endTime"] = end_ms

    try:
        r = requests.get(f"{base}/fapi/v1/fundingRate", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        sys.stderr.write(f"[backend_server] Funding history fetch failed for {symbol}: {e}\n")
        return

    if not isinstance(data, list) or not data:
        return

    # Normalize new rows
    new_rows: list[dict] = []
    for item in data:
        new_rows.append(
            {
                "symbol": str(item.get("symbol") or symbol),
                "fundingRate": str(item.get("fundingRate") or ""),
                "fundingTime": str(item.get("fundingTime") or ""),
                "markPrice": str(item.get("markPrice") or ""),
            }
        )

    # Merge with existing (de-duplicate by fundingTime)
    by_ts: dict[int, dict] = {}
    for r in existing_rows:
        try:
            ts = int(r.get("fundingTime") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        by_ts[ts] = r
    for r in new_rows:
        try:
            ts = int(r.get("fundingTime") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        by_ts[ts] = r

    if not by_ts:
        return

    # Sort descending so newest first (what /api/funding-rate-history expects)
    ordered = [
        by_ts[ts]
        for ts in sorted(by_ts.keys(), reverse=True)
    ]
    try:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["symbol", "fundingRate", "fundingTime", "markPrice"])
            writer.writeheader()
            writer.writerows(ordered)
        sys.stderr.write(
            f"[backend_server] Funding history updated for {symbol}: {len(new_rows)} new rows, total {len(ordered)}\n"
        )
    except Exception as e:
        sys.stderr.write(f"[backend_server] Failed to write funding history {out_path}: {e}\n")


def _funding_rate_history_loop() -> None:
    """
    Background loop: fetch funding rate history CSVs for all symbols in positions.csv.

    - Runs once on start, then every FUNDING_RATE_HISTORY_INTERVAL_SECONDS (default hourly).
    - Uses the same funding symbols as funding estimates (_get_funding_symbols).
    """
    out_dir = DATA_BINANCE / "funding"
    while not _funding_rate_history_stop.is_set():
        try:
            symbols = _get_funding_symbols()
            if symbols:
                sys.stderr.write(
                    f"[backend_server] Funding history: updating {len(symbols)} symbols into {out_dir}...\n"
                )
                for i, sym in enumerate(symbols, 1):
                    _update_funding_rate_history_for_symbol(sym, out_dir)
                    # Gentle pacing for Binance rate limits
                    time_module.sleep(0.4)
        except Exception:
            sys.stderr.write("[backend_server] Exception in funding history loop:\n")
            traceback.print_exc()
        if _funding_rate_history_stop.wait(FUNDING_RATE_HISTORY_INTERVAL_SECONDS):
            break
    sys.stderr.write("[backend_server] Funding history loop stopped.\n")


def _funding_estimate_loop() -> None:
    """Run on start, then every FUNDING_ESTIMATE_INTERVAL_SECONDS (default hourly)."""
    while not _funding_estimate_stop.is_set():
        try:
            _fetch_funding_rate_estimates()
        except Exception:
            traceback.print_exc()
        if _funding_estimate_stop.wait(FUNDING_ESTIMATE_INTERVAL_SECONDS):
            break
    sys.stderr.write("[backend_server] Funding estimate loop stopped.\n")


MARKET_DATA_FIELDS = [
    "currency",
    "maxLeverage",
    "markPrice",
    "pricePrecision",
    "fdv(USDT)",
    "maxCap(USDT)",
    "lastFundingRate",
    "lastFundingTime",
    "fundingTimesPerDay",
    "todayFundRate",
    "avgDayFundRate72h",
    "volume24h(USDT)",
    "priceChange24h(USDT)",
    "priceChange24h%(USDT)",
    "openInterest(USDT)",
    "lastUpdateTime",
    "spotEnabled",
]

# Binance USD-M: funding every 8h -> 3 times per day
FUNDING_TIMES_PER_DAY = 3
_funding_market_data_avg72h: dict = {}  # symbol -> avg day fund rate (72h) as string
_funding_market_data_lock = threading.Lock()
_funding_market_data_thread: Optional[threading.Thread] = None
_funding_market_data_stop = threading.Event()
_funding_fee_history_thread: Optional[threading.Thread] = None
_funding_fee_history_stop = threading.Event()


def _binance_signed_get_module(api_key: str, api_secret: str, path: str, params: Optional[dict] = None) -> Any:
    """Module-level signed GET for Binance USD-M (for use in background threads)."""
    if requests is None:
        raise RuntimeError("requests is required")
    params = dict(params or {})
    params["timestamp"] = int(time_module.time() * 1000)
    qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{BINANCE_FUTURES_BASE}{path}?{qs}&signature={sig}"
    r = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=30)
    r.raise_for_status()
    return r.json()


FUNDING_FEE_HISTORY_CSV_FIELDS = ["time", "time_iso", "symbol", "income", "asset", "tradeId", "info"]


def _income_row_to_csv_row(item: dict) -> dict:
    """Convert Binance income item to CSV row."""
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


def _sync_funding_fee_history_first(api_key: str, api_secret: str) -> None:
    """First sync: fetch last 90 days (24h windows) and write funding_fee_history.csv."""
    days = FUNDING_FEE_HISTORY_FIRST_DAYS
    now_ms = int(time_module.time() * 1000)
    window_ms = 24 * 60 * 60 * 1000
    start_ms = now_ms - days * window_ms
    all_rows: List[dict] = []
    for i in range(days):
        win_start = start_ms + i * window_ms
        win_end = min(win_start + window_ms - 1, now_ms)
        try:
            data = _binance_signed_get_module(
                api_key,
                api_secret,
                "/fapi/v1/income",
                {"incomeType": "FUNDING_FEE", "startTime": win_start, "endTime": win_end, "limit": 1000},
            )
        except Exception as e:
            sys.stderr.write(f"[backend_server] Funding fee history day {i}: {e}\n")
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            all_rows.append(_income_row_to_csv_row(item))
        time_module.sleep(0.2)
        if (i + 1) % 30 == 0:
            sys.stderr.write(f"[backend_server] Funding fee history first sync: {i + 1}/{days} days\n")
    all_rows.sort(key=lambda r: int(r["time"]))
    DATA_BINANCE.mkdir(parents=True, exist_ok=True)
    with open(FUNDING_FEE_HISTORY_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FUNDING_FEE_HISTORY_CSV_FIELDS)
        w.writeheader()
        w.writerows(all_rows)
    sys.stderr.write(f"[backend_server] Funding fee history first sync done: {len(all_rows)} rows -> {FUNDING_FEE_HISTORY_PATH}\n")


def _sync_funding_fee_history_hourly(api_key: str, api_secret: str) -> None:
    """Hourly: fetch latest funding fee (last 2h) and append new rows to CSV."""
    now_ms = int(time_module.time() * 1000)
    two_h_ms = 2 * 60 * 60 * 1000
    start_ms = now_ms - two_h_ms
    existing_max_time = 0
    if FUNDING_FEE_HISTORY_PATH.exists():
        try:
            with open(FUNDING_FEE_HISTORY_PATH, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t = row.get("time") or "0"
                    try:
                        existing_max_time = max(existing_max_time, int(t))
                    except ValueError:
                        pass
        except Exception:
            pass
    start_ms = max(start_ms, existing_max_time + 1) if existing_max_time else start_ms
    try:
        data = _binance_signed_get_module(
            api_key,
            api_secret,
            "/fapi/v1/income",
            {"incomeType": "FUNDING_FEE", "startTime": start_ms, "limit": 1000},
        )
    except Exception as e:
        sys.stderr.write(f"[backend_server] Funding fee history hourly: {e}\n")
        return
    if not isinstance(data, list) or not data:
        return
    new_rows = []
    for item in data:
        t_ms = int(item.get("time") or 0)
        if t_ms > existing_max_time:
            new_rows.append(_income_row_to_csv_row(item))
    if not new_rows:
        return
    new_rows.sort(key=lambda r: int(r["time"]))
    DATA_BINANCE.mkdir(parents=True, exist_ok=True)
    file_exists = FUNDING_FEE_HISTORY_PATH.exists()
    with open(FUNDING_FEE_HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FUNDING_FEE_HISTORY_CSV_FIELDS)
        if not file_exists:
            w.writeheader()
        w.writerows(new_rows)
    sys.stderr.write(f"[backend_server] Funding fee history hourly: appended {len(new_rows)} rows\n")


def _funding_fee_history_loop() -> None:
    """Hourly append of latest funding fee to funding_fee_history.csv. No 90-day sync on start (run scripts/fetch_funding_fee_90d.py manually)."""
    api_key = BINANCE_API_KEY
    api_secret = BINANCE_API_SECRET
    if not api_key or not api_secret:
        sys.stderr.write("[backend_server] Funding fee history: no API key/secret, skipping.\n")
        return
    while not _funding_fee_history_stop.is_set():
        try:
            _sync_funding_fee_history_hourly(api_key, api_secret)
        except Exception:
            traceback.print_exc()
        if _funding_fee_history_stop.wait(FUNDING_FEE_HISTORY_INTERVAL_SECONDS):
            break
    sys.stderr.write("[backend_server] Funding fee history loop stopped.\n")


def _update_funding_for_market_data() -> None:
    """
    Fetch last 9 funding rates (72h) per symbol, compute avg day rate = avg * 3.
    Updates _funding_market_data_avg72h. Run hourly and on service start.
    """
    if not requests:
        return
    base = BINANCE_FUTURES_PUBLIC_BASE
    try:
        r = requests.get(f"{base}/fapi/v1/exchangeInfo", timeout=30)
        r.raise_for_status()
        symbols = [
            str(s["symbol"])
            for s in (r.json().get("symbols") or [])
            if s.get("contractType") == "PERPETUAL" and str(s.get("symbol", "")).endswith("USDT")
        ]
    except Exception as e:
        sys.stderr.write(f"[backend_server] Funding-for-market-data exchangeInfo: {e}\n")
        return
    new_avg72h: dict = {}
    n = len(symbols)
    progress_interval = max(1, n // 10)
    for i, sym in enumerate(symbols):
        try:
            r = requests.get(
                f"{base}/fapi/v1/fundingRate",
                params={"symbol": sym, "limit": 9},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json() or []
            rates = [float(x.get("fundingRate", 0) or 0) for x in data]
            if rates:
                avg_8h = sum(rates) / len(rates)
                avg_day = avg_8h * FUNDING_TIMES_PER_DAY
                new_avg72h[sym] = f"{avg_day:.8f}".rstrip("0").rstrip(".")
        except Exception:
            pass
        if (i + 1) % progress_interval == 0 or (i + 1) == n:
            sys.stderr.write(f"[backend_server] Funding 72h: {i + 1}/{n} symbols\n")
        time_module.sleep(0.12)
    with _funding_market_data_lock:
        _funding_market_data_avg72h.clear()
        _funding_market_data_avg72h.update(new_avg72h)
    sys.stderr.write(f"[backend_server] Funding 72h avg updated for {len(new_avg72h)} symbols\n")


def _funding_market_data_loop() -> None:
    """Run funding update for market_data on start, then every FUNDING_MARKET_DATA_INTERVAL_SECONDS (default 1h)."""
    while not _funding_market_data_stop.is_set():
        try:
            _update_funding_for_market_data()
        except Exception:
            traceback.print_exc()
        if _funding_market_data_stop.wait(FUNDING_MARKET_DATA_INTERVAL_SECONDS):
            break
    sys.stderr.write("[backend_server] Funding market data loop stopped.\n")


def _parse_leverage_brackets(bracket_list: list) -> dict:
    """Build symbol -> max leverage from leverageBracket response."""
    out: dict = {}
    for item in bracket_list:
        sym = item.get("symbol")
        if not sym:
            continue
        brackets = item.get("brackets") or []
        max_lev = 0
        for b in brackets:
            L = b.get("initialLeverage")
            if L is not None:
                try:
                    max_lev = max(max_lev, int(L))
                except (TypeError, ValueError):
                    pass
        if max_lev:
            out[str(sym)] = str(max_lev)
    return out


def _fetch_and_write_market_data() -> None:
    """
    Fetch all Binance USD-M perpetual symbols and write market_data.csv.
    Uses public API for exchangeInfo, premiumIndex, ticker/24hr, openInterest;
    optional signed leverageBracket when API key is set.
    Labels are stored separately in data/binance/backup/market_data_labeled.csv (user-edited).
    """
    if not requests:
        return
    base = BINANCE_FUTURES_PUBLIC_BASE
    t_start = time_module.time()
    sys.stderr.write("[backend_server] Market data: starting fetch (exchangeInfo, premiumIndex, ticker/24hr, openInterest)...\n")
    # 1) Exchange info: all USDT perpetual symbols
    try:
        r = requests.get(f"{base}/fapi/v1/exchangeInfo", timeout=30)
        r.raise_for_status()
        data = r.json()
        symbols_raw = data.get("symbols") or []
        # Build symbol list and per-symbol price precision (from PRICE_FILTER.tickSize)
        symbols = []
        price_precision_by_sym: dict = {}
        for s in symbols_raw:
            sym = str(s.get("symbol", "") or "")
            if not sym:
                continue
            if s.get("contractType") != "PERPETUAL" or not sym.endswith("USDT"):
                continue
            symbols.append(sym)
            tick_size = None
            for flt in s.get("filters", []) or []:
                if flt.get("filterType") == "PRICE_FILTER":
                    tick_size = flt.get("tickSize")
                    break
            prec_str = ""
            if tick_size is not None:
                step = str(tick_size).strip()
                if "." in step:
                    frac = step.rstrip("0").split(".")[1]
                    prec_str = str(len(frac))
                else:
                    prec_str = "0"
            price_precision_by_sym[sym] = prec_str
        sys.stderr.write(f"[backend_server] Market data: exchangeInfo ok, {len(symbols)} USDT perpetual symbols\n")
    except Exception as e:
        sys.stderr.write(f"[backend_server] Market data exchangeInfo: {e}\n")
        return
    if not symbols:
        return
    # 1b) Spot exchangeInfo: set of symbols enabled for SPOT (e.g. BTCUSDT)
    spot_symbols: set = set()
    try:
        r_spot = requests.get(f"{BINANCE_SPOT_BASE}/api/v3/exchangeInfo", timeout=30)
        r_spot.raise_for_status()
        spot_data = r_spot.json()
        for s in spot_data.get("symbols") or []:
            sym = s.get("symbol")
            if not sym:
                continue
            perms = s.get("permissions") or []
            if "SPOT" in perms and (s.get("status") or "").upper() == "TRADING":
                spot_symbols.add(str(sym))
        sys.stderr.write(f"[backend_server] Market data: spot exchangeInfo ok ({len(spot_symbols)} SPOT symbols)\n")
    except Exception as e:
        sys.stderr.write(f"[backend_server] Market data spot exchangeInfo: {e}\n")
    # 2) Premium index (mark price, funding) — all symbols in one call
    premium_by_sym: dict = {}
    try:
        r = requests.get(f"{base}/fapi/v1/premiumIndex", timeout=30)
        r.raise_for_status()
        for item in r.json():
            sym = item.get("symbol")
            if sym:
                premium_by_sym[str(sym)] = item
        sys.stderr.write(f"[backend_server] Market data: premiumIndex ok ({len(premium_by_sym)} symbols)\n")
    except Exception as e:
        sys.stderr.write(f"[backend_server] Market data premiumIndex: {e}\n")
    # 3) 24h ticker — all symbols in one call
    ticker_by_sym: dict = {}
    try:
        r = requests.get(f"{base}/fapi/v1/ticker/24hr", timeout=30)
        r.raise_for_status()
        for item in r.json():
            sym = item.get("symbol")
            if sym:
                ticker_by_sym[str(sym)] = item
        sys.stderr.write(f"[backend_server] Market data: ticker/24hr ok ({len(ticker_by_sym)} symbols)\n")
    except Exception as e:
        sys.stderr.write(f"[backend_server] Market data ticker/24hr: {e}\n")
    # 4) Max leverage (optional, signed)
    leverage_by_sym: dict = {}
    api_key = BINANCE_API_KEY
    api_secret = BINANCE_API_SECRET
    if api_key and api_secret:
        try:
            params = {"timestamp": int(time_module.time() * 1000)}
            qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
            url = f"{BINANCE_FUTURES_BASE}/fapi/v1/leverageBracket?{qs}&signature={sig}"
            r = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=15)
            r.raise_for_status()
            leverage_by_sym = _parse_leverage_brackets(r.json())
            sys.stderr.write(f"[backend_server] Market data: leverageBracket ok ({len(leverage_by_sym)} symbols)\n")
        except Exception:
            pass  # leave max leverage empty if signed call fails
    else:
        sys.stderr.write("[backend_server] Market data: no API key → maxLeverage left empty\n")
    # 5) Open interest per symbol (throttle to avoid 418)
    oi_by_sym: dict = {}
    n_sym = len(symbols)
    progress_interval = max(1, n_sym // 10)  # log every ~10%
    for i, sym in enumerate(symbols):
        try:
            r = requests.get(f"{base}/fapi/v1/openInterest", params={"symbol": sym}, timeout=10)
            r.raise_for_status()
            oi_by_sym[sym] = r.json()
        except Exception:
            pass
        if (i + 1) % progress_interval == 0 or (i + 1) == n_sym:
            pct = 100 * (i + 1) // n_sym
            sys.stderr.write(f"[backend_server] Market data: openInterest {i + 1}/{n_sym} ({pct}%)\n")
        time_module.sleep(0.12)  # ~8 req/s
    # Read existing CSV to preserve funding (and other) fields when new value is empty (update in place)
    existing_by_currency: dict = {}
    if MARKET_DATA_PATH.exists():
        try:
            with open(MARKET_DATA_PATH, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    cur = (row.get("currency") or "").strip().upper()
                    if cur:
                        existing_by_currency[cur] = dict(row)
        except Exception:
            pass
    # Build rows
    now_ts = int(time_module.time())
    rows: List[dict] = []
    for sym in symbols:
        prem = premium_by_sym.get(sym) or {}
        tick = ticker_by_sym.get(sym) or {}
        oi_data = oi_by_sym.get(sym) or {}
        mark_price_str = str(prem.get("markPrice") or "").strip() or ""
        last_funding_rate = str(prem.get("lastFundingRate") or "").strip() or ""
        last_funding_time_ms = prem.get("lastFundingTime")
        if last_funding_time_ms is not None:
            try:
                last_funding_time = str(int(last_funding_time_ms) // 1000)
            except (TypeError, ValueError):
                last_funding_time = ""
        else:
            last_funding_time = ""
        volume_24h = str(tick.get("quoteVolume") or "").strip() or ""  # USDT
        price_change_24h = str(tick.get("priceChange") or "").strip() or ""  # USDT
        price_change_pct = str(tick.get("priceChangePercent") or "").strip() or ""  # for display as %
        oi_contracts = oi_data.get("openInterest")
        if oi_contracts is not None and mark_price_str:
            try:
                oi_usdt = float(oi_contracts) * float(mark_price_str)
                open_interest_usdt = f"{oi_usdt:.2f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                open_interest_usdt = ""
        else:
            open_interest_usdt = str(oi_contracts).strip() if oi_contracts else ""
        # Store full futures symbol (e.g. BTCUSDT) so frontend can display full pair;
        # callers can derive base coin by stripping trailing 'USDT' if needed.
        currency = sym
        cur_upper = currency.upper().replace("USDT", "")
        existing = existing_by_currency.get(cur_upper) or {}
        # todayFundRate = last funding rate * funding times per day (implied daily rate)
        today_fund_rate = ""
        if last_funding_rate:
            try:
                today_fund_rate = f"{float(last_funding_rate) * FUNDING_TIMES_PER_DAY:.8f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                pass
        with _funding_market_data_lock:
            avg72h = _funding_market_data_avg72h.get(sym, "")
        # Preserve existing funding-related values when new value is empty (update in place)
        if not last_funding_rate and existing.get("lastFundingRate"):
            last_funding_rate = (existing.get("lastFundingRate") or "").strip()
        if not last_funding_time and existing.get("lastFundingTime"):
            last_funding_time = (existing.get("lastFundingTime") or "").strip()
        if not today_fund_rate and existing.get("todayFundRate"):
            today_fund_rate = (existing.get("todayFundRate") or "").strip()
        if not avg72h and existing.get("avgDayFundRate72h"):
            avg72h = (existing.get("avgDayFundRate72h") or "").strip()
        funding_times_per_day = str(FUNDING_TIMES_PER_DAY)
        if existing.get("fundingTimesPerDay"):
            funding_times_per_day = (existing.get("fundingTimesPerDay") or "").strip() or funding_times_per_day
        spot_enabled = "true" if sym in spot_symbols else "false"
        if not spot_symbols and existing.get("spotEnabled"):
            spot_enabled = (existing.get("spotEnabled") or "").strip() or spot_enabled
        fdv = (existing.get("fdv(USDT)") or "").strip()
        max_cap = (existing.get("maxCap(USDT)") or "").strip()
        rows.append({
            "currency": currency,
            "maxLeverage": leverage_by_sym.get(sym, ""),
            "markPrice": mark_price_str,
            "pricePrecision": price_precision_by_sym.get(sym, ""),
            "fdv(USDT)": fdv,
            "maxCap(USDT)": max_cap,
            "lastFundingRate": last_funding_rate,
            "lastFundingTime": last_funding_time,
            "fundingTimesPerDay": funding_times_per_day,
            "todayFundRate": today_fund_rate,
            "avgDayFundRate72h": avg72h,
            "volume24h(USDT)": volume_24h,
            "priceChange24h(USDT)": price_change_24h,
            "priceChange24h%(USDT)": price_change_pct,
            "openInterest(USDT)": open_interest_usdt,
            "lastUpdateTime": str(now_ts),
            "spotEnabled": spot_enabled,
        })
    DATA_BINANCE.mkdir(parents=True, exist_ok=True)
    with open(MARKET_DATA_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MARKET_DATA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    duration_s = time_module.time() - t_start
    # Key info summary
    sys.stderr.write(
        "[backend_server] Market data CSV done | "
        f"symbols={len(rows)} | "
        f"premium={len(premium_by_sym)} ticker={len(ticker_by_sym)} oi={len(oi_by_sym)} | "
        f"maxLeverage={'yes' if leverage_by_sym else 'no'} | "
        f"duration={duration_s:.1f}s | "
        f"path={MARKET_DATA_PATH} | "
        f"next in {MARKET_DATA_INTERVAL_SECONDS}s\n"
    )


def _market_data_loop() -> None:
    """Run market data fetch every MARKET_DATA_INTERVAL_SECONDS (default 5 min)."""
    while not _market_data_stop.is_set():
        try:
            _fetch_and_write_market_data()
        except Exception:
            traceback.print_exc()
        if _market_data_stop.wait(MARKET_DATA_INTERVAL_SECONDS):
            break
    sys.stderr.write("[backend_server] Market data loop stopped.\n")


class OrderPayload(TypedDict, total=False):
    currency: str
    size_usdt: float
    direct: str  # "Long" or "Short"
    lever: int | None


@dataclass
class OrderRow:
    currency: str
    size_usdt: float
    direct: str
    lever: int | None = None

    def to_csv_row(self) -> dict:
        return {
            "currency": self.currency,
            "size_usdt": f"{self.size_usdt}",
            "direct": self.direct,
            "lever": "" if self.lever is None else str(self.lever),
        }


def create_app() -> Flask:
    app = Flask(__name__)

    # --- Helpers ---------------------------------------------------------

    def _read_positions() -> List[dict]:
        if not POSITIONS_PATH.exists():
            return []
        with open(POSITIONS_PATH, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Merge funding rate estimates (72h avg as day rate, latest as day rate)
        with _funding_rate_estimates_lock:
            estimates = dict(_funding_rate_estimates)
        for row in rows:
            coin = (row.get("coin") or "").strip()
            symbol = coin + "USDT" if coin and not coin.endswith("USDT") else coin
            est = estimates.get(symbol, {})
            row["fundingRate72hAvgDay"] = est.get("fundingRate72hAvgDay", "")
            row["fundingRateLatestDay"] = est.get("fundingRateLatestDay", "")
        return rows

    def _close_side_by_symbol() -> dict:
        """From positions, return symbol -> 'SELL' (close Long) or 'BUY' (close Short). Binance has no Close side."""
        out = {}
        for row in _read_positions():
            try:
                szi = float(row.get("szi") or 0)
            except (TypeError, ValueError):
                szi = 0.0
            if szi == 0:
                continue
            coin = (row.get("coin") or "").strip()
            direct = (row.get("direct") or "").strip().lower()
            if not coin or not direct:
                continue
            symbol = coin + "USDT" if not coin.endswith("USDT") else coin
            out[symbol] = "SELL" if direct == "long" else "BUY"
        return out

    def _resolve_direct_for_orders(rows: List[dict], *, currency_key: str = "currency") -> List[dict]:
        """Convert direct 'Close' to SELL/BUY using current positions; set reduce_only for script. Returns dicts with keys currency, size_usdt, direct, lever, reduce_only."""
        side_map = _close_side_by_symbol()
        fieldnames = ["currency", "size_usdt", "direct", "lever", "reduce_only"]
        resolved = []
        for r in rows:
            raw = r.get("currency") or r.get(currency_key) or ""
            size_val = r.get("size_usdt")
            if size_val is None or size_val == "":
                size_str = ""
            else:
                size_str = str(size_val).strip()
            row = {
                "currency": str(raw).strip().upper() if raw else "",
                "size_usdt": size_str,
                "direct": str(r.get("direct") or "").strip(),
                "lever": str(r.get("lever") or "").strip(),
                "reduce_only": str(r.get("reduce_only") or "").strip(),
            }
            direct = row["direct"]
            if direct.lower() == "close":
                cur = row["currency"]
                symbol = cur + "USDT" if cur and not cur.endswith("USDT") else cur
                row["direct"] = side_map.get(symbol, "SELL")
                row["reduce_only"] = "true"
            resolved.append(row)
        return resolved

    def _write_orders_audit_file(rows: List[dict], fieldnames: List[str]) -> Path:
        """Write rows to order_YYYYMMDD_HHMMss.csv in same dir as ui_orders; return path."""
        UI_ORDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        audit_path = UI_ORDERS_PATH.parent / f"order_{ts}.csv"
        with open(audit_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return audit_path

    def _read_summary_last_row() -> dict:
        if not SUMMARY_PATH.exists():
            return {}
        with open(SUMMARY_PATH, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows[-1] if rows else {}

    def _read_summary_history(limit: int = 200) -> list[dict]:
        """
        Return up to `limit` most recent summary rows, oldest first.

        Used for PNL (%) over time chart. Reads data/binance/summary.csv which is
        periodically appended by crawl_binance_usdm_positions.py.
        """
        if not SUMMARY_PATH.exists():
            return []
        with open(SUMMARY_PATH, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return []
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        return rows

    def _read_order_meta() -> List[dict]:
        if not ORDER_META_PATH.exists():
            return []
        with open(ORDER_META_PATH, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def _read_market_data() -> List[dict]:
        """Return market_data.csv rows (all Binance USD-M perpetuals). No labels; merge from backup file in API."""
        if not MARKET_DATA_PATH.exists():
            return []
        with open(MARKET_DATA_PATH, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _get_market_data_for_currency(currency: str) -> Optional[dict]:
        """
        Look up one market_data row by currency symbol.

        Accepts either base (e.g. TAO) or full symbol (e.g. TAOUSDT).
        Returns the first matching row or None.
        """
        cur = (currency or "").strip().upper()
        if not cur:
            return None
        symbol = cur if cur.endswith("USDT") else cur + "USDT"
        rows = _read_market_data()
        for row in rows:
            if str(row.get("currency") or "").strip().upper() == symbol:
                return row
        return None

    def _read_market_data_labels() -> dict:
        """Return currency_upper -> labels from data/binance/backup/market_data_labeled.csv."""
        out: dict = {}
        if not MARKET_DATA_LABELED_PATH.exists():
            return out
        try:
            with open(MARKET_DATA_LABELED_PATH, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    cur = (row.get("currency") or "").strip().upper()
                    if cur:
                        out[cur] = (row.get("labels") or "").strip()
        except Exception:
            pass
        return out

    def _append_ai_suggestion(
        user_message: str,
        claude_reply: str,
        orders_csv_block: Optional[str],
    ) -> None:
        """Append a single suggestion record to ai_suggestions.jsonl."""
        AI_SUGGESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "user_message": user_message,
            "claude_reply": claude_reply,
            "orders_csv": orders_csv_block,
        }
        with open(AI_SUGGESTIONS_PATH, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_last_ai_suggestion() -> Optional[dict]:
        """Return the last suggestion record from ai_suggestions.jsonl (or None)."""
        if not AI_SUGGESTIONS_PATH.exists():
            return None
        last_line = ""
        with open(AI_SUGGESTIONS_PATH, "r") as f:
            for line in f:
                if line.strip():
                    last_line = line
        if not last_line:
            return None
        try:
            return json.loads(last_line)
        except json.JSONDecodeError:
            return None

    ORDERS_FIELDNAMES = ["currency", "size_usdt", "direct", "lever", "reduce_only"]

    def _append_orders(rows: List[OrderRow]) -> None:
        dict_rows = [r.to_csv_row() for r in rows]
        resolved = _resolve_direct_for_orders(dict_rows, currency_key="currency")
        UI_ORDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_exists = UI_ORDERS_PATH.exists()
        with open(UI_ORDERS_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ORDERS_FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            for row in resolved:
                writer.writerow({k: row.get(k, "") for k in ORDERS_FIELDNAMES})
        _write_orders_audit_file(resolved, ORDERS_FIELDNAMES)

    def _append_order_history_entry(
        source: str,
        num_orders: int,
        returncode: int,
        stdout: str,
        stderr: str,
        input_csv: str,
    ) -> None:
        """Append a single execution record to order_history.csv."""
        ORDER_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_exists = ORDER_HISTORY_PATH.exists()
        fieldnames = ["timestamp", "source", "num_orders", "returncode", "stdout", "stderr", "input_csv"]
        now_ts = datetime.utcnow().isoformat() + "Z"
        with open(ORDER_HISTORY_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "timestamp": now_ts,
                    "source": source,
                    "num_orders": num_orders,
                    "returncode": returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "input_csv": input_csv,
                }
            )

    def _extract_base_currency_from_message(message: str) -> Optional[str]:
        """
        Heuristic: treat the last whitespace-separated token as symbol, accept BASE or BASEUSDT.
        Returns BASE (no USDT suffix) in upper-case, or None if not parseable.
        """
        tokens = (message or "").strip().replace(",", " ").split()
        if not tokens:
            return None
        last = tokens[-1].strip().upper().strip(".,;:!()")
        if not last:
            return None
        base = last
        if last.endswith("USDT"):
            base = last[:-4] or last
        if not base.isalpha():
            return None
        return base

    def _build_claude_client() -> Anthropic | None:  # type: ignore[name-defined]
        api_key = ANTHROPIC_API_KEY
        sys.stderr.write(f"[backend_server] Using Anthropic key: {api_key[:6]}...{api_key[-4:]}\n")
        if not api_key or Anthropic is None:
            return None
        try:
            # Masked log so we can confirm which key is in use without leaking it.
            sys.stderr.write(
                f"[backend_server] Using Anthropic key: {api_key[:6]}...{api_key[-4:]}\n"
            )
            return Anthropic(api_key=api_key)  # type: ignore[call-arg]
        except Exception:
            return None

    def _get_chat_history(session_id: str | None):
        """
        Return a LangChain FileChatMessageHistory for this session_id, if LangChain is available.

        Falls back to None if langchain is not installed, so the rest of the backend continues to work.
        """
        if not session_id or FileChatMessageHistory is None:
            return None
        history_dir = DATA_BINANCE / "chat_sessions"
        history_dir.mkdir(parents=True, exist_ok=True)
        path = history_dir / f"{session_id}.json"
        try:
            return FileChatMessageHistory(str(path))
        except Exception:
            return None

    def _append_history_message(session_id: str | None, user_message: str, ai_reply: str) -> None:
        """Persist a single user/assistant turn into LangChain chat history (if available)."""
        if (
            not session_id
            or FileChatMessageHistory is None
            or HumanMessage is None
            or AIMessage is None
        ):
            return
        history = _get_chat_history(session_id)
        if history is None:
            return
        try:
            history.add_message(HumanMessage(content=user_message))
            history.add_message(AIMessage(content=ai_reply))
        except Exception:
            # Never let memory issues break chat
            traceback.print_exc()

    def _render_history_for_prompt(session_id: str | None, max_turns: int = 10) -> str:
        """
        Render recent conversation history into plain text for inclusion in Claude prompt.

        This keeps the Anthropic call simple (single user message containing all context)
        while letting LangChain handle persistence.
        """
        if not session_id or FileChatMessageHistory is None:
            return ""
        history = _get_chat_history(session_id)
        if history is None:
            return ""
        try:
            messages = history.messages[-(max_turns * 2) :]  # user+assistant pairs
        except Exception:
            return ""
        if not messages:
            return ""
        lines: list[str] = []
        lines.append("Conversation history (most recent last):")
        for m in messages:
            role = getattr(m, "type", "") or getattr(m, "role", "")
            if role == "human":
                prefix = "User"
            elif role == "ai":
                prefix = "Assistant"
            else:
                prefix = role or "Message"
            content = getattr(m, "content", "") or ""
            lines.append(f"{prefix}: {content}")
        lines.append("")  # trailing blank line
        return "\n".join(lines)

    def _build_claude_prompt(user_message: str, mode: str = "chat") -> str:
        """Assemble context (positions, summary, meta) into a single text prompt.

        mode:
          - "chat" / "analyse": general discussion
          - "suggest": MUST return ORDERS_CSV block with concrete orders
        """
        positions = _read_positions()
        summary = _read_summary_last_row()
        meta = _read_order_meta()

        lines: list[str] = []
        lines.append("You are an AI trading assistant for a Binance USD-M vault.")
        lines.append("")
        lines.append("Account summary:")
        for k, v in summary.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
        lines.append("Open positions (one row per coin):")
        # Only include non-empty positions (szi != 0) to keep context small.
        for row in positions:
            try:
                szi = float(row.get("szi", 0) or 0)
            except (TypeError, ValueError):
                szi = 0.0
            if szi == 0:
                continue
            coin = row.get("coin", "")
            direct = row.get("direct", "")
            entry = row.get("entryPx", "")
            mark = row.get("markPrice", "")
            upnl = row.get("unrealizedPnl", "")
            roe = row.get("returnOnEquity", "")
            lev = row.get("leverage_value", "")
            lines.append(
                f"- {coin} {direct} size={szi}, lev={lev}, entry={entry}, mark={mark}, uPnL={upnl}, ROE={roe}"
            )
        lines.append("")
        lines.append("Order meta/config (per currency):")
        for row in meta:
            lines.append(
                f"- {row.get('currency')}: max_size_usdt={row.get('max_size_usdt')}, "
                f"min_size_usdt={row.get('min_size_usdt')}, default_lever={row.get('default_lever')}, "
                f"enabled_trade={row.get('enabled_trade')}, notes={row.get('notes')}"
            )
        lines.append("")
        lines.append("User message:")
        lines.append(user_message)
        lines.append("")
        lines.append(
            "If you propose trades, describe them clearly, including coin, side (Long/Short), size in USDT, and leverage."
        )

        if mode == "suggest":
            lines.append("")
            lines.append(
                "You MUST return a concrete execution plan as a CSV block between the markers "
                "ORDERS_CSV_START and ORDERS_CSV_END, in the exact format below."
            )
            lines.append("")
            lines.append("ORDERS_CSV_START")
            lines.append("currency,size_usdt,direct,lever")
            lines.append("BTC,1000,Long,10")
            lines.append("ETH,500,Short,5")
            lines.append("ORDERS_CSV_END")
            lines.append("")
            lines.append(
                "Replace the example rows with your real recommended orders. "
                "If you do not recommend any change, still output an empty CSV block like:\n"
                "ORDERS_CSV_START\n"
                "currency,size_usdt,direct,lever\n"
                "ORDERS_CSV_END"
            )
        else:
            lines.append(
                "If you recommend specific orders, you SHOULD also include a CSV block between "
                "ORDERS_CSV_START and ORDERS_CSV_END in the format: currency,size_usdt,direct,lever."
            )
        return "\n".join(lines)

    def _build_claude_prompt_with_memory(
        user_message: str,
        mode: str = "chat",
        session_id: str | None = None,
    ) -> str:
        """
        Extended Claude prompt that prepends recent chat history (from LangChain) before the main context.
        """
        history_block = _render_history_for_prompt(session_id)
        base_prompt = _build_claude_prompt(user_message, mode=mode)
        if not history_block:
            return base_prompt
        return history_block + "\n" + base_prompt

    def _build_claude_prompt_for_order(user_prompt: str, symbols: list[str] | None = None) -> str:
        """
        Build a focused prompt for composing orders to place.

        

        Uses:
          - current positions from positions.csv (filtered by symbols if provided)
          - order template from data/binance/orders/order_template.csv
          - free-form 'what I want' text from the user
        """
        # Load current positions and optionally filter by symbol list.
        all_positions = _read_positions()
        positions: list[dict]
        if symbols:
            want_coins = {sym[:-4] if sym.endswith("USDT") else sym for sym in symbols}
            positions = [
                row
                for row in all_positions
                if (row.get("coin") or "").strip() in want_coins
            ]
        else:
            positions = all_positions
        # Read the raw order_template.csv text (if present)
        template_text = ""
        if ORDER_TEMPLATE_PATH.exists():
            try:
                with open(ORDER_TEMPLATE_PATH, "r", encoding="utf-8") as f:
                    template_text = f.read().strip()
            except Exception:
                template_text = ""

        lines: list[str] = []
        lines.append("You are an AI trading assistant for a Binance USD-M vault.")
        lines.append("Help to compose orders to place")
        lines.append("")
        lines.append("current position")
        for row in positions:
            try:
                szi = float(row.get("szi", 0) or 0)
            except (TypeError, ValueError):
                szi = 0.0
            if szi == 0:
                continue
            coin = row.get("coin", "")
            direct = row.get("direct", "")
            entry = row.get("entryPx", "")
            mark = row.get("markPrice", "")
            upnl = row.get("unrealizedPnl", "")
            roe = row.get("returnOnEquity", "")
            lev = row.get("leverage_value", "")
            lines.append(
                f"- {coin} {direct} size={szi}, lev={lev}, entry={entry}, mark={mark}, uPnL={upnl}, ROE={roe}"
            )
        lines.append("")
        lines.append("what i want")
        lines.append(user_prompt or "")
        lines.append("")
        lines.append("order template")
        if template_text:
            lines.append(template_text)
        else:
            lines.append("currency,size_usdt,direct,lever,side")
            lines.append("BTC,100,Long,10,BUY")
            lines.append("ETH,100,Short,10,BUY")
        lines.append("")
        lines.append("give me order list need to place")
        lines.append("")
        lines.append(
            "Return the orders as a CSV block between ORDERS_CSV_START and ORDERS_CSV_END "
            "in the exact format below."
        )
        lines.append("")
        lines.append("ORDERS_CSV_START")
        lines.append("currency,size_usdt,direct,lever")
        lines.append("BTC,1000,Long,10")
        lines.append("ETH,500,Short,5")
        lines.append("ORDERS_CSV_END")
        lines.append("")
        lines.append(
            "Replace the example rows with your real recommended orders. "
            "If you do not recommend any change, still output an empty CSV block like:\n"
            "ORDERS_CSV_START\n"
            "currency,size_usdt,direct,lever\n"
            "ORDERS_CSV_END"
        )
        return "\n".join(lines)

    def _debug_log_claude_prompt(source: str, prompt: str) -> None:
        """Log the full prompt being sent to Claude (truncated for safety)."""
        max_len = 4000
        display = prompt if len(prompt) <= max_len else prompt[:max_len] + "... [truncated]"
        sys.stderr.write(f"[backend_server] Claude prompt from {source}:\n{display}\n")
        sys.stderr.write(f"prompt: {prompt}\n")

    def _extract_orders_csv_block(text: str) -> Optional[str]:
        """Extract CSV lines between ORDERS_CSV_START and ORDERS_CSV_END, if present."""
        start_marker = "ORDERS_CSV_START"
        end_marker = "ORDERS_CSV_END"
        start_idx = text.find(start_marker)
        if start_idx == -1:
            return None
        end_idx = text.find(end_marker, start_idx)
        if end_idx == -1:
            return None
        block = text[start_idx + len(start_marker) : end_idx]
        # Normalize newlines and strip
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            return None
        # Ensure header present; if AI omitted it, we can't safely parse, so return raw block.
        return "\n".join(lines)

    def _append_orders_csv_to_ui(csv_block: str) -> int:
        """
        Append parsed CSV rows from a block (without ORDERS_CSV_* markers) to ui_orders.csv.
        Converts direct 'Close' to SELL/BUY from positions. Also writes audit file order_YYYYMMDD_HHMMss.csv.
        Returns number of rows written.
        """
        lines = [ln for ln in csv_block.splitlines() if ln and not ln.lstrip().startswith("#")]
        if not lines:
            return 0
        reader = csv.DictReader(lines)
        batch = []
        for row in reader:
            out = {
                "currency": (row.get("currency") or "").strip().upper(),
                "size_usdt": (row.get("size_usdt") or "").strip(),
                "direct": (row.get("direct") or "").strip(),
                "lever": (row.get("lever") or "").strip(),
            }
            if not out["currency"] or not out["size_usdt"] or not out["direct"]:
                continue
            batch.append(out)
        if not batch:
            return 0
        resolved = _resolve_direct_for_orders(batch, currency_key="currency")
        UI_ORDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_exists = UI_ORDERS_PATH.exists()
        with open(UI_ORDERS_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ORDERS_FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            for row in resolved:
                writer.writerow({k: row.get(k, "") for k in ORDERS_FIELDNAMES})
        _write_orders_audit_file(resolved, ORDERS_FIELDNAMES)
        return len(resolved)

    def _format_execution_reply(
        success: bool,
        num_orders: int,
        returncode: int,
        stdout: str,
        stderr: str,
        error_title: str | None = None,
    ) -> str:
        """Format execution result: small markdown table + compact detail for sidebar."""
        if success:
            table = (
                "| Status | Orders |\n"
                "|--------|--------|\n"
                f"| OK | {num_orders} |"
            )
            out_stdout = (stdout or "").strip()
            if out_stdout:
                # Keep output compact: one line or few lines
                lines = out_stdout.splitlines()
                table += "\n\n" + ("\n".join(lines[:5]) if len(lines) > 5 else out_stdout)
            return table
        title = error_title or "Execution failed"
        table = (
            "| Status | Detail |\n"
            "|--------|--------|\n"
            f"| Error | {title} (code {returncode}) |"
        )
        err = (stderr or "").strip() or (stdout or "").strip()
        if err:
            table += "\n\n" + err.split("\n")[0][:120]  # one line, truncated
        return table

    def _is_apply_last_suggestion_command(msg: str) -> bool:
        m = msg.strip().lower()
        return m in {
            "apply last suggestion",
            "apply last",
            "execute last suggestion",
            "execute last",
        }

    def _infer_chat_mode(message: str) -> str:
        """Infer 'suggest' vs 'chat' from user message for general use (no explicit mode UI).

        Returns 'suggest' when the user appears to be asking for order/position recommendations,
        otherwise 'chat'.
        """
        m = message.strip().lower()
        if not m:
            return "chat"
        suggest_phrases = (
            "suggest",
            "recommend",
            "recommendation",
            "rebalance",
            "what should i",
            "what to buy",
            "what to sell",
            "what positions",
            "order suggestion",
            "position suggestion",
            "position change",
            "trading plan",
            "advice on",
            "ideas for",
            "should i add",
            "should i close",
            "should i open",
            "give me order",
            "concrete order",
            "csv order",
        )
        for phrase in suggest_phrases:
            if phrase in m:
                return "suggest"
        if re.search(r"\b(orders?|rebalance|advice)\b", m) and re.search(
            r"\b(positions?|trade|buy|sell|open|close)\b", m
        ):
            return "suggest"
        return "chat"

    def _read_claude_config() -> dict:
        """Return { enabled: bool, model: str }. Defaults: enabled True, model from env or CLAUDE_DEFAULT_MODEL (Haiku 4.5)."""
        default_model = ANTHROPIC_MODEL or CLAUDE_DEFAULT_MODEL
        default = {"enabled": True, "model": default_model}
        if not CLAUDE_CONFIG_PATH.exists():
            return default
        try:
            with open(CLAUDE_CONFIG_PATH, "r") as f:
                data = json.load(f)
            enabled = data.get("enabled")
            if not isinstance(enabled, bool):
                enabled = default["enabled"]
            raw_model = str(data.get("model") or default["model"]).strip() or default["model"]
            model = _claude_model_or_default(raw_model)
            return {"enabled": enabled, "model": model}
        except Exception:
            return default

    def _write_claude_config(updates: dict) -> dict:
        """Merge updates into config, write to file, return full config."""
        current = _read_claude_config()
        if "enabled" in updates:
            current["enabled"] = bool(updates["enabled"])
        if "model" in updates and updates["model"]:
            current["model"] = str(updates["model"]).strip()
        CLAUDE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLAUDE_CONFIG_PATH, "w") as f:
            json.dump(current, f, indent=2)
        return current

    # --- Routes ---------------------------------------------------------

    @app.get("/api/health")
    def health() -> tuple[dict, int]:
        return {"status": "ok"}, 200

    @app.post("/api/start-positions-crawler")
    def start_positions_crawler() -> tuple[dict, int]:
        """
        Start a background loop that runs crawl_binance_usdm_positions.py every
        CRAWL_POSITIONS_INTERVAL_SECONDS (default 10s).
        Safe to call multiple times; only one thread will run.
        """
        global _positions_crawler_thread
        if _positions_crawler_thread is not None and _positions_crawler_thread.is_alive():
            return {
                "status": "already_running",
                "interval_seconds": CRAWL_POSITIONS_INTERVAL_SECONDS,
            }, 200
        _positions_crawler_stop.clear()
        t = threading.Thread(target=_positions_crawler_loop, name="positions_crawler", daemon=True)
        _positions_crawler_thread = t
        t.start()
        return {"status": "started", "interval_seconds": CRAWL_POSITIONS_INTERVAL_SECONDS}, 200

    @app.post("/api/stop-positions-crawler")
    def stop_positions_crawler() -> tuple[dict, int]:
        """Stop the background positions crawler loop, if running."""
        global _positions_crawler_thread
        _positions_crawler_stop.set()
        if _positions_crawler_thread is not None:
            _positions_crawler_thread = None
        return {"status": "stopped"}, 200

    @app.post("/api/refresh-positions-once")
    def refresh_positions_once() -> tuple[dict, int]:
        """
        Trigger a single run of crawl_binance_usdm_positions.py (synchronous).
        Used by the frontend Refresh button to pull latest Binance positions.
        """
        script_path = ROOT / "scripts" / "crawl_binance_usdm_positions.py"
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except Exception as e:
            sys.stderr.write("[backend_server] Failed to run crawl_binance_usdm_positions.py (manual refresh):\n")
            traceback.print_exc()
            return {"status": "error", "error": str(e)}, 500

        status = "ok" if proc.returncode == 0 else "error"
        return {
            "status": status,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }, 200 if status == "ok" else 500

    @app.get("/api/positions")
    def get_positions() -> tuple[dict, int]:
        """Return all Binance positions (one row per coin)."""
        positions = _read_positions()
        return {"positions": positions}, 200

    @app.get("/api/summary")
    def get_summary() -> tuple[dict, int]:
        """Return latest Binance account summary row."""
        summary = _read_summary_last_row()
        return {"summary": summary}, 200

    @app.get("/api/pnl-history")
    def get_pnl_history() -> tuple[dict, int]:
        """
        Return historical PNL (%) points derived from summary.csv.

        Each point:
          - time: UNIX timestamp in milliseconds (from 'timestamp' column if present)
          - pnl_percent: unrealized PNL percentage = totalUnrealizedProfit / (totalMarginBalance or totalWalletBalance) * 100
        """
        # Limit rows for performance / UI clarity.
        try:
            limit_raw = request.args.get("limit", "").strip()
            limit = int(limit_raw) if limit_raw else 200
        except Exception:
            limit = 200
        rows = _read_summary_history(limit=limit)
        if not rows:
            return {"points": []}, 200

        points: list[dict] = []
        for row in rows:
            unreal = row.get("totalUnrealizedProfit") or ""
            base = row.get("totalMarginBalance") or row.get("totalWalletBalance") or ""
            try:
                unreal_f = float(unreal)
                base_f = float(base)
            except Exception:
                continue
            if not math.isfinite(unreal_f) or not math.isfinite(base_f) or base_f == 0:
                continue
            pnl_percent = (unreal_f / base_f) * 100.0

            ts_str = (row.get("timestamp") or "").strip()
            ts_ms: Optional[int]
            if ts_str:
                try:
                    # Accept ISO-8601 with optional 'Z'
                    ts_clean = ts_str[:-1] if ts_str.endswith("Z") else ts_str
                    dt = datetime.fromisoformat(ts_clean)
                    ts_ms = int(dt.timestamp() * 1000)
                except Exception:
                    ts_ms = None
            else:
                ts_ms = None

            points.append(
                {
                    "time": ts_ms,
                    "pnl_percent": pnl_percent,
                }
            )

        # If many rows have missing timestamps, synthesize a simple index-based time to keep chart monotonic.
        if any(p["time"] is None for p in points):
            base_ts = int(datetime.utcnow().timestamp() * 1000) - len(points) * 60_000
            for idx, p in enumerate(points):
                if p["time"] is None:
                    p["time"] = base_ts + idx * 60_000

        # Ensure all times are integers and list is sorted ascending.
        cleaned = [
            {"time": int(p["time"]), "pnl_percent": float(p["pnl_percent"])}
            for p in points
            if p.get("time") is not None
        ]
        cleaned.sort(key=lambda p: p["time"])
        return {"points": cleaned}, 200

    @app.get("/api/order-meta")
    def get_order_meta() -> tuple[dict, int]:
        """Return Binance order meta / config rows."""
        rows = _read_order_meta()
        return {"meta": rows}, 200

    @app.get("/api/tools/order-meta")
    def get_order_meta_tool() -> tuple[dict, int]:
        """
        Tool: get one order_meta row by currency/pair name.

        Query params:
          - currency: base (e.g. TAO) or full symbol (e.g. TAOUSDT)
        """
        cur_raw = (request.args.get("currency") or "").strip().upper()
        if not cur_raw:
            return {"error": "Missing 'currency' query parameter"}, 400
        base = cur_raw.replace("USDT", "")
        if not base:
            return {"error": "Invalid currency"}, 400
        for row in _read_order_meta():
            if (row.get("currency") or "").strip().upper() == base:
                return {"meta": row}, 200
        return {"error": f"No order_meta row found for {base!r}"}, 404

    @app.get("/api/tools/market-data")
    def get_market_data_for_symbol() -> tuple[dict, int]:
        """
        Helper tool: return a single market_data row for a given currency/symbol.

        Query params:
          - currency: base (e.g. TAO) or full symbol (e.g. TAOUSDT)
        """
        cur = (request.args.get("currency") or "").strip()
        if not cur:
            return {"error": "Missing 'currency' query parameter"}, 400
        row = _get_market_data_for_currency(cur)
        if not row:
            return {"error": f"No market data found for {cur!r}"}, 404
        return {"market_data": row}, 200

    @app.get("/api/market-data")
    def get_market_data() -> tuple[dict, int]:
        """Return market data table (currency, maxLeverage, markPrice, funding, volume, etc.) with labels from backup file."""
        rows = _read_market_data()
        labels_by_currency = _read_market_data_labels()
        for row in rows:
            cur = (row.get("currency") or "").strip().upper()
            row["labels"] = labels_by_currency.get(cur, "")
        return {"market_data": rows}, 200

    @app.patch("/api/market-data/labels")
    def patch_market_data_labels() -> tuple[dict, int]:
        """Update labels in data/binance/backup/market_data_labeled.csv. Body: { "currency": "BTC", "labels": "Meme" }."""
        data = request.get_json(silent=True) or {}
        currency = (data.get("currency") or "").strip()
        labels = (data.get("labels") or "").strip()
        if not currency:
            return {"error": "Missing or empty 'currency'"}, 400
        labeled_rows: List[dict] = []
        if MARKET_DATA_LABELED_PATH.exists():
            try:
                with open(MARKET_DATA_LABELED_PATH, newline="", encoding="utf-8") as f:
                    labeled_rows = list(csv.DictReader(f))
            except Exception:
                labeled_rows = []
        currency_upper = currency.upper()
        found = False
        for row in labeled_rows:
            if (row.get("currency") or "").strip().upper() == currency_upper:
                row["labels"] = labels
                found = True
                break
        if not found:
            labeled_rows.append({"currency": currency, "labels": labels})
        MARKET_DATA_LABELED_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MARKET_DATA_LABELED_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["currency", "labels"])
            writer.writeheader()
            writer.writerows(labeled_rows)
        return {"ok": True, "currency": currency, "labels": labels}, 200

    @app.get("/api/funding-rate-history")
    def get_funding_rate_history() -> tuple[dict, int]:
        """
        Return funding rate history for a given symbol as JSON.

        Query params:
          - symbol: e.g. BTCUSDT or BTC (BTC will be normalized to BTCUSDT)
          - limit: optional max number of rows (default 200)
        """
        symbol_raw = request.args.get("symbol", "").strip().upper()
        if not symbol_raw:
            return {"error": "Missing 'symbol' query parameter"}, 400
        symbol = symbol_raw if symbol_raw.endswith("USDT") else symbol_raw + "USDT"
        try:
            limit = int(request.args.get("limit", "200"))
        except ValueError:
            limit = 200
        if limit <= 0:
            limit = 200
        csv_path = DATA_BINANCE / "funding" / f"funding_rate_history_{symbol}.csv"
        if not csv_path.exists():
            return {"symbol": symbol, "rows": []}, 200
        rows: list[dict] = []
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    rows.append(
                        {
                            "symbol": r.get("symbol", symbol),
                            "fundingRate": r.get("fundingRate", ""),
                            "fundingTime": r.get("fundingTime", ""),
                            "markPrice": r.get("markPrice", ""),
                        }
                    )
        except Exception as e:
            return {"error": f"Failed to read {csv_path}: {e}"}, 500
        # CSVs are written with fundingTime desc; enforce again just in case and apply limit.
        def _key(row: dict) -> int:
            try:
                return int(row.get("fundingTime") or 0)
            except (TypeError, ValueError):
                return 0

        rows.sort(key=_key, reverse=True)
        if limit and len(rows) > limit:
            rows = rows[:limit]
        return {"symbol": symbol, "rows": rows}, 200

    @app.post("/api/sync-funding-rate-history-once")
    def sync_funding_rate_history_once() -> tuple[dict, int]:
        """
        On-demand sync of funding rate history for a single symbol.

        Body (JSON):
          { "symbol": "BTCUSDT" }  # BTC will be normalized to BTCUSDT if needed

        This will:
          - Append any missing recent fundingRate rows to data/binance/funding/funding_rate_history_<symbol>.csv
          - Create the CSV with ~last 7 days if it does not exist yet.
        """
        data = request.get_json(silent=True) or {}
        symbol_raw = str(data.get("symbol") or "").strip().upper()
        if not symbol_raw:
            return {"error": "Missing 'symbol' in JSON body"}, 400
        symbol = symbol_raw if symbol_raw.endswith("USDT") else symbol_raw + "USDT"
        out_dir = DATA_BINANCE / "funding"
        try:
            _update_funding_rate_history_for_symbol(symbol, out_dir)
        except Exception as e:
            sys.stderr.write(f"[backend_server] sync-funding-rate-history-once error for {symbol}: {e}\n")
            traceback.print_exc()
            return {"ok": False, "symbol": symbol, "error": str(e)}, 500
        return {"ok": True, "symbol": symbol}, 200

    @app.get("/api/coinglass/orderbook-history")
    def get_coinglass_orderbook_history() -> tuple[dict, int]:
        """
        Proxy to CoinGlass orderbook ask-bids history (spot or futures).

        Query params:
          - symbol: e.g. BTCUSDT (pair format)
          - market: "spot" or "futures" (default: "futures")
          - interval: optional, e.g. 1d or 4h (default: 4h)

        API: GET .../api/spot/orderbook/ask-bids-history or .../api/futures/orderbook/ask-bids-history
        Params: exchange=Binance, symbol=BTCUSDT, interval=...
        Header: CG-API-KEY
        """
        if not COINGLASS_API_KEY:
            return {"error": "COINGLASS_API_KEY is not set"}, 503
        symbol_raw = request.args.get("symbol", "").strip().upper()
        if not symbol_raw:
            return {"error": "Missing 'symbol' query parameter"}, 400
        symbol = symbol_raw if symbol_raw.endswith("USDT") else symbol_raw + "USDT"
        market = (request.args.get("market") or "futures").strip().lower()
        if market not in ("spot", "futures"):
            market = "futures"
        interval = request.args.get("interval", "4h").strip() or "4h"

        if requests is None:
            return {"error": "requests library required"}, 503

        if market == "spot":
            url = f"{COINGLASS_BASE.rstrip('/')}/api/spot/orderbook/ask-bids-history"
        else:
            url = f"{COINGLASS_BASE.rstrip('/')}/api/futures/orderbook/ask-bids-history"
        # by default, use 30 days ago to now
        start_time = int((datetime.utcnow() - timedelta(days=30)).timestamp() * 1000)
        end_time = int(time_module.time() * 1000)
        params = {
            "exchange": "Binance",
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
        }
        headers = {
            "CG-API-KEY": COINGLASS_API_KEY,
            "accept": "application/json",
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "data" not in data and "msg" in data:
                # API-level error (e.g. symbol not supported for spot)
                if market == "spot":
                    return {"market": "spot", "spotSupported": False, "data": [], "msg": data.get("msg", "")}, 200
                return {"error": f"CoinGlass: {data.get('msg', 'Unknown error')}"}, 502
        except requests.exceptions.RequestException as e:
            if market == "spot":
                return {"market": "spot", "spotSupported": False, "data": [], "msg": str(e)}, 200
            if hasattr(e, "response") and e.response is not None:
                try:
                    return {"error": f"CoinGlass API error: {e.response.text[:500]}"}, 502
                except Exception:
                    pass
            return {"error": str(e)}, 502
        out = data if isinstance(data, dict) else {"data": data}
        if market == "spot" and isinstance(out, dict):
            out["market"] = "spot"
            out["spotSupported"] = True
        return out, 200

    def _binance_signed_get(api_key: str, api_secret: str, path: str, params: Optional[dict] = None) -> Any:
        """GET Binance USD-M private endpoint with HMAC signature."""
        if requests is None:
            raise RuntimeError("requests is required for Binance API")
        params = dict(params or {})
        params["timestamp"] = int(time_module.time() * 1000)
        qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"{BINANCE_FUTURES_BASE}{path}?{qs}&signature={sig}"
        r = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=15)
        r.raise_for_status()
        return r.json()

    def _parse_order_to_row(o: dict) -> dict:
        """Convert one Binance order dict to our API row format."""
        t_ms = int(o.get("time") or 0)
        dt = datetime.utcfromtimestamp(t_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S") if t_ms else "-"
        price = o.get("price") or "0"
        avg_price = o.get("avgPrice") or "0"
        if avg_price == "0" and float(o.get("executedQty") or 0) > 0:
            cq = float(o.get("cumQuote") or o.get("cummulativeQuoteQty") or 0)
            eq = float(o.get("executedQty") or 0)
            avg_price = f"{cq / eq:.6f}".rstrip("0").rstrip(".") if eq else "0"
        cum_quote = float(o.get("cumQuote") or o.get("cummulativeQuoteQty") or 0)
        executed_str = f"{cum_quote:.4f} USDT".rstrip("0").rstrip(".") if cum_quote else "-"
        status = str(o.get("status") or "").upper()
        if status == "FILLED":
            status = "Filled"
        elif status in ("CANCELED", "CANCELLED"):
            status = "Canceled"
        elif status == "NEW":
            status = "New"
        elif status == "EXPIRED":
            status = "Expired"
        return {
            "time": dt,
            "orderId": str(o.get("orderId") or ""),
            "symbol": f"{o.get('symbol', '')} Perpetual",
            "orderType": o.get("type") or o.get("origType") or "-",
            "side": o.get("side") or "-",
            "price": price,
            "avgPrice": avg_price,
            "executed": executed_str,
            "amount": executed_str,
            "triggerConditions": "-",
            "status": status or "-",
        }

    def _fetch_one_symbol_orders(api_key: str, api_secret: str, symbol: str) -> List[dict]:
        """Fetch allOrders for one symbol; returns list of row dicts or empty list on error."""
        try:
            data = _binance_signed_get(api_key, api_secret, "/fapi/v1/allOrders", {"symbol": symbol, "limit": "100"})
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code not in (400, 404):
                sys.stderr.write(f"[backend_server] Binance allOrders {symbol}: {e}\n")
            return []
        if not isinstance(data, list):
            return []
        return [_parse_order_to_row(o) for o in data]

    def _order_history_symbols() -> List[str]:
        """Symbols to query for order history: only those with open position, to avoid rate limit (418)."""
        if POSITIONS_PATH.exists():
            try:
                with open(POSITIONS_PATH, newline="") as f:
                    reader = csv.DictReader(f)
                    symbols = []
                    for row in reader:
                        coin = (row.get("coin") or "").strip()
                        if not coin:
                            continue
                        szi_s = (row.get("szi") or "0").strip()
                        try:
                            szi = float(szi_s)
                        except ValueError:
                            szi = 0.0
                        if szi != 0.0:
                            symbols.append(coin + "USDT" if not coin.endswith("USDT") else coin)
                    if symbols:
                        return symbols
            except Exception:
                pass
        # No open positions: fallback to first few from order_meta to avoid 48 parallel requests
        meta = _read_order_meta()
        symbols = [f"{row.get('currency', '').strip().upper()}USDT" for row in meta if row.get("currency")]
        return symbols[:8] if symbols else ["BTCUSDT", "ETHUSDT"]

    def _fetch_binance_order_history() -> tuple[List[dict], Optional[str]]:
        """Fetch order history from Binance USD-M. Only symbols with open position (or up to 8 fallback); sequential with delay to avoid 418."""
        api_key = BINANCE_API_KEY
        api_secret = BINANCE_API_SECRET
        if not api_key or not api_secret:
            return [], "Set BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) in .env or environment."
        if requests is None:
            return [], "Backend missing 'requests' package for Binance API."
        symbols = _order_history_symbols()
        if not symbols:
            return [], "No symbols to query (no open positions and no order_meta)."
        rows: List[dict] = []
        # Sequential requests with delay to stay under Binance rate limit (418)
        for sym in symbols:
            rows.extend(_fetch_one_symbol_orders(api_key, api_secret, sym))
            time_module.sleep(0.4)
        rows.sort(key=lambda x: x["time"], reverse=True)
        return rows, None

    def _write_binance_order_history_csv(rows: List[dict]) -> None:
        """Write order history rows to BINANCE_ORDER_HISTORY_CSV."""
        if not rows:
            return
        fieldnames = ["time", "orderId", "symbol", "orderType", "side", "price", "avgPrice", "executed", "amount", "triggerConditions", "status"]
        BINANCE_ORDER_HISTORY_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(BINANCE_ORDER_HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _read_binance_order_history_from_csv() -> List[dict]:
        """Read order history from BINANCE_ORDER_HISTORY_CSV. Returns [] if file missing."""
        if not BINANCE_ORDER_HISTORY_CSV.exists():
            return []
        try:
            with open(BINANCE_ORDER_HISTORY_CSV, newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))
        except Exception:
            return []

    def _order_history_refresh_loop() -> None:
        """Background loop: every ORDER_HISTORY_REFRESH_SECONDS fetch order history and write to CSV."""
        while not _order_history_refresh_stop.is_set():
            try:
                orders, hint = _fetch_binance_order_history()
                if orders:
                    _write_binance_order_history_csv(orders)
            except Exception as e:
                sys.stderr.write(f"[backend_server] order history refresh: {e}\n")
            if _order_history_refresh_stop.wait(ORDER_HISTORY_REFRESH_SECONDS):
                break
        sys.stderr.write("[backend_server] Order history refresh stopped.\n")

    def _fetch_binance_funding_fee_history() -> tuple[List[dict], Optional[str]]:
        """Fetch funding fee income from Binance USD-M. GET /fapi/v1/income with incomeType=FUNDING_FEE. Sorted by time desc. Returns (rows, error_hint)."""
        api_key = BINANCE_API_KEY
        api_secret = BINANCE_API_SECRET
        if not api_key or not api_secret:
            return [], "Set BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) in .env or environment."
        if requests is None:
            return [], "Backend missing 'requests' package for Binance API."
        try:
            data = _binance_signed_get(
                api_key,
                api_secret,
                "/fapi/v1/income",
                {"incomeType": "FUNDING_FEE", "limit": "1000"},
            )
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (400, 404):
                sys.stderr.write("[backend_server] Funding fee income not available for this environment.\n")
                return [], "Funding fee not available for this environment (e.g. testnet)."
            sys.stderr.write(f"[backend_server] Binance income FUNDING_FEE: {e}\n")
            return [], str(e)
        if not isinstance(data, list):
            return [], None
        rows: List[dict] = []
        for item in data:
            t_ms = int(item.get("time") or 0)
            dt = datetime.utcfromtimestamp(t_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S") if t_ms else "-"
            income = item.get("income") or "0"
            if isinstance(income, (int, float)):
                income = f"{income:.8f}".rstrip("0").rstrip(".")
            else:
                income = str(income).strip()
            rows.append({
                "time": dt,
                "asset": item.get("asset") or "USDT",
                "amount": income,
                "symbol": f"{item.get('symbol', '')} Perpetual",
            })
        rows.sort(key=lambda x: x["time"], reverse=True)
        return rows, None

    @app.post("/api/refresh-binance-order-history")
    def refresh_binance_order_history() -> tuple[dict, int]:
        """Manually fetch Binance USD-M order history and write to CSV. Binance allOrders requires one symbol per request (no batch); we query symbols with open positions, sequential with delay."""
        try:
            orders, hint = _fetch_binance_order_history()
            if orders:
                _write_binance_order_history_csv(orders)
            symbols = _order_history_symbols()
            out = {
                "orders": len(orders),
                "symbols_queried": len(symbols),
                "refreshed": True,
                "message": f"Fetched {len(orders)} orders for {len(symbols)} symbols (Binance allOrders is per-symbol only).",
            }
            if hint:
                out["hint"] = hint
            return out, 200
        except Exception as e:
            sys.stderr.write(f"[backend_server] refresh-binance-order-history: {e}\n")
            return {"orders": 0, "refreshed": False, "error": str(e)}, 200

    @app.get("/api/binance-order-history")
    def get_binance_order_history() -> tuple[dict, int]:
        """Return Binance USD-M order history from local CSV. Call POST /api/refresh-binance-order-history to refresh."""
        try:
            orders = _read_binance_order_history_from_csv()
            out = {"orders": orders}
            if not orders and not BINANCE_ORDER_HISTORY_CSV.exists():
                out["message"] = "Order history is refreshing in background; ensure BINANCE_API_KEY/SECRET are set and try again in a few seconds."
            return out, 200
        except Exception as e:
            sys.stderr.write(f"[backend_server] binance-order-history: {e}\n")
            traceback.print_exc()
            return {"orders": [], "message": str(e)}, 200

    @app.get("/api/order-status")
    def get_order_status() -> tuple[dict, int]:
        """Query order status by symbol and orderId (Binance GET /fapi/v1/order). Optional ?write_audit=1 to append to order_status_audit.csv."""
        try:
            symbol = (request.args.get("symbol") or "").strip().upper()
            if not symbol:
                return {"error": "Missing required query: symbol (e.g. BTCUSDT)"}, 400
            if not symbol.endswith("USDT"):
                symbol = symbol + "USDT"
            order_id_str = (request.args.get("orderId") or request.args.get("order_id") or "").strip()
            if not order_id_str:
                return {"error": "Missing required query: orderId (or order_id)"}, 400
            try:
                order_id = int(order_id_str)
            except ValueError:
                return {"error": "orderId must be an integer"}, 400
            write_audit = (request.args.get("write_audit") or "").strip().lower() in ("1", "true", "yes")
            api_key = BINANCE_API_KEY
            api_secret = BINANCE_API_SECRET
            if not api_key or not api_secret:
                return {"error": "Set BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) in environment."}, 503
            if requests is None:
                return {"error": "Backend missing 'requests' package for Binance API."}, 503
            data = _binance_signed_get(api_key, api_secret, "/fapi/v1/order", {"symbol": symbol, "orderId": str(order_id)})
            if write_audit:
                audit_fields = [
                    "timestamp_utc", "event_type", "order_id", "client_order_id", "symbol", "side", "order_type",
                    "status", "orig_qty", "executed_qty", "avg_price", "cum_quote", "source",
                ]
                from datetime import datetime as _dt
                row = {
                    "timestamp_utc": _dt.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "event_type": "status_check",
                    "order_id": str(data.get("orderId") or ""),
                    "client_order_id": str(data.get("clientOrderId") or ""),
                    "symbol": str(data.get("symbol") or ""),
                    "side": str(data.get("side") or ""),
                    "order_type": str(data.get("type") or data.get("origType") or ""),
                    "status": str(data.get("status") or ""),
                    "orig_qty": str(data.get("origQty") or ""),
                    "executed_qty": str(data.get("executedQty") or ""),
                    "avg_price": str(data.get("avgPrice") or ""),
                    "cum_quote": str(data.get("cumQuote") or ""),
                    "source": "api",
                }
                ORDER_STATUS_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
                file_exists = ORDER_STATUS_AUDIT_PATH.exists()
                with open(ORDER_STATUS_AUDIT_PATH, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=audit_fields, extrasaction="ignore")
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(row)
            return {"order": data}, 200
        except Exception as e:
            sys.stderr.write(f"[backend_server] order-status: {e}\n")
            traceback.print_exc()
            return {"error": str(e)}, 200

    @app.get("/api/binance-funding-fee-history")
    def get_binance_funding_fee_history() -> tuple[dict, int]:
        """Return Binance USD-M funding fee history. Sorted by time desc. No filter."""
        try:
            rows, hint = _fetch_binance_funding_fee_history()
            out = {"fundingFees": rows}
            if hint:
                out["message"] = hint
            return out, 200
        except Exception as e:
            sys.stderr.write(f"[backend_server] binance-funding-fee-history: {e}\n")
            traceback.print_exc()
            return {"fundingFees": [], "message": str(e)}, 200

    @app.get("/api/claude-config")
    def get_claude_config() -> tuple[dict, int]:
        """Return Claude config: enabled, model, and list of model IDs for dropdown."""
        config = _read_claude_config()
        return {
            "enabled": config["enabled"],
            "model": config["model"],
            "models": CLAUDE_MODELS,
        }, 200

    @app.post("/api/claude-config")
    def post_claude_config() -> tuple[dict, int]:
        """Update Claude config. Body: { enabled?: bool, model?: str }."""
        data = request.get_json(silent=True) or {}
        updates = {}
        if "enabled" in data:
            updates["enabled"] = data["enabled"]
        if "model" in data:
            updates["model"] = data["model"]
        config = _write_claude_config(updates) if updates else _read_claude_config()
        return {
            "enabled": config["enabled"],
            "model": config["model"],
            "models": CLAUDE_MODELS,
        }, 200

    @app.post("/api/orders")
    def post_orders() -> tuple[dict, int]:
        """
        Accept one or more orders from the UI and append to ui_orders.csv.

        Expected JSON:
            {
              "orders": [
                {"currency": "BTC", "size_usdt": 1000, "direct": "Long", "lever": 10},
                ...
              ]
            }
        """
        payload = request.get_json(silent=True) or {}
        raw_orders = payload.get("orders")
        if not isinstance(raw_orders, list) or not raw_orders:
            return {"error": "orders must be a non-empty list"}, 400

        parsed: List[OrderRow] = []
        for idx, item in enumerate(raw_orders):
            if not isinstance(item, dict):
                return {"error": f"orders[{idx}] must be an object"}, 400
            cur = str(item.get("currency") or "").strip().upper()
            size = item.get("size_usdt")
            direct = str(item.get("direct") or "").strip()
            lever_val = item.get("lever")
            if not cur or size is None or not direct:
                return {
                    "error": f"orders[{idx}] missing required fields (currency, size_usdt, direct)"
                }, 400
            try:
                size_f = float(size)
            except (TypeError, ValueError):
                return {"error": f"orders[{idx}].size_usdt must be a number"}, 400
            if size_f <= 0:
                return {"error": f"orders[{idx}].size_usdt must be > 0"}, 400
            lever_int: int | None = None
            if lever_val is not None and lever_val != "":
                try:
                    lever_int = int(lever_val)
                except (TypeError, ValueError):
                    return {"error": f"orders[{idx}].lever must be int or blank"}, 400
            parsed.append(OrderRow(currency=cur, size_usdt=size_f, direct=direct, lever=lever_int))

        _append_orders(parsed)
        return {
            "status": "ok",
            "saved_orders": [asdict(o) for o in parsed],
            "csv_path": str(UI_ORDERS_PATH.relative_to(ROOT)),
        }, 200

    @app.get("/api/tools/order-meta/defaults")
    def get_order_meta_defaults_tool() -> tuple[dict, int]:
        """
        Tool: propose default order_meta values for a new currency (no write).

        Query params:
          - currency: base (e.g. TAO) or full symbol (e.g. TAOUSDT)
        """
        cur_raw = (request.args.get("currency") or "").strip().upper()
        if not cur_raw:
            return {"error": "Missing 'currency' query parameter"}, 400
        base = cur_raw.replace("USDT", "")
        if not base:
            return {"error": "Invalid currency"}, 400

        # Do not propose if row already exists
        for row in _read_order_meta():
            if (row.get("currency") or "").strip().upper() == base:
                return {
                    "error": f"order_meta already has entry for {base}",
                    "meta": row,
                }, 400

        md_row = _get_market_data_for_currency(base) or _get_market_data_for_currency(base + "USDT")
        max_leverage_val: int | None = None
        if md_row is not None:
            try:
                max_leverage_val = int(float(str(md_row.get("maxLeverage") or "0")))
            except ValueError:
                max_leverage_val = None
        if max_leverage_val is None or max_leverage_val <= 0:
            max_leverage_val = 10

        proposed = {
            "currency": base,
            "enabled_trade": True,
            "default_lever": min(max_leverage_val, 10),
            "max_size_usdt": 1000.0,
            "min_size_usdt": 0.0,
        }
        return {"proposed": proposed}, 200

    @app.post("/api/tools/add-order-pair")
    def add_order_pair_tool() -> tuple[dict, int]:
        """
        Helper tool: initialize a new entry in order_meta.csv for a currency.

        Body:
          {
            "currency": "TAO",          # base or full symbol
            "enabled_trade": true,      # optional, default true
            "default_lever": 5,         # optional, default from market data maxLeverage capped at 10
            "max_size_usdt": 1000,      # optional, default 1000
            "min_size_usdt": 0,         # optional, default 0
            "order_type": "MARKET",     # optional, default MARKET
            "quantity_precision": 0,    # optional, default 0
            "notes": "auto-added",      # optional
          }
        """
        data = request.get_json(silent=True) or {}
        currency_raw = (data.get("currency") or "").strip().upper()
        if not currency_raw:
            return {"error": "Missing 'currency' in JSON body"}, 400
        base = currency_raw.replace("USDT", "")
        if not base:
            return {"error": "Invalid currency"}, 400

        # Prevent duplicates
        existing = _read_order_meta()
        for row in existing:
            if (row.get("currency") or "").strip().upper() == base:
                return {"error": f"order_meta already has entry for {base}"}, 400

        # Derive sensible defaults from market_data when possible
        md_row = _get_market_data_for_currency(base) or _get_market_data_for_currency(base + "USDT")
        max_leverage_val: int | None = None
        if md_row is not None:
            try:
                max_leverage_val = int(float(str(md_row.get("maxLeverage") or "0")))
            except ValueError:
                max_leverage_val = None
        if max_leverage_val is None or max_leverage_val <= 0:
            max_leverage_val = 10

        enabled_trade = bool(data.get("enabled_trade", True))
        default_lever = int(data.get("default_lever") or min(max_leverage_val, 10))
        max_size_usdt = float(data.get("max_size_usdt") or 1000.0)
        min_size_usdt = float(data.get("min_size_usdt") or 0.0)
        order_type = str(data.get("order_type") or "MARKET").strip().upper() or "MARKET"
        quantity_precision = int(data.get("quantity_precision") or 0)
        notes = str(data.get("notes") or "auto-added from add-order-pair tool")

        # Append to order_meta.csv
        ORDER_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_exists = ORDER_META_PATH.exists()
        fieldnames = [
            "currency",
            "quantity_precision",
            "max_size_usdt",
            "min_size_usdt",
            "order_type",
            "enabled_trade",
            "default_lever",
            "notes",
            "max_leverage",
            "max_position_at_max_leverage_usdt",
        ]
        new_row = {
            "currency": base,
            "quantity_precision": str(quantity_precision),
            "max_size_usdt": f"{max_size_usdt:.2f}",
            "min_size_usdt": f"{min_size_usdt:.2f}",
            "order_type": order_type,
            "enabled_trade": "true" if enabled_trade else "false",
            "default_lever": str(default_lever),
            "notes": notes,
            "max_leverage": str(max_leverage_val),
            # Conservative default for max position; can be edited later.
            "max_position_at_max_leverage_usdt": f"{max_size_usdt * 5:.2f}",
        }
        try:
            with open(ORDER_META_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                if not file_exists:
                    writer.writeheader()
                writer.writerow(new_row)
        except Exception as e:
            sys.stderr.write(f"[backend_server] add-order-pair tool failed: {e}\n")
            traceback.print_exc()
            return {"error": f"Failed to append order_meta: {e}"}, 500

        return {"status": "ok", "meta_row": new_row}, 200

    def _maybe_handle_chat_tools(message: str) -> Optional[tuple[dict, int]]:
        """
        Handle simple tool-style commands in chat before calling Claude.

        Supported intents (heuristic, keyword-based):
          - Add order pair: contains 'add' and one of:
            'order pair', 'currency pair', 'currencypair', 'trade pair', 'ticker'
          - Get order_meta: 'order meta' and 'get'/'show'
          - Get market data: 'market data' and 'get'/'show'
          - Propose order_meta defaults: 'order meta' and 'default'
        """
        m = (message or "").strip()
        lower = m.lower()
        if not m:
            return None

        # Add order pair
        add_keywords = ("order pair", "currency pair", "currencypair", "trade pair", "ticker")
        if "add" in lower and any(kw in lower for kw in add_keywords):
            base = _extract_base_currency_from_message(m)
            if not base:
                return {"reply": "Could not detect which currency to add order pair for."}, 200
            # If already exists, just report
            for row in _read_order_meta():
                if (row.get("currency") or "").strip().upper() == base:
                    return {
                        "reply": f"Order pair for {base} already exists in order_meta.",
                    }, 200
            # Use defaults tool logic
            defaults_body, status = get_order_meta_defaults_tool()
            if status != 200 or "proposed" not in defaults_body:
                # Fallback: propose hard-coded defaults
                proposed = {
                    "currency": base,
                    "enabled_trade": True,
                    "default_lever": 10,
                    "max_size_usdt": 1000.0,
                    "min_size_usdt": 0.0,
                }
            else:
                proposed = defaults_body["proposed"]
            # Immediately add with proposed values
            data = {
                "currency": proposed["currency"],
                "enabled_trade": proposed.get("enabled_trade", True),
                "default_lever": proposed.get("default_lever", 10),
                "max_size_usdt": proposed.get("max_size_usdt", 1000.0),
                "min_size_usdt": proposed.get("min_size_usdt", 0.0),
            }
            # Simulate JSON body for the tool
            with app.test_request_context(
                "/api/tools/add-order-pair",
                method="POST",
                json=data,
            ):
                body, st = add_order_pair_tool()
            if st != 200:
                return {"reply": f"Failed to add order pair for {base}: {body.get('error', 'unknown error')}"}, 200
            meta_row = body.get("meta_row", {})
            reply_lines = [
                f"Added order pair for {base} with config:",
                f"- enabled_trade: {meta_row.get('enabled_trade')}",
                f"- default_lever: {meta_row.get('default_lever')}",
                f"- max_size_usdt: {meta_row.get('max_size_usdt')}",
                f"- min_size_usdt: {meta_row.get('min_size_usdt')}",
            ]
            return {"reply": "\n".join(reply_lines)}, 200

        # Get order_meta by currency
        if "order meta" in lower and any(kw in lower for kw in ("get", "show")):
            base = _extract_base_currency_from_message(m)
            if not base:
                return {"reply": "Could not detect which currency to look up in order_meta."}, 200
            for row in _read_order_meta():
                if (row.get("currency") or "").strip().upper() == base:
                    reply = (
                        f"order_meta for {base}:\n"
                        f"- enabled_trade: {row.get('enabled_trade')}\n"
                        f"- default_lever: {row.get('default_lever')}\n"
                        f"- max_size_usdt: {row.get('max_size_usdt')}\n"
                        f"- min_size_usdt: {row.get('min_size_usdt')}\n"
                        f"- order_type: {row.get('order_type')}\n"
                        f"- notes: {row.get('notes') or ''}"
                    )
                    return {"reply": reply}, 200
            return {"reply": f"No order_meta row found for {base}."}, 200

        # Get market data for a symbol
        if "market data" in lower and any(kw in lower for kw in ("get", "show")):
            base = _extract_base_currency_from_message(m)
            if not base:
                return {"reply": "Could not detect which symbol to show market data for."}, 200
            row = _get_market_data_for_currency(base)
            if not row:
                return {"reply": f"No market data found for {base}."}, 200
            reply = (
                f"Market data for {row.get('currency')}:\n"
                f"- maxLeverage: {row.get('maxLeverage')}\n"
                f"- markPrice: {row.get('markPrice')}\n"
                f"- pricePrecision: {row.get('pricePrecision')}\n"
                f"- lastFundingRate: {row.get('lastFundingRate')}\n"
                f"- volume24h(USDT): {row.get('volume24h(USDT)')}"
            )
            return {"reply": reply}, 200

        # Propose order_meta defaults without writing
        if "order meta" in lower and "default" in lower:
            base = _extract_base_currency_from_message(m)
            if not base:
                return {"reply": "Could not detect which currency to propose defaults for."}, 200
            with app.test_request_context(
                "/api/tools/order-meta/defaults",
                method="GET",
                query_string={"currency": base},
            ):
                body, st = get_order_meta_defaults_tool()
            if st != 200 or "proposed" not in body:
                return {"reply": f"Could not compute default order_meta for {base}: {body.get('error', 'unknown error')}"}, 200
            proposed = body["proposed"]
            reply = (
                f"Proposed order_meta defaults for {base} (not yet saved):\n"
                f"- enabled_trade: {proposed.get('enabled_trade')}\n"
                f"- default_lever: {proposed.get('default_lever')}\n"
                f"- max_size_usdt: {proposed.get('max_size_usdt')}\n"
                f"- min_size_usdt: {proposed.get('min_size_usdt')}\n"
                "Reply with 'add order pair {base}' to create this entry."
            )
            return {"reply": reply}, 200

        return None

    @app.post("/api/close-positions")
    def post_close_positions() -> tuple[dict, int]:
        """
        Close one or more positions (100% each). Writes order_close_template.csv and runs binance_trade_api.py --close-template.

        Body (JSON):
          - symbols: ["BTCUSDT", "ETHUSDT"]  # USDT normalized
          - orderType: "MARKET" | "LIMIT" (default MARKET)
          - useMarkPrice: true to use current mark price for LIMIT (default false)
          - limitPrice: optional number for LIMIT when useMarkPrice is false
        """
        payload = request.get_json(silent=True) or {}
        raw = payload.get("symbols")
        if not isinstance(raw, list) or not raw:
            return {"error": "symbols must be a non-empty list"}, 400
        symbols: List[str] = []
        for s in raw:
            sym = str(s).strip().upper()
            if not sym:
                continue
            if not sym.endswith("USDT"):
                sym = sym + "USDT"
            symbols.append(sym)
        if not symbols:
            return {"error": "No valid symbols"}, 400
        order_type = (payload.get("orderType") or payload.get("order_type") or "MARKET").strip().upper()
        if order_type not in ("MARKET", "LIMIT"):
            order_type = "MARKET"
        use_mark_price = (payload.get("useMarkPrice") or payload.get("use_mark_price") or False) is True
        limit_price = payload.get("limitPrice") or payload.get("limit_price")
        if limit_price is not None:
            try:
                limit_price = float(limit_price)
            except (TypeError, ValueError):
                limit_price = None
        # Build order_close_template.csv: symbol,fraction,order_type,price
        price_val = ""
        if order_type == "LIMIT":
            price_val = "mark" if use_mark_price else (str(limit_price) if limit_price is not None else "mark")
        rows = [{"symbol": sym, "fraction": "1.0", "order_type": order_type, "price": price_val} for sym in symbols]
        ORDER_CLOSE_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(ORDER_CLOSE_TEMPLATE_PATH, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["symbol", "fraction", "order_type", "price"])
                writer.writeheader()
                writer.writerows(rows)
        except Exception as e:
            return {"error": f"Failed to write order_close_template.csv: {e}"}, 500
        try:
            import binance_trade_api as bta  # type: ignore[import]
            bta.place_close_orders_from_template(ORDER_CLOSE_TEMPLATE_PATH)
        except Exception as e:
            sys.stderr.write(f"[backend_server] close-positions: {e}\n")
            traceback.print_exc()
            return {"error": str(e), "executed": False}, 500
        return {
            "ok": True,
            "symbols": symbols,
            "orderType": order_type,
            "executed": True,
            "success": True,
        }, 200

    @app.get("/api/mark-prices")
    def get_mark_prices() -> tuple[dict, int]:
        """Return { symbol: markPrice } for symbols from positions and market-data (for limit order default)."""
        positions = _read_positions()
        market = _read_market_data()
        out = {}
        for row in positions:
            coin = (row.get("coin") or "").strip()
            if not coin:
                continue
            symbol = coin + "USDT" if not coin.endswith("USDT") else coin
            mp = row.get("markPrice") or row.get("mark_price") or ""
            if mp and str(mp).strip():
                try:
                    out[symbol] = float(mp)
                except (TypeError, ValueError):
                    pass
        for row in market:
            cur = (row.get("currency") or "").strip().upper()
            if not cur:
                continue
            symbol = cur + "USDT" if not cur.endswith("USDT") else cur
            if symbol in out:
                continue
            mp = row.get("markPrice") or row.get("mark_price") or ""
            if mp and str(mp).strip():
                try:
                    out[symbol] = float(mp)
                except (TypeError, ValueError):
                    pass
        symbols_param = request.args.get("symbols")
        if symbols_param:
            want = {s.strip().upper() for s in symbols_param.split(",") if s.strip()}
            want = {s if s.endswith("USDT") else s + "USDT" for s in want}
            out = {k: v for k, v in out.items() if k in want}
        return {"markPrices": out}, 200

    @app.post("/api/place-batch-orders")
    def post_place_batch_orders() -> tuple[dict, int]:
        """
        Place multiple orders via Binance batch API (max 5 per batch; chunks automatically).

        Body (JSON): { "leverage"?: int, "orders": [ { "symbol", "type": "MARKET"|"LIMIT", "price?", "amountUsdt", "positionSide": "LONG"|"SHORT" } ] }
        If leverage is provided, set_leverage(symbol, leverage) is called for each unique symbol before placing.
        """
        payload = request.get_json(silent=True) or {}
        leverage = payload.get("leverage")
        if leverage is not None:
            try:
                leverage = int(leverage)
                if leverage < 1:
                    leverage = None
            except (TypeError, ValueError):
                leverage = None
        raw = payload.get("orders")
        if not isinstance(raw, list) or not raw:
            return {"error": "orders must be a non-empty list"}, 400
        orders = []
        for i, o in enumerate(raw):
            if not isinstance(o, dict):
                return {"error": f"orders[{i}] must be an object"}, 400
            sym = (o.get("symbol") or "").strip().upper()
            if not sym:
                return {"error": f"orders[{i}]: symbol is required"}, 400
            if not sym.endswith("USDT"):
                sym = sym + "USDT"
            order_type = (o.get("type") or o.get("orderType") or "MARKET").strip().upper()
            if order_type not in ("MARKET", "LIMIT"):
                order_type = "MARKET"
            amount_raw = o.get("amountUsdt") or o.get("amount_usdt")
            try:
                amount_usdt = float(amount_raw)
            except (TypeError, ValueError):
                return {"error": f"orders[{i}]: amountUsdt must be a number"}, 400
            if amount_usdt <= 0:
                return {"error": f"orders[{i}]: amountUsdt must be positive"}, 400
            pos_side = (o.get("positionSide") or o.get("position_side") or "LONG").strip().upper()
            if pos_side not in ("LONG", "SHORT"):
                pos_side = "LONG"
            item = {
                "symbol": sym,
                "type": order_type,
                "amountUsdt": amount_usdt,
                "positionSide": pos_side,
            }
            if order_type == "LIMIT" and o.get("price") is not None and str(o.get("price")).strip() != "":
                try:
                    item["price"] = float(o.get("price"))
                except (TypeError, ValueError):
                    pass
            orders.append(item)
        try:
            # Import lazily so backend_server can run without trading deps if needed.
            sys.path.insert(0, str(ROOT))
            import binance_trade_api as bta  # type: ignore[import]

            responses = bta.place_batch_orders(orders, leverage=leverage)
        except Exception as e:
            # Surface Binance auth / permission errors as a user-facing message instead of 500.
            traceback.print_exc()
            msg = str(e)
            if "Binance error" in msg:
                return {"error": msg, "ok": False, "responses": []}, 200
            return {"error": msg, "ok": False, "responses": []}, 500
        return {"ok": True, "responses": responses}, 200

    @app.post("/api/compose-orders")
    def post_compose_orders() -> tuple[dict, int]:
        """
        Use Claude to propose a batch of orders based on a natural-language prompt and a list of symbols.

        Body (JSON):
          - prompt: free-form user text describing what they want
          - symbols: ["BTCUSDT", "ETHUSDT", ...]

        Response (JSON):
          - ok: bool
          - reply: full Claude reply text
          - orders: [
              {
                "currency": "BTC",
                "amountUsdt": 1000.0,
                "positionSide": "LONG",
                "orderType": "MARKET",
                "limitPrice": null
              },
              ...
            ]
          - error?: string
        """
        data = request.get_json(silent=True) or {}
        prompt_text = str(data.get("prompt") or "").strip()
        raw_symbols = data.get("symbols") or []
        if raw_symbols is None:
            raw_symbols = []
        if not isinstance(raw_symbols, list):
            return {"error": "symbols must be a list"}, 400
        # Normalize to upper-case symbol list with USDT suffix
        symbols: list[str] = []
        for s in raw_symbols:
            sym = str(s or "").strip().upper()
            if not sym:
                continue
            if not sym.endswith("USDT"):
                sym = sym + "USDT"
            symbols.append(sym)

        claude_config = _read_claude_config()
        if not claude_config.get("enabled", True):
            return {
                "ok": False,
                "error": "Claude is disabled. Enable it in chat settings to use AI.",
                "reply": "(Claude is disabled. Enable it in chat settings to use AI.)",
                "orders": [],
            }, 200

        client = _build_claude_client()
        if client is None:
            sys.stderr.write(
                "[backend_server] Claude client is not configured for /api/compose-orders.\n"
            )
            return {
                "ok": False,
                "error": "Claude client is not configured. Install anthropic and set ANTHROPIC_API_KEY.",
                "reply": "(stub, no Claude) Unable to call Claude for order composition.",
                "orders": [],
            }, 200

        user_message = prompt_text or ""
        prompt = _build_claude_prompt_for_order(user_message, symbols=symbols)
        _debug_log_claude_prompt("/api/compose-orders", prompt)
        model = _claude_model_or_default(
            claude_config.get("model") or ANTHROPIC_MODEL
        )
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=4000,
                temperature=0.1,
                system="You are an AI assistant helping manage a Binance USD-M vault.",
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}],
                    }
                ],
            )
            try:
                sys.stderr.write(f"[backend_server] /api/compose-orders raw Claude resp: {resp}\n")
            except Exception:
                pass
            text_parts: list[str] = []
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
            reply_text = "\n".join(text_parts) if text_parts else "(no reply)"

            print(f"model reply_text: {reply_text}")

            orders_block = _extract_orders_csv_block(reply_text)
            _append_ai_suggestion(user_message, reply_text, orders_block)

            suggestions: list[dict] = []
            if orders_block:
                # Parse the CSV block and convert into suggestions suitable for the UI table.
                lines = [
                    ln
                    for ln in orders_block.splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")
                ]
                if lines:
                    reader = csv.DictReader(lines)
                    for row in reader:
                        cur_raw = (row.get("currency") or "").strip().upper()
                        if not cur_raw:
                            continue
                        size_str = (row.get("size_usdt") or "").strip()
                        try:
                            size_val = float(size_str)
                        except (TypeError, ValueError):
                            continue
                        if size_val <= 0:
                            continue
                        direct = (row.get("direct") or "").strip().lower()
                        if direct in {"long", "buy"}:
                            side = "LONG"
                        elif direct in {"short", "sell"}:
                            side = "SHORT"
                        else:
                            # Skip unsupported/ambiguous directions like "Close" for now.
                            continue
                        # Normalize to asset currency without the USDT suffix for the UI.
                        cur = cur_raw[:-4] if cur_raw.endswith("USDT") else cur_raw
                        suggestions.append(
                            {
                                "currency": cur,
                                "amountUsdt": size_val,
                                "positionSide": side,
                                "orderType": "MARKET",
                                "limitPrice": None,
                            }
                        )

            return {
                "ok": True,
                "reply": reply_text,
                "orders": suggestions,
            }, 200
        except Exception as e:
            sys.stderr.write("[backend_server] Claude API error in /api/compose-orders:\n")
            traceback.print_exc()
            return {
                "ok": False,
                "error": f"Claude API error: {e}",
                "reply": "",
                "orders": [],
            }, 500

    @app.post("/api/set-leverage")
    def post_set_leverage() -> tuple[dict, int]:
        """
        Set leverage for a single Binance futures symbol.

        Body (JSON):
          - symbol: "BTCUSDT" (will auto-append USDT if missing)
          - leverage: integer, 1 <= leverage <= maxLeverage (enforced by Binance)
        """
        payload = request.get_json(silent=True) or {}
        symbol_raw = (payload.get("symbol") or "").strip().upper()
        if not symbol_raw:
            return {"error": "symbol is required"}, 400
        if not symbol_raw.endswith("USDT"):
            symbol = symbol_raw + "USDT"
        else:
            symbol = symbol_raw
        lev_raw = payload.get("leverage")
        try:
            leverage = int(lev_raw)
        except (TypeError, ValueError):
            return {"error": "Invalid leverage value"}, 400
        if leverage < 1:
            leverage = 1
        try:
            # Import lazily so backend_server can run without trading deps if needed.
            sys.path.insert(0, str(ROOT))
            import binance_trade_api as bta  # type: ignore[import]

            res = bta.set_leverage(symbol, leverage)
        except Exception as e:  # pragma: no cover - network/external errors
            traceback.print_exc()
            return {"error": str(e)}, 500
        return {"ok": True, "symbol": symbol, "leverage": leverage, "response": res}, 200

    @app.post("/api/chat")
    def chat() -> tuple[dict, int]:
        data = request.get_json(silent=True) or {}
        message = str(data.get("message") or "").strip()
        mode = str(data.get("mode") or "chat").strip().lower()
        session_id = str(data.get("session_id") or "").strip() or None
        attachments = data.get("attachments")
        if isinstance(attachments, list) and attachments:
            names = [str(a.get("name") or a.get("filename") or "file") for a in attachments[:10]]
            message = message + "\n\n[User attached " + str(len(attachments)) + " file(s): " + ", ".join(names) + "]"
        if not message:
            return {"error": "message is required"}, 400

        # 0) Tool-style commands before Claude (order_meta / market_data helpers)
        tool_result = _maybe_handle_chat_tools(message)
        if tool_result is not None:
            return tool_result

        # 1) Command path: e.g. apply last suggestion / execute / clear
        if mode in {"apply_last"} or _is_apply_last_suggestion_command(message):
            last = _read_last_ai_suggestion()
            if not last:
                return {"reply": "No previous AI suggestion found to apply."}, 200
            orders_block = last.get("orders_csv") or ""
            if not orders_block:
                return {
                    "reply": "Last suggestion did not include any ORDERS CSV block; nothing to apply."
                }, 200
            try:
                rows_written = _append_orders_csv_to_ui(orders_block)
            except Exception as e:
                sys.stderr.write("[backend_server] Error applying last suggestion to ui_orders.csv:\n")
                traceback.print_exc()
                return {"reply": f"Failed to apply last suggestion: {e}"}, 200
            return {
                "reply": f"Applied last suggestion: wrote {rows_written} orders to {UI_ORDERS_PATH.name}. "
                "Review the CSV before executing trades.",
            }, 200

        if mode in {"execute"}:
            # Treat message as CSV content with header currency,size_usdt,direct,lever (context-based; no file dependency).
            lines = [ln for ln in message.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
            if not lines:
                return {"reply": "Execute failed: no CSV content provided."}, 200
            reader = csv.DictReader(lines)
            required_fields = {"currency", "size_usdt", "direct"}
            if not required_fields.issubset(set(reader.fieldnames or [])):
                return {
                    "reply": "Execute failed: CSV must include header currency, size_usdt, direct (lever optional)."
                }, 200
            rows_out: list[dict] = []
            for row in reader:
                cur = (row.get("currency") or "").strip().upper()
                size_str = (row.get("size_usdt") or "").strip()
                direct = (row.get("direct") or "").strip()
                lever = (row.get("lever") or "").strip()
                if not cur or not size_str or not direct:
                    continue
                try:
                    size_val = float(size_str)
                except ValueError:
                    return {"reply": f"Execute failed: invalid size_usdt {size_str!r}."}, 200
                if size_val <= 0:
                    return {"reply": f"Execute failed: size_usdt must be > 0, got {size_str!r}."}, 200
                rows_out.append(
                    {
                        "currency": cur,
                        "size_usdt": f"{size_val}",
                        "direct": direct,
                        "lever": lever,
                    }
                )
            if not rows_out:
                return {"reply": "Execute failed: no valid order rows in CSV."}, 200

            # Resolve Close -> SELL/BUY from positions (Binance has no Close side), then overwrite ui_orders.csv and write audit
            resolved_out = _resolve_direct_for_orders(rows_out, currency_key="currency")
            UI_ORDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(UI_ORDERS_PATH, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=ORDERS_FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                for row in resolved_out:
                    writer.writerow({k: row.get(k, "") for k in ORDERS_FIELDNAMES})
            _write_orders_audit_file(resolved_out, ORDERS_FIELDNAMES)

            script_path = ROOT / "scripts" / "binance_trade_api.py"
            cmd = [sys.executable, str(script_path), str(UI_ORDERS_PATH)]
            # Preserve the raw CSV input for history.
            input_csv_text = "\n".join(lines)

            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except Exception as e:
                sys.stderr.write("[backend_server] Failed to run binance_trade_api.py:\n")
                traceback.print_exc()
                _append_order_history_entry(
                    source="chat_execute",
                    num_orders=len(rows_out),
                    returncode=-1,
                    stdout="",
                    stderr=str(e),
                    input_csv=input_csv_text,
                )
                reply = _format_execution_reply(
                    success=False,
                    num_orders=len(rows_out),
                    returncode=-1,
                    stdout="",
                    stderr=str(e),
                    error_title="Failed to run binance_trade_api.py",
                )
                return {"reply": reply, "executed": True, "success": False, "num_orders": len(rows_out)}, 200

            _append_order_history_entry(
                source="chat_execute",
                num_orders=len(rows_out),
                returncode=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                input_csv=input_csv_text,
            )

            if proc.returncode != 0:
                reply = _format_execution_reply(
                    success=False,
                    num_orders=len(rows_out),
                    returncode=proc.returncode,
                    stdout=proc.stdout or "",
                    stderr=proc.stderr or "",
                    error_title="binance_trade_api.py exited with non-zero status",
                )
                return {"reply": reply, "executed": True, "success": False, "num_orders": len(rows_out)}, 200

            reply = _format_execution_reply(
                success=True,
                num_orders=len(rows_out),
                returncode=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
            )
            return {"reply": reply, "executed": True, "success": True, "num_orders": len(rows_out)}, 200

        # Infer chat vs suggest when not in a special command (so we can drop Chat/Suggest UI and use "auto")
        if mode not in {"execute", "apply_last"}:
            mode = _infer_chat_mode(message)

        # 2) Normal / analyse / suggest chat path → Claude with full context
        claude_config = _read_claude_config()
        if not claude_config.get("enabled", True):
            reply = "(Claude is disabled. Enable it in chat settings to use AI.)"
            _append_history_message(session_id, message, reply)
            return {"reply": reply}, 200

        client = _build_claude_client()
        if client is None:
            # Fallback: echo if Claude is not configured.
            sys.stderr.write(
                "[backend_server] Claude client is not configured. "
                "Ensure anthropic is installed and ANTHROPIC_API_KEY is set.\n"
            )
            reply = f"(stub, no Claude) You said: {message}"
            _append_history_message(session_id, message, reply)
            return {"reply": reply}, 200

        prompt = _build_claude_prompt_with_memory(message, mode=mode, session_id=session_id)

        _debug_log_claude_prompt(f"/api/chat mode={mode}", prompt)
        # Per-request model override from frontend (must be in CLAUDE_MODELS)
        request_model = str(data.get("model") or "").strip()
        if request_model and request_model in CLAUDE_MODELS:
            model = request_model
        else:
            model = _claude_model_or_default(
                claude_config.get("model") or ANTHROPIC_MODEL
            )
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=1500 if mode == "suggest" else 800,
                temperature=0.2,
                system="You are an AI assistant helping manage a Binance USD-M vault.",
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}],
                    }
                ],
            )
            try:
                sys.stderr.write(f"[backend_server] /api/chat raw Claude resp: {resp}\n")
            except Exception:
                pass
            # anthropic.Messages.create returns content list; we take the text blocks.
            text_parts = []
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
            reply = "\n".join(text_parts) if text_parts else "(no reply)"
            orders_block = _extract_orders_csv_block(reply)
            _append_ai_suggestion(message, reply, orders_block)
            _append_history_message(session_id, message, reply)
            # Suggest: return orders in response for approve flow; do not write to ui_orders.csv (context-based).
            out = {"reply": reply}
            if mode == "suggest" and orders_block:
                out["orders_csv"] = orders_block
            return (out, 200)
        except Exception as e:
            sys.stderr.write("[backend_server] Claude API error:\n")
            traceback.print_exc()
            return {"error": f"Claude API error: {e}"}, 500

    @app.post("/api/chat/stream")
    def chat_stream() -> Response:
        """
        SSE wrapper around /api/chat for assistant-ui.

        This reuses the existing /api/chat logic (including LangChain-based memory)
        and streams the final JSON response as a single SSE event.
        """

        # Call the JSON chat handler once within the current request context,
        # then stream that single response as SSE.
        body, status = chat()

        def generate():
            if status != 200:
                payload = {
                    "ok": False,
                    "status": status,
                    "error": (body or {}).get("error") or (body or {}).get("reply") or "Chat error",
                }
                yield "event: error\n"
                yield f"data: {json.dumps(payload)}\n\n"
                return

            payload = dict(body or {})
            payload.setdefault("ok", True)
            yield "event: message\n"
            yield f"data: {json.dumps(payload)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    # Order history is NOT auto-refreshed; call POST /api/refresh-binance-order-history when needed.

    # Serve frontend build for same-place deploy (API already handles /api/*)
    FRONTEND_DIST = ROOT / "frontend" / "dist"

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path: str):
        if path.startswith("api/"):
            return {"error": "Not found"}, 404
        if not FRONTEND_DIST.exists():
            return {"error": "Frontend not built. Run: cd frontend && npm run build"}, 503
        if path:
            file_path = FRONTEND_DIST / path
            if file_path.is_file():
                return send_from_directory(str(FRONTEND_DIST), path)
        return send_from_directory(str(FRONTEND_DIST), "index.html")

    return app


if __name__ == "__main__":
    port = BACKEND_PORT
    app = create_app()
    if RUN_FETCH_LOOPS:
        # Auto-start positions crawler (updates data/binance/positions.csv every CRAWL_POSITIONS_INTERVAL_SECONDS)
        if _positions_crawler_thread is None or not _positions_crawler_thread.is_alive():
            _positions_crawler_stop.clear()
            _positions_crawler_thread = threading.Thread(
                target=_positions_crawler_loop, name="positions_crawler", daemon=True
            )
            _positions_crawler_thread.start()
            sys.stderr.write(
                f"[backend_server] Positions crawler started (every {CRAWL_POSITIONS_INTERVAL_SECONDS}s)\n"
            )
        # Funding rate estimate: on start then hourly (72h avg → day rate, latest → day rate; merged into positions)
        if _funding_estimate_thread is None or not _funding_estimate_thread.is_alive():
            _funding_estimate_stop.clear()
            _funding_estimate_thread = threading.Thread(
                target=_funding_estimate_loop, name="funding_estimate", daemon=True
            )
            _funding_estimate_thread.start()
            sys.stderr.write(
                f"[backend_server] Funding estimate started (every {FUNDING_ESTIMATE_INTERVAL_SECONDS}s)\n"
            )
        # Market data: all Binance USD-M perpetuals -> market_data.csv every 5 min
        if _market_data_thread is None or not _market_data_thread.is_alive():
            _market_data_stop.clear()
            _market_data_thread = threading.Thread(
                target=_market_data_loop, name="market_data", daemon=True
            )
            _market_data_thread.start()
            sys.stderr.write(
                f"[backend_server] Market data started (every {MARKET_DATA_INTERVAL_SECONDS}s)\n"
            )
        # Funding for market_data (72h avg): on start then every hour
        if _funding_market_data_thread is None or not _funding_market_data_thread.is_alive():
            _funding_market_data_stop.clear()
            _funding_market_data_thread = threading.Thread(
                target=_funding_market_data_loop, name="funding_market_data", daemon=True
            )
            _funding_market_data_thread.start()
            sys.stderr.write(
                f"[backend_server] Funding for market_data started (every {FUNDING_MARKET_DATA_INTERVAL_SECONDS}s)\n"
            )
        # Funding fee history: first sync 90 days, then hourly append -> funding_fee_history.csv
        if _funding_fee_history_thread is None or not _funding_fee_history_thread.is_alive():
            _funding_fee_history_stop.clear()
            _funding_fee_history_thread = threading.Thread(
                target=_funding_fee_history_loop, name="funding_fee_history", daemon=True
            )
            _funding_fee_history_thread.start()
            sys.stderr.write(
                f"[backend_server] Funding fee history started (hourly append only; run scripts/fetch_funding_fee_90d.py for 90d fetch)\n"
            )
        # Real-time order status: Binance User Data Stream -> order_status_audit.csv (ORDER_TRADE_UPDATE)
        try:
            _scripts = ROOT / "scripts"
            if str(_scripts) not in sys.path:
                sys.path.insert(0, str(_scripts))
            import binance_order_status_ws as _order_ws
            _order_ws_thread = threading.Thread(
                target=lambda: _order_ws.run_order_status_ws(silent=True),
                name="binance_order_status_ws",
                daemon=True,
            )
            _order_ws_thread.start()
            sys.stderr.write("[backend_server] Binance order status WebSocket started (ORDER_TRADE_UPDATE -> order_status_audit.csv)\n")
        except Exception as e:
            sys.stderr.write(f"[backend_server] Order status WebSocket not started (install websocket-client if needed): {e}\n")
    else:
        sys.stderr.write("[backend_server] RUN_FETCH_LOOPS=false: positions/market/order/funding fetch loops and order-status WebSocket are disabled.\n")
    app.run(host="127.0.0.1", port=port, debug=True)

