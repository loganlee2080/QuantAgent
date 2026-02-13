# Test plan: binance_trade_api.py (Phase 1)

**Component:** `scripts/binance_trade_api.py`  
**Test levels:** Unit, Integration (mocked API)  
**Test types:** Functional, Regression, Smoke

## Risk-based prioritization

| Risk | Area | Priority | Test type |
|------|------|----------|-----------|
| High | Order placement (wrong side/size) | P1 | Functional, Regression |
| High | Close position (wrong side/fraction) | P1 | Functional, Regression |
| Medium | CSV parsing / batch orders | P2 | Functional |
| Medium | Leverage / quantity precision | P2 | Functional |
| Low | Config load, CLI usage | P3 | Smoke, Sanity |

---

## Test cases

### TC-01: _direct_to_side (unit, functional)

| Case | Input | Expected |
|------|--------|----------|
| TC-01a | `"long"`, `"Long"`, `"LONG"` | `"BUY"` |
| TC-01b | `"short"`, `"Short"`, `"SHORT"` | `"SELL"` |
| TC-01c | `"unknown"`, `""` | `ValueError` |

**Risk:** Low. **Automation:** Unit test.

---

### TC-02: _quantity_from_usdt (unit, functional)

- **Setup:** Mock or patch `ORDER_META` (e.g. BTC with quantity_precision=6).
- **Inputs:** symbol, amount_usdt, price (e.g. BTCUSDT, 1000, 50000).
- **Expected:** String quantity with correct precision; positive; no float artifacts.
- **Edge:** amount_usdt/price → qty ≤ 0 → `ValueError`. price ≤ 0 → `ValueError`.

**Risk:** Medium. **Automation:** Unit test with patched meta.

---

### TC-03: _load_order_meta (unit)

- **TC-03a:** When `order_meta.csv` does not exist → return `{}`.
- **TC-03b:** When file exists with valid rows → return dict keyed by currency; blank currency skipped.

**Risk:** Low. **Automation:** Unit test (temp file or path mock).

---

### TC-04: set_leverage (integration, mocked)

- **Mock:** `_signed_request` returns 200 and a stub body.
- **Input:** symbol, leverage (e.g. 10); leverage < 1 → clamped to 1.
- **Expected:** POST /fapi/v1/leverage with symbol and leverage in params.

**Risk:** Medium. **Automation:** Integration test with mock.

---

### TC-05: place_market_order – validation (unit/integration, functional)

- **Mock:** `_get_mark_price`, `_signed_request`, `_get_keys`.
- **TC-05a:** side not BUY/SELL → `ValueError`.
- **TC-05b:** quote_usdt ≤ 0 → `ValueError`.
- **TC-05c:** Valid inputs → _signed_request called with type=MARKET, correct side and quantity format.

**Risk:** High. **Automation:** Unit/integration.

---

### TC-06: close_position – no position / fraction (unit/integration)

- **Mock:** `_signed_request` (positionRisk returns list with no open position or zero amt).
- **TC-06a:** No position for symbol → returns `None`, no order placed.
- **TC-06b:** fraction ≤ 0 → returns `None`.
- **TC-06c:** fraction > 1 → clamped to 1.0; order placed with correct side and reduceOnly.

**Risk:** High. **Automation:** Integration with mock.

---

### TC-07: close_position_limit (integration, mocked)

- Same position fetch mock as TC-06; LIMIT order params: timeInForce=GTC, price rounded, reduceOnly=true.
- **Expected:** POST /fapi/v1/order with type=LIMIT and correct quantity/price.

**Risk:** High. **Automation:** Integration with mock.

---

### TC-08: place_batch_orders (integration, functional)

- **Mock:** `_get_keys`, `_get_mark_price`, `_signed_request`.
- **TC-08a:** Empty list → returns `[]`.
- **TC-08b:** amountUsdt ≤ 0 → `ValueError`.
- **TC-08c:** > 5 orders → chunked; batchOrders called per chunk (max 5).
- **TC-08d:** positionSide LONG/SHORT → side BUY/SELL; symbol normalized to *USDT.

**Risk:** Medium. **Automation:** Integration with mocks.

---

### TC-09: place_orders_from_csv (integration, functional)

