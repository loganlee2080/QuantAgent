# CryptoQuant

demo link: https://lees-macbook-pro.tail187a83.ts.net/

**Python:** 3.9+ (tested on 3.9.19). Scripts avoid 3.10+ syntax (e.g. use `typing.Optional` / `Union` instead of `X | Y`).

## Setup

Use a virtual environment so the script uses the same Python where dependencies are installed:

```bash
cd /path/to/CryptoQuant
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Then run scripts with that environment activated:

```bash
python scripts/crawl_hyperliquid_vault.py
# or (after setting Binance env in .env):
python scripts/crawl_binance_usdm_positions.py
```

If you see `ModuleNotFoundError: No module named 'requests'`, you're running with a different Python than the one that has `requests`. Install and run with the **same** interpreter:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/crawl_binance_usdm_positions.py
```

Or use the venv above so one Python is used for both install and run.

## Command cheat sheet

### Backend / data loops

- **Run backend with all background loops (positions, market data, funding, etc.):**
  ```bash
  python scripts/backend_server.py
  ```
- **Run backend without background loops (manual control over crawlers):**
  ```bash
  RUN_FETCH_LOOPS=false python scripts/backend_server.py
  ```
- **Manually refresh Binance market data CSV (includes `pricePrecision`):**
  ```bash
  # from project root
  PYTHONPATH=./scripts python -c "from backend_server import _fetch_and_write_market_data; _fetch_and_write_market_data()"
  ```

### Binance trading / audits

- **Test a small live trade + audit flow (demo/testnet if `BINANCE_FUTURES_BASE` uses `demo-fapi`):**
  ```bash
  python scripts/test_order_place_and_track.py
  ```
- **Place orders from CSV (see `data/binance/orders/order_template.csv`):**
  ```bash
  python scripts/binance_trade_api.py data/binance/orders/order_template.csv
  ```
- **Query order status by orderId and append audit row:**
  ```bash
  python scripts/binance_trade_api.py --order-status BTCUSDT 12345678
  # or via backend:
  curl "http://localhost:8000/api/order-status?symbol=BTCUSDT&orderId=12345678"
  ```
- **Close positions for selected symbols (backend API; writes close template and executes via trade API):**
  ```bash
  curl -X POST http://localhost:8000/api/close-positions \
    -H "Content-Type: application/json" \
    -d '{"symbols": ["BTCUSDT"], "orderType": "MARKET"}'
  ```

### Funding history (how to update)

There are two kinds of funding-related history:

**1. Funding rate history** (the chart when you click a symbol’s “Last funding rate” in the UI)

- **Where it’s stored:** `data/binance/funding/funding_rate_history_<symbol>.csv` (e.g. `funding_rate_history_BTCUSDT.csv`).
- **Automatic updates:**
  - With the backend running, a background loop updates these CSVs **hourly** for every symbol that appears in `data/binance/positions.csv` (`FUNDING_RATE_HISTORY_INTERVAL_SECONDS`, default 3600).
  - When you open the funding history dialog for a symbol, if the latest data is older than 3 days (or missing), the app calls `POST /api/sync-funding-rate-history-once` and then reloads the chart.
- **Manual update (one symbol):** Easiest is to open the funding history dialog in the UI for that symbol (it triggers a sync if data is stale). Or call the API: `POST /api/sync-funding-rate-history-once` with body `{"symbol": "BTCUSDT"}`. From the CLI:
  ```bash
  python scripts/fetch_binance_funding_history.py --rate --symbol BTCUSDT --out-rate data/binance/funding/funding_rate_history_BTCUSDT.csv [--limit 500]
  ```
  (The backend reads from `data/binance/funding/funding_rate_history_<symbol>.csv`.)
- **Manual update (all symbols from positions.csv):**
  ```bash
  python scripts/fetch_binance_funding_history.py --rate --all-from-positions [--append]
  ```
  Uses the currency list from `data/binance/positions.csv` and writes per-symbol CSVs to `data/binance/funding/`.
- **Manual update (all symbols from market data):**
  ```bash
  python scripts/fetch_binance_funding_history.py --rate --all-from-market-data [--per-symbol-out-dir data/binance/funding] [--append]
  ```
  Default per-symbol directory is `data/binance/funding/`.

**2. Funding fee history** (your actual funding fee income, in the Funding fee table)

