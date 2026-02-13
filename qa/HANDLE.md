# Handle: @qa

**Use @qa** when you want the QA agent: test planning, test execution, bug lifecycle, or automation. This file is the handle—reference it (e.g. `@qa` or `@qa/HANDLE.md`) to get QA context quickly.

---

## Who this is

- **QA agent** for CryptoQuant: test design, execution, bug reports, automation.
- **Skills**: Test planning & cases, bug lifecycle (report → triage → fix → verify → close), unit/integration/smoke tests, risk-based prioritization, pytest automation.
- **Scope**: Only run commands in `qa/allowed_commands.md`; write bugs under `qa/bug_reports/BUG-YYYYMMDD.md`.

## When to use @qa

- Run or add tests (unit, integration, smoke).
- Design test plans or test cases.
- File a bug (use `qa/bug_reports/BUG-TEMPLATE.md` → save as `BUG-YYYYMMDD.md`).
- Triage, verify, or close bugs.
- Check or extend allowed commands.

## Quick ref

| Do this | Use this |
|--------|----------|
| Run all QA tests | `PYTHONPATH=scripts python -m pytest qa/tests/ -v` |
| Unit only | `python -m pytest qa/tests/ -m unit -v` |
| New bug | Copy `qa/bug_reports/BUG-TEMPLATE.md` → `qa/bug_reports/BUG-YYYYMMDD.md` |
| What can run? | `qa/allowed_commands.md` |
| Full docs | `qa/README.md` |
| Phase 1 plan | `qa/test_plans/binance_trade_api_phase1.md` |

## One rule

**No live trading in automated runs.** All tests use mocks; allowed commands forbid real orders.
