# MarketCapBacktest — Project Ground Truth

**Last updated:** 2026-03-17
**Plan version:** v2.0 (post-audit)
**Python target:** 3.10+ (3.9 supported via `from __future__ import annotations`)

---

## Project Summary

Market-cap weighted portfolio backtest: three monthly-rebalancing strategies allocating based on equity market capitalization rankings. $10K initial capital, $1K monthly contributions, configurable start date (earliest 1990-01). Compares against Gold, NQ, ES, S&P 500 benchmarks. Institutional-grade performance metrics. Streamlit dashboard.

---

## Architecture

```
MarketCapBacktest/
├── CLAUDE.md                              ← this file
├── requirements.txt                       # Pinned: yfinance, streamlit, plotly, pandas, scipy, etc.
├── docs/
│   ├── IMPLEMENTATION_PLAN.md             # v2.0 — canonical spec
│   └── DASHBOARD_DESIGN_REFERENCE.md      # Best practices reference
├── data/
│   └── delisted_monthly.csv               # 609 rows: ENRNQ, WCOEQ, LEH, GMGMQ, MOB
├── scripts/
│   ├── config.py                          # 47 active + 5 delisted tickers, benchmarks, cost schedule, grids
│   ├── data_fetcher.py                    # yfinance + FRED acquisition, SHA-256 manifest, parquet caching
│   ├── market_cap_estimator.py            # Split-adjusted shares outstanding, BRK-A/B aggregation, validation
│   ├── strategies.py                      # Strategy 1 (top-1), 2 (top-N equal), 3 (log-momentum)
│   ├── backtest_engine.py                 # Monthly rebalance loop, TWR, XIRR cash flows, trade log
│   ├── metrics.py                         # Sharpe, Sortino, Calmar, Omega, VaR/CVaR, Alpha, Beta, etc.
│   ├── grid_search.py                     # Walk-forward (60/36/12), White's Reality Check, 48-combo grid
│   ├── app.py                             # Streamlit dashboard
│   ├── .streamlit/config.toml             # Light theme, headless server
│   ├── test_phase2.py                     # 9/9 PASS
│   ├── test_phase3.py                     # 8/8 PASS
│   ├── test_phase4.py                     # 5/5 PASS
│   ├── test_phase5.py                     # Streamlit tests
│   └── test_phase6_audit.py              # 12/12 PASS
├── results/                               # Cached parquet, data_manifest.json, grid_search_results.csv
└── audits/                                # 6 audit files dated 2026-03-17
    └── audit_dashboard_consolidated_20260317.md  # 82 findings, 5 parallel audits
```

---

## Phase Status

| Phase | Description | Status | Tests |
|-------|-------------|--------|-------|
| 1. Data | data_fetcher, market_cap_estimator, config, delisted CSV | COMPLETE | Validation via checkpoint years |
| 2. Backtest Core | backtest_engine, strategies | COMPLETE | 9/9 PASS (test_phase2.py) |
| 3. Metrics | metrics.py (TWR, MWR, risk-adjusted, benchmark-relative) | COMPLETE | 8/8 PASS (test_phase3.py) |
| 4. Grid Search | Walk-forward, White's Reality Check, 48-combo grid | COMPLETE | 5/5 PASS (test_phase4.py) |
| 5. Visualization | Streamlit dashboard (app.py) | COMPLETE | test_phase5.py |
| 6. Audit | 6 audit documents, all findings logged | COMPLETE | — |
| 7. Dashboard Audit & Overhaul | Consolidated audit, KPI tiles, tabbed layout, fixes | COMPLETE | 12/12 PASS (test_phase6_audit.py) |

---

## Audit History & Finding Disposition

### Implementation Plan Audit (14 findings → 14 remediated)

All F1–F14 from `audit_implementation_plan_20260317.md` were remediated in the plan v2.0 revision. Key changes: corrected market cap formula, added TWR/MWR spec, replaced expanding with sliding walk-forward window, added White's Reality Check, integrated transaction costs, specified rebalancing mechanics.

### Phase 1 Audit (15 findings → 15 remediated)

| ID | Finding | Resolution |
|----|---------|------------|
| C1 | Python 3.9 type hint incompatibility | `from __future__ import annotations` added to both modules |
| C2 | Gold FRED fallback dead code | `_try_fetch_fred_benchmark()` added; fallback chain extended |
| C3 | Non-month-end delisted dates | CSV corrected (LEH→2008-09-30, GMGMQ→2009-06-30); code snaps via `MonthEnd(0)` |
| C4 | 3 of 8 checkpoint years missing | 1990, 1995, 2025 added to `known_market_caps` dict |
| M1 | Cache blind trust | `load_cached()` now verifies SHA-256 against manifest |
| M2 | Split factor O(T*D) loop | Vectorized via `np.searchsorted` + cumulative product |
| M3 | Truthiness bug in gap_pct | Fixed to `not np.isnan(mc1) and not np.isnan(mc2) and mc1 != 0` |
| M4 | WCOEQ shares understated | Post-MCI-merger shares updated to 2.65B (Sept 1998+) |
| M5 | Delisted tickers missing depth | ENRNQ→1993, LEH→1994, MOB→1990 (total 609 rows, was 333) |
| M6 | 2005 rank-1 debatable | Changed to XOM primary, GE as alt |
| M7 | Missing numpy-financial | Added to requirements.txt |
| L1 | Dead code `_month_end_resample` | Removed |
| L2 | NFLX year 1990 | Corrected to 2002; QCOM→1991, GILD→1992 |
| L3 | fredapi unused | Removed from requirements.txt |
| L4 | AVGO/CRM dates | Informational; config is more accurate than plan grouping |

