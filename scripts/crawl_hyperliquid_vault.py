#!/usr/bin/env python3
"""
Crawl positions data from a Hyperliquid vault and save to CSV.
Vault URL: https://app.hyperliquid.xyz/vaults/0xd6e56265890b76413d1d527eb9b75e334c0c5b42
Uses Hyperliquid Info API: clearinghouseState.
"""

import csv
import json
import sys
from math import trunc
from pathlib import Path

import requests


from env_manager import HYPERLIQUID_VAULT_ADDRESS, HYPERLIQUID_INFO_HOST

VAULT_ADDRESS = HYPERLIQUID_VAULT_ADDRESS
API_URLS = [
    f"{HYPERLIQUID_INFO_HOST}/info",
    HYPERLIQUID_INFO_HOST,
]


def fetch_vault_state(address: str) -> dict:
    """Fetch clearinghouse state for a vault address from Hyperliquid API."""
    payload = {"type": "clearinghouseState", "user": address}
    last_error = None
    for url in API_URLS:
        try:
            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_error = e
            continue
    raise RuntimeError(f"All API URLs failed. Last error: {last_error}") from last_error


def flatten_position(asset_pos: dict) -> dict:
    """Turn one assetPosition entry into a flat dict for CSV."""
    pos = asset_pos.get("position", {})
    lev = pos.get("leverage", {}) or {}
    cum = pos.get("cumFunding", {}) or {}
    return {
        "coin": pos.get("coin", ""),
        "szi": pos.get("szi", ""),
        "leverage_type": lev.get("type", ""),
        "leverage_value": lev.get("value", ""),
        "entryPx": pos.get("entryPx", ""),
        "positionValue": pos.get("positionValue", ""),
        "unrealizedPnl": pos.get("unrealizedPnl", ""),
        "returnOnEquity": pos.get("returnOnEquity", ""),
        "liquidationPx": pos.get("liquidationPx", ""),
        "marginUsed": pos.get("marginUsed", ""),
        "maxLeverage": pos.get("maxLeverage", ""),
        "cumFunding_allTime": cum.get("allTime", ""),
        "cumFunding_sinceOpen": cum.get("sinceOpen", ""),
        "cumFunding_sinceChange": cum.get("sinceChange", ""),
        "time": pos.get("time", ""),
    }


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent
    csv_path = out_dir / "data" / "hyperliquid_vault_positions.csv"

    print(f"Fetching vault state for {VAULT_ADDRESS}...")
    data = fetch_vault_state(VAULT_ADDRESS)

    # Optional: save raw JSON for debugging
    raw_path = out_dir / "data" / "hyperliquid_vault_state.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Raw state saved to {raw_path}")

    positions = data.get("assetPositions") or []
    margin = data.get("marginSummary") or {}
    cross = data.get("crossMarginSummary") or {}
    total_margin_used = (cross or margin).get("totalMarginUsed") or "0"
    try:
        total_margin_used_f = float(total_margin_used)
    except (TypeError, ValueError):
        total_margin_used_f = 0.0

    if not positions:
        print("No asset positions in response. Writing empty CSV with margin summary.")
        rows = []
    else:
        rows = [flatten_position(p) for p in positions]
        for row in rows:
            mu = row.get("marginUsed", "")
            try:
                pct = (float(mu) / total_margin_used_f * 100) if total_margin_used_f else ""
            except (TypeError, ValueError):
                pct = ""
            if pct != "":
                row["marginUsedPercentage"] = f"{trunc(pct * 100) / 100:.2f}"
            else:
                row["marginUsedPercentage"] = ""

    # CSV: positions
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = [
            "coin", "szi", "leverage_type", "leverage_value", "entryPx",
            "positionValue", "unrealizedPnl", "returnOnEquity", "liquidationPx",
            "marginUsed", "marginUsedPercentage", "maxLeverage", "cumFunding_allTime",
            "cumFunding_sinceOpen", "cumFunding_sinceChange", "time",
        ]

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} positions to {csv_path}")

    # Print margin summary
    if margin or cross:
        print("\nMargin summary:")
        for k, v in (margin or {}).items():
            print(f"  marginSummary.{k}: {v}")
        for k, v in (cross or {}).items():
            print(f"  crossMarginSummary.{k}: {v}")

    # Also write a one-line summary CSV (account-level) for easy time series
    summary_path = out_dir / "data" / "hyperliquid_vault_summary.csv"
    summary_exists = summary_path.exists()
    summary_fields = ["accountValue", "totalNtlPos", "totalRawUsd", "totalMarginUsed", "withdrawable"]
    summary_row = {
        "accountValue": (cross or margin).get("accountValue", ""),
        "totalNtlPos": (cross or margin).get("totalNtlPos", ""),
        "totalRawUsd": (cross or margin).get("totalRawUsd", ""),
        "totalMarginUsed": (cross or margin).get("totalMarginUsed", ""),
        "withdrawable": cross.get("withdrawable", ""),
    }
    with open(summary_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        if not summary_exists:
            w.writeheader()
        w.writerow(summary_row)
    print(f"Appended summary row to {summary_path}")


if __name__ == "__main__":
    main()
    sys.exit(0)
