# Consolidated Dashboard Audit Report

**Date:** 2026-03-17
**Scope:** app.py dashboard, metrics.py, strategies.py, backtest_engine.py, market_cap_estimator.py, grid_search.py, all test files
**Agents:** 5 parallel audits (UX/flow, metrics tables, calculation correctness, best practices research, test coverage)

---

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Dashboard UX/Flow (D-) | 3 | — | 10 | 8 | 21 |
| Metrics Tables (T-) | 2 | — | 6 | 5 | 13 |
| Calculations (CALC-) | 1 | — | 3 | 3 | 7 |
| Test Coverage (TEST-G) | 1 | 6 | 20 | 14 | 41 |
| **Total** | **7** | **6** | **39** | **30** | **82** |

**Top 3 blockers:**
1. **CALC-C4** — BRK ticker mismatch: Berkshire Hathaway silently excluded from all strategy portfolios
2. **D-C2 / CALC-M3** — Dashboard XIRR uses only 2 cash flows (initial + terminal), omitting all monthly contributions — MWR is meaningless
3. **D-C3 / T-C1** — No executive summary, no KPI cards, metrics table uses raw snake_case column names

**Stale CLAUDE.md items:** Phase 3 M5/M6/M7 (MaxDD/Calmar/Ulcer on dollar equity) are already fixed in code but listed as "OPEN — Must Fix Before Production."

---

## 1. Calculation Correctness Findings

### CALC-C4 | CRITICAL | BRK ranking ticker has no matching price data

**Files:** `market_cap_estimator.py:216`, `backtest_engine.py:252-256`

The market cap estimator aggregates BRK-A + BRK-B into ticker "BRK". When a strategy selects "BRK" as a holding, `backtest_engine.py:252` filters `if t in prices_today` — "BRK" has no price data (only "BRK-A" and "BRK-B" exist), so it is silently dropped. The remaining weights are rescaled to fill 100% (line 260), redistributing BRK's allocation to other holdings.

**Impact:** Berkshire is consistently top-10 by market cap. Strategy 2 (top-N) and Strategy 3 (momentum) are affected whenever BRK is a candidate. Returns are misattributed to non-BRK holdings.

**Fix:** Map "BRK" → "BRK-B" in strategy output or use "BRK-B" as the ranking ticker in the estimator.

---

### CALC-M3 | MEDIUM | Dashboard XIRR uses simplified 2-point cash flows

**File:** `app.py:272-275`

For all series (strategies AND benchmarks), XIRR is computed with only initial outflow and terminal value. Monthly contributions are omitted. This overstates MWR because the terminal value (inflated by contributions) is attributed to the initial investment alone.

The backtest engine correctly records all cash flows in `result.cash_flows`, but the dashboard discards them.

**Fix:** Use `strategy_results[name].cash_flows` for strategies. For benchmarks, construct the full monthly cash flow series.

---

### CALC-M8 | MEDIUM | Capture ratios use arithmetic mean (undocumented convention)

**File:** `metrics.py:426-449`

Up/down capture computed as `mean(port_returns) / mean(bench_returns)` for up/down months respectively. This is the arithmetic convention — the geometric convention uses compounded returns. Both are valid, but the choice should be documented.

---

### CALC-L1 | LOW | Rank-1 tie-breaking is arbitrary

**File:** `market_cap_estimator.py:243-245`

Uses `method="min"` for ranking, so ties produce identical ranks. `strategy_top1` takes `iloc[0]` for rank-1 ties. Exact float ties are astronomically unlikely with real data.

---

### Verified Correct (No Issues)

- TWR: `(value_before_cf - prev_value) / prev_value` — correct
- Transaction costs: `cost_bps / 20000` per leg, time-varying schedule — correct
- Monthly contributions: $1K after month 0 — correct
- Sharpe annualization: `(mean_excess / std_excess) * sqrt(12)` — correct
- Sortino annualization: consistent with Sharpe — correct
- Log-momentum formula: `np.log(mc_now / mc_past)` — correct
- Split factor: `np.searchsorted` + cumulative product — correct
- No look-ahead bias in backtest engine or grid search
- Cornish-Fisher VaR formula — correct
- Jensen's alpha and beta — correct
- Phase 3 M5/M6/M7 (MaxDD/Calmar/Ulcer) — **already fixed** (uses TWR equity)

