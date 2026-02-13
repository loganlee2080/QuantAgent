#!/usr/bin/env python3
"""
Crawl Binance USD-M futures positions and account, mirroring Hyperliquid position table.
One row per tick in TICK_LIST (position = 0 if flat).
Output: data/binance/positions.csv, summary.csv, account.json.
Env: BINANCE_API_KEY, BINANCE_API_SECRET (from environment or .env in project root).
Ref: https://github.com/binance/binance-connector-python (implementation uses requests + HMAC).
"""

import csv
import hashlib
import hmac
import json
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import trunc
from pathlib import Path
from typing import List, Optional, Union

import requests

from env_manager import (
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_PUBLIC_BASE,
    BINANCE_FUNDING_LOOKBACK_DAYS,
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    DATA_BINANCE,
)

# Coins to track (one row each; no position → szi=0).
# Only include symbols with Binance USD‑M futures support.
TICK_LIST = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK",
    "LTC", "BCH", "DOT", "ATOM", "TON", "NEAR", "ETC", "XLM", "ICP", "FIL",
    "APT", "SUI", "WIF", "ARB", "OP", "IMX", "INJ", "RENDER", "TAO", "KAS",
    "GALA", "AAVE", "UNI", "LDO", "MKR", "SNX", "DYDX", "TIA", "WLD", "ENA",
    "JASMY", "SEI", "STRK", "PYTH", "BLUR", "PENDLE", "GMX", "ROSE",
]

# Hyperliquid-mirror column order + extra market fields
POSITION_FIELDS = [
    "coin",
    "szi",
    "direct",
    "leverage_type",
    "leverage_value",
    "entryPx",
    "positionValue",
    "unrealizedPnl",
    "returnOnEquity",
    "liquidationPx",
    "marginUsed",
    "marginUsedPercentage",
    "maxLeverage",
    "cumFunding_allTime",
    "cumFunding_sinceOpen",
    "cumFunding_sinceChange",
    "time",
    "lastFundingRate",
    "markPrice",
    "volume24h(USDT)",
    "openInterest(USDT)",
    "maxPositionAtMaxLeverage(USDT)",
    "maxPositionCurLeverage",
    "maxAvailablePositionOpen(USDT)",
    "binanceUsdm",
]


def _binance_signed_get(api_key: str, api_secret: str, path: str, params: Optional[dict] = None) -> Union[dict, list]:
    """GET a Binance USD-M private endpoint with HMAC signature."""
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{BINANCE_FUTURES_BASE}{path}?{qs}&signature={sig}"
    r = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=15)
    r.raise_for_status()
    return r.json()


def get_binance_income_history(
    api_key: str,
    api_secret: str,
    income_type: Optional[str] = None,
    symbol: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    limit: int = 1000,
) -> List[dict]:
    """
    GET /fapi/v1/income.

    Used here to aggregate cumulative funding fees per symbol.
    Note: Binance only keeps the last ~3 months of income history.
    """
    params: dict = {}
    if income_type is not None:
        params["incomeType"] = income_type
    if symbol is not None:
        params["symbol"] = symbol
    if start_time is not None:
        params["startTime"] = int(start_time)
    if end_time is not None:
        params["endTime"] = int(end_time)
    if limit:
        params["limit"] = int(limit)
    res = _binance_signed_get(api_key, api_secret, "/fapi/v1/income", params)
    # API returns a JSON array
    return list(res or [])


def get_binance_account(api_key: str, api_secret: str) -> dict:
    """GET /fapi/v2/account."""
    return _binance_signed_get(api_key, api_secret, "/fapi/v2/account")


def get_binance_position_risk(api_key: str, api_secret: str) -> List[dict]:
    """GET /fapi/v2/positionRisk."""
    return _binance_signed_get(api_key, api_secret, "/fapi/v2/positionRisk")


