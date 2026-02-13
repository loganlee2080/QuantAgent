#!/usr/bin/env python3
"""
Test flow: place order -> verify audit CSV -> get_order by orderId -> (optional) wait for FILLED.

Run from project root (uses demo/testnet if BINANCE_FUTURES_BASE contains demo-fapi):
  python scripts/test_order_place_and_track.py

Requires BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) in .env or environment.
"""
import csv
import sys
import time
from pathlib import Path

# Ensure scripts on path when run as python scripts/test_order_place_and_track.py
_scripts = Path(__file__).resolve().parent
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

import binance_trade_api as bta


def audit_contains_order_id(order_id: int) -> bool:
    path = bta.ORDER_STATUS_AUDIT_PATH
    if not path.exists():
        return False
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if str(row.get("order_id", "")) == str(order_id):
                return True
    return False


def main() -> int:
    symbol = "BTCUSDT"
    quantity_precision = 3
    # With 3 decimals, min qty 0.001 BTC. Binance requires order notional >= 100; 0.001 at edge. Use 200 so qty=0.002.
    notional = 200.0
    print("1) Placing small market BUY order...")
    try:
        # Don't set leverage (use account default) to avoid -2028 insufficient margin / leverage checks
        order = bta.place_market_order(
            symbol, "BUY", notional, leverage=10, quantity_precision=quantity_precision
        )
    except Exception as e:
        print(f"   FAIL: {e}", file=sys.stderr)
        return 1
    order_id = order.get("orderId")
    if not order_id:
        print("   FAIL: no orderId in response", file=sys.stderr)
        return 1
    print(f"   OK orderId={order_id}")

    print("2) Checking order_status_audit.csv for placed row...")
    if not audit_contains_order_id(order_id):
        print("   FAIL: audit CSV does not contain this order_id", file=sys.stderr)
        return 1
    print("   OK audit contains order_id")

    print("3) get_order(symbol, order_id) and append status_check to audit...")
    try:
        status_data = bta.get_order(symbol, order_id=order_id, write_audit=True)
    except Exception as e:
        print(f"   FAIL: {e}", file=sys.stderr)
        return 1
    status = status_data.get("status", "").upper()
    print(f"   OK status={status}")

    print("4) Optional: wait for FILLED (market order)...")
    for i in range(8):
        if status == "FILLED":
            print("   OK FILLED")
            break
        time.sleep(1)
        status_data = bta.get_order(symbol, order_id=order_id)
        status = status_data.get("status", "").upper()
        print(f"   poll {i+1} status={status}")
    else:
        print(f"   (still {status} after 8s)")

    print("5) Close position (flat)...")
    try:
        close_resp = bta.close_position(symbol, fraction=1.0)
        if close_resp is None:
            print("   (no position to close)")
        else:
            print(f"   OK close orderId={close_resp.get('orderId')}")
    except Exception as e:
        print(f"   WARN: {e}", file=sys.stderr)

    print("Done. Check data/binance/orders/order_status_audit.csv for placed + status_check rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
