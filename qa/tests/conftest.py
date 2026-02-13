"""
Pytest fixtures for QA tests.
Mocks Binance API and file I/O so tests do not hit live services.
Demo tests (marker: demo) hit Binance demo API when credentials are set.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Project root and script under test
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _has_demo_credentials():
    key = os.environ.get("BINANCE_API_KEY") or os.environ.get("BINANCE_UM_API_KEY")
    secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get("BINANCE_UM_API_SECRET")
    return bool(key and secret)


@pytest.fixture
def require_demo_credentials():
    """Skip demo tests when BINANCE_API_KEY / BINANCE_API_SECRET are not set."""
    if not _has_demo_credentials():
        pytest.skip(
            "BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) not set; "
            "skip demo integration tests. Use demo account only."
        )
    yield


@pytest.fixture
def mock_get_keys():
    """Provide fake API key/secret so _get_keys() does not read env or exit."""
    with patch("binance_trade_api._get_keys") as m:
        m.return_value = ("fake_key_1234", "fake_secret_5678")
        yield m


@pytest.fixture
def mock_signed_request():
    """Mock _signed_request to avoid real HTTP calls."""
    with patch("binance_trade_api._signed_request") as m:
        m.return_value = (200, {"orderId": 12345, "symbol": "BTCUSDT"})
        yield m


@pytest.fixture
def mock_get_mark_price():
    """Mock _get_mark_price to return a fixed price."""
    with patch("binance_trade_api._get_mark_price") as m:
        m.return_value = 50000.0
        yield m


@pytest.fixture(autouse=True)
def mock_append_order_status_audit():
    """Avoid writing to order_status_audit.csv during tests."""
    with patch("binance_trade_api.append_order_status_audit") as m:
        yield m


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for _get_mark_price when testing that function directly."""
    # Patch where used (binance_trade_api imports requests)
    with patch("binance_trade_api.requests.get") as m:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"price": "50000.5"}
        resp.raise_for_status = MagicMock()
        m.return_value = resp
        yield m


@pytest.fixture
def temp_order_meta_csv(tmp_path):
    """Create a temporary order_meta.csv and return its path."""
    path = tmp_path / "order_meta.csv"
    path.write_text(
        "currency,quantity_precision,enabled_trade,max_size_usdt,min_size_usdt,default_lever\n"
        "BTC,6,true,10000,5,10\n"
        "ETH,5,true,5000,5,20\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def temp_orders_csv(tmp_path):
    """Create a temporary orders CSV for place_orders_from_csv tests."""
    path = tmp_path / "orders.csv"
    path.write_text(
        "currency,size_usdt,direct,lever\n"
        "BTC,100,Long,10\n"
        "ETH,50,Short,20\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def temp_close_template_csv(tmp_path):
    """Create a temporary close template CSV."""
    path = tmp_path / "order_close_template.csv"
    path.write_text(
        "symbol,fraction,order_type,price\n"
        "BTCUSDT,1.0,MARKET,\n"
        "ETHUSDT,0.5,LIMIT,3000\n",
        encoding="utf-8",
    )
    return path
