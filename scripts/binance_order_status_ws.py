#!/usr/bin/env python3
"""
Binance USD-M User Data Stream: append ORDER_TRADE_UPDATE events to order_status_audit.csv.

Run in background to get real-time order status updates (NEW, PARTIALLY_FILLED, FILLED,
CANCELED, EXPIRED) without polling. Logs to data/binance/orders/ws.log.

Usage:
  python scripts/binance_order_status_ws.py

Stops on Ctrl+C. Keeps listenKey alive every 30 min.
"""

import csv
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

from env_manager import (
    BINANCE_FUTURES_BASE,
    BINANCE_WS_BASE,
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    ORDER_STATUS_AUDIT_PATH,
    ROOT,
)

WS_LOG_PATH = ORDER_STATUS_AUDIT_PATH.parent / "ws.log"


def _get_logger() -> logging.Logger:
    """Logger that writes only to ws.log (no console)."""
    log = logging.getLogger("binance_order_status_ws")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)
    log.propagate = False
    ORDER_STATUS_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(WS_LOG_PATH, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)
    return log


AUDIT_FIELDS = [
    "timestamp_utc", "event_type", "order_id", "client_order_id", "symbol", "side", "order_type",
    "status", "orig_qty", "executed_qty", "avg_price", "cum_quote", "source",
]


def _order_update_to_row(msg: dict) -> dict:
    """Map Binance ORDER_TRADE_UPDATE payload to our audit row. Uses 'o' (order) object inside event."""
    o = msg.get("o") or {}
    # ORDER_TRADE_UPDATE: o has s, c, S, o, q, X, i, z, ap, etc.
    return {
        "timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(msg.get("E", 0) / 1000)),
        "event_type": "ws_update",
        "order_id": str(o.get("i") or ""),
        "client_order_id": str(o.get("c") or ""),
        "symbol": str(o.get("s") or ""),
        "side": str(o.get("S") or ""),
        "order_type": str(o.get("o") or ""),
        "status": str(o.get("X") or ""),
        "orig_qty": str(o.get("q") or ""),
        "executed_qty": str(o.get("z") or ""),
        "avg_price": str(o.get("ap") or ""),
        "cum_quote": "",  # ORDER_TRADE_UPDATE does not include cum quote; use REST get_order for full details
        "source": "websocket",
    }


def append_audit_row(row: dict) -> None:
    ORDER_STATUS_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = ORDER_STATUS_AUDIT_PATH.exists()
    with open(ORDER_STATUS_AUDIT_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=AUDIT_FIELDS, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        w.writerow(row)


def run_order_status_ws(*, silent: bool = False) -> None:
    """
    Run the Binance User Data Stream WebSocket in the current thread; blocks until closed.
    Appends ORDER_TRADE_UPDATE events to order_status_audit.csv. Logs to ws.log.
    When silent=True (e.g. when called from backend), no sys.exit(); just return on missing creds/deps.
    """
    import threading
    log = _get_logger()
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        log.warning("Missing BINANCE_API_KEY or BINANCE_API_SECRET")
        if not silent:
            print("Set BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_UM_*) in .env or environment.", file=sys.stderr)
            sys.exit(1)
        return
    api_key = BINANCE_API_KEY
    api_secret = BINANCE_API_SECRET

    try:
        import requests
        import websocket
    except ImportError as e:
        log.error("Missing dependency: %s", e)
        if not silent:
            print(f"Install requests and websocket-client: {e}", file=sys.stderr)
            sys.exit(1)
        return

    try:
        session = requests.Session()
        session.headers["X-MBX-APIKEY"] = api_key
        resp = session.post(f"{BINANCE_FUTURES_BASE.rstrip('/')}/fapi/v1/listenKey", timeout=10)
        resp.raise_for_status()
        listen_key = resp.json().get("listenKey")
    except Exception as e:
        log.exception("Failed to get listenKey: %s", e)
        if not silent:
            print(f"Failed to get listenKey: {e}", file=sys.stderr)
            sys.exit(1)
        return
    if not listen_key:
        log.error("listenKey empty in response")
        if not silent:
            print("Failed to get listenKey.", file=sys.stderr)
            sys.exit(1)
        return

    url = f"{BINANCE_WS_BASE.rstrip('/')}/ws/{listen_key}"
    log.info("Connected to User Data Stream; audit=%s", ORDER_STATUS_AUDIT_PATH)

    last_keepalive_ref = [time.time()]
    KEEPALIVE_INTERVAL = 30 * 60  # 30 min

    # Throttle position refreshes to avoid spamming Binance on bursty order streams.
    last_positions_refresh_ref = [0.0]
    POSITIONS_REFRESH_INTERVAL = 5.0  # seconds

    def _refresh_positions_if_needed() -> None:
        now = time.time()
        if now - last_positions_refresh_ref[0] < POSITIONS_REFRESH_INTERVAL:
            return
        try:
            script_path = ROOT / "scripts" / "crawl_binance_usdm_positions.py"
            log.info("Refreshing positions via %s", script_path)
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                log.error(
                    "Positions refresh failed (code=%s): stdout=%s stderr=%s",
                    proc.returncode,
                    proc.stdout,
                    proc.stderr,
                )
            else:
                log.info("Positions refreshed successfully.")
            last_positions_refresh_ref[0] = now
        except Exception as e:  # pragma: no cover - network / subprocess
            log.error("Positions refresh error: %s", e, exc_info=True)

    def on_message(ws, message):
        try:
            msg = json.loads(message)
            if msg.get("e") == "ORDER_TRADE_UPDATE":
                row = _order_update_to_row(msg)
                append_audit_row(row)
                log.info(
                    "ORDER_TRADE_UPDATE orderId=%s symbol=%s status=%s",
                    row["order_id"],
                    row["symbol"],
                    row["status"],
                )
                _refresh_positions_if_needed()
        except Exception as e:
            log.exception("Parse/audit error: %s", e)

    def on_error(ws, error):
        log.error("WebSocket error: %s", error)

    def on_close(ws, close_status_code, close_msg):
        log.info("WebSocket closed (code=%s msg=%s)", close_status_code, close_msg)

    def on_open(ws):
        log.info("User Data Stream open; listening for ORDER_TRADE_UPDATE")

    ws = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )

    keepalive_stop = threading.Event()

    def keepalive_loop():
        while not keepalive_stop.wait(timeout=60):
            if time.time() - last_keepalive_ref[0] >= KEEPALIVE_INTERVAL:
                try:
                    session.put(f"{BINANCE_FUTURES_BASE.rstrip('/')}/fapi/v1/listenKey", timeout=10)
                    last_keepalive_ref[0] = time.time()
                    log.info("ListenKey keepalive sent")
                except Exception as e:
                    log.error("Keepalive failed: %s", e)

    k = threading.Thread(target=keepalive_loop, daemon=True)
    k.start()

    try:
        ws.run_forever()
    except KeyboardInterrupt:
        pass
    keepalive_stop.set()
    log.info("Stopped")


def main() -> None:
    """CLI entrypoint: run WebSocket; exit with 1 on missing creds or deps."""
    run_order_status_ws(silent=False)


if __name__ == "__main__":
    main()