def get_binance_premium_index() -> List[dict]:
    """GET /fapi/v1/premiumIndex (public). Returns lastFundingRate, markPrice per symbol. Uses public base (mainnet) so testnet 503/empty don't leave lastFundingRate blank."""
    r = requests.get(BINANCE_FUTURES_PUBLIC_BASE + "/fapi/v1/premiumIndex", timeout=15)
    r.raise_for_status()
    return r.json()


def get_binance_ticker_24hr() -> List[dict]:
    """GET /fapi/v1/ticker/24hr (public). Returns volume per symbol."""
    r = requests.get(BINANCE_FUTURES_PUBLIC_BASE + "/fapi/v1/ticker/24hr", timeout=15)
    r.raise_for_status()
    return r.json()


def get_binance_open_interest(symbol: str) -> dict:
    """GET /fapi/v1/openInterest (public). Returns openInterest for symbol."""
    r = requests.get(BINANCE_FUTURES_PUBLIC_BASE + "/fapi/v1/openInterest", params={"symbol": symbol}, timeout=15)
    r.raise_for_status()
    return r.json()


def get_binance_leverage_bracket(api_key: str, api_secret: str) -> list:
    """GET /fapi/v1/leverageBracket (signed). Returns max leverage per symbol via brackets."""
    return _binance_signed_get(api_key, api_secret, "/fapi/v1/leverageBracket")


def _usdt_notional(amount_str: str, mark_price_str: str) -> str:
    """Compute amount * markPrice for USDT notional. Returns "" if either missing or invalid."""
    if not amount_str or not mark_price_str:
        return ""
    try:
        return str(float(amount_str) * float(mark_price_str))
    except (TypeError, ValueError):
        return ""


def _parse_max_leverage_from_brackets(bracket_list: list) -> dict:
    """Build symbol -> maxLeverage from leverageBracket response (max of initialLeverage in brackets)."""
    out = {}
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
            out[sym] = str(max_lev)
    return out


def _supported_usdt_symbols_from_brackets(bracket_list: list) -> set:
    """Set of USDT symbol strings that Binance USD-M supports (from leverageBracket)."""
    return {str(item["symbol"]) for item in bracket_list if item.get("symbol")}


def _parse_max_position_at_max_leverage_from_brackets(bracket_list: list) -> dict:
    """Build symbol -> notionalCap (USDT) of the bracket with max initialLeverage (max position at max leverage)."""
    out = {}
    for item in bracket_list:
        sym = item.get("symbol")
        if not sym:
            continue
        brackets = item.get("brackets") or []
        best_cap = None
        best_lev = 0
        for b in brackets:
            L = b.get("initialLeverage")
            cap = b.get("notionalCap")
            if L is not None and cap is not None:
                try:
                    lev = int(L)
                    cap_val = float(cap)
                    if lev > best_lev or (lev == best_lev and (best_cap is None or cap_val > best_cap)):
                        best_lev = lev
                        best_cap = cap_val
                except (TypeError, ValueError):
                    pass
        if best_cap is not None:
            out[sym] = str(int(best_cap))
    return out


def _empty_row(
    coin: str,
    last_funding_rate: Optional[str] = None,
    mark_price: Optional[str] = None,
    volume_24h: Optional[str] = None,
    open_interest: Optional[str] = None,
    max_leverage: Optional[str] = None,
    max_position_at_max_leverage: Optional[str] = None,
    binance_usdm: Optional[str] = None,
) -> dict:
    row = {f: "" for f in POSITION_FIELDS} | {"coin": coin, "szi": "0", "direct": "", "leverage_type": "cross", "leverage_value": "0"}
    if last_funding_rate is not None:
        row["lastFundingRate"] = last_funding_rate
    if mark_price is not None:
        row["markPrice"] = mark_price
    if volume_24h is not None:
        row["volume24h(USDT)"] = volume_24h
    if open_interest is not None:
        row["openInterest(USDT)"] = open_interest
    if max_leverage is not None:
        row["maxLeverage"] = max_leverage
    if max_position_at_max_leverage is not None:
        row["maxPositionAtMaxLeverage(USDT)"] = max_position_at_max_leverage
    if binance_usdm is not None:
        row["binanceUsdm"] = binance_usdm
    return row


