"""
Live integration tests for scripts/binance_trade_api.py against Binance DEMO API.

Run only when you intend to hit the demo account:
  PYTHONPATH=scripts python -m pytest qa/tests/test_binance_trade_api_demo.py -v -m demo

Requires BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) set for demo.
Default BINANCE_FUTURES_BASE is https://demo-fapi.binance.com (demo).
"""
import csv
import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = PROJECT_ROOT / "src"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import binance_trade_api as bta


def _audit_contains_order_id(order_id: int) -> bool:
    """Return True if order_status_audit.csv has a row with this order_id."""
    path = bta.ORDER_STATUS_AUDIT_PATH
    if not path.exists():
        return False
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if str(row.get("order_id", "")) == str(order_id):
                return True
    return False


# ---------- Public endpoint (no auth) ----------
@pytest.mark.demo
@pytest.mark.integration
def test_demo_get_mark_price():
    """Call real demo API ticker/price (public, no credentials)."""
    # Ensure we use demo base; default in module is already demo-fapi.binance.com
    base = os.environ.get("BINANCE_FUTURES_BASE", "https://demo-fapi.binance.com")
    assert "demo" in base or "testnet" in base.lower(), "Use demo/testnet base only"
    price = bta._get_mark_price("BTCUSDT")
    assert isinstance(price, float)
    assert price > 0


# ---------- Signed endpoints (require demo credentials) ----------
@pytest.mark.demo
@pytest.mark.integration
def test_demo_position_risk(require_demo_credentials):
    """GET /fapi/v2/positionRisk returns list (signed, demo)."""
    api_key, api_secret = bta._get_keys()
    status, data = bta._signed_request(
        api_key, api_secret, "GET", "/fapi/v2/positionRisk", {}
    )
    assert status == 200
    assert isinstance(data, list)


@pytest.mark.demo
@pytest.mark.integration
def test_demo_set_leverage(require_demo_credentials):
    """Set leverage to 2 then back to 1 on BTCUSDT (demo)."""
    result = bta.set_leverage("BTCUSDT", 2)
    assert "leverage" in result or "symbol" in str(result).lower()
    result2 = bta.set_leverage("BTCUSDT", 1)
    assert "leverage" in result2 or "symbol" in str(result2).lower()


@pytest.mark.demo
@pytest.mark.integration
def test_demo_place_small_market_order_then_close(require_demo_credentials):
    """Place minimal BUY then close on demo (no real money)."""
    symbol = "BTCUSDT"
    # Minimal notional on demo (e.g. 5–6 USDT) to satisfy min notional
    notional = 6.0
    order = bta.place_market_order(symbol, "BUY", notional, leverage=None)
    assert "orderId" in order
    # Close the position we just opened
    close_resp = bta.close_position(symbol, fraction=1.0)
    assert close_resp is None or "orderId" in close_resp


@pytest.mark.demo
@pytest.mark.integration
def test_demo_order_place_then_track_status(require_demo_credentials):
    """Place order -> verify audit CSV has it -> get_order by orderId -> close position."""
    symbol = "BTCUSDT"
    notional = 6.0
    # 1) Place order
    order = bta.place_market_order(symbol, "BUY", notional, leverage=None)
    order_id = order["orderId"]
    assert order_id is not None
    # 2) Audit CSV should have a "placed" row for this order_id
    assert _audit_contains_order_id(order_id), "order_status_audit.csv should contain placed order"
    # 3) Track status via get_order (and optionally write status_check to audit)
    status_data = bta.get_order(symbol, order_id=order_id, write_audit=True)
    assert status_data.get("orderId") == order_id
    assert status_data.get("symbol") == symbol
    status = status_data.get("status", "").upper()
    assert status in ("NEW", "PARTIALLY_FILLED", "FILLED"), f"unexpected status {status}"
    # 4) Audit should now have at least placed + status_check for this order
    assert _audit_contains_order_id(order_id)
    # 5) Optional: wait a moment for FILLED on market order then re-query
    for _ in range(5):
        if status == "FILLED":
            break
        time.sleep(1)
        status_data = bta.get_order(symbol, order_id=order_id)
        status = status_data.get("status", "").upper()
    # 6) Close position so demo account is flat
    close_resp = bta.close_position(symbol, fraction=1.0)
    assert close_resp is None or "orderId" in close_resp