- **Mock:** `_get_keys`, `place_market_order`, `close_position`; real or temp CSV.
- **TC-09a:** File not found → sys.exit(1).
- **TC-09b:** Empty CSV → no orders, no exit.
- **TC-09c:** Row missing currency/size_usdt/direct → row skipped.
- **TC-09d:** Invalid size_usdt → row skipped.
- **TC-09e:** direct=Close or reduce_only → close_position called; else place_market_order with correct args.

**Risk:** Medium. **Automation:** Integration with mocks and temp CSV.

---

### TC-10: place_close_orders_from_template (integration)

- **Mock:** `_get_keys`, `close_position`, `close_position_limit`, `_get_mark_price`.
- **TC-10a:** File not found → sys.exit(1).
- **TC-10b:** order_type=MARKET → close_position called; LIMIT with price=mark → _get_mark_price then close_position_limit.

**Risk:** Medium. **Automation:** Integration with mocks and temp CSV.

---

### TC-11: main() CLI (smoke)

- **TC-11a:** No args (or only script name) → exit code 1, usage message.
- **TC-11b:** `--close-template` [path] → place_close_orders_from_template invoked (mock to avoid real I/O).
- **TC-11c:** csv_file → place_orders_from_csv invoked.

**Risk:** Low. **Automation:** Unit (patch main’s dependencies).

---

### TC-12: _get_mark_price (unit, mocked HTTP)

- **Mock:** requests.get return status 200, body `{"price": "50000.5"}`.
- **Expected:** float 50000.5; 4xx/5xx → raise.

**Risk:** Low. **Automation:** Unit.

---

## Execution matrix

| Level     | Type        | Run with |
|-----------|-------------|----------|
| Unit      | Functional  | `pytest qa/tests/test_binance_trade_api.py -m unit` |
| Integration | Functional, Regression | `pytest qa/tests/test_binance_trade_api.py -m integration` |
| Smoke     | Sanity      | `pytest qa/tests/test_binance_trade_api.py -m smoke` |
| **Demo**  | Live vs demo API | `pytest qa/tests/test_binance_trade_api_demo.py -v -m demo` (requires `BINANCE_*` env; demo account only) |

## Demo integration tests

File: `qa/tests/test_binance_trade_api_demo.py`. Run with `PYTHONPATH=scripts python -m pytest qa/tests/test_binance_trade_api_demo.py -v -m demo`.

| Test | What it does |
|------|----------------|
| `test_demo_get_mark_price` | Public ticker/price (no credentials); asserts demo base URL. |
| `test_demo_position_risk` | GET positionRisk (signed); skips if no credentials. |
| `test_demo_set_leverage` | set_leverage(BTCUSDT, 2) then 1 (signed). |
| `test_demo_place_small_market_order_then_close` | Place 6 USDT BUY then close (signed, demo only). |

Demo tests skip when `BINANCE_API_KEY` / `BINANCE_API_SECRET` are not set. Default base is `https://demo-fapi.binance.com`.

## First test run summary

**Date:** 2026-02-10  
**Scope:** Phase 1 — `scripts/binance_trade_api.py`  
**Command:** `PYTHONPATH=scripts python -m pytest qa/tests/test_binance_trade_api.py -v -m "unit or integration or smoke"`

| Result | Count |
|--------|--------|
| Passed | 34 |
| Failed | 0 (after fix below) |
| Skipped | 0 |

**Levels / types covered:** Unit (functional), integration (functional, regression), smoke (sanity). All tests use mocks; no live API calls.

**Issue found and fixed during first run:**
- **Test:** `test_place_batch_orders_chunks_of_five`
- **Cause:** (1) Real `ORDER_META` gave some symbols `quantity_precision` 0, so 50 USDT at mock price 50_000 floored to qty 0 and triggered `ValueError`. (2) Mock returned 7 items per batch → 14 total instead of 6.
- **Fix:** Patch `ORDER_META` in the test with `quantity_precision` 5 for batch symbols; use `side_effect` so first batch returns 5 responses, second returns 1.

**Sign-off (first run):**
- [x] All P1 tests automated and passing
- [x] P2 tests automated where feasible
- [x] No bug reports filed (no product bugs; one test fix only)
- [x] No unmocked live API calls in automated runs

---

## Sign-off (template for future runs)

- [ ] All P1 tests automated and passing
- [ ] P2 tests automated where feasible
- [ ] Bug reports (if any) filed under `qa/bug_reports/BUG-*.md`
- [ ] No unmocked live API calls in automated runs
