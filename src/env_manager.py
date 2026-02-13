"""
Central env manager for scripts. Loads .env once into local variables; other code imports from here.

Uses python-dotenv with override=False so that already-set env vars (e.g. RUN_FETCH_LOOPS=false in the shell)
take precedence over .env. Load order: .env then .env.local (if present); .env.local overrides .env for
keys not already set. Keep local-only values (e.g. API keys) in .env.local and add it to .gitignore.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        # override=False: shell / process env wins (e.g. RUN_FETCH_LOOPS=false)
        load_dotenv(_ROOT / ".env", override=False)
        local_env = _ROOT / ".env.local"
        if local_env.is_file():
            load_dotenv(local_env, override=False)
    except ImportError:
        pass


_load_env()

# Path used for .env.local (for debug)
_ENV_LOCAL_PATH = _ROOT / ".env.local"

# Must import after _load_env so .env is applied
import os

# --- Paths (derived from project root) ---
ROOT = _ROOT
DATA_BINANCE = ROOT / "data" / "binance"
ORDER_STATUS_AUDIT_PATH = DATA_BINANCE / "orders" / "order_status_audit.csv"

# --- Binance ---
BINANCE_FUTURES_BASE = os.getenv("BINANCE_FUTURES_BASE", "https://demo-fapi.binance.com")
BINANCE_FUTURES_PUBLIC_BASE = os.getenv("BINANCE_FUTURES_PUBLIC_BASE", "https://fapi.binance.com")
BINANCE_SPOT_BASE = os.getenv("BINANCE_SPOT_BASE", "https://api.binance.com")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY") or os.getenv("BINANCE_UM_API_KEY") or ""
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_UM_API_SECRET") or ""

# --- Binance optional config ---
BINANCE_FUNDING_LOOKBACK_DAYS = int(os.getenv("BINANCE_FUNDING_LOOKBACK_DAYS", "90"))
# User Data Stream WebSocket base (default: mainnet vs testnet from BINANCE_FUTURES_BASE)
_default_ws = "wss://stream.binancefuture.com" if "demo-fapi" in BINANCE_FUTURES_BASE else "wss://fstream.binance.com"
BINANCE_WS_BASE = os.getenv("BINANCE_WS_BASE", _default_ws)

# --- Backend ---
# Prefer generic hosting env var PORT (e.g. Railway, Render, Heroku) with BACKEND_PORT as an override.
_port_env = os.getenv("PORT") or os.getenv("BACKEND_PORT") or "8000"
BACKEND_PORT = int(_port_env)
# If false/0/no/off, backend does not start any fetch loops (positions, market data, order history, funding, WS). Default true.
_run_fetch_loops = os.getenv("RUN_FETCH_LOOPS", "true").strip().lower()
RUN_FETCH_LOOPS = _run_fetch_loops not in ("false", "0", "no", "off")
CRAWL_POSITIONS_INTERVAL_SECONDS = int(os.getenv("CRAWL_POSITIONS_INTERVAL_SECONDS", "60"))
ORDER_HISTORY_REFRESH_SECONDS = int(os.getenv("ORDER_HISTORY_REFRESH_SECONDS", "60"))
FUNDING_ESTIMATE_INTERVAL_SECONDS = int(os.getenv("FUNDING_ESTIMATE_INTERVAL_SECONDS", "3600"))
MARKET_DATA_INTERVAL_SECONDS = int(os.getenv("MARKET_DATA_INTERVAL_SECONDS", "300"))
FUNDING_RATE_HISTORY_INTERVAL_SECONDS = int(os.getenv("FUNDING_RATE_HISTORY_INTERVAL_SECONDS", "3600"))
FUNDING_MARKET_DATA_INTERVAL_SECONDS = int(os.getenv("FUNDING_MARKET_DATA_INTERVAL_SECONDS", "3600"))
FUNDING_FEE_HISTORY_INTERVAL_SECONDS = int(os.getenv("FUNDING_FEE_HISTORY_INTERVAL_SECONDS", "3600"))
FUNDING_FEE_HISTORY_FIRST_DAYS = int(os.getenv("FUNDING_FEE_HISTORY_FIRST_DAYS", "90"))

# --- External APIs ---
COINGLASS_BASE = os.getenv("COINGLASS_BASE", "https://open-api-v4.coinglass.com")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# --- Hyperliquid ---
HYPERLIQUID_VAULT_ADDRESS = os.getenv("HYPERLIQUID_VAULT_ADDRESS", "0xd6e56265890b76413d1d527eb9b75e334c0c5b42")
HYPERLIQUID_INFO_HOST = os.getenv("HYPERLIQUID_INFO_HOST", "https://api.hyperliquid.xyz")

# --- Debug: list of all exported names (for print_env_for_debug) ---
_ENV_MANAGER_VARS = [
    "ROOT", "DATA_BINANCE", "ORDER_STATUS_AUDIT_PATH",
    "BINANCE_FUTURES_BASE", "BINANCE_FUTURES_PUBLIC_BASE", "BINANCE_SPOT_BASE",
    "BINANCE_API_KEY", "BINANCE_API_SECRET",
    "BINANCE_FUNDING_LOOKBACK_DAYS", "BINANCE_WS_BASE",
    "BACKEND_PORT", "RUN_FETCH_LOOPS",
    "CRAWL_POSITIONS_INTERVAL_SECONDS", "ORDER_HISTORY_REFRESH_SECONDS",
    "FUNDING_ESTIMATE_INTERVAL_SECONDS", "MARKET_DATA_INTERVAL_SECONDS",
    "FUNDING_RATE_HISTORY_INTERVAL_SECONDS", "FUNDING_MARKET_DATA_INTERVAL_SECONDS",
    "FUNDING_FEE_HISTORY_INTERVAL_SECONDS", "FUNDING_FEE_HISTORY_FIRST_DAYS",
    "COINGLASS_BASE", "COINGLASS_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "HYPERLIQUID_VAULT_ADDRESS", "HYPERLIQUID_INFO_HOST",
]
_MASK_KEYS = frozenset(("BINANCE_API_KEY", "BINANCE_API_SECRET", "COINGLASS_API_KEY", "ANTHROPIC_API_KEY"))


def _mask(s: str, max_visible: int = 4) -> str:
    if not s or len(s) <= max_visible * 2:
        return "***" if s else ""
    return f"{s[:max_visible]}***{s[-max_visible:]}"


def print_env_for_debug() -> None:
    """Print all env_manager variables for debugging; API keys/secrets are masked."""
    import sys
    mod = sys.modules.get("env_manager") or sys.modules.get("__main__")
    if mod is None:
        return
    for name in _ENV_MANAGER_VARS:
        val = getattr(mod, name, None)
        if name in _MASK_KEYS and isinstance(val, str) and val:
            val = _mask(val)
        print(f"  {name}={val!r}")
    # Debug env loading: where we look for .env.local and what RUN_FETCH_LOOPS came from
    local_path = _ENV_LOCAL_PATH
    print(f"  ---")
    print(f"  .env.local path: {local_path}")
    print(f"  .env.local exists: {local_path.is_file()}")
    raw = os.getenv("RUN_FETCH_LOOPS")
    print(f"  os.getenv('RUN_FETCH_LOOPS'): {raw!r}")


if __name__ == "__main__":
    print("env_manager variables (secrets masked):")
    print_env_for_debug()