---

## 2. Dashboard UX/Flow Findings

### D-C3 | CRITICAL | No executive summary or KPI cards

**File:** `app.py:297`

Dashboard launches directly into an equity curve chart. No `st.metric()` KPI cards. A portfolio manager cannot see headline numbers (CAGR, Sharpe, MaxDD, total return) without scrolling through 7 charts to the metrics table.

**Fix:** Add a row of 5 `st.metric()` tiles above the first chart: CAGR, Sharpe, MaxDD, Sortino, Final Value — with benchmark deltas.

---

### D-C2 | CRITICAL | Benchmark XIRR cash flows incomplete

Same as CALC-M3 above. The dashboard constructs synthetic 2-row cash flows for both strategies and benchmarks, ignoring the engine's proper `cash_flows` attribute.

---

### D-C1 | CRITICAL | Benchmark equity curve has no transaction costs

**File:** `app.py:243-249`

Strategies pay 10-50 bps per trade. Benchmarks pay zero. This inflates benchmark performance relative to strategies, creating an unfair comparison.

**Fix:** Either apply a representative cost to benchmark purchases or document the cost asymmetry prominently.

---

### D-M1 | MEDIUM | Comparison bar chart mixes incompatible scales

**File:** `app.py:468-481`

CAGR (~0.10), Sharpe (~1.5), MaxDD (~-0.35), Sortino (~2.0), and Calmar (~0.3) plotted on the same y-axis. Visually misleading — Sharpe appears 15x larger than CAGR.

**Fix:** Use faceted subplots (`facet_col="Metric"`) or a radar chart.

---

### D-M2 | MEDIUM | Equity curve vs drawdown use different bases (dollar vs TWR)

**File:** `app.py:300-308` (dollar equity), `app.py:317-327` (TWR drawdown)

Equity chart shows dollar values (including contributions). Drawdown chart uses TWR cumulative returns (excluding contributions). Both are correct, but the distinction is never explained to the user.

**Fix:** Add explanatory caption below drawdown chart.

---

### D-M3 | MEDIUM | Date inputs use raw text_input with no validation

**File:** `app.py:96-99`

Entering invalid dates crashes the app. No try/except, no `st.date_input()`.

**Fix:** Replace with `st.date_input` or add input validation.

---

### D-M4 | MEDIUM | VaR/CVaR lines shown only for first strategy

**File:** `app.py:396-404`

Return distribution overlays all strategies, but risk markers only for the first non-benchmark.

---

### D-M5 | MEDIUM | Metrics table is flat, unformatted, 30+ columns wide

**File:** `app.py:488-513`

Raw snake_case column names, no grouping, no highlighting, requires horizontal scrolling. See T-C1 for details.

---

### D-M6 | MEDIUM | No data download capability

No `st.download_button()` for any data — equity curves, metrics, trade log.

---

### D-M7 | MEDIUM | Trade log never displayed

`BacktestResult.trades` exists but is never shown. Essential for backtest validation.

---

### D-M8 | MEDIUM | No consistent color scheme across charts

**File:** All chart code

No fixed color map. Same strategy can appear in different colors across charts when trace order shifts.

**Fix:** Define `COLOR_MAP = {"Top-1": "#1f77b4", ...}` and apply everywhere.

---

### D-M9 | MEDIUM | Heatmap height calculation produces cramped charts for short date ranges

**File:** `app.py:378`

`max(300, len(hm_pivot) * 22)` — too small multiplier for few years.

---

### D-M10 | MEDIUM | Benchmark `pct_change()` drops first month silently

**File:** `app.py:217-218`

Can misalign benchmark and strategy date ranges by one month.

---

### D-L1–D-L8 | LOW

- L1: X-axes not consistently formatted across charts
- L2: Strategy 2 checkbox label hardcodes "Top-N"
- L3: No `st.spinner()` for chart rendering
- L4: `_clean_twr` duplicates logic in `compute_metrics`
- L5: Correlation chart missing horizontal legend
- L6: Benchmark checkboxes not alphabetically sorted
- L7: No favicon
- L8: Grid search selected-row check uses fragile `== True`

