#!/usr/bin/env python3
"""
Basic Binance USD-M trading API.

- Live trading (uses your real API key/secret).
- Market orders only (for now), one-way mode.
- Order size specified in USDT (quote), via `quoteOrderQty`.
- Per-order leverage can be set before placing the order.

Order status tracking (order_status_audit.csv at ORDER_STATUS_AUDIT_PATH):
- Every placed order is appended to order_status_audit.csv (order_id, symbol, status, etc.).
- get_order(symbol, order_id) and CLI --order-status append a status_check row to the same audit by default.
- Optional WebSocket: python scripts/binance_order_status_ws.py appends real-time ORDER_TRADE_UPDATE events to the same audit CSV.

Env (same as crawler):
- BINANCE_API_KEY / BINANCE_UM_API_KEY
- BINANCE_API_SECRET / BINANCE_UM_API_SECRET

Example CSV (order table):
    currency,size_usdt,direct,lever
    BTC,1000,Long,100
    DOGE,500,Short,20

Run:
    python scripts/binance_trade_api.py orders.csv

This will:
- For each row, map `currency` -> symbol (e.g. BTC -> BTCUSDT)
- Set leverage (if provided)
- Place a MARKET order in USD-M futures with `quoteOrderQty = size_usdt`
"""

import csv
import hashlib
import hmac
import json
import math
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from typing import Any, Dict, List, Optional, Tuple

import requests

from env_manager import (
    BINANCE_FUTURES_BASE,
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    DATA_BINANCE,
    ORDER_STATUS_AUDIT_PATH,
)

ORDER_META_PATH = DATA_BINANCE / "orders" / "order_meta.csv"

ORDER_STATUS_AUDIT_FIELDS = [
    "timestamp_utc",
    "event_type",
    "order_id",
    "client_order_id",
    "symbol",
    "side",
    "order_type",
    "status",
    "orig_qty",
    "executed_qty",
    "avg_price",
    "cum_quote",
    "source",
]


def _load_order_meta() -> Dict[str, Dict[str, str]]:
    meta: Dict[str, Dict[str, str]] = {}
    if not ORDER_META_PATH.exists():
        return meta
    with open(ORDER_META_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur = (row.get("currency") or "").strip().upper()
            if not cur:
                continue
            meta[cur] = row
    return meta


ORDER_META = _load_order_meta()


def _signed_request(
    api_key: str,
    api_secret: str,
    method: str,
    path: str,
    params: Optional[Dict[str, str]] = None,
) -> Tuple[int, dict]:
    """Generic signed request to Binance USD-M REST API."""
    params = dict(params or {})
    params["timestamp"] = str(int(time.time() * 1000))
    # Use standard URL encoding so signature matches Binance expectations
    qs = urlencode(sorted(params.items()))
    sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{BINANCE_FUTURES_BASE}{path}?{qs}&signature={sig}"
    headers = {"X-MBX-APIKEY": api_key}
    method = method.upper()
    # Debug print of request (without secret) for troubleshooting
    print(f"[Binance {_signed_request.__name__}] {method} {path} params={params}")

    if method == "GET":
        r = requests.get(url, headers=headers, timeout=15)
    elif method == "POST":
        r = requests.post(url, headers=headers, timeout=15)
    else:
        raise ValueError(f"Unsupported method: {method}")
    status = r.status_code
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text}
    if status >= 400:
        raise RuntimeError(f"Binance error {status}: {data}")
    return status, data


def _order_response_to_audit_row(o: dict, event_type: str = "placed", source: str = "api") -> Dict[str, str]:
    """Convert Binance order response (or GET order result) to one audit CSV row."""
    return {
        "timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "event_type": event_type,
        "order_id": str(o.get("orderId") or o.get("order_id") or ""),
        "client_order_id": str(o.get("clientOrderId") or o.get("client_order_id") or ""),
        "symbol": str(o.get("symbol") or ""),
        "side": str(o.get("side") or ""),
        "order_type": str(o.get("type") or o.get("origType") or ""),
        "status": str(o.get("status") or ""),
        "orig_qty": str(o.get("origQty") or o.get("orig_qty") or ""),
        "executed_qty": str(o.get("executedQty") or o.get("executed_qty") or ""),
        "avg_price": str(o.get("avgPrice") or o.get("avg_price") or ""),
        "cum_quote": str(o.get("cumQuote") or o.get("cum_quote") or ""),
        "source": source,
    }


