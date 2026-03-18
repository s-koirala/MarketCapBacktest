"""
test_phase5.py -- Phase 5 validation gate tests.

Tests:
1. app.py parses and all imports resolve
2. Chart data construction doesn't crash on synthetic backtest results
3. Metrics table formatting works
4. Annual returns table works
5. All §4.2 chart types produce valid Plotly figures
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")

import plotly.graph_objects as go
import plotly.express as px

from backtest_engine import BacktestResult, run_backtest, make_top1_fn, make_topn_fn
from metrics import compute_metrics, compute_annual_returns, compute_rolling_returns


def _make_backtest_results():
    """Create synthetic backtest results for dashboard testing."""
    np.random.seed(42)
    n = 60
    dates = pd.date_range("2020-01-31", periods=n, freq="ME")
    tickers = ["AAA", "BBB"]

    prices_data = []
    mcap_data = []
    rank_data = []

    price_a, price_b = 100.0, 50.0
    for d in dates:
        price_a *= (1 + np.random.normal(0.01, 0.04))
        price_b *= (1 + np.random.normal(0.005, 0.03))
        mc_a = price_a * 1e7
        mc_b = price_b * 1e7
        for ticker, price, mc, rank in [("AAA", price_a, mc_a, 1), ("BBB", price_b, mc_b, 2)]:
            prices_data.append({
                "date": d, "ticker": ticker,
                "open": price, "high": price, "low": price,
                "close": price, "adj_close": price, "volume": 1e6,
            })
            mcap_data.append({"date": d, "ticker": ticker, "estimated_market_cap": mc})
            rank_data.append({"date": d, "ticker": ticker, "estimated_market_cap": mc, "rank": rank})

    prices = pd.DataFrame(prices_data)
    mcaps = pd.DataFrame(mcap_data)
    rankings = pd.DataFrame(rank_data)
    rf = pd.Series(0.003, index=dates, name="rf_monthly")
    bench_r = pd.Series(np.random.normal(0.007, 0.035, n), index=dates)

    # Run two strategies
    res1 = run_backtest(
        make_top1_fn(), prices, rankings, mcaps, rf,
        initial_capital=10000, monthly_contribution=1000,
        cost_schedule={"1990-01-01": 10},
        strategy_name="Top-1",
    )
    res2 = run_backtest(
        make_topn_fn(2), prices, rankings, mcaps, rf,
        initial_capital=10000, monthly_contribution=1000,
        cost_schedule={"1990-01-01": 10},
        strategy_name="Top-2 EW",
    )

    return {"Top-1": res1, "Top-2 EW": res2}, rf, bench_r


# =========================================================================
# TEST 1: Module parse and imports
# =========================================================================
def test_module_imports():
    """Verify app.py parses and all dependencies are importable."""
    import ast
    with open("app.py") as f:
        ast.parse(f.read())

    import importlib
    for mod in ["streamlit", "plotly.express", "plotly.graph_objects"]:
        importlib.import_module(mod)

    print("TEST 1 -- Module imports")
    print("  app.py parses, all dependencies importable")
    print("  PASS")
    return True


# =========================================================================
# TEST 2: Equity curve chart construction
# =========================================================================
def test_equity_curves():
    """Build equity curve chart from synthetic data."""
    results, rf, bench_r = _make_backtest_results()

    fig = go.Figure()
    for name, res in results.items():
        eq = res.equity_curve
        fig.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines", name=name))

    # Benchmark
    cum = (1 + bench_r).cumprod() * 10000
    fig.add_trace(go.Scatter(x=cum.index, y=cum.values, mode="lines", name="Bench"))

    print("\nTEST 2 -- Equity curve chart")
    assert len(fig.data) == 3, f"FAIL: expected 3 traces, got {len(fig.data)}"
    print(f"  {len(fig.data)} traces")
    print("  PASS")
    return True


# =========================================================================
# TEST 3: Metrics table
# =========================================================================
def test_metrics_table():
    """Compute full metrics and verify table formatting."""
    results, rf, bench_r = _make_backtest_results()

    all_metrics = {}
    for name, res in results.items():
        m = compute_metrics(
            twr_returns=res.twr_returns,
            cash_flows=res.cash_flows,
            equity_curve=res.equity_curve,
            benchmark_returns=bench_r,
            risk_free=rf,
            holdings_history=res.holdings_history,
        )
        all_metrics[name] = m

    table = pd.DataFrame(all_metrics).T
    print("\nTEST 3 -- Metrics table")
    print(f"  Shape: {table.shape}")
    assert table.shape[0] == 2, "FAIL: should have 2 strategies"
    assert "sharpe_ratio" in table.columns, "FAIL: missing sharpe_ratio"
    assert "max_drawdown" in table.columns, "FAIL: missing max_drawdown"
    assert "mtd" in table.columns, "FAIL: missing mtd"
    print("  PASS")
    return True


# =========================================================================
# TEST 4: Annual returns
# =========================================================================
def test_annual_returns():
    """Verify annual returns table."""
    results, _, _ = _make_backtest_results()

    annual_data = {}
    for name, res in results.items():
        twr = res.twr_returns
        if not twr.empty:
            annual_data[name] = compute_annual_returns(twr)

    annual_df = pd.DataFrame(annual_data)
    print("\nTEST 4 -- Annual returns table")
    print(f"  Shape: {annual_df.shape}")
    assert annual_df.shape[0] >= 1, "FAIL: no annual returns"
    assert annual_df.shape[1] == 2, "FAIL: should have 2 strategies"
    print("  PASS")
    return True


# =========================================================================
# TEST 5: All chart types produce valid figures
# =========================================================================
def test_all_chart_types():
    """Verify drawdown, heatmap, distribution, holdings, correlation charts."""
    results, rf, bench_r = _make_backtest_results()
    res = list(results.values())[0]
    twr = res.twr_returns
    returns = twr

    print("\nTEST 5 -- All chart types")

    # Drawdown
    eq = (1 + returns).cumprod()
    dd = (eq - eq.cummax()) / eq.cummax() * 100
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy"))
    assert len(fig_dd.data) == 1
    print("  Drawdown: OK")

    # Heatmap
    hm_df = pd.DataFrame({"year": returns.index.year, "month": returns.index.month, "return": returns.values * 100})
    hm_pivot = hm_df.pivot_table(index="year", columns="month", values="return")
    fig_hm = px.imshow(hm_pivot, color_continuous_scale="RdYlGn")
    assert fig_hm is not None
    print("  Heatmap: OK")

    # Distribution
    fig_dist = go.Figure()
    fig_dist.add_trace(go.Histogram(x=returns.values * 100, nbinsx=30))
    assert len(fig_dist.data) == 1
    print("  Distribution: OK")

    # Holdings timeline
    hh = res.holdings_history
    if not hh.empty:
        hh_pivot = hh.pivot_table(index="date", columns="ticker", values="weight", aggfunc="sum").fillna(0)
        fig_ht = go.Figure()
        for col in hh_pivot.columns:
            fig_ht.add_trace(go.Scatter(x=hh_pivot.index, y=hh_pivot[col].values, stackgroup="one"))
        assert len(fig_ht.data) > 0
        print("  Holdings timeline: OK")

    # Rolling correlation
    aligned = pd.DataFrame({"strat": returns, "bench": bench_r}).dropna()
    if len(aligned) >= 12:
        rolling_corr = aligned["strat"].rolling(12).corr(aligned["bench"]).dropna()
        fig_corr = go.Figure()
        fig_corr.add_trace(go.Scatter(x=rolling_corr.index, y=rolling_corr.values))
        assert len(fig_corr.data) == 1
        print("  Rolling correlation: OK")

    # Comparison bar
    fig_comp = px.bar(
        pd.DataFrame([
            {"Strategy": "A", "Metric": "Sharpe", "Value": 0.5},
            {"Strategy": "B", "Metric": "Sharpe", "Value": 0.7},
        ]),
        x="Metric", y="Value", color="Strategy", barmode="group",
    )
    assert fig_comp is not None
    print("  Comparison bar: OK")

    print("  PASS")
    return True


# =========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PHASE 5 VALIDATION GATE TESTS")
    print("=" * 60)

    results = []
    results.append(("Module imports", test_module_imports()))
    results.append(("Equity curves", test_equity_curves()))
    results.append(("Metrics table", test_metrics_table()))
    results.append(("Annual returns", test_annual_returns()))
    results.append(("All chart types", test_all_chart_types()))

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
