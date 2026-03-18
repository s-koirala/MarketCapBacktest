"""
grid_search.py — Walk-forward parameter optimization for Strategy 3.

Implements:
- Sliding-window walk-forward validation (60m train / 36m test / 12m step)
- 48-combination grid (8 N_candidates x 6 k_lookback)
- Out-of-sample Sharpe ratio per fold
- White's Reality Check for multiple-testing correction
- Full results table with mean/std Sharpe across folds

Ref: White (2000) "A Reality Check for Data Snooping"
     Politis & Romano (1994) stationary bootstrap
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd

from config import (
    DEFAULT_RANDOM_SEED,
    STRATEGY3_K_LOOKBACK,
    STRATEGY3_N_CANDIDATES,
    WF_STEP_MONTHS,
    WF_TEST_MONTHS,
    WF_TRAIN_MONTHS,
    WRC_BOOTSTRAP_REPS,
    WRC_SIGNIFICANCE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Walk-Forward Fold Generation
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardFold:
    """A single walk-forward fold with train/test date ranges."""
    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def generate_folds(
    all_dates: pd.DatetimeIndex,
    train_months: int = WF_TRAIN_MONTHS,
    test_months: int = WF_TEST_MONTHS,
    step_months: int = WF_STEP_MONTHS,
) -> list[WalkForwardFold]:
    """
    Generate sliding-window walk-forward folds.

    Ensures: train_end < test_start (no overlap, no look-ahead).
    """
    folds = []
    fold_id = 0
    dates_sorted = sorted(all_dates)

    # Start from the earliest date + train_months
    i = 0
    while True:
        train_start_idx = i
        train_end_idx = i + train_months - 1
        test_start_idx = i + train_months
        test_end_idx = i + train_months + test_months - 1

        if test_end_idx >= len(dates_sorted):
            break

        fold = WalkForwardFold(
            fold_id=fold_id,
            train_start=dates_sorted[train_start_idx],
            train_end=dates_sorted[train_end_idx],
            test_start=dates_sorted[test_start_idx],
            test_end=dates_sorted[test_end_idx],
        )

        # Validate: no look-ahead
        assert fold.train_end < fold.test_start, (
            f"Fold {fold_id}: train_end {fold.train_end} >= test_start {fold.test_start}"
        )

        folds.append(fold)
        fold_id += 1
        i += step_months

    logger.info(
        "Generated %d walk-forward folds: train=%dm, test=%dm, step=%dm",
        len(folds), train_months, test_months, step_months,
    )
    return folds


# ---------------------------------------------------------------------------
# Out-of-Sample Sharpe Computation
# ---------------------------------------------------------------------------

def compute_oos_sharpe(
    monthly_returns: pd.Series,
    risk_free: pd.Series,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
) -> float:
    """
    Compute annualized Sharpe ratio for the test period only.
    """
    test_r = monthly_returns[
        (monthly_returns.index >= test_start) &
        (monthly_returns.index <= test_end)
    ]
    rf_aligned = risk_free.reindex(test_r.index).fillna(0)
    excess = test_r - rf_aligned

    if len(excess) < 2 or excess.std(ddof=1) == 0:
        return 0.0

    return (excess.mean() / excess.std(ddof=1)) * np.sqrt(12)


# ---------------------------------------------------------------------------
# Strategy 3 Return Series (lightweight, no full backtest)
# ---------------------------------------------------------------------------

def compute_strategy3_returns(
    prices: pd.DataFrame,
    rankings: pd.DataFrame,
    market_caps: pd.DataFrame,
    n_candidates: int,
    k_lookback: int,
    dates: list[pd.Timestamp],
) -> pd.Series:
    """
    Compute monthly returns for Strategy 3 with given parameters.

    Uses a lightweight approach — no full backtest engine (no contributions,
    no transaction costs) to keep grid search fast. Transaction costs are
    accounted for in the final backtest, not the parameter search.

    IMPORTANT: Weights are computed at date t-1 (prior month-end) and applied
    to returns from t-1 to t. This avoids look-ahead bias: the strategy
    only uses information available before the return period begins.

    Months where the strategy produces no weights (e.g., insufficient
    lookback history) are excluded (NaN), not recorded as 0.0, to avoid
    inflating Sharpe with zero-volatility observations.

    The full-period return computation is safe because the function only
    accesses causal data (weights from t-1, returns at t) at each timestep.
    """
    from strategies import strategy_momentum

    # Build adj_close lookup
    price_pivot = prices.pivot_table(
        index="date", columns="ticker", values="adj_close", aggfunc="last"
    )
    # Monthly returns per ticker: r(t) = price(t)/price(t-1) - 1
    ticker_returns = price_pivot.pct_change()

    returns = []
    # Start from index 1: weights from dates[i-1], returns at dates[i]
    for i in range(1, len(dates)):
        date = dates[i]
        prev_date = dates[i - 1]

        if date not in ticker_returns.index:
            continue
        if prev_date not in ticker_returns.index:
            continue

        # Weights computed at PRIOR month-end (no look-ahead)
        weights = strategy_momentum(
            rankings, market_caps, prev_date, n_candidates, k_lookback,
        )

        if not weights:
            # No signal — exclude this month (NaN), don't record 0.0
            continue

        # Portfolio return = weighted sum of individual ticker returns
        r_today = ticker_returns.loc[date]
        port_r = sum(
            w * r_today.get(t, 0.0)
            for t, w in weights.items()
            if not np.isnan(r_today.get(t, np.nan))
        )
        returns.append({"date": date, "return": port_r})

    df = pd.DataFrame(returns)
    if df.empty:
        return pd.Series(dtype=float)
    return pd.Series(df["return"].values, index=df["date"], name="return")


# ---------------------------------------------------------------------------
# Benchmark Return Series (equal-weight top-5)
# ---------------------------------------------------------------------------

def compute_benchmark_returns(
    prices: pd.DataFrame,
    rankings: pd.DataFrame,
    dates: list[pd.Timestamp],
) -> pd.Series:
    """
    Compute monthly returns for the benchmark: equal-weight top-5.
    Used as the null hypothesis in White's Reality Check.

    Weights at date t-1, returns from t-1 to t (same as strategy returns).
    """
    from strategies import strategy_topn_equal

    price_pivot = prices.pivot_table(
        index="date", columns="ticker", values="adj_close", aggfunc="last"
    )
    ticker_returns = price_pivot.pct_change()

    returns = []
    for i in range(1, len(dates)):
        date = dates[i]
        prev_date = dates[i - 1]

        if date not in ticker_returns.index:
            continue
        if prev_date not in ticker_returns.index:
            continue

        weights = strategy_topn_equal(rankings, prev_date, 5)
        if not weights:
            continue
        r_today = ticker_returns.loc[date]
        port_r = sum(
            w * r_today.get(t, 0.0)
            for t, w in weights.items()
            if not np.isnan(r_today.get(t, np.nan))
        )
        returns.append({"date": date, "return": port_r})

    df = pd.DataFrame(returns)
    if df.empty:
        return pd.Series(dtype=float)
    return pd.Series(df["return"].values, index=df["date"], name="return")


# ---------------------------------------------------------------------------
# White's Reality Check
# ---------------------------------------------------------------------------

def stationary_bootstrap_indices(
    n: int, block_mean: float, rng: np.random.Generator,
) -> np.ndarray:
    """
    Generate bootstrap indices using the stationary bootstrap
    (Politis & Romano, 1994).

    block_mean: expected block length (geometric distribution parameter).
    """
    indices = np.empty(n, dtype=int)
    prob = 1.0 / block_mean
    i = 0
    pos = rng.integers(0, n)
    while i < n:
        indices[i] = pos % n
        i += 1
        if rng.random() < prob:
            pos = rng.integers(0, n)
        else:
            pos += 1
    return indices


def _run_bootstrap(
    centered: dict[tuple, np.ndarray],
    n_folds: int,
    block_mean: float,
    n_reps: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Run stationary bootstrap and return array of max-mean-excess stats."""
    stats = []
    for _ in range(n_reps):
        idx = stationary_bootstrap_indices(n_folds, block_mean, rng)
        max_boot = max(
            centered_e[idx].mean() for centered_e in centered.values()
        )
        stats.append(max_boot)
    return np.array(stats)