def append_order_status_audit(
    order_response: dict,
    event_type: str = "placed",
    source: str = "api",
) -> None:
    """
    Append one row to order_status_audit.csv for auditing (by order_id / client_order_id).
    Call after placing an order or after querying status via get_order (with event_type='status_check').
    """
    row = _order_response_to_audit_row(order_response, event_type=event_type, source=source)
    ORDER_STATUS_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = ORDER_STATUS_AUDIT_PATH.exists()
    with open(ORDER_STATUS_AUDIT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ORDER_STATUS_AUDIT_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def get_order(
    symbol: str,
    order_id: Optional[int] = None,
    client_order_id: Optional[str] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    write_audit: bool = True,
) -> dict:
    """
    Query order status by orderId or clientOrderId (Binance GET /fapi/v1/order).
    At least one of order_id or client_order_id must be provided.
    By default appends a row to order_status_audit.csv (ORDER_STATUS_AUDIT_PATH) with event_type=status_check.
    Set write_audit=False to skip writing to the audit.
    """
    if api_key is None or api_secret is None:
        api_key, api_secret = _get_keys()
    if order_id is None and not (client_order_id or "").strip():
        raise ValueError("Either order_id or client_order_id must be provided")
    params: Dict[str, str] = {"symbol": symbol}
    if order_id is not None:
        params["orderId"] = str(int(order_id))
    if (client_order_id or "").strip():
        params["origClientOrderId"] = (client_order_id or "").strip()
    _, data = _signed_request(api_key, api_secret, "GET", "/fapi/v1/order", params)
    if write_audit:
        append_order_status_audit(data, event_type="status_check", source="api")
    return data


def _get_keys() -> Tuple[str, str]:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        print(
            "Set BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_API_*) in .env or environment.\n"
            "Use env_manager (python-dotenv) or export in shell.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Using Binance key: {BINANCE_API_KEY[:4]}***{BINANCE_API_KEY[-4:]}")
    return BINANCE_API_KEY, BINANCE_API_SECRET


def set_leverage(
    symbol: str,
    leverage: int,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> dict:
    """Set initial leverage for a symbol. 1 <= leverage <= maxLeverage."""
    if api_key is None or api_secret is None:
        api_key, api_secret = _get_keys()
    leverage = int(leverage)
    if leverage < 1:
        leverage = 1
    _, data = _signed_request(
        api_key,
        api_secret,
        "POST",
        "/fapi/v1/leverage",
        {"symbol": symbol, "leverage": str(leverage)},
    )
    return data


def _get_mark_price(symbol: str) -> float:
    """Fetch current mark/last price for symbol from ticker endpoint."""
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/price"
    r = requests.get(url, params={"symbol": symbol}, timeout=15)
    r.raise_for_status()
    data = r.json()
    return float(data["price"])


def close_position(
    symbol: str,
    fraction: float = 1.0,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> Optional[dict]:
    """
    Close all or part of the open position for a symbol using a MARKET reduce-only order.

    - symbol: e.g. BTCUSDT
    - fraction: 1.0 to close 100%, 0.5 to close 50%, etc. (clamped to [0, 1]).
    - Uses /fapi/v2/positionRisk to detect current positionAmt.
    - If no open position, returns None.
    """
    if api_key is None or api_secret is None:
        api_key, api_secret = _get_keys()

    # Fetch current position for this symbol
    _, positions = _signed_request(
        api_key,
        api_secret,
        "GET",
        "/fapi/v2/positionRisk",
        {},
    )
    position = None
    for p in positions:
        if str(p.get("symbol")) == symbol:
            amt = float(p.get("positionAmt", 0) or 0)
            if amt != 0:
                position = p
                break

    if position is None:
        print(f"No open position for {symbol}; nothing to close.")
        return None

    amt = float(position.get("positionAmt", 0) or 0)
    if amt == 0:
        print(f"Position size is zero for {symbol}; nothing to close.")
        return None
    # Clamp fraction to [0, 1]
    try:
        frac = float(fraction)
    except (TypeError, ValueError):
        frac = 1.0
    if frac <= 0:
        print(f"Fraction {fraction} <= 0; nothing to close for {symbol}.")
        return None
    if frac > 1:
        frac = 1.0

    side = "SELL" if amt > 0 else "BUY"
    qty = abs(amt) * frac
    qty_str = str(qty)

    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "reduceOnly": "true",
        "quantity": qty_str,
    }
    print(f"Closing position for {symbol}: side={side}, qty={qty_str} (MARKET)")
    _, data = _signed_request(api_key, api_secret, "POST", "/fapi/v1/order", params)
    append_order_status_audit(data, event_type="placed", source="close_position")
    return data


def close_position_limit(
    symbol: str,
    fraction: float,
    price: float,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> Optional[dict]:
    """
    Close all or part of the open position for a symbol using a LIMIT reduce-only order.

    - symbol: e.g. BTCUSDT
    - fraction: 1.0 to close 100%, 0.5 to close 50%, etc. (clamped to [0, 1]).
    - price: limit price for the order.
    """
    if api_key is None or api_secret is None:
        api_key, api_secret = _get_keys()

    _, positions = _signed_request(
        api_key,
        api_secret,
        "GET",
        "/fapi/v2/positionRisk",
        {},
    )
    position = None
    for p in positions:
        if str(p.get("symbol")) == symbol:
            amt = float(p.get("positionAmt", 0) or 0)
            if amt != 0:
                position = p
                break

    if position is None:
        print(f"No open position for {symbol}; nothing to close.")
        return None

    amt = float(position.get("positionAmt", 0) or 0)
    if amt == 0:
        print(f"Position size is zero for {symbol}; nothing to close.")
        return None
    try:
        frac = float(fraction)
    except (TypeError, ValueError):
        frac = 1.0
    frac = max(0.0, min(1.0, frac))
    if frac <= 0:
        print(f"Fraction {fraction} <= 0; nothing to close for {symbol}.")
        return None

    side = "SELL" if amt > 0 else "BUY"
    qty = abs(amt) * frac
    # Round quantity to reasonable precision (same as market close)
    qty = round(qty, 8)
    if qty <= 0:
        return None

    # Round price to 2 decimals (Binance accepts; adjust if symbol needs more precision)
    price_rounded = round(float(price), 2)

    params = {
        "symbol": symbol,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": f"{qty}",
        "price": f"{price_rounded}",
        "reduceOnly": "true",
    }
    print(f"Closing position for {symbol}: side={side}, qty={qty}, price={price_rounded} (LIMIT)")
    _, data = _signed_request(api_key, api_secret, "POST", "/fapi/v1/order", params)
    append_order_status_audit(data, event_type="placed", source="close_limit")
    return data


def place_market_order(
    symbol: str,
    side: str,
    quote_usdt: float,
    leverage: Optional[int] = None,
    quantity_precision: Optional[int] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> dict:
    """
    Place a MARKET order on Binance USD-M futures using a USDT notional.

    - symbol: e.g. BTCUSDT
    - side: "BUY" or "SELL"
    - quote_usdt: notional size in USDT (float)
    - leverage: optional, set before placing the order
    - quantity_precision: optional, max decimal places for quantity (from order_meta)
    """
    if api_key is None or api_secret is None:
        api_key, api_secret = _get_keys()

    if leverage is not None:
        print(f"Setting leverage for {symbol} to {leverage}x...")
        set_leverage(symbol, leverage, api_key=api_key, api_secret=api_secret)

    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError(f"Invalid side: {side}")

    notional = float(quote_usdt)
    if notional <= 0:
        raise ValueError("quote_usdt must be positive")

    # Derive contract quantity from notional and current price.
    price = _get_mark_price(symbol)
    if price <= 0:
        raise RuntimeError(f"Got non-positive price for {symbol}: {price}")
    # Use a reasonable precision; Binance will reject if too granular.
    raw_qty = notional / price
    prec = quantity_precision if quantity_precision is not None else 6
    # Clamp precision to a sensible range
    if prec < 0:
        prec = 0
    if prec > 8:
        prec = 8
    factor = 10**prec
    quantity = math.floor(raw_qty * factor) / factor
    if quantity <= 0:
        raise RuntimeError(f"Computed non-positive quantity for {symbol}: {quantity}")

    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        # Format quantity using the allowed precision so we don't exceed Binance's limits.
        "quantity": f"{quantity:.{prec}f}",
    }
    print(f"Placing MARKET {side} on {symbol}: ~{notional} USDT, qty ≈ {quantity}")
    _, data = _signed_request(api_key, api_secret, "POST", "/fapi/v1/order", params)
    append_order_status_audit(data, event_type="placed", source="market_order")
    return data


def _direct_to_side(direct: str) -> str:
    d = direct.strip().lower()
    if d == "long":
        return "BUY"
    if d == "short":
        return "SELL"
    raise ValueError(f"Unknown direct: {direct!r} (expected 'Long' or 'Short')")


def _quantity_from_usdt(symbol: str, amount_usdt: float, price: float) -> str:
    """Compute contract quantity from USDT notional and price; return string for API."""
    currency = symbol.replace("USDT", "") if symbol.endswith("USDT") else symbol
    meta = ORDER_META.get(currency, {})
    qp_str = (meta.get("quantity_precision") or "").strip()
    prec = 6
    if qp_str:
        try:
            prec = int(qp_str)
        except ValueError:
            pass
    prec = max(0, min(8, prec))
    if price <= 0:
        raise ValueError(f"Invalid price for {symbol}: {price}")
    raw_qty = amount_usdt / price
    factor = 10**prec
    quantity = math.floor(raw_qty * factor) / factor
    if quantity <= 0:
        raise ValueError(f"Computed non-positive quantity for {symbol}: {quantity} (amount_usdt={amount_usdt}, price={price})")
    return f"{quantity:.{prec}f}"


def place_batch_orders(
    orders: list[dict],
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    leverage: Optional[int] = None,
) -> list:
    """
    Place multiple orders via Binance POST /fapi/v1/batchOrders (max 5 per request).
    Chunks into batches of 5 and returns combined responses.

    Each order dict:
      - symbol: e.g. BTCUSDT
      - type: "MARKET" or "LIMIT"
      - amountUsdt: notional in USDT (float)
      - positionSide: "LONG" or "SHORT" (maps to side BUY/SELL)
      - price: optional; required for LIMIT; if LIMIT and missing, use mark price

    If leverage is set, set_leverage(symbol, leverage) is called for each unique symbol before placing.
    """
    if api_key is None or api_secret is None:
        api_key, api_secret = _get_keys()
    if not orders:
        return []

    if leverage is not None:
        leverage = max(1, int(leverage))
        symbols_seen: set = set()
        for o in orders:
            sym = (o.get("symbol") or "").strip().upper()
            if sym and sym.endswith("USDT") and sym not in symbols_seen:
                symbols_seen.add(sym)
                set_leverage(sym, leverage, api_key=api_key, api_secret=api_secret)

    BATCH_SIZE = 5
    all_responses: list = []
    for i in range(0, len(orders), BATCH_SIZE):
        chunk = orders[i : i + BATCH_SIZE]
        batch_payloads = []
        for o in chunk:
            symbol = (o.get("symbol") or "").strip().upper()
            if not symbol or not symbol.endswith("USDT"):
                symbol = (symbol or "") + "USDT"
            order_type = (o.get("type") or o.get("orderType") or "MARKET").strip().upper()
            if order_type not in ("MARKET", "LIMIT"):
                order_type = "MARKET"
            amount_usdt = float(o.get("amountUsdt") or o.get("amount_usdt") or 0)
            if amount_usdt <= 0:
                raise ValueError(f"Order for {symbol}: amountUsdt must be positive, got {amount_usdt}")
            pos_side = (o.get("positionSide") or o.get("position_side") or "LONG").strip().upper()
            if pos_side not in ("LONG", "SHORT"):
                pos_side = "LONG"
            side = "BUY" if pos_side == "LONG" else "SELL"

            if order_type == "MARKET":
                price = _get_mark_price(symbol)
            else:
                price_val = o.get("price")
                if price_val is None or price_val == "":
                    price = _get_mark_price(symbol)
                else:
                    price = float(price_val)
            qty_str = _quantity_from_usdt(symbol, amount_usdt, price)

            payload = {
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "quantity": qty_str,
            }
            if order_type == "LIMIT":
                payload["timeInForce"] = "GTC"
                payload["price"] = f"{round(price, 8)}"
            batch_payloads.append(payload)

        # Binance expects batchOrders as a compact JSON string parameter; encode with separators
        # so the signed querystring matches what is actually sent.
        params = {"batchOrders": json.dumps(batch_payloads, separators=(",", ":"))}
        _, data = _signed_request(api_key, api_secret, "POST", "/fapi/v1/batchOrders", params)
        chunk = data if isinstance(data, list) else [data]
        for item in chunk:
            if isinstance(item, dict) and item.get("orderId") is not None:
                append_order_status_audit(item, event_type="placed", source="batch")
        if isinstance(data, list):
            all_responses.extend(data)
        else:
            all_responses.append(data)
    return all_responses


def place_orders_from_csv(csv_path: Path) -> None:
    """
    Place a batch of market orders from a CSV file with header:

        currency,size_usdt,direct,lever[,reduce_only]

    - currency: e.g. BTC, ETH, DOGE
    - size_usdt: notional in USDT (float)
    - direct: 'Long', 'Short', 'Close', or 'SELL'/'BUY' (Close or reduce_only=true = close 100% of position)
    - lever: integer leverage (optional/blank -> no change)
    - reduce_only: optional 'true' when direct is SELL/BUY for closing (Binance has no Close side)
    """
    api_key, api_secret = _get_keys()
    csv_path = csv_path.resolve()
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading orders from {csv_path}...")
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("No orders in CSV.")
        return

    for row in rows:
        currency = (row.get("currency") or "").strip().upper()
        size_str = (row.get("size_usdt") or row.get("size") or "").strip()
        direct = (row.get("direct") or "").strip()
        lever_str = (row.get("lever") or "").strip()
        reduce_only = (row.get("reduce_only") or "").strip().lower() in ("true", "1", "yes", "y")

        if not currency or not size_str or not direct:
            print(f"Skipping invalid row: {row}")
            continue

        try:
            size_usdt = float(size_str)
        except ValueError:
            print(f"Invalid size_usdt in row (skipping): {row}")
            continue

        # Apply meta configuration if present
        meta = ORDER_META.get(currency, {})
        enabled = (meta.get("enabled_trade") or "true").strip().lower()
        if enabled not in ("1", "true", "yes", "y"):
            print(f"Trading disabled for {currency} in order_meta.csv; skipping row: {row}")
            continue

        # Max / min size in USDT
        max_size_str = (meta.get("max_size_usdt") or "").strip()
        min_size_str = (meta.get("min_size_usdt") or "").strip()
        try:
            max_size = float(max_size_str) if max_size_str else 1000.0
        except ValueError:
            max_size = 1000.0
        # Binance enforces a minimum notional (often 5 USDT); use 5.0 as a safe default floor
        try:
            min_size = float(min_size_str) if min_size_str else 5.0
        except ValueError:
            min_size = 5.0

        if not reduce_only:
            if size_usdt > max_size:
                print(f"Clamping {currency} size from {size_usdt} to max_size_usdt {max_size}")
                size_usdt = max_size
            if size_usdt < min_size:
                print(f"Size {size_usdt} below min_size_usdt {min_size} for {currency}; skipping row.")
                continue

        leverage = None
        if lever_str:
            try:
                leverage = int(lever_str)
            except ValueError:
                print(f"Invalid lever in row (skipping leverage change): {row}")
        elif meta.get("default_lever"):
            try:
                leverage = int(meta["default_lever"])
            except ValueError:
                pass

        quantity_precision = None
        qp_str = (meta.get("quantity_precision") or "").strip()
        if qp_str:
            try:
                quantity_precision = int(qp_str)
            except ValueError:
                pass

        symbol = currency + "USDT"
        try:
            d = direct.strip().lower()
            if d == "close" or reduce_only:
                resp = close_position(symbol, fraction=1.0, api_key=api_key, api_secret=api_secret)
                if resp is not None:
                    print(f"Order OK (close): {json.dumps(resp, indent=2)}")
            elif d in ("sell", "buy"):
                side = direct.strip().upper()
                resp = place_market_order(
                    symbol,
                    side,
                    size_usdt,
                    leverage=leverage,
                    quantity_precision=quantity_precision,
                    api_key=api_key,
                    api_secret=api_secret,
                )
                print(f"Order OK: {json.dumps(resp, indent=2)}")
            else:
                side = _direct_to_side(direct)
                resp = place_market_order(
                    symbol,
                    side,
                    size_usdt,
                    leverage=leverage,
                    quantity_precision=quantity_precision,
                    api_key=api_key,
                    api_secret=api_secret,
                )
                print(f"Order OK: {json.dumps(resp, indent=2)}")
        except Exception as e:
            print(f"Order FAILED for {row}: {e}", file=sys.stderr)


ORDER_CLOSE_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "binance" / "orders" / "order_close_template.csv"
)


def place_close_orders_from_template(csv_path: Optional[Path] = None) -> None:
    """
    Execute close orders from a CSV with header: symbol,fraction,order_type,price

    - symbol: e.g. BTCUSDT
    - fraction: 1.0 = 100%, 0.5 = 50%
    - order_type: MARKET or LIMIT
    - price: for MARKET leave empty; for LIMIT use a number or "mark" to use current mark price
    """
    path = (csv_path or ORDER_CLOSE_TEMPLATE_PATH).resolve()
    if not path.exists():
        print(f"Close template not found: {path}", file=sys.stderr)
        sys.exit(1)

    api_key, api_secret = _get_keys()
    print(f"Reading close template from {path}...")
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("No rows in close template.")
        return

    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        if not symbol.endswith("USDT"):
            symbol = symbol + "USDT"
        try:
            fraction = float(row.get("fraction") or "1.0")
        except ValueError:
            fraction = 1.0
        fraction = max(0.0, min(1.0, fraction))
        order_type = (row.get("order_type") or row.get("orderType") or "MARKET").strip().upper()
        if order_type not in ("MARKET", "LIMIT"):
            order_type = "MARKET"
        price_str = (row.get("price") or "").strip()

        try:
            if order_type == "MARKET":
                resp = close_position(symbol, fraction=fraction, api_key=api_key, api_secret=api_secret)
                if resp is not None:
                    print(f"Order OK (close MARKET): {json.dumps(resp, indent=2)}")
            else:
                if price_str.upper() == "MARK" or price_str == "":
                    price = _get_mark_price(symbol)
                    print(f"Using mark price for {symbol}: {price}")
                else:
                    price = float(price_str)
                resp = close_position_limit(
                    symbol,
                    fraction=fraction,
                    price=price,
                    api_key=api_key,
                    api_secret=api_secret,
                )
                if resp is not None:
                    print(f"Order OK (close LIMIT): {json.dumps(resp, indent=2)}")
        except Exception as e:
            print(f"Close FAILED for {symbol}: {e}", file=sys.stderr)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print(
            "Usage:\n"
            "  python scripts/binance_trade_api.py orders.csv\n"
            "  python scripts/binance_trade_api.py --close-template [path]\n"
            "  python scripts/binance_trade_api.py --order-status SYMBOL ORDER_ID\n\n"
            "Orders CSV format: currency,size_usdt,direct,lever\n"
            "Close template format: symbol,fraction,order_type,price (order_type=MARKET|LIMIT, price=number|mark)\n"
            "Order status: query by symbol and orderId; result is appended to order_status_audit.csv.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    if argv[1] == "--close-template":
        path = Path(argv[2]) if len(argv) > 2 else None
        print(f"Using Binance futures base: {BINANCE_FUTURES_BASE}")
        place_close_orders_from_template(path)
    elif argv[1] == "--order-status" and len(argv) >= 4:
        symbol = (argv[2] or "").strip().upper()
        if not symbol.endswith("USDT"):
            symbol = symbol + "USDT"
        try:
            order_id = int(argv[3])
        except ValueError:
            print("ORDER_ID must be an integer.", file=sys.stderr)
            sys.exit(1)
        # Always append to order_status_audit.csv (same as data/binance/orders/order_status_audit.csv)
        print(f"Using Binance futures base: {BINANCE_FUTURES_BASE}")
        data = get_order(symbol, order_id=order_id, write_audit=True)
        print(json.dumps(data, indent=2))
    else:
        csv_file = Path(argv[1])
        print(f"Using Binance futures base: {BINANCE_FUTURES_BASE}")
        place_orders_from_csv(csv_file)


if __name__ == "__main__":
    main(sys.argv)