### Phase 2 Audit (8 findings → 7 remediated, 1 deferred)

| ID | Finding | Resolution |
|----|---------|------------|
| C1 | Modified Dietz W=1 incorrect | Pure TWR: `r = (value_before_cf - prev_value) / prev_value`. No W factor. |
| C2 | Delist liquidation + rebuy | Delisted tickers stripped from target_weights + renormalized |
| M1 | Plan text cost formula wrong | **DEFERRED** — code correct (`cost_bps/20000` per leg); plan text not updated |
| M2 | 100% single-stock momentum | Documented as intentional design decision in docstring |
| M3 | `portfolio_value_before_cf` unused | Fixed as part of C1 (now used for TWR) |
| M4 | Silent under-investment | `logger.debug` added for cash-constrained buys |
| L1 | Tests lack non-zero returns | Tests 7/8/9 added (TWR, delisting, position switch) |
| L2 | Circular import workaround | **DEFERRED** — low severity, functional |

### Phase 3 Audit (10 findings → 3 remediated, 7 deferred)

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| M1 | Sortino ddof=0 vs Sharpe ddof=1 | MEDIUM | OPEN — ~0.1% effect, document convention |
| M2 | XIRR 21bps from 365.25 convention | MEDIUM | OPEN — standard convention, acceptable |
| M3 | First zero-return month drop fragile | MEDIUM | OPEN — works in practice but brittle |
| M4 | MTD/QTD/YTD not in compute_metrics | MEDIUM | OPEN — likely computed in dashboard layer |
| M5 | MaxDD uses dollar equity, not TWR equity | MEDIUM | FIXED — `twr_equity = (1 + returns).cumprod()` used for drawdown metrics |
| M6 | Calmar inherits M5 | MEDIUM | FIXED — uses TWR equity via M5 fix |
| M7 | Ulcer Index inherits M5 | MEDIUM | FIXED — uses TWR equity via M5 fix |
| L1 | Test 4 redundant date construction | LOW | OPEN |
| L2 | Turnover/HHI/holdings untested | LOW | OPEN |
| L3 | groupby.apply FutureWarning | LOW | OPEN |

### Phase 4 Audit (8 findings → 8 remediated)

| ID | Finding | Resolution |
|----|---------|------------|
| C1 | Look-ahead in return computation | Loop starts at index 1; weights at `prev_date`, returns at `date` |
| M2 | Zero returns for no-signal months | Changed to `continue` (skip) |
| M3 | Bootstrap block length too short | Floor raised to `max(5.0, n^(1/3))`; sensitivity across {3, primary, 8} |
| M4 | rc_pvalue duplicated per row | Moved to `results_df.attrs["rc_pvalue"]` |
| M5 | Training period unused | Documented in docstring as non-parametric temporal buffer |
| L1 | Synthetic data too clean | Acknowledged; standalone RC test covers both H0 cases |
| L2 | No 48-combo test | Acknowledged; 4-combo subset validates same logic |
| L3 | No data hash in output | `grid_search_meta.json` written with SHA-256 snapshot |

---

## Outstanding Items (Priority Order)

### Must Fix Before Production

(None remaining — CALC-C4 and CALC-M3 fixed in Phase 7.)

### Should Fix

1. **Phase 3 M3** — First zero-return month filtering is a fragile `== 0` float comparison. Better: have backtest engine not emit month-0 TWR.
2. **Phase 3 M1** — Document ddof convention inconsistency (Sharpe ddof=1, downside deviation ddof=0).

### Nice to Have

3. **Phase 2 M1** — Update plan §2.4 text to say `cost_bps / 20000` per leg (not `cost_bps / 10000`).
4. **Phase 3 M4** — Add MTD/QTD/YTD to `compute_metrics` or document as dashboard-layer.
5. **Python upgrade** — Upgrade from 3.9.13 to 3.12+. Python 3.9 is EOL since Oct 2025.
6. **D-C1** — Benchmark returns are gross (no transaction costs) while strategy returns are net. Document or add cost-adjusted benchmark series.
7. **CALC-M8** — Document capture ratio convention (arithmetic vs geometric).
8. **T-L2** — Bull/bear market regime analysis section (placeholder in dashboard).

---

## Key Design Decisions

1. **Market cap estimation:** `close(t) × shares_outstanding_current / cumulative_split_factor(t→now)`. Uses unadjusted close to avoid double-counting splits. Buyback/issuance error quantified at 8 checkpoint years.

