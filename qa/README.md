# QA Agent

**Handle: @qa** — Use `@qa` or `@qa/HANDLE.md` for quick QA context. See `qa/HANDLE.md` for a short reference.

QA agent for CryptoQuant: test planning, execution, bug lifecycle, and automation.

## Skill set

- **Test planning & design**: Test plans, test cases, risk-based prioritization
- **Test execution**: Unit, integration, system, acceptance (UAT)
- **Test types**: Functional, regression, smoke, sanity, exploratory
- **Bug lifecycle**: Report → triage → fix → verify → close
- **Bug reports**: `qa/bug_reports/BUG-YYYYMMDD.md` (or `BUG-YYYYMMDD-N.md` for multiple per day)
- **Automation**: Pytest-based tests; allowed commands defined in `qa/allowed_commands.md`

## Test levels

| Level       | Scope                    | When / where run        |
|------------|---------------------------|--------------------------|
| Unit       | Single functions/classes | `pytest qa/tests/ -m unit` |
| Integration| Modules + mocked I/O      | `pytest qa/tests/ -m integration` |
| System     | Full stack, real services| Manual / CI (with env)   |
| UAT        | User acceptance          | Manual / staging         |

## Test types

- **Functional**: Feature behavior (inputs → outputs, API contracts)
- **Regression**: No breakage after changes
- **Smoke**: Critical paths after deploy
- **Sanity**: Quick check before deeper testing
- **Exploratory**: Unscripted; findings → bug reports or new cases

## Bug lifecycle

1. **Report**: Create `qa/bug_reports/BUG-YYYYMMDD.md` (or `-N`) using the template
2. **Triage**: Assign severity/priority; link to test case if any
3. **Fix**: Dev implements fix; reference bug ID in commit
4. **Verify**: Re-run relevant tests; confirm fix
5. **Close**: Update bug report status to Closed; optional short note

## Allowed commands

The QA agent may run only commands listed in `qa/allowed_commands.md`. That file is the single source of truth for automation and safety.

## Phase 1: binance_trade_api.py

- Test plan: `qa/test_plans/binance_trade_api_phase1.md`
- Tests: `qa/tests/test_binance_trade_api.py`
- Run: `pytest qa/tests/test_binance_trade_api.py -v` (see below for markers)

## Running tests

```bash
# From project root (install deps first: pip install -r requirements.txt)
PYTHONPATH=scripts python -m pytest qa/tests/ -v                # all QA tests
PYTHONPATH=scripts python -m pytest qa/tests/ -m unit -v        # unit only
PYTHONPATH=scripts python -m pytest qa/tests/ -m "not integration" -v  # skip integration
PYTHONPATH=scripts python -m pytest qa/tests/ --cov=binance_trade_api --cov-report=term-missing  # coverage
# Demo API (requires BINANCE_* env; demo account only):
PYTHONPATH=scripts python -m pytest qa/tests/test_binance_trade_api_demo.py -v -m demo
```

## Directory layout

```
qa/
├── HANDLE.md                 # @qa handle — short ref for invoking QA agent
├── README.md                 # this file
├── allowed_commands.md       # commands the QA agent may run
├── bug_reports/
│   ├── BUG-TEMPLATE.md       # template for new bugs
│   └── BUG-YYYYMMDD.md       # actual bug reports
├── test_plans/
│   └── binance_trade_api_phase1.md
└── tests/
    ├── conftest.py           # shared fixtures, mocks
    └── test_binance_trade_api.py
```
