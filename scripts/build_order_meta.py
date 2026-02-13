#!/usr/bin/env python3
"""
Build / update order meta table for Binance USD-M symbols.

Reads:
- data/binance/positions.csv  (coins we care about, with maxLeverage, binanceUsdm)

Calls Binance (public):
- GET /fapi/v1/exchangeInfo        -> lot size (stepSize) per symbol

Writes:
- data/binance/orders/order_meta.csv

Columns:
- currency
- quantity_precision   (derived from LOT_SIZE.stepSize)
- max_size_usdt        (default 1000 if empty)
- min_size_usdt        (default 0)
- order_type           (MARKET for now)
- enabled_trade        (true by default)
- default_lever        (min(maxLeverage, 10) if available)
- notes
"""

import csv
import sys
from pathlib import Path
from typing import Dict

import requests


from env_manager import BINANCE_FUTURES_BASE, DATA_BINANCE

POSITIONS_CSV = DATA_BINANCE / "positions.csv"
META_CSV = DATA_BINANCE / "orders" / "order_meta.csv"


def _read_positions() -> Dict[str, Dict[str, str]]:
    coins: Dict[str, Dict[str, str]] = {}
    if not POSITIONS_CSV.exists():
        print(f"positions.csv not found at {POSITIONS_CSV}", file=sys.stderr)
        return coins
    with open(POSITIONS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            coin = (row.get("coin") or "").strip().upper()
            if not coin:
                continue
            # Only keep coins that are tradable on Binance USD-M
            if (row.get("binanceUsdm") or "").strip().lower() not in ("yes", "true", "1"):
                continue
            coins[coin] = row
    return coins


def _read_existing_meta() -> Dict[str, Dict[str, str]]:
    if not META_CSV.exists():
        return {}
    out: Dict[str, Dict[str, str]] = {}
    with open(META_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur = (row.get("currency") or "").strip().upper()
            if not cur:
                continue
            out[cur] = row
    return out


def _fetch_exchange_info() -> Dict[str, dict]:
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/exchangeInfo"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    symbols: Dict[str, dict] = {}
    for s in data.get("symbols", []):
        sym = s.get("symbol")
        if not sym:
            continue
        symbols[str(sym)] = s
    return symbols


def _precision_from_step(step: str) -> int:
    """Convert LOT_SIZE.stepSize string to decimal precision."""
    step = step.strip()
    if "." not in step:
        return 0
    frac = step.rstrip("0").split(".")[1]
    return len(frac)


def build_meta() -> None:
    coins = _read_positions()
    if not coins:
        print("No coins from positions.csv (or none with binanceUsdm=yes). Nothing to do.")
        return

    existing = _read_existing_meta()
    symbols = _fetch_exchange_info()

    header = [
        "currency",
        "quantity_precision",
        "max_size_usdt",
        "min_size_usdt",
        "order_type",
        "enabled_trade",
        "default_lever",
        "notes",
    ]
    rows = []

    for coin, pos_row in coins.items():
        symbol = coin + "USDT"
        meta = existing.get(coin, {})

        # quantity_precision from LOT_SIZE.stepSize
        qp = (meta.get("quantity_precision") or "").strip()
        if not qp:
            ex_sym = symbols.get(symbol)
            if ex_sym:
                step = None
                for flt in ex_sym.get("filters", []):
                    if flt.get("filterType") == "LOT_SIZE":
                        step = flt.get("stepSize")
                        break
                if step:
                    try:
                        qp = str(_precision_from_step(str(step)))
                    except Exception:
                        qp = ""

        # default sizes
        max_size = (meta.get("max_size_usdt") or "").strip() or "1000"
        min_size = (meta.get("min_size_usdt") or "").strip() or "0"

        # order type & enabled
        order_type = (meta.get("order_type") or "MARKET").strip().upper()
        enabled_trade = (meta.get("enabled_trade") or "true").strip().lower()

        # default leverage from positions maxLeverage, capped at 10
        def_lever = (meta.get("default_lever") or "").strip()
        if not def_lever:
            max_lev_str = (pos_row.get("maxLeverage") or "").strip()
            try:
                max_lev = int(max_lev_str)
                def_lever = str(min(max_lev, 10))
            except Exception:
                def_lever = "5"

        notes = meta.get("notes") or ""

        row = {
            "currency": coin,
            "quantity_precision": qp,
            "max_size_usdt": max_size,
            "min_size_usdt": min_size,
            "order_type": order_type or "MARKET",
            "enabled_trade": enabled_trade or "true",
            "default_lever": def_lever,
            "notes": notes,
        }
        rows.append(row)

    META_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(META_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote order meta for {len(rows)} currencies to {META_CSV}")


def main(argv: list[str]) -> None:
    build_meta()


if __name__ == "__main__":
    main(sys.argv)

