# Summary

Long: BTC/ETH/HYPE  
Short: Altcoin

---

## Vault: [ Systemic Strategies ] ♾️ HyperGrowth ♾️

- **Vault:** https://app.hyperliquid.xyz/vaults/0xd6e56265890b76413d1d527eb9b75e334c0c5b42
- **Crawl:** `python scripts/crawl_hyperliquid_vault.py`
- **Output:**
  - `data/hyperliquid_vault_positions.csv` — per-asset positions (see field list below)
  - `data/hyperliquid_vault_state.json` — raw API response
  - `data/hyperliquid_vault_summary.csv` — account-level summary (append-only for time series)

---

## Vault positions: field list

**Source:** Hyperliquid Info API `clearinghouseState` → `assetPositions[]` and root-level summary.

### Per-position fields (one row per asset in CSV)

| Field | Description |
|-------|-------------|
| `coin` | Asset symbol (e.g. ATOM, HYPE, OP). |
| `szi` | Position size in contracts; negative = short, positive = long. |
| `leverage_type` | Margin mode, e.g. `cross`. |
| `leverage_value` | Leverage multiple (e.g. 3, 5, 10, 20). |
| `entryPx` | Volume-weighted average entry price. |
| `positionValue` | Current notional (abs(size × mark)). |
| `unrealizedPnl` | Unrealized PnL in USD. |
| `returnOnEquity` | ROE (unrealized PnL / margin used). |
| `liquidationPx` | Estimated liquidation price. |
| `marginUsed` | Margin allocated to this position. |
| `marginUsedPercentage` | This position’s share of total margin used (%). Precision 2 decimals, truncate (e.g. 0.01, 1.22, 1.00). |
| `maxLeverage` | Max leverage allowed for this asset. |
| `cumFunding_allTime` | Cumulative funding paid/received, all time. |
| `cumFunding_sinceOpen` | Cumulative funding since position open. |
| `cumFunding_sinceChange` | Cumulative funding since last size change. |
| `time` | (If present) Position-level timestamp from API. |

**Raw API:** Each element in `assetPositions` also has `type` (e.g. `oneWay`).

### Account-level fields (summary CSV / raw JSON root)

| Field | Description |
|-------|-------------|
| `marginSummary.accountValue` | Total account value (USD). |
| `marginSummary.totalNtlPos` | Total notional exposure (absolute). |
| `marginSummary.totalRawUsd` | Raw USD balance component. |
| `marginSummary.totalMarginUsed` | Total margin used. |
| `crossMarginSummary.*` | Same as above for cross-margin view. |
| `crossMaintenanceMarginUsed` | Maintenance margin (cross). |
| `withdrawable` | Withdrawable balance (USD). |
| `time` | Snapshot timestamp (ms, root of response). |

---

## Strategy analysis: [ Systemic Strategies ] ♾️ HyperGrowth ♾️

**Vault address:** `0xd6e56265890b76413d1d527eb9b75e334c0c5b42`

### What the data shows (from latest crawl)

- **Structure:** One large **long** (HYPE) and many **shorts** across altcoins. Aligns with “Long BTC/ETH/HYPE, Short Altcoin” — in this perp snapshot the only long is HYPE (~$5.94M notional); BTC/ETH may be held spot or in other products.
- **Long:** HYPE only — `szi` positive, ~179k units, ~10× leverage, notional ~$5.94M, large positive unrealized PnL and large cumulative funding received.
- **Shorts:** 30 names — ATOM, AVAX, OP, SUI, CRV, XRP, APT, WLD, SEI, ZRO, BLUR, TIA, ADA, NEAR, PYTH, XAI, ONDO, ZETA, W, MERL, BLAST, MORPHO, BERA, LAYER, IP, ZORA, ASTER, AVNT, ICP, etc. Sizes are negative; notional per short roughly ~$45k–$105k; leverage 3×–20× (mostly 3×, 5×, 10×).
- **Risk:** Cross-margin; liquidation prices and margin used are per position; account-level margin and withdrawable indicate capacity for further allocation or withdrawals.
- **Funding:** Each position has `cumFunding_allTime`, `sinceOpen`, `sinceChange`; mix of payers and receivers; HYPE is a large funding receiver; several alt shorts have negative all-time funding (net payer).
- **PnL:** Most shorts show large positive unrealized PnL (alt underperformance vs entry); one short (MORPHO) shows negative unrealized PnL.

### Interpretation

- **Relative-value / alt short:** The book is structured as a long HYPE (and conceptually long BTC/ETH) vs a diversified short alt basket, capturing spread and funding. Sizing and leverage vary by coin (vol/liquidity).
- **Use of the fields:** Track `positionValue`, `unrealizedPnl`, `cumFunding_*`, and `liquidationPx` over time (via repeated crawls and summary CSV) to monitor risk, funding drag/benefit, and PnL; use account-level `accountValue` and `withdrawable` for vault-level risk and capacity.

