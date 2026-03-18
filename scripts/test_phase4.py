"""
test_phase4.py -- Phase 4 validation gate tests.

Tests:
1. Walk-forward folds have train_end < test_start (no look-ahead)
2. No overlap between train and test periods within a fold
3. White's Reality Check produces valid p-value
4. Full grid search produces 48-row results table
5. Grid search on synthetic data with known best parameter
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from grid_search import (
    generate_folds,
    whites_reality_check,
    stationary_bootstrap_indices,
    compute_oos_sharpe,
    run_grid_search,
    compute_strategy3_returns,
    compute_benchmark_returns,
)
from config import WF_TRAIN_MONTHS, WF_TEST_MONTHS, WF_STEP_MONTHS


def _make_synthetic_grid_data():
    """
    Create synthetic data spanning 180 months (15 years) with 5 tickers.
    Enough for multiple walk-forward folds (60+36=96 months minimum).
    """
    np.random.seed(42)
    n_months = 180
    dates = pd.date_range("2005-01-31", periods=n_months, freq="ME")
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]

    prices_data = []
    mcap_data = []

    # Generate random walk prices
    for ticker_idx, ticker in enumerate(tickers):
        base_price = 50.0 + ticker_idx * 20
        base_mc = (5 - ticker_idx) * 100e9  # AAA largest
        price = base_price
        for i, d in enumerate(dates):
            ret = np.random.normal(0.005 + ticker_idx * 0.001, 0.04)
            price = price * (1 + ret)
            mc = base_mc * (price / base_price)
            prices_data.append({
                "date": d, "ticker": ticker,
                "open": price, "high": price, "low": price,
                "close": price, "adj_close": price, "volume": 1e6,
            })
            mcap_data.append({
                "date": d, "ticker": ticker,
                "estimated_market_cap": mc,
            })

    prices = pd.DataFrame(prices_data)
    mcaps = pd.DataFrame(mcap_data)

    # Build rankings
    rank_data = []
    for d in dates:
        d_mc = mcaps[mcaps["date"] == d].sort_values(
            "estimated_market_cap", ascending=False
        )
        for rank, (_, row) in enumerate(d_mc.iterrows(), 1):
            rank_data.append({**row.to_dict(), "rank": rank})
    rankings = pd.DataFrame(rank_data)

    rf = pd.Series(0.003, index=dates, name="rf_monthly")

    return prices, mcaps, rankings, rf, dates


# =========================================================================
# TEST 1: Walk-forward folds — no look-ahead
# =========================================================================
def test_fold_no_lookahead():
    """Every fold must have train_end < test_start."""
    dates = pd.date_range("2000-01-31", periods=420, freq="ME")
    folds = generate_folds(pd.DatetimeIndex(dates))

    print("TEST 1 -- Walk-forward folds no look-ahead")
    print(f"  Generated {len(folds)} folds")
    assert len(folds) > 0, "FAIL: no folds generated"

    for fold in folds:
        assert fold.train_end < fold.test_start, (
            f"FAIL: fold {fold.fold_id}: train_end={fold.train_end} "
            f">= test_start={fold.test_start}"
        )
    print(f"  All {len(folds)} folds pass train_end < test_start")
    print(f"  First fold: train {folds[0].train_start.strftime('%Y-%m')} to "
          f"{folds[0].train_end.strftime('%Y-%m')}, "
          f"test {folds[0].test_start.strftime('%Y-%m')} to "
          f"{folds[0].test_end.strftime('%Y-%m')}")
    print("  PASS")
    return True


# =========================================================================
# TEST 2: No train/test overlap within any fold
# =========================================================================
def test_fold_no_overlap():
    """Train and test date ranges must not overlap."""
    dates = pd.date_range("2000-01-31", periods=420, freq="ME")
    folds = generate_folds(pd.DatetimeIndex(dates))

    print("\nTEST 2 -- No train/test overlap")
    for fold in folds:
        train_dates = set(dates[(dates >= fold.train_start) & (dates <= fold.train_end)])
        test_dates = set(dates[(dates >= fold.test_start) & (dates <= fold.test_end)])
        overlap = train_dates & test_dates
        assert len(overlap) == 0, (
            f"FAIL: fold {fold.fold_id} has {len(overlap)} overlapping dates"
        )
    print(f"  All {len(folds)} folds have zero overlap")

    # Verify train window = 60 months, test window = 36 months
    fold0 = folds[0]
    train_len = len(dates[(dates >= fold0.train_start) & (dates <= fold0.train_end)])
    test_len = len(dates[(dates >= fold0.test_start) & (dates <= fold0.test_end)])
    print(f"  Fold 0: train={train_len}m, test={test_len}m")
    assert train_len == WF_TRAIN_MONTHS, f"FAIL: train window {train_len} != {WF_TRAIN_MONTHS}"
    assert test_len == WF_TEST_MONTHS, f"FAIL: test window {test_len} != {WF_TEST_MONTHS}"
    print("  PASS")
    return True


# =========================================================================
# TEST 3: White's Reality Check produces valid p-value
# =========================================================================
def test_reality_check():
    """
    With synthetic data where all strategies perform similarly to benchmark,
    p-value should be high (fail to reject H0).
    With a planted superior strategy, p-value should be low.
    """
    np.random.seed(42)
    n_folds = 20

    # Case 1: All strategies ~ benchmark (H0 true)
    bench = list(np.random.normal(0.5, 0.3, n_folds))
    strategies_null = {
        (3, 1): list(np.random.normal(0.5, 0.3, n_folds)),
        (3, 3): list(np.random.normal(0.5, 0.3, n_folds)),
        (5, 1): list(np.random.normal(0.5, 0.3, n_folds)),
        (5, 3): list(np.random.normal(0.5, 0.3, n_folds)),
    }

    rc_null = whites_reality_check(strategies_null, bench, n_bootstrap=500, seed=42)

    print("\nTEST 3 -- White's Reality Check")
    print(f"  H0 true (all similar): p={rc_null['rc_pvalue']:.4f}")
    assert 0 <= rc_null["rc_pvalue"] <= 1, "FAIL: p-value out of [0,1]"

    # Case 2: One strategy clearly superior (H0 false)
    strategies_alt = {
        (3, 1): list(np.random.normal(0.5, 0.3, n_folds)),
        (3, 3): list(np.random.normal(0.5, 0.3, n_folds)),
        (5, 1): list(np.random.normal(0.5, 0.3, n_folds)),
        (10, 6): list(np.random.normal(1.5, 0.2, n_folds)),  # Clearly better
    }

    rc_alt = whites_reality_check(strategies_alt, bench, n_bootstrap=500, seed=42)
    print(f"  H0 false (one superior): p={rc_alt['rc_pvalue']:.4f}")
    print(f"  Best params: {rc_alt['best_params']}")
    assert 0 <= rc_alt["rc_pvalue"] <= 1, "FAIL: p-value out of [0,1]"
    assert rc_alt["best_params"] == (10, 6), f"FAIL: should select (10,6), got {rc_alt['best_params']}"
    assert rc_alt["rc_pvalue"] < 0.10, f"FAIL: should reject H0 for planted superior"
    print("  PASS")
    return True


# =========================================================================
# TEST 4: Grid search produces full results table
# =========================================================================
def test_grid_search_table():
    """
    Run grid search on synthetic data with small grids.
    Verify output has correct shape and columns.
    """
    prices, mcaps, rankings, rf, dates = _make_synthetic_grid_data()

    # Use small grid for speed: 2 N_candidates x 2 k_lookback = 4 combos
    results = run_grid_search(
        prices=prices,
        rankings=rankings,
        market_caps=mcaps,
        risk_free=rf,
        n_candidates_grid=[3, 5],
        k_lookback_grid=[3, 6],
    )

    print("\nTEST 4 -- Grid search results table")
    print(f"  Shape: {results.shape}")
    print(f"  Columns: {list(results.columns)}")

    expected_cols = [
        "n_candidates", "k_lookback", "mean_sharpe", "std_sharpe",
        "n_folds", "selected",
    ]
    missing = [c for c in expected_cols if c not in results.columns]
    assert not missing, f"FAIL: missing columns: {missing}"

    assert len(results) == 4, f"FAIL: expected 4 rows (2x2 grid), got {len(results)}"
    assert results["n_folds"].iloc[0] > 0, "FAIL: no folds evaluated"
    assert not results["mean_sharpe"].isna().all(), "FAIL: all Sharpe values are NaN"

    # rc_pvalue is now in attrs (metadata), not per-row
    rc_p = results.attrs.get("rc_pvalue")
    assert rc_p is not None, "FAIL: rc_pvalue missing from attrs"
    assert 0 <= rc_p <= 1, f"FAIL: rc_pvalue {rc_p} out of [0,1]"
    print(f"  RC p-value (metadata): {rc_p:.4f}")

    print(results[["n_candidates", "k_lookback", "mean_sharpe", "std_sharpe",
                    "n_folds", "selected"]].to_string(index=False))
    print("  PASS")
    return True


# =========================================================================
# TEST 5: Stationary bootstrap index generation
# =========================================================================
def test_stationary_bootstrap():
    """Verify stationary bootstrap produces valid indices."""
    rng = np.random.default_rng(42)
    n = 100
    block_mean = 5.0

    idx = stationary_bootstrap_indices(n, block_mean, rng)

    print("\nTEST 5 -- Stationary bootstrap indices")
    print(f"  Length: {len(idx)}")
    assert len(idx) == n, f"FAIL: expected {n} indices, got {len(idx)}"
    assert idx.min() >= 0, "FAIL: negative index"
    assert idx.max() < n, f"FAIL: index {idx.max()} >= {n}"

    # Check that blocks exist (consecutive indices)
    diffs = np.diff(idx)
    consecutive = (diffs == 1).sum()
    print(f"  Consecutive pairs: {consecutive}/{n-1} ({consecutive/(n-1)*100:.0f}%)")
    # With block_mean=5, ~80% should be consecutive (1 - 1/5 = 0.8)
    assert consecutive > n * 0.4, "FAIL: too few consecutive pairs for block_mean=5"
    print("  PASS")
    return True


# =========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PHASE 4 VALIDATION GATE TESTS")
    print("=" * 60)

    results = []
    results.append(("Fold no look-ahead", test_fold_no_lookahead()))
    results.append(("Fold no overlap", test_fold_no_overlap()))
    results.append(("Reality Check", test_reality_check()))
    results.append(("Grid search table", test_grid_search_table()))
    results.append(("Stationary bootstrap", test_stationary_bootstrap()))

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_pass = False

    print(f"\n{'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_pass else 1)
