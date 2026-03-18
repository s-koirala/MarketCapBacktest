# Audit: Phase 4 Deliverables

**Date:** 2026-03-17
**Scope:** Code-level audit of `grid_search.py`, `test_phase4.py` against implementation plan §2 (walk-forward, White's Reality Check, grid search)
**Test execution:** 5/5 PASS confirmed via independent run

---

## CRITICAL FINDINGS

### C1. Grid Search Uses Weights from Current Date but Returns from Current Date — Look-Ahead in Return Calculation

**File:** `grid_search.py` lines 158-177
**Severity:** HIGH

```python
for i, date in enumerate(dates):
    weights = strategy_momentum(rankings, market_caps, date, n_candidates, k_lookback)
    r_today = ticker_returns.loc[date]
    port_r = sum(w * r_today.get(t, 0.0) for t, w in weights.items() ...)
```

`ticker_returns = price_pivot.pct_change()` computes the return from the **prior** month-end to the **current** month-end. The strategy computes weights at the **current** month-end using market cap data available at that date. The portfolio return is then `sum(w_i * r_i)` where `r_i` is the return that **already happened** from last month to this month.

This is a **look-ahead bias**: the strategy observes the market cap at month-end (which incorporates this month's price changes), selects weights based on that information, and then applies those weights to the returns that already occurred during the same month.

**Correct approach:** Weights should be computed at date `t-1` (prior month-end), then applied to returns from `t-1` to `t`. This means the portfolio return at date `t` should use `weights[t-1]`:

```python
for i, date in enumerate(dates[1:], 1):
    prev_date = dates[i - 1]
    weights = strategy_momentum(rankings, market_caps, prev_date, ...)
    r_today = ticker_returns.loc[date]
    port_r = sum(w * r_today.get(t, 0.0) for t, w in weights.items() ...)
```

The same issue applies to `compute_benchmark_returns` at lines 206-219.

**Impact:** The grid search evaluates strategies on look-ahead-contaminated returns. Parameter selection may favor parameters that exploit this bias. The selected "optimal" parameters may underperform in the actual backtest (which correctly uses prior-month weights via the backtest engine's rebalance-then-hold logic).

**Note:** The backtest engine (`backtest_engine.py`) does NOT have this issue — it rebalances at date `t`, then holds until date `t+1`, earning the return between `t` and `t+1`. The look-ahead is isolated to the grid search's lightweight return computation.

---

## MEDIUM FINDINGS

### M1. Fold Count Discrepancy: 28 Folds Generated vs Plan's ~27

**File:** `grid_search.py` lines 51-98
**Severity:** LOW-MEDIUM (informational)

Test 1 output: 28 folds from 420 months. The plan (§2) says "approximately 27 folds." The difference comes from boundary handling — the code generates one extra fold depending on alignment. Not an error, but the fold count should be documented in the grid search output.

---

### M2. `compute_strategy3_returns` Returns 0.0 When Weights Are Empty

**File:** `grid_search.py` lines 166-168
**Severity:** MEDIUM

```python
if not weights:
    returns.append({"date": date, "return": 0.0})
    continue
```

When the strategy returns no weights (e.g., insufficient lookback history), the return is recorded as 0.0. This creates a bias: months where the strategy has no signal are treated as zero-return months rather than excluded. For the first `k_lookback` months, all strategies will show 0.0 returns, which inflates the Sharpe ratio by adding zero-volatility observations.

**Recommendation:** Either exclude no-signal months from the return series (skip the append entirely) or use NaN and handle NaN-aware Sharpe computation. The `compute_oos_sharpe` function should then be NaN-aware.

---

### M3. Block Length in Stationary Bootstrap Is Data-Adaptive but Not Validated

**File:** `grid_search.py` line 299
**Severity:** MEDIUM

```python
block_mean = max(2.0, n_folds ** (1 / 3))
```

The block mean `n^(1/3)` is a standard heuristic (Politis & Romano, 1994; Patton, Politis & White, 2009), but with n_folds = 28 (from test output), `28^(1/3) ≈ 3.04`. This means average block length is ~3 folds. Given that fold Sharpe ratios may have serial correlation from overlapping test windows (test windows overlap because step=12 < test=36), the block length should be long enough to capture this dependence.

With 12-month step and 36-month test window, adjacent folds share 24 months of overlap. The autocorrelation of fold Sharpes could be significant. A block mean of 3 may be too short.

**Recommendation:** Use the automatic block-length selection procedure of Politis & White (2004), or at minimum run a sensitivity analysis with block_mean ∈ {3, 5, 8} and verify the p-value is stable.

---

### M4. `rc_pvalue` Is Identical for All Rows in Results DataFrame

**File:** `grid_search.py` line 434
**Severity:** MEDIUM

```python
results_df["rc_pvalue"] = rc_pvalue
```

The Reality Check produces a single p-value for the joint null hypothesis "no strategy beats the benchmark." This is correct per White (2000) — it's a single test, not per-strategy. However, assigning the same p-value to every row in the results table is confusing. A reader might interpret it as each strategy having p=0.0, which is wrong.

**Recommendation:** Report `rc_pvalue` once as metadata, not per row. Or add a column `rc_applies_to_selected` that is True only for the selected row.

---

### M5. No Handling of Train Period in Grid Search — Strategy Trains on Nothing

**File:** `grid_search.py` lines 379-415
**Severity:** MEDIUM

The walk-forward framework defines train/test periods, but the grid search **never uses the training period**. The full return series is computed once over all dates (line 383-385), and then Sharpe is evaluated on the test period only (line 399-401). The training period exists solely to create a temporal buffer.

This is acceptable IF Strategy 3's parameters don't require fitting (they don't — the momentum formula is fixed, only N and k vary). But the plan's language (§2: "train on expanding window" / "sliding window") implies the training period is used for parameter selection within each fold. In the current implementation, the "training" is happening implicitly: the momentum weights at date `t` use market cap data from `t-k` to `t`, which falls within the training period for early test dates.

This is not incorrect for Strategy 3's non-parametric approach, but should be documented to avoid confusion with traditional train/test semantics where model parameters are estimated in-sample.

---

## LOW FINDINGS

### L1. Test 4 Grid Search Uses rc_pvalue=0.0 — Suspiciously Perfect

**File:** `test_phase4.py` lines 184-219
**Severity:** LOW

The synthetic data grid search produces `rc_pvalue=0.0` for all strategies. This means the bootstrap never produced a statistic as extreme as the observed one in 500 replications. This likely indicates the synthetic data is too clean (deterministic trends, no noise) or the benchmark (equal-weight top-5) is much weaker than the momentum strategies.

This doesn't indicate a bug, but the test doesn't exercise the "fail to reject" case for the grid search (Test 3 does exercise it for the standalone Reality Check). A more rigorous test would use synthetic data where the momentum strategy and benchmark perform similarly.

---

### L2. No Test for 48-Combination Full Grid

**File:** `test_phase4.py`
**Severity:** LOW

Test 4 uses a 2×2 = 4-combination grid for speed. The plan specifies 48 combinations (8×6). While the logic is the same regardless of grid size, there is no test verifying the full 48-row output. This is acceptable for CI speed but should be run manually at least once.

---

### L3. Grid Search Saves Results Without Data Hash

**File:** `grid_search.py` lines 509-511
**Severity:** LOW

```python
results.to_csv(RESULTS_DIR / "grid_search_results.csv", index=False)
```

The grid search results are saved without recording which data version produced them. Per the plan (§5.3), cached results should include a data hash. If the underlying data changes, stale grid search results may be used.

---

## PLAN COMPLIANCE CHECK

| Plan Requirement (§2) | Code Status | Finding |
|-----------------------|-------------|---------|
| Sliding window (not expanding) | Implemented: fixed 60m window | OK |
| Train window: 60 months | Verified in Test 2: 60m | OK |
| Test window: 36 months | Verified in Test 2: 36m | OK |
| Step size: 12 months | Verified: 28 folds from 420 months | OK |
| ~27 folds | 28 folds (close enough) | M1 |
| OOS Sharpe per fold | `compute_oos_sharpe` | OK |
| Mean ± std Sharpe across folds | In results table | OK |
| train_end < test_start (no look-ahead) | Assert in `generate_folds`, Test 1 | OK |
| N_candidates ∈ {3,4,5,6,7,8,9,10} | Default from config | OK |
| k_lookback ∈ {1,2,3,6,9,12} | Default from config | OK |
| 48 combinations | 8×6=48 (tested with 4-combo subset) | OK |
| White's Reality Check | `whites_reality_check` | OK |
| Stationary bootstrap (Politis & Romano 1994) | `stationary_bootstrap_indices` | OK |
| 1000 bootstrap replications | Default `WRC_BOOTSTRAP_REPS=1000` | OK |
| p > 0.10 → default to equal weight | Lines 444-451 | OK |
| Report full 48-combination table | `run_grid_search` returns DataFrame | OK |
| Returns use weights from **prior** date | **Look-ahead bug** | **C1** |

---

## PHASE 4 VALIDATION GATE ASSESSMENT

| Gate (§6) | Test | Result | Notes |
|-----------|------|--------|-------|
| Walk-forward folds: non-overlapping train/test | Tests 1 & 2 | PASS | |
| No future data leaks into training window | Test 1 (train_end < test_start) | PASS | **But C1: returns themselves have look-ahead** |
| Reality Check p-value reported | Test 3 | PASS | |
| Full results table generated | Test 4 (4-combo subset) | PASS | |

**Gate assessment caveat:** The fold structure is correctly non-overlapping (no future *dates* leak), but the return computation within each date has look-ahead contamination (C1). The validation gate test checks date-level separation but not data-level separation.

---

## SUMMARY

| # | Finding | Severity | Blocks Phase 5? |
|---|---------|----------|-----------------|
| C1 | Grid search return computation uses same-date weights+returns (look-ahead) | HIGH | YES — parameter selection is unreliable |
| M2 | Zero returns for no-signal months inflate Sharpe | MEDIUM | No (conservative bias) |
| M3 | Bootstrap block length may be too short for overlapping folds | MEDIUM | No |
| M4 | rc_pvalue duplicated across all rows | MEDIUM | No (cosmetic) |
| M5 | Training period unused (acceptable for non-parametric strategy) | MEDIUM | No |
| L1 | Test synthetic data too clean for realistic RC test | LOW | No |
| L2 | No test for full 48-combo grid | LOW | No |
| L3 | Grid search results saved without data hash | LOW | No |

**C1 must be resolved before Phase 5.** The grid search's lightweight return computation applies weights from date `t` to returns that occurred from `t-1` to `t`. Weights should use date `t-1` market cap data so that returns at date `t` are genuinely out-of-sample. Without this fix, the selected parameters are contaminated by look-ahead and may not perform as expected in the actual backtest.