- **Where it’s stored:** Backend can read from `data/binance/funding_fee_history.csv`; the “Binance funding fee history” API also fetches **live** from Binance when you load the table.
- **Automatic:** With the backend running, an hourly loop appends new funding fee rows (after an initial sync; see below).
- **Manual (e.g. first-time or 90-day backfill):**
  ```bash
  python scripts/fetch_funding_fee_90d.py [--days 90]
  ```
  Requires `BINANCE_API_KEY` and `BINANCE_API_SECRET` (or `BINANCE_UM_*`).

# Frontend

## Summary

Frontend: to monitor/manage current position

Hyperliquidity Provider (HLP) reference: https://app.hyperliquid.xyz/vaults/0xdfc24b077bc1425ad1dea75bcb6f8158e10df303

function set
- metric
    - TVL(usdt)
    - month APR
    - balance
    - any other import metric for user
- Positon list
    - field order refer to HLP style
    - add color to PNL/funding(red loss/green profit)

- Advance(hiding by default, entry locate on top right)
    - Chat box(chatgpt like) for interact with AI Agent & backend data/resource
    - In chat box, we can assemble order open/close

method:
- UI: just keep it simple, easy to build with using mature library refer to @resource/hyperliquid-hlp.png
- tech stack: reactjs

## Q&A (Frontend)

- **Q: What is the primary user goal?**  
  **A:** Quickly see total vault performance (TVL, APR, PnL) and manage Binance/Hyperliquid positions from a single dashboard.

- **Q: What data sources power the UI?**  
  **A:** CSV/JSON outputs under `data/` (e.g. `data/binance/positions.csv`, `data/binance/summary.csv`, Hyperliquid crawler outputs).

- **Q: How often should data refresh?**  
  **A:** Start with manual refresh (button) plus optional auto‑refresh every 30–60 seconds.

- **Q: What is the minimal first version scope?**  
  **A:** Read‑only metrics + position list (no trading), with PnL/funding coloring and basic filters/sorting.

- **Q: Any non‑goals for v1?**  
  **A:** Mobile‑perfect UI and advanced order management; focus on desktop monitoring first.

# Deploy

**Recommended: deploy frontend and backend in the same place.** One host serves both the API and the built frontend: one URL, one deploy, no CORS or proxy setup. Use a Python-capable host (Railway, Render, Fly.io, or a VPS).

## 1. Same place (one host)

- **Build frontend:** `cd frontend && npm ci && npm run build` → output in `frontend/dist`.
- **Serve both from the backend:** Run the Flask app so that:
  - `/api/*` is handled by your existing routes.
  - All other requests are served the static frontend (e.g. serve `frontend/dist` as static files and return `index.html` for SPA routes).
- **Single deploy:** One service, one port (e.g. `BACKEND_PORT=8000`). The app uses relative `/api/...` URLs, so everything works with no extra config.
- **Data:** Include `data/` in the deploy or mount a volume so CSVs persist.

(If the backend doesn’t yet serve the frontend build, add a static file mount for `frontend/dist` and a catch-all route that serves `index.html` for non-API paths.)

## 2. Dataset and env

- **Dataset:** Ensure `data/` exists and is writable. Run crawlers once (or restore a backup) so CSVs are present.
- **Env:** Set at least:
  - `BINANCE_API_KEY`, `BINANCE_API_SECRET` (or `BINANCE_UM_*`) for positions/orders.
  - `COINGLASS_API_KEY` for orderbook history.
  - `ANTHROPIC_API_KEY` if using chat.
  - Optional: `BACKEND_PORT`, `BINANCE_FUTURES_BASE`, `COINGLASS_BASE`, etc.
- Keep `.env` out of the repo; use the host’s env / secrets UI.

## 3. CI/CD and quick updates

- **Deploy:** On push to `main`, build frontend, then deploy the repo (with `frontend/dist` and `data/` as needed) to your single host. One pipeline is enough.
- **Updates:** Push to `main` and redeploy; if `data/` is on a volume, only code changes; data persists.
- **Env changes:** Update in the host’s dashboard and restart (or redeploy) so the backend picks up new vars.

---

**Alternative (split):** You can deploy the frontend to Vercel/Netlify and the backend to Railway/Render/etc. Then you must either proxy `/api` to the backend or set a build-time `VITE_API_URL` so the frontend calls the backend URL. Same-place deploy is simpler unless you need to scale or host them separately.