# Action

## Binance USD-M positions crawl (PRD)

Crawl Binance USD-M futures positions and account; output mirrors the Hyperliquid position table and includes margin/account summary.

### Requirements (done)

| Item | Choice |
|------|--------|
| **Output shape** | Mirror Hyperliquid position table (same columns: coin, szi, leverage_type, leverage_value, entryPx, positionValue, unrealizedPnl, returnOnEquity, liquidationPx, marginUsed, marginUsedPercentage, maxLeverage, cumFunding_*, time). |
| **Tick list** | Provided in script (no CMC API). |
| **Account** | Single API key (for now). |
| **Position mode** | One-way. |
| **Output location** | `data/binance/`. |
| **Summary** | Margin/account summary and any useful data (totalWalletBalance, totalUnrealizedProfit, totalMarginBalance, totalPositionInitialMargin, availableBalance, maxWithdrawAmount, etc.). |

### Implementation

- **Script:** `scripts/crawl_binance_usdm_positions.py`
- **Docs:** https://developers.binance.com/docs/derivatives/Introduction
- **API keys:** From environment: `BINANCE_API_KEY`, `BINANCE_API_SECRET` (no keys in repo).
- **Futures:** USD-M (USD-margined).
- **Tick list:** Defined in script; one row per tick, position = 0 when flat.
- **Library (reference):** https://github.com/binance/binance-connector-python (script uses `requests` + HMAC for compatibility.)

### Environment

| Variable | Purpose |
|----------|---------|
| `BINANCE_API_KEY` | Binance API key (or `BINANCE_UM_API_KEY`). |
| `BINANCE_API_SECRET` | Binance API secret (or `BINANCE_UM_API_SECRET`). Both key and secret are read from environment. |

### Outputs (under `data/binance/`)

| File | Description |
|------|-------------|
| `positions.csv` | One row per tick (script tick list); Hyperliquid-mirror columns + `lastFundingRate`, `markPrice`, `volume24h(USDT)` (= volume24h × markPrice), `openInterest(USDT)` (= openInterest × markPrice), `maxLeverage`, `maxPositionAtMaxLeverage(USDT)` (max notional position at max leverage, from Binance bracket), `binanceUsdm` (yes/no — whether Binance USD-M lists this coin) (exchange max); position = 0 when flat. |
| `summary.csv` | Account-level summary (append-only): totalWalletBalance, totalUnrealizedProfit, totalMarginBalance, totalPositionInitialMargin, totalOpenOrderInitialMargin, availableBalance, maxWithdrawAmount. |
| `account.json` | Raw Binance account response (full balance, positions, etc.). |

### Run

```bash
# Set env vars, then (mainnet):
python scripts/crawl_binance_usdm_positions.py

# Or use Binance USD-M TESTNET (demo-fapi.binance.com):
python scripts/crawl_binance_usdm_positions.py --testnet
```

# Trading

## Summary

Basic Binance USD-M trading API (live, trade-only keys; env already used by crawler).

## Current capabilities

- **Market orders only** (limit/advanced logic can be added later).
- **One-way mode**: `Long` = BUY, `Short` = SELL.
- **Per-order leverage**: leverage can be set before sending each order.
- **Batch orders from CSV** for a simple order table.

## Script

- `scripts/binance_trade_api.py`

### Environment

Uses the same env as the Binance crawler:

| Variable | Purpose |
|----------|---------|
| `BINANCE_API_KEY` / `BINANCE_UM_API_KEY` | Binance USD-M trade/query key (no withdraw). |
| `BINANCE_API_SECRET` / `BINANCE_UM_API_SECRET` | Secret for the key above. |

### Order table (CSV)

Sample CSV (`orders.csv`):

```csv
currency,size_usdt,direct,lever
BTC,1000,Long,100
DOGE,500,Short,20
```

- **currency**: base asset (e.g. `BTC`, `ETH`, `DOGE`). Mapped to `BTCUSDT`, `ETHUSDT`, etc.
- **size_usdt**: notional size in USDT, sent as `quoteOrderQty`.
- **direct**: `Long` → BUY, `Short` → SELL.
- **lever**: integer leverage (optional; blank → no change).

### Run (batch orders)

```bash
python scripts/binance_trade_api.py orders.csv
```

For each row:

- Optionally **set leverage** for the symbol: `POST /fapi/v1/leverage`.
- Place a **MARKET** order on USD-M futures:
  - `symbol = <currency>USDT`
  - `side = BUY` for `Long`, `SELL` for `Short`
  - `quoteOrderQty = size_usdt`

## Next steps (future improvements)

- Add **limit-order policies** (e.g. mark ± x%).
- Add **pair orders** (e.g. BTC long + meme short) with simple wrappers on top of this API.
- Connect trading logic to analytics (vault / positions CSVs) for automation.