---

## 3. Metrics Tables Findings

### T-C1 | CRITICAL | Snake_case columns, no grouping, no explanations

**File:** `app.py:488-513`

Main metrics table dumps ~30+ keys as raw identifiers (e.g., `cagr_twr`, `var_95_historical`, `max_drawdown_duration_days`). No human-readable labels, no logical grouping, no tooltips.

**Fix:** Rename columns, group into sections (Returns / Risk / Risk-Adjusted / Benchmark-Relative), add `st.caption()` explanations.

---

### T-C2 | CRITICAL | 11 metrics displayed as raw unformatted floats

**File:** `app.py:493-504`

Missing from `format_cols`: `max_drawdown_duration_days`, `var_95_cornish_fisher`, `var_95_bootstrap_ci_lower/upper`, `var_99_cornish_fisher`, `var_99_bootstrap_ci_lower/upper`, `avg_turnover`, `avg_hhi`, `avg_holdings`. Display with 15+ decimal digits.

**Fix:** Add all keys to format dictionary.

---

### T-M1 | MEDIUM | No summary scorecard — cannot quickly identify winner

No compact scorecard with green/red highlighting per metric. No "Rank" column.

---

### T-M2 | MEDIUM | Comparison bar chart mixes incompatible scales

Same as D-M1.

---

### T-M3 | MEDIUM | No conditional formatting on main metrics table

`st.dataframe()` without any `Styler`. Compare with annual returns table which correctly uses `.background_gradient()`.

---

### T-M4 | MEDIUM | Benchmark rows show meaningless zeros for self-relative metrics

Alpha, beta, tracking error, information ratio all show 0.0 for benchmarks when they should show "N/A".

---

### T-M5 | MEDIUM | Annual returns table lacks summary row

No average or cumulative return row.

---

### T-M6 | MEDIUM | Final holdings table missing total row

No total showing aggregate value and confirming weights sum to ~100%.

---

### T-L1 | LOW | Table orientation forces horizontal scrolling

30+ columns, 2-4 rows. Should transpose: metrics as rows, strategies as columns.

---

### T-L2 | LOW | No bull/bear market regime analysis

No sub-period analysis for dot-com, GFC, COVID.

---

### T-L3 | LOW | Drawdown computed independently in chart and metrics

Maintenance risk if one changes without the other.

---

### T-L4 | LOW | String formatting breaks numeric sort in st.dataframe

Pre-converting to strings makes column sorting lexicographic. Use `Styler.format()` instead.

---

### T-L5 | LOW | VaR/CVaR lines only for first strategy in distribution chart

Same as D-M4.

---

## 4. Test Coverage Gaps

### Critical

| ID | Gap | Description |
|----|-----|-------------|
| TEST-G15 | MaxDD regression test | Code appears fixed (M5/M6/M7), but no test would catch a regression. Need: dollar equity with contributions vs TWR equity, assert `compute_metrics` returns TWR-based drawdown. |

### High Priority

| ID | Gap | Description |
|----|-----|-------------|
| TEST-G4 | Single positive momentum | 100% concentration when only 1 ticker has positive momentum — no regression guard |
| TEST-G11 | Multi-ticker non-trivial returns | All tests use flat prices or single tickers. No test with AAA +10%, BBB -5% verifying portfolio TWR = 2.5% |
| TEST-G16 | `compute_calmar` dollar vs TWR | Could silently use dollar equity if called outside `compute_metrics` |
| TEST-G32 | `compute_strategy3_returns` look-ahead | Critical function for grid search — no direct test verifying weights-at-t-1 applied to returns-at-t |
| TEST-G38 | Benchmark end-to-end | No test verifies benchmark return series are correctly computed and aligned |
| TEST-G40 | Strategy 3 through full backtest | Momentum strategy never tested through `run_backtest` with costs, contributions, delisting |

### Medium Priority (20 gaps)

Key items: weight sum assertions (G7, G14), cash-constrained buys (G9), standalone tests for Sortino/Ulcer/Information Ratio/Treynor/Alpha/Beta/Capture Ratios (G17-G28), grid search RC fallback (G36), Strategy 2 integration (G39).

### Low Priority (14 gaps)

