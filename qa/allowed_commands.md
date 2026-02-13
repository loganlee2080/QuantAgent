# QA Agent – Allowed Commands

Only these commands (and their arguments) may be run by the QA agent. Add or change entries here to expand or restrict automation.

## Setup (one-time)

| Command | Purpose |
|--------|---------|
| `pip install -r requirements.txt` | Install dependencies including pytest, pytest-cov |

## Test execution

| Command | Purpose | Example |
|--------|---------|--------|
| `pytest qa/tests/` | Run all QA tests | `pytest qa/tests/ -v` |
| `pytest qa/tests/ -m unit` | Run unit tests only | — |
| `pytest qa/tests/ -m integration` | Run integration tests only | — |
| `pytest qa/tests/ -m "not integration"` | Skip integration (no live API) | — |
| `pytest qa/tests/ --cov=scripts.binance_trade_api --cov-report=term-missing` | Coverage report | — |
| `pytest qa/tests/test_binance_trade_api.py -v` | Run Phase 1 tests only | — |
| `pytest qa/tests/ -m demo` | Run **demo** integration tests (Binance demo API) | Requires `BINANCE_*` env; demo only, no real money |
| `pytest qa/tests/ -m "not demo"` | Run all tests except demo (default for CI) | — |

## File operations (by path)

| Allowed | Path pattern | Purpose |
|--------|---------------|---------|
| Read | `qa/**`, `scripts/binance_trade_api.py`, `data/binance/orders/*.csv` | Test plans, code, fixtures |
| Write | `qa/bug_reports/BUG-*.md` | Create/update bug reports only |
| Write | `qa/tests/**`, `qa/test_plans/**` | Add/update tests and plans |

## Environment

- Default automated runs (no `-m demo`): do **not** require `BINANCE_*`; use mocks.
- When running **demo** tests (`-m demo`): `BINANCE_API_KEY` and `BINANCE_API_SECRET` (or `BINANCE_UM_*`) may be set; use **demo** base only (`BINANCE_FUTURES_BASE` default `https://demo-fapi.binance.com`). No real money.

## Disallowed

- Sending real orders or modifying **live** (non-demo) Binance account. Demo account is allowed for `-m demo` runs.
- Installing packages not listed in `requirements.txt` without updating it and documenting in this file.
- Running scripts that perform real trades (e.g. `python scripts/binance_trade_api.py real_orders.csv`) as part of automated QA.