def whites_reality_check(
    strategy_sharpes: dict[tuple, list[float]],
    benchmark_sharpes: list[float],
    n_bootstrap: int = WRC_BOOTSTRAP_REPS,
    seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, float]:
    """
    White's Reality Check for data snooping.

    Tests H0: no strategy is better than the benchmark.

    Parameters
    ----------
    strategy_sharpes : {(n_cand, k_look): [sharpe_per_fold]}
    benchmark_sharpes : [sharpe_per_fold] for benchmark
    n_bootstrap : number of stationary bootstrap replications
    seed : random seed

    Returns
    -------
    dict with:
        best_params: (n_cand, k_look)
        best_mean_sharpe: float
        rc_statistic: float (max mean excess Sharpe across strategies)
        rc_pvalue: float
    """
    rng = np.random.default_rng(seed)
    n_folds = len(benchmark_sharpes)
    bench_arr = np.array(benchmark_sharpes)

    # Compute excess Sharpe per fold for each strategy
    excess_sharpes = {}
    for params, sharpes in strategy_sharpes.items():
        arr = np.array(sharpes[:n_folds])
        excess_sharpes[params] = arr - bench_arr[:len(arr)]

    # Observed test statistic: max over strategies of mean excess Sharpe
    mean_excess = {p: e.mean() for p, e in excess_sharpes.items()}
    best_params = max(mean_excess, key=mean_excess.get)
    observed_stat = mean_excess[best_params]

    # Bootstrap distribution of the test statistic under H0
    # Under H0, center the excess Sharpes at zero
    centered = {p: e - e.mean() for p, e in excess_sharpes.items()}

    # Block length: with 12-month step and 36-month test, adjacent folds
    # share 24 months of overlap, inducing serial correlation. Use
    # max(n^(1/3), overlap_ratio * n) as a conservative lower bound.
    # Politis & White (2004) suggest automatic selection; we use the
    # higher of n^(1/3) and 5 as a pragmatic choice, then verify
    # stability across block_mean in {3, 5, 8}.
    block_mean_primary = max(5.0, n_folds ** (1 / 3))
    block_means_sensitivity = [3.0, block_mean_primary, 8.0]

    # Run with primary block length
    bootstrap_stats = _run_bootstrap(
        centered, n_folds, block_mean_primary, n_bootstrap, rng,
    )
    pvalue = (bootstrap_stats >= observed_stat).mean()

    # Sensitivity check: verify p-value is stable across block lengths
    for bm in block_means_sensitivity:
        if bm == block_mean_primary:
            continue
        bs = _run_bootstrap(centered, n_folds, bm, n_bootstrap // 2, rng)
        p_alt = (bs >= observed_stat).mean()
        logger.info(
            "  RC sensitivity: block_mean=%.1f -> p=%.4f", bm, p_alt,
        )

    logger.info(
        "Reality Check: best=%s, mean_excess_sharpe=%.4f, p=%.4f",
        best_params, observed_stat, pvalue,
    )

    return {
        "best_params": best_params,
        "best_mean_sharpe": mean_excess[best_params] + np.mean(bench_arr),
        "rc_statistic": observed_stat,
        "rc_pvalue": pvalue,
    }


# ---------------------------------------------------------------------------
# Full Grid Search
# ---------------------------------------------------------------------------

def run_grid_search(
    prices: pd.DataFrame,
    rankings: pd.DataFrame,
    market_caps: pd.DataFrame,
    risk_free: pd.Series,
    n_candidates_grid: list[int] | None = None,
    k_lookback_grid: list[int] | None = None,
) -> pd.DataFrame:
    """
    Run walk-forward grid search over Strategy 3 parameters.

    Note on training period: Strategy 3's momentum formula is non-parametric
    (no model parameters are estimated in-sample). The training window serves
    as a temporal buffer ensuring the strategy has sufficient price history
    for the k_lookback calculation, not for parameter fitting. The "training"
    happens implicitly: momentum weights at the start of the test period use
    market cap data from the preceding k months, which falls within the
    training window.

    Returns DataFrame with columns:
        n_candidates, k_lookback, mean_sharpe, std_sharpe,
        n_folds, sharpes_per_fold, rc_pvalue, selected
    """
    if n_candidates_grid is None:
        n_candidates_grid = STRATEGY3_N_CANDIDATES
    if k_lookback_grid is None:
        k_lookback_grid = STRATEGY3_K_LOOKBACK

    # Get available dates from prices
    all_dates = sorted(prices["date"].unique())
    date_index = pd.DatetimeIndex(all_dates)

    # Generate walk-forward folds
    folds = generate_folds(date_index)
    if not folds:
        raise RuntimeError("No walk-forward folds could be generated.")

    logger.info(
        "Grid search: %d parameter combos x %d folds = %d evaluations",
        len(n_candidates_grid) * len(k_lookback_grid),
        len(folds),
        len(n_candidates_grid) * len(k_lookback_grid) * len(folds),
    )

    # Compute benchmark (equal-weight top-5) returns once
    bench_returns = compute_benchmark_returns(prices, rankings, all_dates)
    benchmark_fold_sharpes = []
    for fold in folds:
        s = compute_oos_sharpe(bench_returns, risk_free, fold.test_start, fold.test_end)
        benchmark_fold_sharpes.append(s)

    # Evaluate each parameter combination
    results = []
    all_fold_sharpes = {}  # {(n, k): [sharpe_per_fold]}

    for n_cand, k_look in product(n_candidates_grid, k_lookback_grid):
        logger.info("Evaluating N=%d, k=%d...", n_cand, k_look)

        # Compute full return series for this parameter set
        strat_returns = compute_strategy3_returns(
            prices, rankings, market_caps, n_cand, k_look, all_dates,
        )

        if strat_returns.empty:
            results.append({
                "n_candidates": n_cand, "k_lookback": k_look,
                "mean_sharpe": np.nan, "std_sharpe": np.nan,
                "n_folds": 0, "fold_sharpes": [],
            })
            all_fold_sharpes[(n_cand, k_look)] = []
            continue

        # Compute OOS Sharpe for each fold
        fold_sharpes = []
        for fold in folds:
            s = compute_oos_sharpe(
                strat_returns, risk_free, fold.test_start, fold.test_end,
            )
            fold_sharpes.append(s)

        mean_s = np.mean(fold_sharpes)
        std_s = np.std(fold_sharpes, ddof=1) if len(fold_sharpes) > 1 else 0.0

        results.append({
            "n_candidates": n_cand,
            "k_lookback": k_look,
            "mean_sharpe": mean_s,
            "std_sharpe": std_s,
            "n_folds": len(fold_sharpes),
            "fold_sharpes": fold_sharpes,
        })
        all_fold_sharpes[(n_cand, k_look)] = fold_sharpes

    # --- White's Reality Check ---
    valid_strategies = {
        k: v for k, v in all_fold_sharpes.items() if len(v) == len(folds)
    }

    if valid_strategies:
        rc = whites_reality_check(
            valid_strategies, benchmark_fold_sharpes,
        )
        rc_pvalue = rc["rc_pvalue"]
        best_params = rc["best_params"]
    else:
        rc_pvalue = 1.0
        best_params = None

    # Build results DataFrame
    results_df = pd.DataFrame(results)

    # RC p-value is a joint test ("no strategy beats benchmark"), not per-strategy.
    # Store once as metadata attribute, not duplicated per row.
    results_df.attrs["rc_pvalue"] = rc_pvalue
    results_df.attrs["rc_best_params"] = best_params

    # Selection: best mean Sharpe that passes Reality Check
    if best_params is not None and rc_pvalue <= WRC_SIGNIFICANCE:
        results_df["selected"] = results_df.apply(
            lambda row: (
                row["n_candidates"] == best_params[0] and
                row["k_lookback"] == best_params[1]
            ), axis=1,
        )
    else:
        # No parameter set passes — default to equal weight
        results_df["selected"] = False
        logger.warning(
            "Reality Check p=%.4f > %.2f. No parameter set significantly "
            "beats benchmark. Strategy 3 defaults to equal-weight top-5.",
            rc_pvalue, WRC_SIGNIFICANCE,
        )

    # Drop the raw fold_sharpes list for clean CSV output
    results_df = results_df.drop(columns=["fold_sharpes"])

    # Sort by mean Sharpe descending
    results_df = results_df.sort_values("mean_sharpe", ascending=False).reset_index(drop=True)

    logger.info(
        "Grid search complete. Best: N=%s, k=%s, mean_sharpe=%.4f, RC p=%.4f",
        best_params[0] if best_params else "N/A",
        best_params[1] if best_params else "N/A",
        results_df["mean_sharpe"].iloc[0] if not results_df.empty else 0,
        rc_pvalue,
    )

    return results_df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from data_fetcher import fetch_all
    from market_cap_estimator import estimate_market_caps, rank_by_market_cap

    logger.info("Fetching data...")
    data = fetch_all(use_cache=True)

    logger.info("Estimating market caps...")
    mcaps = estimate_market_caps(
        data["prices"], data["splits"], data["shares_outstanding"], data["delisted"]
    )
    rankings = rank_by_market_cap(mcaps)

    logger.info("Running grid search...")
    results = run_grid_search(
        prices=data["prices"],
        rankings=rankings,
        market_caps=mcaps,
        risk_free=data["risk_free"],
    )

    logger.info("=== Grid Search Results (top 10) ===\n%s", results.head(10).to_string(index=False))

    selected = results[results["selected"]]
    if not selected.empty:
        logger.info("Selected: N=%d, k=%d, mean_sharpe=%.4f",
                    selected.iloc[0]['n_candidates'],
                    selected.iloc[0]['k_lookback'],
                    selected.iloc[0]['mean_sharpe'])
    else:
        logger.info("No parameter set selected (RC p > 0.10). Default to equal-weight top-5.")

    # Save results with data hash for reproducibility
    import hashlib, json
    from config import RESULTS_DIR, DATA_MANIFEST
    results.to_csv(RESULTS_DIR / "grid_search_results.csv", index=False)

    # Record metadata alongside results
    meta = {
        "rc_pvalue": results.attrs.get("rc_pvalue"),
        "rc_best_params": str(results.attrs.get("rc_best_params")),
        "n_folds": int(results["n_folds"].iloc[0]) if len(results) > 0 else 0,
        "grid_size": len(results),
    }
    if DATA_MANIFEST.exists():
        with open(DATA_MANIFEST) as f:
            manifest = json.load(f)
        meta["data_manifest_snapshot"] = {
            k: v.get("sha256", "unknown") for k, v in manifest.items()
        }
    with open(RESULTS_DIR / "grid_search_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Saved grid_search_results.csv and grid_search_meta.json")
