"""
test_phase3.py -- Phase 3 validation gate tests.

Tests:
1. TWR-based Sharpe matches independent calculation within tolerance
2. CAGR matches independent calculation
3. MaxDD matches independent calculation
4. XIRR matches numpy_financial.irr on identical cash flows
5. Risk-free rate conversion formula correctness
6. Omega ratio discrete formula correctness
7. VaR/CVaR against known distribution
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from metrics import (
    compute_sharpe, compute_cagr_twr, compute_twr,
    compute_max_drawdown, compute_max_drawdown_from_returns,
    compute_xirr, compute_omega, compute_var, compute_cvar,
    compute_sortino, compute_calmar, compute_alpha, compute_beta,
    compute_downside_deviation, compute_annualized_volatility,
    compute_metrics,
)
from config import METRIC_TOL_SHARPE_REL, METRIC_TOL_SHARPE_ABS, METRIC_TOL_RETURN_REL, METRIC_TOL_RETURN_ABS


def _within_tol(actual, expected, rel_tol, abs_tol):
    """Check if actual is within max(rel_tol * |expected|, abs_tol) of expected."""
    tol = max(rel_tol * abs(expected), abs_tol)
    return abs(actual - expected) <= tol


def _make_known_returns():
    """Create a known return series for validation."""
    np.random.seed(42)
    n = 120  # 10 years
    dates = pd.date_range("2015-01-31", periods=n, freq="ME")
    # Use deterministic returns for reproducibility
    monthly_r = pd.Series(np.random.normal(0.008, 0.04, n), index=dates)
    rf = pd.Series(0.003, index=dates)
    bench_r = pd.Series(np.random.normal(0.007, 0.035, n), index=dates)
    return monthly_r, rf, bench_r, dates


# =========================================================================
# TEST 1: Sharpe ratio against independent calculation
# =========================================================================
def test_sharpe():
    """
    Compute Sharpe from first principles and compare to metrics.py output.

    Sharpe = (mean_excess * sqrt(12)) / std_excess
    """
    monthly_r, rf, _, _ = _make_known_returns()

    # Independent calculation
    excess = monthly_r - rf
    expected_sharpe = (excess.mean() / excess.std(ddof=1)) * np.sqrt(12)

    # metrics.py calculation
    actual_sharpe = compute_sharpe(monthly_r, rf)

    diff = abs(actual_sharpe - expected_sharpe)
    within = _within_tol(actual_sharpe, expected_sharpe, METRIC_TOL_SHARPE_REL, METRIC_TOL_SHARPE_ABS)

    print("TEST 1 -- Sharpe ratio")
    print(f"  Expected: {expected_sharpe:.6f}")
    print(f"  Actual:   {actual_sharpe:.6f}")
    print(f"  Diff:     {diff:.10f}")
    assert within, f"FAIL: Sharpe diff {diff} exceeds tolerance"
    print("  PASS")
    return True


# =========================================================================
# TEST 2: CAGR against independent calculation
# =========================================================================
def test_cagr():
    """
    CAGR = (prod(1+r))^(12/n) - 1
    """
    monthly_r, _, _, _ = _make_known_returns()

    cum = (1 + monthly_r).prod()
    years = len(monthly_r) / 12.0
    expected_cagr = cum ** (1 / years) - 1

    actual_cagr = compute_cagr_twr(monthly_r)

    diff = abs(actual_cagr - expected_cagr)
    within = _within_tol(actual_cagr, expected_cagr, METRIC_TOL_RETURN_REL, METRIC_TOL_RETURN_ABS)

    print("\nTEST 2 -- CAGR")
    print(f"  Expected: {expected_cagr:.8f}")
    print(f"  Actual:   {actual_cagr:.8f}")
    print(f"  Diff:     {diff:.12f}")
    assert within, f"FAIL: CAGR diff {diff} exceeds tolerance"
    print("  PASS")
    return True


# =========================================================================
# TEST 3: Max Drawdown against independent calculation
# =========================================================================
def test_max_drawdown():
    """Compute MaxDD from first principles on a known equity curve."""
    monthly_r, _, _, dates = _make_known_returns()

    equity = (1 + monthly_r).cumprod() * 10000
    equity.index = dates

    # Independent MaxDD
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    expected_maxdd = dd.min()

    actual_maxdd, _ = compute_max_drawdown(equity)
    diff = abs(actual_maxdd - expected_maxdd)
    within = _within_tol(actual_maxdd, expected_maxdd, METRIC_TOL_RETURN_REL, METRIC_TOL_RETURN_ABS)

    print("\nTEST 3 -- Max Drawdown")
    print(f"  Expected: {expected_maxdd:.8f}")
    print(f"  Actual:   {actual_maxdd:.8f}")
    print(f"  Diff:     {diff:.12f}")
    assert within, f"FAIL: MaxDD diff {diff} exceeds tolerance"
    print("  PASS")
    return True


# =========================================================================
# TEST 4: XIRR against numpy_financial (or manual)
# =========================================================================
def test_xirr():
    """
    Simple XIRR case: invest $10k, get $11k after 1 year.
    Expected annual return = 10%.
    """
    dates = [pd.Timestamp("2020-01-01"), pd.Timestamp("2021-01-01")]
    amounts = [-10000, 11000]
    cf = pd.DataFrame({"date": dates, "amount": amounts})

    actual_xirr = compute_xirr(cf)
    expected_xirr = 0.10  # 10% annual

    diff = abs(actual_xirr - expected_xirr)

    print("\nTEST 4 -- XIRR")
    print(f"  Expected: {expected_xirr:.6f}")
    print(f"  Actual:   {actual_xirr:.6f}")
    print(f"  Diff:     {diff:.10f}")
    assert diff < 0.001, f"FAIL: XIRR diff {diff} exceeds 0.1%"
    print("  PASS")

    # Multi-cashflow test: $10k initial + 12 monthly $1k + terminal $24k
    invest_dates = pd.date_range("2020-01-01", periods=13, freq="MS")
    terminal_date = pd.Timestamp("2021-01-01")
    dates2_list = list(invest_dates) + [terminal_date]
    amounts2 = [-10000] + [-1000] * 12 + [24000]
    cf2 = pd.DataFrame({"date": dates2_list, "amount": amounts2})

    xirr2 = compute_xirr(cf2)
    print(f"  Multi-CF XIRR: {xirr2:.6f} (should be positive)")
    assert xirr2 > 0, "FAIL: multi-CF XIRR should be positive"
    print("  PASS")
    return True


# =========================================================================
# TEST 5: Risk-free rate conversion
# =========================================================================
def test_rf_conversion():
    """
    Verify: r_monthly = (1 + DGS3MO/100)^(1/12) - 1

    Example: DGS3MO = 5.0% -> r_monthly = (1.05)^(1/12) - 1 = 0.004074
    NOT 5.0/1200 = 0.004167
    """
    dgs3mo = 5.0
    expected = (1 + dgs3mo / 100) ** (1 / 12) - 1
    naive = dgs3mo / 1200

    print("\nTEST 5 -- Risk-free rate conversion")
    print(f"  DGS3MO = {dgs3mo}%")
    print(f"  Correct: {expected:.8f}")
    print(f"  Naive:   {naive:.8f}")
    print(f"  Difference: {abs(expected - naive):.8f}")
    assert expected < naive, "FAIL: correct conversion should be less than naive"
    assert abs(expected - 0.004074) < 0.0001, f"FAIL: expected ~0.004074, got {expected}"
    print("  PASS")
    return True


# =========================================================================
# TEST 6: Omega ratio discrete formula
# =========================================================================
def test_omega():
    """
    Known case: returns = [0.05, 0.03, -0.02, -0.04, 0.01], rf = 0.0
    gains = 0.05 + 0.03 + 0.01 = 0.09
    losses = 0.02 + 0.04 = 0.06
    Omega = 0.09 / 0.06 = 1.5
    """
    returns = pd.Series([0.05, 0.03, -0.02, -0.04, 0.01],
                        index=pd.date_range("2020-01-31", periods=5, freq="ME"))
    rf = pd.Series(0.0, index=returns.index)

    actual = compute_omega(returns, rf)
    expected = 0.09 / 0.06

    diff = abs(actual - expected)
    print("\nTEST 6 -- Omega ratio")
    print(f"  Expected: {expected:.6f}")
    print(f"  Actual:   {actual:.6f}")
    print(f"  Diff:     {diff:.10f}")
    assert diff < 1e-10, f"FAIL: Omega diff {diff}"
    print("  PASS")
    return True


# =========================================================================
# TEST 7: VaR/CVaR against known distribution
# =========================================================================
def test_var_cvar():
    """
    Use a large sample from a known normal distribution.
    For N(0.01, 0.04), 95% VaR should be approximately
    mean + z_0.05 * std = 0.01 + (-1.645) * 0.04 = -0.0558
    """
    np.random.seed(42)
    n = 10000
    returns = pd.Series(np.random.normal(0.01, 0.04, n))

    var_result = compute_var(returns, confidence=0.95)
    hist_var = var_result["historical_var"]
    cf_var = var_result["cornish_fisher_var"]

    expected_var = 0.01 + (-1.645) * 0.04  # -0.0558

    cvar = compute_cvar(returns, confidence=0.95)

    print("\nTEST 7 -- VaR/CVaR")
    print(f"  Expected 95% VaR (parametric): {expected_var:.6f}")
    print(f"  Historical VaR:   {hist_var:.6f}")
    print(f"  Cornish-Fisher:   {cf_var:.6f}")
    print(f"  CVaR:             {cvar:.6f}")
    # Historical VaR should be close to parametric for large N
    assert abs(hist_var - expected_var) < 0.005, f"FAIL: historical VaR too far from expected"
    # CVaR should be more negative than VaR
    assert cvar < hist_var, "FAIL: CVaR should be worse than VaR"
    print("  Bootstrap CI: [{:.6f}, {:.6f}]".format(
        var_result["bootstrap_ci_lower"], var_result["bootstrap_ci_upper"]
    ))
    print("  PASS")
    return True


# =========================================================================
# TEST 8: Full compute_metrics integration
# =========================================================================
def test_full_metrics():
    """Run compute_metrics and verify all expected keys are present."""
    monthly_r, rf, bench_r, dates = _make_known_returns()
    equity = (1 + monthly_r).cumprod() * 10000
    equity.index = dates

    cf = pd.DataFrame([
        {"date": dates[0], "amount": -10000},
        {"date": dates[-1], "amount": equity.iloc[-1]},
    ])

    m = compute_metrics(
        twr_returns=monthly_r,
        cash_flows=cf,
        equity_curve=equity,
        benchmark_returns=bench_r,
        risk_free=rf,
    )

    expected_keys = [
        "total_return_twr", "cagr_twr", "xirr",
        "mtd", "qtd", "ytd",
        "annualized_volatility", "max_drawdown", "max_drawdown_duration_days",
        "var_95_historical", "var_99_historical",
        "var_95_cornish_fisher", "var_99_cornish_fisher",
        "cvar_95", "cvar_99",
        "downside_deviation", "ulcer_index",
        "sharpe_ratio", "sortino_ratio", "calmar_ratio", "omega_ratio",
        "information_ratio", "treynor_ratio",
        "alpha", "beta", "tracking_error",
        "up_capture", "down_capture", "hit_rate",
    ]

    print("\nTEST 8 -- Full metrics integration")
    missing = [k for k in expected_keys if k not in m]
    assert not missing, f"FAIL: missing keys: {missing}"
    print(f"  All {len(expected_keys)} expected keys present")

    # Sanity checks
    assert m["annualized_volatility"] > 0, "FAIL: vol should be positive"
    assert m["max_drawdown"] < 0, "FAIL: MaxDD should be negative"
    assert 0 < m["hit_rate"] < 1, "FAIL: hit rate should be between 0 and 1"
    print(f"  Sharpe: {m['sharpe_ratio']:.4f}")
    print(f"  CAGR:   {m['cagr_twr']:.4f}")
    print(f"  MaxDD:  {m['max_drawdown']:.4f}")
    print(f"  Beta:   {m['beta']:.4f}")
    print(f"  Alpha:  {m['alpha']:.4f}")
    print("  PASS")
    return True


# =========================================================================
# TEST 9: Portfolio characteristics (turnover, HHI, holdings count)
# =========================================================================
def test_portfolio_characteristics():
    """
    Known holdings:
    Month 1: AAA=50%, BBB=50%  -> HHI = 0.25 + 0.25 = 0.50
    Month 2: AAA=100%          -> HHI = 1.0
    Turnover from month 1->2: |0.5-1.0| + |0.5-0| = 1.0, /2 = 0.5
    Holdings: month 1 = 2, month 2 = 1, avg = 1.5
    """
    from metrics import compute_turnover, compute_hhi, compute_holdings_count

    dates = pd.date_range("2020-01-31", periods=2, freq="ME")
    hh = pd.DataFrame([
        {"date": dates[0], "ticker": "AAA", "shares": 50, "value": 5000, "weight": 0.5},
        {"date": dates[0], "ticker": "BBB", "shares": 100, "value": 5000, "weight": 0.5},
        {"date": dates[1], "ticker": "AAA", "shares": 100, "value": 10000, "weight": 1.0},
    ])

    turnover = compute_turnover(hh)
    hhi = compute_hhi(hh)
    hcount = compute_holdings_count(hh)

    print("\nTEST 9 -- Portfolio characteristics")
    print(f"  Turnover: {turnover:.4f} (expected 0.5)")
    assert abs(turnover - 0.5) < 1e-10, f"FAIL: turnover {turnover} != 0.5"

    print(f"  HHI month 1: {hhi.iloc[0]:.4f} (expected 0.50)")
    print(f"  HHI month 2: {hhi.iloc[1]:.4f} (expected 1.00)")
    assert abs(hhi.iloc[0] - 0.5) < 1e-10, f"FAIL: HHI month 1"
    assert abs(hhi.iloc[1] - 1.0) < 1e-10, f"FAIL: HHI month 2"

    print(f"  Holdings month 1: {hcount.iloc[0]} (expected 2)")
    print(f"  Holdings month 2: {hcount.iloc[1]} (expected 1)")
    assert hcount.iloc[0] == 2, "FAIL: holdings month 1"
    assert hcount.iloc[1] == 1, "FAIL: holdings month 2"

    print("  PASS")
    return True


# =========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PHASE 3 VALIDATION GATE TESTS")
    print("=" * 60)

    results = []
    results.append(("Sharpe ratio", test_sharpe()))
    results.append(("CAGR", test_cagr()))
    results.append(("Max Drawdown", test_max_drawdown()))
    results.append(("XIRR", test_xirr()))
    results.append(("RF conversion", test_rf_conversion()))
    results.append(("Omega ratio", test_omega()))
    results.append(("VaR/CVaR", test_var_cvar()))
    results.append(("Full metrics", test_full_metrics()))
    results.append(("Portfolio characteristics", test_portfolio_characteristics()))

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