def _row_from_binance_position(
    pos: dict,
    total_margin_used: float,
    last_funding_rate: Optional[str] = None,
    cum_funding_all_time: Optional[str] = None,
    mark_price_override: Optional[str] = None,
    volume_24h: Optional[str] = None,
    open_interest: Optional[str] = None,
    max_leverage: Optional[str] = None,
    max_position_at_max_leverage: Optional[str] = None,
    binance_usdm: Optional[str] = None,
) -> dict:
    """Map Binance position to Hyperliquid-mirror row."""
    position_amt = float(pos.get("positionAmt", 0) or 0)
    entry_price = float(pos.get("entryPrice", 0) or 0)
    mark_price_val = float(pos.get("markPrice", 0) or 0)
    mark_price_str = mark_price_override if mark_price_override is not None else (str(mark_price_val) if mark_price_val else "")
    notional = abs(float(pos.get("notional", 0) or 0))
    if notional == 0 and position_amt != 0 and mark_price_val:
        notional = abs(position_amt * mark_price_val)
    leverage = int(pos.get("leverage", 1) or 1)
    if leverage <= 0:
        leverage = 1
    margin_used = notional / leverage
    if pos.get("marginType") == "isolated" and pos.get("isolatedMargin"):
        margin_used = float(pos.get("isolatedMargin", 0) or 0)
    un_realized = float(pos.get("unRealizedProfit", 0) or 0)
    # ROE = Unrealized PnL / Position (notional)
    roe = (un_realized / notional) if notional else ""
    liq = pos.get("liquidationPrice") or ""
    if liq != "":
        try:
            liq = str(float(liq))
        except (TypeError, ValueError):
            pass
    # marginUsedPercentage: truncate to 2 decimals
    if total_margin_used and total_margin_used > 0 and margin_used is not None:
        pct = margin_used / total_margin_used * 100
        pct_str = f"{trunc(pct * 100) / 100:.2f}"
    else:
        pct_str = ""
    direction = ""
    if position_amt > 0:
        direction = "Long"
    elif position_amt < 0:
        direction = "Short"

    # szi is always >= 0 (size); direction is in direct (Long/Short)
    szi_val = abs(position_amt) if position_amt else 0
    # maxPositionCurLeverage = max_position_at_max_leverage * (leverage / max_leverage); maxAvailablePositionOpen = maxPositionCurLeverage - currentPosition (USDT)
    max_at_current_str = ""
    max_available = ""
    if max_position_at_max_leverage and max_leverage:
        try:
            max_at_max = float(max_position_at_max_leverage)
            max_lev = int(max_leverage)
            if max_lev > 0 and max_at_max >= 0:
                max_at_current = max_at_max * (leverage / max_lev)
                max_at_current_str = f"{max_at_current:.2f}".rstrip("0").rstrip(".")
                if notional is not None:
                    avail = max_at_current - notional
                    max_available = f"{max(0, avail):.2f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            pass
    return {
        "coin": (pos.get("symbol") or "").replace("USDT", ""),
        "szi": str(szi_val),
        "direct": direction,
        "leverage_type": str(pos.get("marginType") or "cross").lower(),
        "leverage_value": str(leverage),
        "entryPx": str(entry_price) if entry_price else "",
        "positionValue": str(notional) if notional else "",
        "unrealizedPnl": str(un_realized) if un_realized else "",
        "returnOnEquity": str(roe) if roe != "" else "",
        "liquidationPx": liq,
        "marginUsed": str(margin_used) if margin_used else "",
        "marginUsedPercentage": pct_str,
        "maxLeverage": max_leverage if max_leverage is not None else str(leverage),
        "cumFunding_allTime": cum_funding_all_time if cum_funding_all_time is not None else "",
        "cumFunding_sinceOpen": "",
        "cumFunding_sinceChange": "",
        "time": pos.get("updateTime") or "",
        "lastFundingRate": last_funding_rate if last_funding_rate is not None else "",
        "markPrice": mark_price_str,
        "volume24h(USDT)": volume_24h if volume_24h is not None else "",
        "openInterest(USDT)": open_interest if open_interest is not None else "",
        "maxPositionAtMaxLeverage(USDT)": max_position_at_max_leverage if max_position_at_max_leverage is not None else "",
        "maxPositionCurLeverage": max_at_current_str,
        "maxAvailablePositionOpen(USDT)": max_available,
        "binanceUsdm": binance_usdm if binance_usdm is not None else "yes",
    }