Edge cases: N=0/1, empty data, prev_value<=0, string-true parsing, smoke-test-only Phase 5 tests.

---

## 5. Recommended Section Order (Per Best Practices Research)

Current order vs recommended (derived from Bloomberg PORT, FactSet, QuantConnect, GIPS):

| # | Current | Recommended |
|---|---------|-------------|
| 1 | Equity Curves | **KPI Tiles** (CAGR, Sharpe, MaxDD, Sortino, Final Value) |
| 2 | Drawdowns | **Equity Curve + Drawdown subplot** (shared x-axis) |
| 3 | Rolling Sharpe | **Comparison Table** (strategies vs benchmarks, conditional formatting) |
| 4 | Monthly Heatmap | **Annual Returns Table** |
| 5 | Return Distribution | **Monthly Returns Heatmap** |
| 6 | Holdings Timeline | **Rolling Statistics** (Sharpe, Volatility) |
| 7 | Rolling Correlation | **Return Distribution + VaR/CVaR** |
| 8 | Comparison Bar Chart | **Rolling Benchmark Correlation** |
| 9 | Metrics Table | **Holdings Timeline** |
| 10 | Annual Returns | **Top 10 Best/Worst Months** |
| 11 | Top 10 Best/Worst | **Final Holdings** |
| 12 | Final Holdings | **Trade Log** (currently missing) |

Use `st.tabs(["Performance", "Risk", "Comparison", "Grid Search"])` for progressive disclosure.

---

## 6. Priority Remediation Plan

### Tier 1 — Must Fix (Correctness)

| # | Finding | Effort |
|---|---------|--------|
| 1 | **CALC-C4**: BRK ticker mapping | Small — add `"BRK" → "BRK-B"` mapping in strategy output or estimator |
| 2 | **CALC-M3 / D-C2**: Fix XIRR cash flows | Medium — use `result.cash_flows` for strategies, build full series for benchmarks |
| 3 | **Update CLAUDE.md**: Mark M5/M6/M7 as FIXED | Small |

### Tier 2 — Must Fix (UX)

| # | Finding | Effort |
|---|---------|--------|
| 4 | **D-C3**: Add KPI tiles row | Small |
| 5 | **T-C1**: Rename columns to human-readable labels | Medium |
| 6 | **T-C2**: Add missing format keys | Small |
| 7 | **D-M8**: Define and apply consistent color map | Medium |
| 8 | **T-L1**: Transpose metrics table (metrics as rows) | Small |
| 9 | **T-M3**: Add conditional formatting (Styler) | Medium |
| 10 | **D-M1 / T-M2**: Fix comparison chart (faceted subplots) | Medium |

### Tier 3 — Should Fix

| # | Finding | Effort |
|---|---------|--------|
| 11 | Reorder sections per recommended architecture | Medium |
| 12 | Add `st.tabs()` for Performance/Risk/Comparison/Grid Search | Medium |
| 13 | Add equity curve + drawdown subplot (shared x-axis) | Medium |
| 14 | **T-M4**: Show "N/A" for benchmark self-relative metrics | Small |
| 15 | **D-M3**: Replace text_input with date_input | Small |
| 16 | **D-M6**: Add download buttons | Small |
| 17 | **D-M7**: Add trade log section | Medium |
| 18 | **D-C1**: Document benchmark cost asymmetry | Small |
| 19 | Add custom CSS for metric card styling | Medium |
| 20 | Apply Plotly financial layout template | Medium |

### Tier 4 — Test Coverage

| # | Finding | Effort |
|---|---------|--------|
| 21 | TEST-G15: MaxDD regression test | Small |
| 22 | TEST-G11: Multi-ticker TWR test | Small |
| 23 | TEST-G32: Grid search look-ahead test | Small |
| 24 | TEST-G40: Strategy 3 full backtest test | Medium |
| 25 | TEST-G38: Benchmark end-to-end test | Medium |

---

## Reference Documents

- [DASHBOARD_DESIGN_REFERENCE.md](../docs/DASHBOARD_DESIGN_REFERENCE.md) — Best practices compiled from Bloomberg, FactSet, QuantConnect, GIPS, CFA Institute, Tufte. Includes ready-to-use Plotly template, CSS, color palette, and implementation checklist.
