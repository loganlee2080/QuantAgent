"""
Phase 1 tests for scripts/binance_trade_api.py.
Unit (pure logic), integration (mocked API), and smoke (CLI).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts dir on path (conftest does this; re-do for import)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import binance_trade_api as bta


# ---------- TC-01: _direct_to_side (unit, functional) ----------
@pytest.mark.unit
def test_direct_to_side_long():
    assert bta._direct_to_side("long") == "BUY"
    assert bta._direct_to_side("Long") == "BUY"
    assert bta._direct_to_side("  LONG  ") == "BUY"


@pytest.mark.unit
def test_direct_to_side_short():
    assert bta._direct_to_side("short") == "SELL"
    assert bta._direct_to_side("Short") == "SELL"
    assert bta._direct_to_side("  SHORT  ") == "SELL"


@pytest.mark.unit
def test_direct_to_side_invalid_raises():
    with pytest.raises(ValueError, match="Unknown direct"):
        bta._direct_to_side("unknown")
    with pytest.raises(ValueError, match="Unknown direct"):
        bta._direct_to_side("")


# ---------- TC-02: _quantity_from_usdt (unit, functional) ----------
@pytest.mark.unit
def test_quantity_from_usdt_basic():
    # Default precision 6 when no meta
    with patch.dict(bta.ORDER_META, {}, clear=True):
        qty = bta._quantity_from_usdt("BTCUSDT", 1000.0, 50000.0)
        assert qty == "0.020000"  # 1000/50000 = 0.02, 6 decimals


@pytest.mark.unit
def test_quantity_from_usdt_with_meta_precision():
    with patch.dict(bta.ORDER_META, {"BTC": {"quantity_precision": "4"}}, clear=False):
        qty = bta._quantity_from_usdt("BTCUSDT", 1000.0, 50000.0)
        assert qty == "0.0200"


@pytest.mark.unit
def test_quantity_from_usdt_invalid_price():
    with patch.dict(bta.ORDER_META, {}, clear=True):
        with pytest.raises(ValueError, match="Invalid price"):
            bta._quantity_from_usdt("BTCUSDT", 1000.0, 0)
        with pytest.raises(ValueError, match="Invalid price"):
            bta._quantity_from_usdt("BTCUSDT", 1000.0, -1.0)


@pytest.mark.unit
def test_quantity_from_usdt_non_positive_quantity():
    with patch.dict(bta.ORDER_META, {}, clear=True):
        with pytest.raises(ValueError, match="non-positive quantity"):
            bta._quantity_from_usdt("BTCUSDT", 0.0001, 50000.0)  # qty too small


# ---------- TC-03: _load_order_meta (unit) ----------
@pytest.mark.unit
def test_load_order_meta_missing_file(tmp_path):
    with patch.object(bta, "ORDER_META_PATH", tmp_path / "nonexistent.csv"):
        meta = bta._load_order_meta()
        assert meta == {}


@pytest.mark.unit
def test_load_order_meta_with_file(tmp_path):
    meta_path = tmp_path / "order_meta.csv"
    meta_path.write_text(
        "currency,quantity_precision\nBTC,6\n,skip\nETH,5\n",
        encoding="utf-8",
    )
    with patch.object(bta, "ORDER_META_PATH", meta_path):
        meta = bta._load_order_meta()
        assert "BTC" in meta
        assert meta["BTC"].get("quantity_precision") == "6"
        assert "ETH" in meta
        assert "" not in meta  # blank currency skipped


# ---------- TC-04: set_leverage (integration, mocked) ----------
@pytest.mark.integration
def test_set_leverage_calls_signed_request(mock_get_keys, mock_signed_request):
    mock_signed_request.return_value = (200, {"leverage": 10, "symbol": "BTCUSDT"})
    result = bta.set_leverage("BTCUSDT", 10, api_key="k", api_secret="s")
    assert result["leverage"] == 10
    mock_signed_request.assert_called_once()
    call_args = mock_signed_request.call_args
    assert call_args[0][2] == "POST"
    assert call_args[0][3] == "/fapi/v1/leverage"
    assert call_args[0][4]["symbol"] == "BTCUSDT"
    assert call_args[0][4]["leverage"] == "10"


@pytest.mark.integration
def test_set_leverage_clamps_below_one(mock_get_keys, mock_signed_request):
    mock_signed_request.return_value = (200, {"leverage": 1})
    bta.set_leverage("BTCUSDT", 0, api_key="k", api_secret="s")
    call_args = mock_signed_request.call_args
    assert call_args[0][4]["leverage"] == "1"


# ---------- TC-05: place_market_order validation (unit/integration) ----------
@pytest.mark.unit
def test_place_market_order_invalid_side(mock_get_keys, mock_signed_request, mock_get_mark_price):
    with pytest.raises(ValueError, match="Invalid side"):
        bta.place_market_order("BTCUSDT", "INVALID", 1000.0, api_key="k", api_secret="s")


@pytest.mark.unit
def test_place_market_order_quote_usdt_non_positive(mock_get_keys, mock_signed_request, mock_get_mark_price):
    with pytest.raises(ValueError, match="quote_usdt must be positive"):
        bta.place_market_order("BTCUSDT", "BUY", 0, api_key="k", api_secret="s")
    with pytest.raises(ValueError, match="quote_usdt must be positive"):
        bta.place_market_order("BTCUSDT", "BUY", -100, api_key="k", api_secret="s")


@pytest.mark.integration
def test_place_market_order_success(mock_get_keys, mock_signed_request, mock_get_mark_price):
    mock_signed_request.return_value = (200, {"orderId": 999, "symbol": "BTCUSDT"})
    result = bta.place_market_order("BTCUSDT", "BUY", 1000.0, api_key="k", api_secret="s")
    assert result["orderId"] == 999
    mock_signed_request.assert_called_once()
    params = mock_signed_request.call_args[0][4]
    assert params["type"] == "MARKET"
    assert params["side"] == "BUY"
    assert "quantity" in params


# ---------- TC-06: close_position (integration) ----------
@pytest.mark.integration
def test_close_position_no_position_returns_none(mock_get_keys, mock_signed_request):
    mock_signed_request.return_value = (200, [])  # no positions
    result = bta.close_position("BTCUSDT", fraction=1.0, api_key="k", api_secret="s")
    assert result is None


@pytest.mark.integration
def test_close_position_zero_amt_returns_none(mock_get_keys, mock_signed_request):
    mock_signed_request.side_effect = [
        (200, [{"symbol": "BTCUSDT", "positionAmt": "0"}]),
    ]
    result = bta.close_position("BTCUSDT", fraction=1.0, api_key="k", api_secret="s")
    assert result is None


@pytest.mark.integration
def test_close_position_fraction_zero_returns_none(mock_get_keys, mock_signed_request):
    mock_signed_request.return_value = (200, [{"symbol": "BTCUSDT", "positionAmt": "0.1"}])
    result = bta.close_position("BTCUSDT", fraction=0, api_key="k", api_secret="s")
    assert result is None


@pytest.mark.integration
def test_close_position_success_reduce_only(mock_get_keys, mock_signed_request):
    mock_signed_request.side_effect = [
        (200, [{"symbol": "BTCUSDT", "positionAmt": "0.1"}]),  # positionRisk
        (200, {"orderId": 1}),  # order
    ]
    result = bta.close_position("BTCUSDT", fraction=1.0, api_key="k", api_secret="s")
    assert result["orderId"] == 1
    assert mock_signed_request.call_count == 2
    order_params = mock_signed_request.call_args_list[1][0][4]
    assert order_params["reduceOnly"] == "true"
    assert order_params["side"] == "SELL"
    assert order_params["type"] == "MARKET"


# ---------- TC-07: close_position_limit (integration) ----------
@pytest.mark.integration
def test_close_position_limit_success(mock_get_keys, mock_signed_request):
    mock_signed_request.side_effect = [
        (200, [{"symbol": "BTCUSDT", "positionAmt": "-0.05"}]),  # short
        (200, {"orderId": 2}),
    ]
    result = bta.close_position_limit(
        "BTCUSDT", fraction=1.0, price=49000.0, api_key="k", api_secret="s"
    )
    assert result["orderId"] == 2
    order_params = mock_signed_request.call_args_list[1][0][4]
    assert order_params["type"] == "LIMIT"
    assert order_params["timeInForce"] == "GTC"
    assert order_params["reduceOnly"] == "true"
    assert order_params["side"] == "BUY"


# ---------- TC-08: place_batch_orders (integration) ----------
@pytest.mark.integration
def test_place_batch_orders_empty_returns_empty(mock_get_keys):
    result = bta.place_batch_orders([], api_key="k", api_secret="s")
    assert result == []


@pytest.mark.integration
def test_place_batch_orders_invalid_amount_raises(mock_get_keys, mock_get_mark_price, mock_signed_request):
    with pytest.raises(ValueError, match="amountUsdt must be positive"):
        bta.place_batch_orders(
            [{"symbol": "BTCUSDT", "amountUsdt": 0, "positionSide": "LONG"}],
            api_key="k",
            api_secret="s",
        )


@pytest.mark.integration
def test_place_batch_orders_chunks_of_five(mock_get_keys, mock_get_mark_price, mock_signed_request):
    # First batch 5 orders, second batch 1 order
    mock_signed_request.side_effect = [
        (200, [{"orderId": i} for i in range(5)]),
        (200, [{"orderId": 5}]),
    ]
    # Use ORDER_META with precision so 50 USDT at mock price 50000 -> qty 0.001 is valid
    meta = {c: {"quantity_precision": "5"} for c in ("BTC", "ETH", "DOGE", "SOL", "XRP", "ADA")}
    orders = [
        {"symbol": "BTCUSDT", "amountUsdt": 100, "positionSide": "LONG"},
        {"symbol": "ETHUSDT", "amountUsdt": 100, "positionSide": "SHORT"},
        {"symbol": "DOGEUSDT", "amountUsdt": 50, "positionSide": "LONG"},
        {"symbol": "SOLUSDT", "amountUsdt": 50, "positionSide": "SHORT"},
        {"symbol": "XRPUSDT", "amountUsdt": 50, "positionSide": "LONG"},
        {"symbol": "ADAUSDT", "amountUsdt": 50, "positionSide": "LONG"},
    ]
    with patch.dict(bta.ORDER_META, meta, clear=False):
        result = bta.place_batch_orders(orders, api_key="k", api_secret="s")
        assert len(result) == 6
        # Batch size 5: first call with 5, second with 1
        assert mock_signed_request.call_count == 2


@pytest.mark.integration
def test_place_batch_orders_position_side_maps_to_side(mock_get_keys, mock_get_mark_price, mock_signed_request):
    mock_signed_request.return_value = (200, [{"orderId": 1}])
    bta.place_batch_orders(
        [{"symbol": "BTCUSDT", "amountUsdt": 100, "positionSide": "SHORT"}],
        api_key="k",
        api_secret="s",
    )
    payload = mock_signed_request.call_args[0][4]
    import json
    batch = json.loads(payload["batchOrders"])
    assert batch[0]["side"] == "SELL"


# ---------- TC-09: place_orders_from_csv (integration) ----------
@pytest.mark.integration
def test_place_orders_from_csv_file_not_found():
    with patch.object(bta, "_get_keys", return_value=("k", "s")):
        with pytest.raises(SystemExit):
            bta.place_orders_from_csv(Path("/nonexistent/orders.csv"))


@pytest.mark.integration
def test_place_orders_from_csv_empty_file(mock_get_keys, tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("currency,size_usdt,direct,lever\n", encoding="utf-8")
    bta.place_orders_from_csv(empty)  # no raise, no orders


@pytest.mark.integration
def test_place_orders_from_csv_skips_invalid_row(mock_get_keys, tmp_path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "currency,size_usdt,direct,lever\n"
        ",100,Long,10\n"
        "BTC,,Long,10\n",
        encoding="utf-8",
    )
    with patch.object(bta, "place_market_order", MagicMock()) as mock_order:
        bta.place_orders_from_csv(csv_path)
        mock_order.assert_not_called()


@pytest.mark.integration
def test_place_orders_from_csv_close_calls_close_position(mock_get_keys, mock_signed_request, tmp_path):
    mock_signed_request.side_effect = [
        (200, [{"symbol": "BTCUSDT", "positionAmt": "0.1"}]),
        (200, {"orderId": 1}),
    ]
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "currency,size_usdt,direct,lever,reduce_only\n"
        "BTC,0,Close,,true\n",
        encoding="utf-8",
    )
    with patch.dict(bta.ORDER_META, {"BTC": {"enabled_trade": "true"}}, clear=False):
        bta.place_orders_from_csv(csv_path)
    assert mock_signed_request.call_count >= 2


# ---------- TC-10: place_close_orders_from_template (integration) ----------
@pytest.mark.integration
def test_place_close_orders_from_template_file_not_found():
    with patch.object(bta, "_get_keys", return_value=("k", "s")):
        with pytest.raises(SystemExit):
            bta.place_close_orders_from_template(Path("/nonexistent/close.csv"))


@pytest.mark.integration
def test_place_close_orders_from_template_market(mock_get_keys, mock_signed_request, temp_close_template_csv):
    mock_signed_request.side_effect = [
        (200, [{"symbol": "BTCUSDT", "positionAmt": "0.1"}]),
        (200, {"orderId": 1}),
    ]
    bta.place_close_orders_from_template(temp_close_template_csv)
    assert mock_signed_request.call_count >= 2


# ---------- TC-11: main() CLI (smoke) ----------
@pytest.mark.smoke
def test_main_no_args_exits():
    with patch.object(sys, "argv", ["binance_trade_api.py"]):
        with pytest.raises(SystemExit) as exc_info:
            bta.main(sys.argv)
        assert exc_info.value.code == 1


@pytest.mark.smoke
def test_main_close_template_calls_place_close(mock_get_keys):
    with patch.object(bta, "place_close_orders_from_template", MagicMock()) as m:
        with patch.object(sys, "argv", ["binance_trade_api.py", "--close-template", "/some/path.csv"]):
            bta.main(sys.argv)
        m.assert_called_once()
        assert m.call_args[0][0] == Path("/some/path.csv")


@pytest.mark.smoke
def test_main_orders_csv_calls_place_orders(mock_get_keys, temp_orders_csv):
    with patch.object(bta, "place_orders_from_csv", MagicMock()) as m:
        with patch.object(sys, "argv", ["binance_trade_api.py", str(temp_orders_csv)]):
            bta.main(sys.argv)
        m.assert_called_once()
        assert m.call_args[0][0] == temp_orders_csv


# ---------- get_order (order status by orderId) ----------
@pytest.mark.unit
def test_get_order_requires_order_id_or_client_order_id(mock_get_keys):
    with pytest.raises(ValueError, match="Either order_id or client_order_id"):
        bta.get_order("BTCUSDT", api_key="k", api_secret="s")


@pytest.mark.integration
def test_get_order_by_order_id(mock_get_keys, mock_signed_request, mock_append_order_status_audit):
    mock_signed_request.return_value = (200, {"orderId": 84047010, "symbol": "BTCUSDT", "status": "FILLED"})
    result = bta.get_order("BTCUSDT", order_id=84047010, api_key="k", api_secret="s", write_audit=False)
    assert result["orderId"] == 84047010
    assert result["status"] == "FILLED"
    mock_signed_request.assert_called_once()
    call_args = mock_signed_request.call_args[0]
    assert call_args[3] == "GET"
    assert call_args[4].get("symbol") == "BTCUSDT"
    assert call_args[4].get("orderId") == "84047010"
    mock_append_order_status_audit.assert_not_called()


@pytest.mark.integration
def test_get_order_write_audit_calls_append(mock_get_keys, mock_signed_request, mock_append_order_status_audit):
    mock_signed_request.return_value = (200, {"orderId": 1, "symbol": "ETHUSDT", "status": "NEW"})
    bta.get_order("ETHUSDT", order_id=1, api_key="k", api_secret="s", write_audit=True)
    mock_append_order_status_audit.assert_called_once()
    call_args = mock_append_order_status_audit.call_args[0]
    assert call_args[0]["orderId"] == 1
    assert call_args[1] == "status_check"
    assert call_args[2] == "api"


@pytest.mark.smoke
def test_main_order_status_calls_get_order(mock_get_keys, mock_signed_request, mock_append_order_status_audit):
    mock_signed_request.return_value = (200, {"orderId": 123, "symbol": "BTCUSDT", "status": "FILLED"})
    with patch.object(sys, "argv", ["binance_trade_api.py", "--order-status", "BTCUSDT", "123"]):
        bta.main(sys.argv)
    mock_signed_request.assert_called_once()


# ---------- TC-12: _get_mark_price (unit, mocked HTTP) ----------
@pytest.mark.unit
def test_get_mark_price_success(mock_requests_get):
    price = bta._get_mark_price("BTCUSDT")
    assert price == 50000.5


@pytest.mark.unit
def test_get_mark_price_http_error():
    with patch("binance_trade_api.requests.get") as m:
        resp = MagicMock()
        resp.status_code = 404
        resp.raise_for_status.side_effect = Exception("404")
        m.return_value = resp
        with pytest.raises(Exception):
            bta._get_mark_price("BTCUSDT")