def main(use_testnet: bool = False) -> None:
    global BINANCE_FUTURES_BASE
    if use_testnet:
        BINANCE_FUTURES_BASE = "https://demo-fapi.binance.com"
        print("Using Binance USD-M TESTNET (demo-fapi)...")

    api_key = BINANCE_API_KEY
    api_secret = BINANCE_API_SECRET
    if api_key:
        # Masked print so we can verify which key is in use without leaking it
        print(f"Using Binance key: {api_key[:4]}***{api_key[-4:]}")

    if not api_key or not api_secret:
        print(
            "Set BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_API_*) in environment.\n"
            "If using .zshrc: use 'export BINANCE_API_KEY=...' and run this script from a terminal.\n"
            "Or add them to a .env file in the project root (optional: pip install python-dotenv).",
            file=sys.stderr,
        )
        sys.exit(1)

    # 1) Binance account + position risk
    print("Fetching Binance USD-M account and positions...")
    try:
        account = get_binance_account(api_key, api_secret)
        position_risk = get_binance_position_risk(api_key, api_secret)
        print(f"position_risk: {position_risk}")
    except Exception as e:
        print(f"Binance error: {e}", file=sys.stderr)
        sys.exit(1)

    # Total margin used (cross): from account totalPositionInitialMargin or similar
    total_initial_margin = float(account.get("totalPositionInitialMargin", 0) or 0)
    total_margin_used = total_initial_margin

    # Build map: base symbol -> Binance position (only non-zero)
    pos_by_base: dict[str, dict] = {}
    for p in position_risk:
        amt = float(p.get("positionAmt", 0) or 0)
        if amt == 0:
            continue
        sym = (p.get("symbol") or "").replace("USDT", "")
        pos_by_base[sym] = p

    # Optional 1b) Cumulative funding fee per symbol over a configurable lookback window.
    # This uses /fapi/v1/income with incomeType=FUNDING_FEE and sums all entries for each symbol.
    print("Fetching cumulative funding fees per symbol (this may take a few seconds)...")

    def _cumulative_funding_for_symbol(usdt_symbol: str, start_time_ms: int) -> str:
        """Sum FUNDING_FEE income for a symbol from start_time_ms to now."""
        total = 0.0
        cursor = start_time_ms
        while True:
            try:
                batch = get_binance_income_history(
                    api_key,
                    api_secret,
                    income_type="FUNDING_FEE",
                    symbol=usdt_symbol,
                    start_time=cursor,
                    end_time=None,
                    limit=1000,
                )
            except Exception as e:
                print(f"Warning: could not fetch income history for {usdt_symbol}: {e}", file=sys.stderr)
                break
            if not batch:
                break
            max_time = None
            for item in batch:
                try:
                    inc = float(item.get("income", 0) or 0)
                    total += inc
                except (TypeError, ValueError):
                    continue
                t = item.get("time")
                if t is not None:
                    try:
                        t_int = int(t)
                    except (TypeError, ValueError):
                        continue
                    if max_time is None or t_int > max_time:
                        max_time = t_int
            # If we got fewer than the limit or we couldn't advance the cursor, we're done.
            if len(batch) < 1000 or max_time is None or max_time <= cursor:
                break
            cursor = max_time + 1
            # Small sleep to be polite with API rate limits.
            time.sleep(0.1)
        return str(total)

    now_ms = int(time.time() * 1000)
    lookback_ms = now_ms - BINANCE_FUNDING_LOOKBACK_DAYS * 24 * 60 * 60 * 1000
    cum_funding_by_symbol: dict[str, str] = {}

    # Fetch cumulative funding per symbol in parallel to speed things up (only for symbols with positions).
    symbols_with_pos = [base_sym + "USDT" for base_sym in pos_by_base.keys()]

    def _funding_task(usdt_symbol: str) -> tuple[str, str]:
        return usdt_symbol, _cumulative_funding_for_symbol(usdt_symbol, lookback_ms)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_funding_task, s) for s in symbols_with_pos]
        for fut in as_completed(futures):
            try:
                usdt_sym, total_str = fut.result()
                cum_funding_by_symbol[usdt_sym] = total_str
            except Exception as e:
                print(f"Warning: funding task failed: {e}", file=sys.stderr)

    # Market data (public APIs): funding, mark price, 24h volume, open interest, max leverage
    print("Fetching funding rates and mark prices...")
    funding_by_symbol = {}
    mark_price_by_symbol = {}
    try:
        premium_index = get_binance_premium_index()
        for item in premium_index:
            s = item.get("symbol")
            if s is None:
                continue
            s = str(s)
            if item.get("lastFundingRate") is not None:
                funding_by_symbol[s] = str(item["lastFundingRate"])
            if item.get("markPrice") is not None:
                mark_price_by_symbol[s] = str(item["markPrice"])
    except Exception as e:
        print("Warning: could not fetch premium index:", e, file=sys.stderr)

    print("Fetching 24h volume...")
    volume24h_by_symbol = {}
    try:
        ticker_24 = get_binance_ticker_24hr()
        for item in ticker_24:
            s = item.get("symbol")
            v = item.get("volume")
            if s is not None and v is not None:
                volume24h_by_symbol[str(s)] = str(v)
    except Exception as e:
        print("Warning: could not fetch 24h ticker:", e, file=sys.stderr)

    print("Fetching leverage brackets (max leverage, max position at max lev, supported symbols)...")
    max_leverage_by_symbol = {}
    max_position_at_max_lev_by_symbol = {}
    supported_usdt_symbols = set()
    try:
        bracket_list = get_binance_leverage_bracket(api_key, api_secret)
        max_leverage_by_symbol = _parse_max_leverage_from_brackets(bracket_list)
        max_position_at_max_lev_by_symbol = _parse_max_position_at_max_leverage_from_brackets(bracket_list)
        supported_usdt_symbols = _supported_usdt_symbols_from_brackets(bracket_list)
    except Exception as e:
        print("Warning: could not fetch leverage brackets:", e, file=sys.stderr)

    # Determine which base symbols to track in positions.csv.
    # Union of static TICK_LIST and all bases that currently have positions (from positionRisk),
    # so that newly-opened pairs like HYPE are always included.
    tracked_bases = sorted(set(TICK_LIST) | set(pos_by_base.keys()))

    print("Fetching open interest per symbol (parallel)...")
    open_interest_by_symbol = {}

    def _fetch_oi(usdt: str):
        try:
            oi = get_binance_open_interest(usdt)
            val = oi.get("openInterest")
            return (usdt, str(val) if val is not None else None)
        except Exception:
            return (usdt, None)

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(_fetch_oi, s + "USDT") for s in tracked_bases]
        for future in as_completed(futures):
            usdt, val = future.result()
            if val is not None:
                open_interest_by_symbol[usdt] = val

    # 2) One row per tick (Hyperliquid-mirror schema)
    # volume24h(USDT) = volume24h * markPrice; openInterest(USDT) = openInterest * markPrice
    rows = []
    for symbol in tracked_bases:
        usdt_symbol = symbol + "USDT"
        last_funding = funding_by_symbol.get(usdt_symbol, "")
        mark_px = mark_price_by_symbol.get(usdt_symbol, "")
        vol_24_raw = volume24h_by_symbol.get(usdt_symbol, "")
        oi_raw = open_interest_by_symbol.get(usdt_symbol, "")
        vol_24 = _usdt_notional(vol_24_raw, mark_px)
        oi = _usdt_notional(oi_raw, mark_px)
        max_lev = max_leverage_by_symbol.get(usdt_symbol, "")
        max_pos_at_max_lev = max_position_at_max_lev_by_symbol.get(usdt_symbol, "")
        binance_usdm = "yes" if usdt_symbol in supported_usdt_symbols else "no"
        if symbol in pos_by_base:
            cum_funding_all_time = cum_funding_by_symbol.get(usdt_symbol)
            row = _row_from_binance_position(
                pos_by_base[symbol],
                total_margin_used,
                last_funding_rate=last_funding or None,
                cum_funding_all_time=cum_funding_all_time,
                volume_24h=vol_24 or None,
                open_interest=oi or None,
                max_leverage=max_lev or None,
                max_position_at_max_leverage=max_pos_at_max_lev or None,
                binance_usdm=binance_usdm,
            )
        else:
            row = _empty_row(
                symbol,
                last_funding_rate=last_funding or None,
                mark_price=mark_px or None,
                volume_24h=vol_24 or None,
                open_interest=oi or None,
                max_leverage=max_lev or None,
                max_position_at_max_leverage=max_pos_at_max_lev or None,
                binance_usdm=binance_usdm,
            )
        rows.append(row)

    # 3) Write data/binance/
    DATA_BINANCE.mkdir(parents=True, exist_ok=True)

    positions_path = DATA_BINANCE / "positions.csv"
    with open(positions_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=POSITION_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {positions_path}")
    unsupported = [r["coin"] for r in rows if r.get("binanceUsdm") == "no"]
    if unsupported:
        print("Binance USD-M not supported for:", ", ".join(unsupported))

    # Account / margin summary (useful fields) with timestamp for PNL% tracking
    summary_fields = [
        "timestamp",
        "totalWalletBalance",
        "totalUnrealizedProfit",
        "totalMarginBalance",
        "totalPositionInitialMargin",
        "totalOpenOrderInitialMargin",
        "availableBalance",
        "maxWithdrawAmount",
    ]
    summary_row = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        **{k: account.get(k, "") for k in summary_fields if k != "timestamp"},
    }
    summary_path = DATA_BINANCE / "summary.csv"
    summary_exists = summary_path.exists()

    # If file exists but doesn't yet have a timestamp column, rewrite header and backfill blank timestamps.
    if summary_exists:
        with open(summary_path, newline="") as f:
            reader = csv.DictReader(f)
            existing_rows = list(reader)
            existing_fieldnames = reader.fieldnames or []
        if "timestamp" not in existing_fieldnames:
            with open(summary_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=summary_fields)
                w.writeheader()
                for row in existing_rows:
                    out = {k: "" for k in summary_fields}
                    for k in existing_fieldnames:
                        if k in out:
                            out[k] = row.get(k, "")
                    w.writerow(out)
            print(f"Rewrote existing summary file {summary_path} with timestamp column")

    with open(summary_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        if not summary_exists:
            w.writeheader()
        w.writerow(summary_row)
    print(f"Appended summary to {summary_path}")

    # Raw account JSON
    account_path = DATA_BINANCE / "account.json"
    with open(account_path, "w") as f:
        json.dump(account, f, indent=2)
    print(f"Saved raw account to {account_path}")

    # Print a few summary stats
    print("\nAccount summary (sample):")
    for k in summary_fields:
        v = account.get(k, "")
        if v != "":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    # Simple CLI flag: --testnet to use Binance USD-M testnet (demo-fapi.binance.com)
    use_testnet_flag = "--testnet" in sys.argv
    if use_testnet_flag:
        sys.argv = [arg for arg in sys.argv if arg != "--testnet"]
    main(use_testnet=use_testnet_flag)
    sys.exit(0)