2. **TWR calculation:** Pure TWR using `portfolio_value_before_cf` (mark-to-market before any cash flows). No Modified Dietz W-factor needed — contributions arrive at period end with zero exposure.

3. **Strategy 3 momentum formula:** `μ_i(t) = log(M_i(t) / M_i(t-k))`. Log-ratio avoids incumbent-leader bias of the original `M_i/M_1 × ΔM_i` formulation. 100% concentration in a single ticker is permitted by design when only one candidate has positive momentum.

4. **Transaction costs:** Integrated into core loop. Time-varying round-trip: 50 bps (pre-2001), 20 bps (2001-2004), 10 bps (2005+). Per-leg cost = `cost_bps / 20000`.

5. **Grid search returns:** Weights from `t-1`, returns from `t-1` to `t`. No-signal months excluded (not zero-filled). Critical to avoid look-ahead bias.

6. **Walk-forward validation:** 60-month sliding train, 36-month test, 12-month step. White's Reality Check with stationary bootstrap (block mean = max(5, n^(1/3))), 1000 replications. p > 0.10 → default to equal-weight top-5.

7. **Dashboard architecture:** KPI tiles → tabbed layout (Performance/Risk/Comparison/Details). Plotly financial template with consistent color map (strategies saturated, benchmarks muted). Forced light theme via .streamlit/config.toml. Metrics table transposed (metrics as rows, series as columns) with grouped sections and conditional formatting.

---

## Running Tests

```bash
cd scripts
python test_phase2.py        # 9/9
python test_phase3.py        # 8/8
python test_phase4.py        # 5/5
python test_phase6_audit.py  # 12/12
```

## Running the Dashboard

```bash
cd scripts
streamlit run app.py    # Light theme auto-applied via .streamlit/config.toml
```

## Fetching Fresh Data

```bash
cd scripts
python data_fetcher.py        # Fetches all data, writes parquet + manifest
python market_cap_estimator.py # Estimates market caps, validates rankings
python grid_search.py          # Runs 48-combo walk-forward optimization
```

---

## Changelog

### 2026-03-17 — Initial Development & Full Audit Cycle

- **Plan v2.0:** Revised implementation plan addressing 14 findings from plan-level audit (F1–F14). Major changes: corrected market cap formula, added TWR/MWR spec, sliding walk-forward window, White's Reality Check, integrated transaction costs, rebalancing mechanics.
- **Phase 1:** Built data pipeline. 47 active + 5 delisted tickers, BRK-A/B aggregation, FRED risk-free rate, benchmark fallback chains, SHA-256 manifest. Audit found 15 issues; all 15 remediated (Python 3.9 compat, Gold fallback, delisted dates, WCOEQ shares, checkpoint years, etc.).
- **Phase 2:** Built backtest engine + strategies. 9 tests. Audit found 8 issues; 7 remediated (TWR W-factor bug, delist rebuy, cash-constraint logging, non-zero-return tests). 1 deferred (plan text cosmetic).
- **Phase 3:** Built metrics module. 8 tests. Audit found 10 issues; 3 remediated (M5/M6/M7: MaxDD, Calmar, Ulcer Index now use TWR equity curve).
- **Phase 4:** Built grid search. 5 tests. Audit found 8 issues; all 8 remediated (look-ahead bias fix, no-signal exclusion, block length increase, rc_pvalue as metadata, data hash in output).
- **Phase 5:** Built Streamlit dashboard.
- **Phase 6:** Completed 6 audit documents covering plan + phases 1–4 + dashboard.

### 2026-03-17 — Phase 7: Dashboard Consolidated Audit & Remediation

- **Consolidated dashboard audit:** 82 findings across 5 parallel audits (UX/flow, metrics tables, calculation correctness, best practices research, test coverage). Report: `audits/audit_dashboard_consolidated_20260317.md`.
- **Fixed CALC-C4:** BRK ticker mapping (BRK → BRK-B) in backtest engine via RANKING_TO_TRADE mapping.
- **Fixed CALC-M3:** XIRR cash flows now use full monthly series (result.cash_flows for strategies, constructed series for benchmarks) instead of 2-point approximation.
- **Fixed Phase 3 M5/M6/M7:** Confirmed already remediated in code (`twr_equity = (1 + returns).cumprod()` at metrics.py lines 554-558), updated documentation to reflect FIXED status.
- **Dashboard overhaul:** KPI tiles, tabbed layout (Performance/Risk/Comparison/Details), metrics table redesign (transposed, grouped sections, conditional formatting), consistent color scheme (strategies saturated, benchmarks muted), Plotly financial template, trade log, download buttons, cost asymmetry notice.
- **Added .streamlit/config.toml:** Forced light theme for consistent rendering.
- **Added test_phase6_audit.py:** 12 new tests covering critical/high gaps from the consolidated audit.
- **Best practices reference:** Compiled `docs/DASHBOARD_DESIGN_REFERENCE.md` for financial dashboard design patterns.
