#!/usr/bin/env python3
"""
Bootstrap data/binance/backup/market_supply.csv with circulating_supply and total_supply
per currency. Used by the backend to compute fdv(USDT) and 流通市值(USDT) on each market_data refresh.
Uses a static mapping for major coins; run once to create the file. Empty supply rows are
written for other symbols so the backend can merge by currency; FDV/流通市值 stay empty until
supply is added (e.g. from CoinGecko/CMC or manual edit).
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from typing import Dict, Tuple, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_BINANCE = ROOT / "data" / "binance"
MARKET_DATA_PATH = DATA_BINANCE / "market_data.csv"
SUPPLY_PATH = DATA_BINANCE / "backup" / "market_supply.csv"

try:
    import requests  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    requests = None  # type: ignore[assignment]

# Optional manual overrides for difficult symbols (e.g. 1000PEPE contracts).
# The script will first try to fetch supply dynamically from CoinGecko; if that
# fails for a given base symbol it falls back to this mapping.
# Base symbol (no USDT, no 1000 prefix unless intentionally kept) -> (circulating_supply, total_supply).
# total_supply None = use circulating as proxy for FDV where no max cap.
SUPPLY_BY_BASE: dict[str, tuple[float | None, float | None]] = {
    "BTC": (19_500_000, 21_000_000),
    "ETH": (120_000_000, None),
    "BNB": (153_000_000, 200_000_000),
    "SOL": (460_000_000, 580_000_000),
    "XRP": (55_000_000_000, 100_000_000_000),
    "ADA": (36_000_000_000, 45_000_000_000),
    "DOGE": (144_000_000_000, 144_000_000_000),
    "AVAX": (440_000_000, 720_000_000),
    "DOT": (1_400_000_000, 1_400_000_000),
    "LINK": (600_000_000, 1_000_000_000),
    "MATIC": (9_800_000_000, 10_000_000_000),
    "POL": (9_800_000_000, 10_000_000_000),
    "SHIB": (589_000_000_000_000, 589_000_000_000_000),
    "LTC": (74_000_000, 84_000_000),
    "BCH": (19_600_000, 21_000_000),
    "UNI": (750_000_000, 1_000_000_000),
    "ATOM": (390_000_000, None),
    "XLM": (28_000_000_000, 50_000_000_000),
    "ETC": (147_000_000, 210_700_000),
    "NEAR": (1_000_000_000, None),
    "APT": (400_000_000, 1_000_000_000),
    "SUI": (1_300_000_000, 10_000_000_000),
    "OP": (1_100_000_000, 4_294_967_296),
    "ARB": (3_200_000_000, 10_000_000_000),
    "INJ": (98_000_000, 100_000_000),
    "PEPE": (420_690_000_000_000, 420_690_000_000_000),
    "WIF": (1_000_000_000, 1_000_000_000),
    "BONK": (93_000_000_000_000, 93_000_000_000_000),
    "FLOKI": (9_500_000_000_000, 9_700_000_000_000),
    "AAVE": (14_700_000, 16_000_000),
    "MKR": (1_000_000, 1_000_000),
    "CRV": (900_000_000, 3_300_000_000),
    "LDO": (930_000_000, 1_000_000_000),
    "RUNE": (330_000_000, 500_000_000),
    "FTM": (3_100_000_000, 3_175_000_000),
    "ALGO": (8_200_000_000, 10_000_000_000),
    "VET": (72_700_000_000, 86_700_000_000),
    "FIL": (200_000_000, 2_000_000_000),
    "HBAR": (36_000_000_000, 50_000_000_000),
    "ICP": (460_000_000, 469_000_000),
    "RENDER": (380_000_000, 536_000_000),
    "FET": (2_500_000_000, 2_630_000_000),
    "TAO": (7_000_000, 21_000_000),
    "WLD": (1_000_000_000, 10_000_000_000),
    "JUP": (1_350_000_000, 10_000_000_000),
    "STRK": (728_000_000, 10_000_000_000),
    "ZK": (3_670_000_000, 10_000_000_000),
    "SEI": (2_800_000_000, 10_000_000_000),
    "TIA": (1_000_000_000, 1_000_000_000),
    "TON": (5_100_000_000, 5_100_000_000),
    "STX": (1_500_000_000, 1_818_000_000),
    "XMR": (18_400_000, 18_400_000),
    "ZEC": (16_300_000, 21_000_000),
    "TRX": (88_000_000_000, 99_000_000_000),
    "THETA": (1_000_000_000, 1_000_000_000),
    "EGLD": (26_000_000, 31_000_000),
    "KAVA": (900_000_000, None),
    "DYDX": (210_000_000, 1_000_000_000),
    "GMX": (12_000_000, 13_250_000),
    "EIGEN": (1_000_000_000, 1_670_000_000),
    "1000PEPE": (420_690_000_000_000, 420_690_000_000_000),
    "1000SHIB": (589_000_000_000_000, 589_000_000_000_000),
    "1000FLOKI": (9_500_000_000_000, 9_700_000_000_000),
    "1000BONK": (93_000_000_000_000, 93_000_000_000_000),
}


COINGECKO_API_BASE = "https://api.coingecko.com/api/v3"


def _fetch_coingecko_symbol_map() -> Dict[str, list[str]]:
    """
    Build a map SYMBOL -> [coin_id, ...] from CoinGecko.

    We fetch the full list once and then reuse it for all lookups. This is
    best-effort only; if the request fails we return an empty map and the
    caller will fall back to SUPPLY_BY_BASE / empty supplies.
    """
    if requests is None:
        return {}

    try:
        resp = requests.get(
            f"{COINGECKO_API_BASE}/coins/list",
            params={"include_platform": "false"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # pragma: no cover - network / API failure
        print(f"Warning: failed to fetch CoinGecko coin list: {e}", file=sys.stderr)
        return {}

    by_symbol: Dict[str, list[str]] = {}
    for item in data:
        sym = (item.get("symbol") or "").strip().upper()
        cid = (item.get("id") or "").strip()
        if not sym or not cid:
            continue
        by_symbol.setdefault(sym, []).append(cid)
    return by_symbol


# Canonical CoinGecko ids for major coins (symbol -> id). Multiple coins can share
# a symbol (e.g. "btc" returns a wrapped token); we prefer the main asset.
PREFERRED_COINGECKO_IDS: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "POL": "matic-network",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ETC": "ethereum-classic",
    "NEAR": "near",
    "APT": "aptos",
    "SUI": "sui",
    "OP": "optimism",
    "ARB": "arbitrum",
    "INJ": "injective-protocol",
    "TON": "the-open-network",
    "STX": "blockstack",
    "XMR": "monero",
    "ZEC": "zcash",
    "TRX": "tron",
    "HBAR": "hedera-hashgraph",
    "FIL": "filecoin",
    "ICP": "internet-computer",
    "VET": "vechain",
    "ALGO": "algorand",
    "FTM": "fantom",
    "AAVE": "aave",
    "MKR": "maker",
    "CRV": "curve-dao-token",
    "LDO": "lido-dao",
    "RUNE": "thorchain",
    "WLD": "worldcoin-wld",
    "SEI": "sei-network",
    "TIA": "celestia",
    "JUP": "jupiter-exchange-solana",
    "STRK": "starknet",
    "ZK": "zksync",
    "EIGEN": "eigenlayer",
}


def _choose_coingecko_id(symbol: str, ids: list[str]) -> str:
    """
    Heuristically pick the best CoinGecko id for a given symbol.

    Prefer:
    - PREFERRED_COINGECKO_IDS[symbol] if present in ids (canonical main asset)
    - exact id == lowercased symbol
    - otherwise the first id in the list.
    """
    sym_upper = (symbol or "").strip().upper()
    preferred = PREFERRED_COINGECKO_IDS.get(sym_upper)
    if preferred and preferred in ids:
        return preferred
    sym_lower = symbol.lower()
    for cid in ids:
        if cid.lower() == sym_lower:
            return cid
    return ids[0]


def _fetch_supply_from_coingecko(
    base_symbol: str,
    symbol_map: Dict[str, list[str]],
    *,
    throttle_seconds: float = 1.2,
) -> tuple[Optional[float], Optional[float]]:
    """
    Best-effort fetch of (circulating_supply, total_supply/max_supply) from CoinGecko.

    Returns (None, None) on any error or if the symbol cannot be mapped.
    """
    if requests is None:
        return None, None

    sym = (base_symbol or "").strip().upper()
    if not sym:
        return None, None

    # For 1000-prefixed contracts (e.g. 1000PEPEUSDT), try mapping to the
    # underlying token symbol first so we get better CoinGecko matches.
    lookup_sym = sym
    if lookup_sym.startswith("1000000"):
        lookup_sym = lookup_sym[7:]
    elif lookup_sym.startswith("1000"):
        lookup_sym = lookup_sym[4:]

    ids = symbol_map.get(lookup_sym) or symbol_map.get(sym)
    if not ids:
        return None, None

    coin_id = _choose_coingecko_id(lookup_sym, ids)

    try:
        resp = requests.get(
            f"{COINGECKO_API_BASE}/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
            timeout=30,
        )
        # Be gentle with the public API.
        time.sleep(throttle_seconds)
        resp.raise_for_status()
        data = resp.json()
        md = data.get("market_data") or {}
        circ = md.get("circulating_supply")
        total = md.get("max_supply") or md.get("total_supply")
        circ_f = float(circ) if circ is not None else None
        total_f = float(total) if total is not None else None
        return circ_f, total_f
    except Exception as e:  # pragma: no cover - network / API failure
        print(
            f"Warning: failed to fetch supply for {base_symbol} (CoinGecko id={coin_id}): {e}",
            file=sys.stderr,
        )
        return None, None


def _base_symbol(currency: str) -> str:
    """BTCUSDT -> BTC, 1000PEPEUSDT -> 1000PEPE (keep prefix for SUPPLY_BY_BASE), 1000000MOGUSDT -> MOG."""
    s = (currency or "").strip().upper()
    if not s or not s.endswith("USDT"):
        return s
    base = s[:-4]
    if base.startswith("1000000"):
        base = base[7:]
    elif base.startswith("1000"):
        # Keep 1000PEPE / 1000SHIB etc. for lookup
        pass
    return base


def main() -> int:
    if not MARKET_DATA_PATH.exists():
        print(f"Missing {MARKET_DATA_PATH}", file=sys.stderr)
        return 1

    print("[fill_market_supply] Loading CoinGecko symbol map...", file=sys.stderr)
    symbol_map = _fetch_coingecko_symbol_map()
    print(
        f"[fill_market_supply] CoinGecko symbol map size: {len(symbol_map)} entries",
        file=sys.stderr,
    )

    supply_cache: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    source_cache: Dict[str, str] = {}

    coingecko_count = 0
    override_count = 0
    empty_count = 0

    rows: list[dict] = []
    with open(MARKET_DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            cur = (row.get("currency") or "").strip()
            if not cur:
                continue
            base = _base_symbol(cur)
            circ: Optional[float]
            total: Optional[float]
            source: str

            # Cache lookups so we only hit CoinGecko once per base symbol.
            # Use static overrides first for symbols we know (avoids wrong CoinGecko matches).
            if base in supply_cache:
                circ, total = supply_cache[base]
                source = source_cache.get(base, "cache")
            else:
                override = SUPPLY_BY_BASE.get(base)
                if isinstance(override, tuple):
                    circ, total = override
                    source = "override"
                else:
                    cg_circ, cg_total = _fetch_supply_from_coingecko(base, symbol_map)
                    circ, total = cg_circ, cg_total
                    source = "coingecko" if (cg_circ is not None or cg_total is not None) else "empty"
                supply_cache[base] = (circ, total)
                source_cache[base] = source

            if source == "coingecko":
                coingecko_count += 1
            elif source == "override":
                override_count += 1
            else:
                empty_count += 1

            if idx % 50 == 0:
                print(
                    f"[fill_market_supply] Processed {idx} market_data rows "
                    f"(coingecko={coingecko_count}, overrides={override_count}, empty={empty_count})",
                    file=sys.stderr,
                )

            rows.append({
                "currency": cur,
                "circulating_supply": f"{circ:.0f}" if circ is not None else "",
                "total_supply": f"{total:.0f}" if total is not None else "",
            })

    SUPPLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SUPPLY_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["currency", "circulating_supply", "total_supply"])
        w.writeheader()
        w.writerows(rows)

    filled = sum(1 for r in rows if (r.get("circulating_supply") or "").strip())
    print(
        "[fill_market_supply] Done. "
        f"rows={len(rows)}, with_supply={filled}, "
        f"coingecko={coingecko_count}, overrides={override_count}, empty={empty_count}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
