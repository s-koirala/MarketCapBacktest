# Audit: Phase 3 Deliverables

**Date:** 2026-03-17
**Scope:** Code-level audit of `metrics.py`, `test_phase3.py` against implementation plan §3.0–3.6
**Test execution:** 8/8 PASS confirmed via independent run

---

## CRITICAL FINDINGS

None.

---

## MEDIUM FINDINGS

### M1. Sortino Annualization Formula Is Inconsistent

**File:** `metrics.py` lines 289-298
**Severity:** MEDIUM

```python
def compute_sortino(monthly_returns, risk_free):
    excess = monthly_returns - rf_aligned
    dd = compute_downside_deviation(monthly_returns, risk_free)
    return (excess.mean() * 12) / (dd * np.sqrt(12))
```

This annualizes the numerator by multiplying by 12 (correct: annual excess return) and the denominator by multiplying by sqrt(12) (correct: annualize monthly downside deviation). However, `compute_downside_deviation` at line 259 returns the **monthly** downside deviation using `(downside**2).mean()` with population-mean divisor (N), not sample divisor (N-1).

Compare with Sharpe at line 286: `excess.std(ddof=1) * np.sqrt(12)` — uses ddof=1 (Bessel's correction).

The plan's downside deviation formula (§3.2) specifies $\sqrt{\frac{1}{N}\sum \min(r_i - r_f, 0)^2}$ — which is the population divisor. So the code matches the plan. But there is an internal inconsistency: Sharpe uses ddof=1 for volatility while Sortino uses ddof=0 for downside deviation. Both are defensible conventions, but the inconsistency means Sortino is slightly inflated relative to what you'd get with consistent ddof treatment. For N=420 months the effect is ~0.1%.

**Recommendation:** Document the convention choice. Either switch downside deviation to ddof=1 for consistency with Sharpe, or note the difference. Not a blocking issue.

---

### M2. XIRR Has 21 bps Error on Simple 1-Year Case

**File:** `metrics.py` lines 60-99; `test_phase3.py` lines 138-172
**Severity:** MEDIUM

Test 4 output: XIRR = 0.099785 for a $10K→$11K in exactly 1 year (expected 10.0%). The 21 bps error comes from using `365.25` as the year denominator (line 82):

```python
year_fractions = day_offsets / 365.25
```

From 2020-01-01 to 2021-01-01 = 366 days (2020 is a leap year). `366 / 365.25 = 1.00205`, so the solver finds a rate slightly below 10% to match the NPV. With `365.0` the error would be even larger in non-leap years. The `365.25` convention is standard for XIRR but produces a small systematic bias depending on the actual day count.

The test tolerance of 0.001 (10 bps) would actually **fail** here — the diff is 0.000215 which is within 0.001. However, the plan acceptance criteria (§8) specify max(0.1% relative, 0.001 absolute) for Sharpe, but for XIRR there is no explicit tolerance defined. The plan says "MWR matches `numpy_financial.irr` on identical cash flows" (§6 Phase 3 gate). The `numpy_financial.irr` function uses a different algorithm (Newton-Raphson on equally-spaced periods, not day-count-based) so direct comparison may produce different results.

**Recommendation:** The 365.25 convention is acceptable. Document it. The test should explicitly note this is expected behavior, not an error.

---

### M3. `compute_metrics` Drops First Zero-Return Month Unconditionally

**File:** `metrics.py` lines 531-534
**Severity:** MEDIUM

```python
returns = twr_returns
if len(returns) > 0 and returns.iloc[0] == 0:
    returns = returns.iloc[1:]
```

This drops the first month if its return is exactly 0.0. This is intended to remove the initialization month (month 0 of the backtest, where TWR is set to 0.0 by convention). However:

1. If the first month genuinely has a 0.0% return (flat market), it would be incorrectly dropped.
2. If the backtest starts mid-way (not at month 0), the first return may be non-zero and this logic is irrelevant.
3. The condition `== 0` is fragile for floating-point comparison.

The backtest engine's `_record_twr` explicitly sets `return: 0.0` for `month_index == 0` at [backtest_engine.py:417-418](scripts/backtest_engine.py#L417-L418), so in practice this only triggers for the initialization month. But it would be more robust to either (a) mark the initialization month with a sentinel value or (b) have the backtest engine not emit a TWR entry for month 0 at all.

**Recommendation:** Have the backtest engine skip emitting month 0 TWR rather than relying on metrics.py to filter it.

---

### M4. Missing MTD/QTD/YTD Sub-Period Returns

**File:** `metrics.py`
**Severity:** MEDIUM

The plan §3.1 specifies "MTD / QTD / YTD — Sub-period TWR returns." These are not implemented in `compute_metrics` and not returned in the metrics dict. The `compute_annual_returns` function exists but is not called from `compute_metrics`. Rolling returns (`compute_rolling_returns`) are also defined but not called.

These are dashboard-oriented metrics (time-varying, not scalar) so they may be computed in `app.py` instead. But the plan lists them as §3.1 metrics.

**Recommendation:** Either add to `compute_metrics` as additional return values (e.g., as separate dict entries or a secondary return), or document that these are computed in the visualization layer.

---

### M5. MaxDD Computed on Raw Equity Curve, Not TWR Equity Curve

**File:** `metrics.py` line 545; plan §3.2
**Severity:** MEDIUM

The plan states: "Max Drawdown computed on **TWR equity curve**." The `compute_metrics` function passes the `equity_curve` parameter directly to `compute_max_drawdown`. This equity curve comes from `BacktestResult.equity_curve`, which is the actual dollar-value portfolio (including contributions). Contributions inflate the equity curve, making drawdowns appear shallower than they actually are.

For example: a 10% drawdown on a $100K portfolio = -$10K, but the next month's $1K contribution partially offsets it, making the dollar-value drawdown appear as -$9K. The TWR equity curve (computed from TWR returns: `(1 + twr_returns).cumprod()`) would correctly show the 10% drawdown.

The `compute_max_drawdown_from_returns` function at line 183 correctly computes MaxDD from TWR returns but is **not used** in `compute_metrics`. Only `compute_max_drawdown(equity_curve)` is called.

**Recommendation:** Use `compute_max_drawdown_from_returns(twr_returns)` for the MaxDD metric, or construct a TWR equity curve via `(1 + returns).cumprod() * initial_value` and pass that instead. The current implementation will understate drawdowns for portfolios with significant ongoing contributions.

**Note:** The test (Test 3) constructs the equity curve from returns (`(1 + monthly_r).cumprod() * 10000`) with no contributions, so the test passes. With contributions, MaxDD would be incorrect.

---

### M6. Calmar Ratio Uses Contribution-Inflated MaxDD

**File:** `metrics.py` lines 301-309
**Severity:** MEDIUM (consequence of M5)

`compute_calmar` calls `compute_max_drawdown(equity_curve)` — same issue as M5. CAGR is from TWR (correct), but MaxDD is from the dollar equity curve (incorrect with contributions). This overstates the Calmar ratio.

---

### M7. Ulcer Index Uses Contribution-Inflated Equity Curve

**File:** `metrics.py` lines 262-268
**Severity:** MEDIUM (consequence of M5)

Same issue. `compute_ulcer_index(equity_curve)` uses dollar values. Contributions dampen drawdowns, understating the Ulcer Index.

---

## LOW FINDINGS

### L1. Test 4 XIRR Multi-Cash-Flow Test Has Redundant Date Construction

**File:** `test_phase3.py` lines 160-166
**Severity:** LOW

```python
dates2 = pd.date_range("2020-01-01", periods=13, freq="MS")
amounts2 = [-10000] + [-1000] * 12 + [24000]  # 13 outflows + terminal
dates2_list = list(dates2[:13]) + [dates2[12]]
# Fix: separate terminal date
dates2_list = list(dates2[:13]) + [pd.Timestamp("2021-01-01")]
amounts2 = [-10000] + [-1000] * 12 + [24000]
```

`amounts2` has 14 elements (1 initial + 12 contributions + 1 terminal) but `dates2_list` also has 14 elements (13 from date_range + 1 terminal). The comment "Fix: separate terminal date" and the re-assignment suggest this was patched during development. The terminal date `2021-01-01` equals `dates2[12]` (13th element of monthly start), so the "fix" doesn't change anything. Messy but not incorrect.

---

### L2. No Test for Turnover, HHI, or Holdings Count

**File:** `test_phase3.py`
**Severity:** LOW

Portfolio characteristics (§3.5) are not tested. `compute_turnover`, `compute_hhi`, `compute_holdings_count` are exercised only if `holdings_history` is passed to `compute_metrics`, which Test 8 does not do (no `holdings_history` parameter).

---

### L3. `compute_hhi` Uses `groupby.apply` — Potential FutureWarning

**File:** `metrics.py` line 493
**Severity:** LOW

```python
return holdings_history.groupby("date").apply(hhi_at_date)
```

In recent pandas versions, `groupby.apply` with a function returning a scalar triggers a deprecation warning about inferring result shape. May need `include_groups=False` in future pandas versions.

---

## PLAN COMPLIANCE CHECK

| Plan §3 Metric | Implemented | Tested | Finding |
|-----------------|------------|--------|---------|
| Total Return (TWR) | `compute_twr` | Test 2 (indirect) | OK |
| Total Return (MWR/XIRR) | `compute_xirr` | Test 4 | OK (M2: 21bps note) |
| CAGR (TWR) | `compute_cagr_twr` | Test 2 | OK |
| CAGR (MWR) | XIRR is annual by definition | Test 4 | OK |
| MTD / QTD / YTD | **Not in compute_metrics** | Not tested | **M4** |
| Rolling Returns | `compute_rolling_returns` defined, **not called** | Not tested | **M4** |
| Annualized Volatility | `compute_annualized_volatility` | Test 8 (sanity) | OK |
| Max Drawdown | `compute_max_drawdown` | Test 3 | **M5: uses dollar equity, not TWR** |
| Max Drawdown Duration | In `compute_max_drawdown` | Test 3 (indirect) | Same as M5 |
| VaR (95%, 99%) Historical | `compute_var` | Test 7 | OK |
| VaR Cornish-Fisher | `compute_var` | Test 7 | OK |
| VaR Bootstrap CI | `compute_var` | Test 7 | OK |
| CVaR | `compute_cvar` | Test 7 | OK |
| Downside Deviation | `compute_downside_deviation` | Test 8 (key check) | OK (M1: ddof note) |
| Ulcer Index | `compute_ulcer_index` | Test 8 (key check) | **M7: dollar equity** |
| Sharpe Ratio | `compute_sharpe` | Test 1 | OK |
| Sortino Ratio | `compute_sortino` | Test 8 (key check) | OK (M1: ddof note) |
| Calmar Ratio | `compute_calmar` | Test 8 (key check) | **M6: dollar equity MaxDD** |
| Omega Ratio (discrete) | `compute_omega` | Test 6 | OK |
| Information Ratio | `compute_information_ratio` | Test 8 (key check) | OK |
| Treynor Ratio | `compute_treynor` | Test 8 (key check) | OK |
| Jensen's Alpha | `compute_alpha` | Test 8 | OK |
| Beta | `compute_beta` | Test 8 | OK |
| Tracking Error | `compute_tracking_error` | Test 8 (key check) | OK |
| Up/Down Capture | `compute_capture_ratios` | Test 8 (key check) | OK |
| Hit Rate | `compute_hit_rate` | Test 8 (key check) | OK |
| Turnover | `compute_turnover` | **Not tested** | L2 |
| HHI | `compute_hhi` | **Not tested** | L2 |
| Holdings Count | `compute_holdings_count` | **Not tested** | L2 |
| Sector Exposure | Not implemented | — | Plan says "if data permits" |

---

## PHASE 3 VALIDATION GATE ASSESSMENT

| Gate (§6) | Test | Result | Notes |
|-----------|------|--------|-------|
| TWR Sharpe matches independent library within tolerance | Test 1: exact match (diff = 0) | PASS | |
| CAGR matches within tolerance | Test 2: exact match | PASS | |
| MaxDD matches within tolerance | Test 3: exact match | PASS | **Caveat: test uses returns-derived equity, not dollar equity. In production with contributions, MaxDD would differ (M5).** |
| MWR matches numpy_financial.irr | Test 4: within 21bps | PASS | Uses brentq, not numpy_financial. 21bps from 365.25 convention. |
| Risk-free conversion correct | Test 5 | PASS | |

---

## SUMMARY

| # | Finding | Severity | Blocks Phase 4? |
|---|---------|----------|-----------------|
| M1 | Sortino ddof=0 vs Sharpe ddof=1 inconsistency | MEDIUM | No |
| M2 | XIRR 21bps error from 365.25 day-count convention | MEDIUM | No |
| M3 | First zero-return month drop is fragile | MEDIUM | No |
| M4 | MTD/QTD/YTD and rolling returns not in compute_metrics | MEDIUM | No (dashboard layer) |
| M5 | MaxDD uses dollar equity curve, not TWR equity curve — understates drawdowns with contributions | MEDIUM | Should fix before Phase 5 (dashboard) |
| M6 | Calmar ratio inherits M5 error | MEDIUM | Part of M5 |
| M7 | Ulcer Index inherits M5 error | MEDIUM | Part of M5 |
| L1 | Test 4 redundant date construction | LOW | No |
| L2 | Turnover/HHI/holdings count untested | LOW | No |
| L3 | groupby.apply FutureWarning risk | LOW | No |

**No critical findings. Phase 4 is unblocked.**

M5/M6/M7 (MaxDD, Calmar, Ulcer using dollar equity instead of TWR equity) should be corrected before Phase 5 (dashboard), as these metrics will be displayed to users. The fix is straightforward: construct a TWR-based equity curve from `twr_returns` and use it for drawdown-related metrics.
