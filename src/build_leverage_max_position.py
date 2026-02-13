#!/usr/bin/env python3
"""
Build leverage_max_position.csv: one row per (currency, leverage) with maxPosition in USDT.
Relation: maxPosition(leverage) = max_position_at_max_leverage_usdt * (leverage / max_leverage).
Run once to populate/refresh the table.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDER_META = ROOT / "data" / "binance" / "orders" / "order_meta.csv"
OUT_CSV = ROOT / "data" / "binance" / "orders" / "leverage_max_position.csv"


def main() -> None:
    rows_out = []
    with open(ORDER_META) as f:
        r = csv.DictReader(f)
        for row in r:
            currency = (row.get("currency") or "").strip()
            if not currency:
                continue
            max_lev_s = (row.get("max_leverage") or "").strip()
            max_pos_s = (row.get("max_position_at_max_leverage_usdt") or "").strip()
            if not max_lev_s or not max_pos_s:
                continue
            try:
                max_leverage = int(max_lev_s)
                max_position_at_max = float(max_pos_s)
            except ValueError:
                continue
            if max_leverage < 2:
                continue
            for leverage in range(2, max_leverage + 1):
                # Same margin cap => max notional scales with leverage
                max_position = max_position_at_max * (leverage / max_leverage)
                rows_out.append({
                    "currency": currency,
                    "leverage": str(leverage),
                    "maxPosition": f"{max_position:.2f}",
                })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["currency", "leverage", "maxPosition"])
        w.writeheader()
        w.writerows(rows_out)
    print(f"Wrote {len(rows_out)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
