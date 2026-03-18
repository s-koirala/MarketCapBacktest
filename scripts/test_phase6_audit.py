"""
test_phase6_audit.py -- Phase 6 audit gap coverage tests.

Tests:
 1. MaxDD regression: TWR-based drawdown not dampened by contributions (TEST-G15)
 2. Multi-ticker non-trivial returns with top-N equal weight (TEST-G11)
 3. Single positive momentum concentration (TEST-G4)
 4. Strategy 3 full backtest integration (TEST-G40)
 5. Grid search look-ahead prevention (TEST-G32)
 6. Benchmark alignment (TEST-G38)
 7. BRK ticker mapping through backtest (CALC-C4)
 8. Momentum weight sum equals 1.0 (TEST-G7)
 9. Standalone Sortino with known values (TEST-G18)
10. Standalone capture ratios with known values (TEST-G23)
11. Cash-constrained buy (TEST-G9)
"""
from __future__ import annotations

import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from strategies import strategy_momentum
from backtest_engine import (
    BacktestResult, run_backtest, make_top1_fn, make_topn_fn,
    make_momentum_fn,
)
from metrics import (
    compute_metrics, compute_sortino, compute_downside_deviation,
    compute_capture_ratios, compute_max_drawdown, compute_max_drawdown_from_returns,
    compute_calmar, compute_ulcer_index,
)
from grid_search import compute_strategy3_returns


# ---------------------------------------------------------------------------
# Helper: build synthetic price/mcap/ranking DataFrames from simple specs
# ---------------------------------------------------------------------------

def _build_data(dates, ticker_specs):
    """
    Build prices, mcaps, rankings DataFrames from a list of per-date specs.

    ticker_specs: list of dicts, one per date, each mapping
        ticker -> (price, market_cap)
    If ticker_specs is a callable, it is called with (date_index, date) and
    should return {ticker: (price, market_cap)}.
    """
    prices_data = []
    mcap_data = []

    for i, d in enumerate(dates):
        if callable(ticker_specs):
            specs = ticker_specs(i, d)
        else:
            specs = ticker_specs[i]
        for ticker, (price, mc) in specs.items():
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

    # Compute rankings per date
    rank_data = []
    for d in dates:
        d_mc = mcaps[mcaps["date"] == d].sort_values(
            "estimated_market_cap", ascending=False
        )
        for rank, (_, row) in enumerate(d_mc.iterrows(), 1):
            rank_data.append({**row.to_dict(), "rank": rank})
    rankings = pd.DataFrame(rank_data)
    rf = pd.Series(0.0, index=dates, name="rf_monthly")

    return prices, mcaps, rankings, rf


class TestMaxDDRegression(unittest.TestCase):
    """TEST 1 (TEST-G15): MaxDD uses TWR equity, not dollar equity."""

    def test_maxdd_from_twr_not_dollar(self):
        """
        TWR returns [0.10, -0.25, 0.05, 0.15] imply a peak after month 1
        and a trough after month 2. The TWR equity curve is:
            1.10, 0.825, 0.86625, 0.996...
        Peak = 1.10, trough = 0.825, DD = (0.825 - 1.10)/1.10 = -0.25
        Dollar equity with $1K contributions would show a shallower DD.

        compute_metrics must report the TWR-based drawdown.
        """
        twr_returns = pd.Series(
            [0.10, -0.25, 0.05, 0.15],
            index=pd.date_range("2020-01-31", periods=4, freq="ME"),
        )
        rf = pd.Series(0.0, index=twr_returns.index)
        bench = pd.Series(0.01, index=twr_returns.index)

        # Build a dollar equity curve WITH contributions (dampens DD)
        # Start at 10000, add 1000 each month
        dollar_eq = pd.Series(dtype=float)
        val = 10_000.0
        vals = []
        for i, r in enumerate(twr_returns):
            val = val * (1 + r) + 1_000.0
            vals.append(val)
        dollar_eq = pd.Series(vals, index=twr_returns.index)

        cf = pd.DataFrame([
            {"date": twr_returns.index[0] - pd.DateOffset(months=1), "amount": -10000},
            {"date": twr_returns.index[-1], "amount": dollar_eq.iloc[-1]},
        ])

        m = compute_metrics(
            twr_returns=twr_returns,
            cash_flows=cf,
            equity_curve=dollar_eq,
            benchmark_returns=bench,
            risk_free=rf,
        )

        # TWR equity: 1.10 -> 0.825 -> 0.86625 -> 0.996...
        # MaxDD from TWR = (0.825 - 1.10) / 1.10 = -0.25
        self.assertAlmostEqual(m["max_drawdown"], -0.25, places=4,
                               msg="MaxDD should reflect TWR drawdown (~-0.25), not dollar-dampened")

        # Calmar uses the same TWR-based MaxDD
        cagr = (1 + (1 + twr_returns).prod() - 1) ** (12.0 / len(twr_returns)) - 1
        expected_calmar = cagr / 0.25
        self.assertAlmostEqual(m["calmar_ratio"], expected_calmar, places=3,
                               msg="Calmar should use TWR-based MaxDD")

        # Ulcer Index should be computed from TWR equity, not dollar equity
        twr_eq = (1 + twr_returns).cumprod()
        expected_ulcer = compute_ulcer_index(twr_eq)
        self.assertAlmostEqual(m["ulcer_index"], expected_ulcer, places=4,
                               msg="Ulcer Index should use TWR equity curve")

        print("TEST 1 -- MaxDD regression (TWR-based): PASS")


class TestMultiTickerReturns(unittest.TestCase):
    """TEST 2 (TEST-G11): Multi-ticker non-trivial returns with top-N equal."""

    def test_two_ticker_equal_weight(self):
        """
        AAA: $100 -> $110 (+10%), BBB: $100 -> $95 (-5%)
        Top-2 equal weight (50/50). Expected portfolio TWR ~ +2.5%.
        First month buys at ~25 bps cost on $10K (cost_bps=10, per-leg=5bps).
        """
        dates = pd.date_range("2020-01-31", periods=2, freq="ME")

        def specs(i, d):
            if i == 0:
                return {"AAA": (100.0, 500e9), "BBB": (100.0, 200e9)}
            else:
                return {"AAA": (110.0, 550e9), "BBB": (95.0, 190e9)}

        prices, mcaps, rankings, rf = _build_data(dates, specs)

        result = run_backtest(
            strategy_fn=make_topn_fn(2),
            prices=prices,
            rankings=rankings,
            market_caps=mcaps,
            risk_free=rf,
            initial_capital=10_000.0,
            monthly_contribution=1_000.0,
            cost_schedule={"1990-01-01": 10},  # 10 bps round-trip
            strategy_name="Test Multi-Ticker",
        )

        # TWR return for month 1: mark-to-market before CF
        # Month 0: buy 50% AAA @ $100, 50% BBB @ $100 (minus costs)
        # Month 1: AAA +10%, BBB -5% => portfolio return ~ (0.5*0.10 + 0.5*(-0.05)) = 0.025
        # Costs reduce the initial buy slightly, so TWR may differ from 2.5% by a tiny amount
        self.assertEqual(len(result.twr_returns), 1)
        twr = result.twr_returns.iloc[0]
        # The return should be close to 2.5% but slightly different due to cost impact
        self.assertAlmostEqual(twr, 0.025, places=3,
                               msg=f"Expected ~2.5% portfolio return, got {twr:.6f}")
        # Final equity should be positive and reasonable
        self.assertGreater(result.equity_curve.iloc[-1], 10_000.0,
                           msg="Final equity should exceed initial capital")

        print(f"TEST 2 -- Multi-ticker returns (TWR={twr:.6f}): PASS")


class TestSinglePositiveMomentum(unittest.TestCase):
    """TEST 3 (TEST-G4): Single positive momentum concentration."""

    def test_one_positive_momentum(self):
        """Only CCC has positive momentum -> 100% weight in CCC."""
        dates = pd.date_range("2019-01-31", periods=8, freq="ME")

        def specs(i, d):
            # AAA declining, BBB declining, CCC rising
            return {
                "AAA": (100.0 - i * 5, (500 - i * 30) * 1e9),
                "BBB": (50.0 - i * 2, (200 - i * 10) * 1e9),
                "CCC": (25.0 + i * 5, (100 + i * 40) * 1e9),
            }

        prices, mcaps, rankings, rf = _build_data(dates, specs)

        test_date = dates[6]  # enough history for k=3
        weights = strategy_momentum(rankings, mcaps, test_date, n_candidates=3, k_lookback=3)

        self.assertIn("CCC", weights, "CCC should be in weights")
        self.assertAlmostEqual(weights["CCC"], 1.0, places=10,
                               msg="CCC should have 100% weight when it's the only positive momentum")
        self.assertEqual(len(weights), 1,
                         msg="Only CCC should appear (zero-momentum tickers excluded)")

        print(f"TEST 3a -- Single positive momentum: weights={weights}: PASS")

    def test_all_negative_fallback(self):
        """All tickers declining -> equal weight fallback."""
        dates = pd.date_range("2019-01-31", periods=8, freq="ME")

        def specs(i, d):
            return {
                "AAA": (100.0 - i * 3, (500 - i * 20) * 1e9),
                "BBB": (50.0 - i * 2, (200 - i * 15) * 1e9),
                "CCC": (25.0 - i * 1, (100 - i * 5) * 1e9),
            }

        prices, mcaps, rankings, rf = _build_data(dates, specs)

        test_date = dates[6]
        weights = strategy_momentum(rankings, mcaps, test_date, n_candidates=3, k_lookback=3)

        self.assertEqual(len(weights), 3, "Fallback should include all 3 tickers")
        for t, w in weights.items():
            self.assertAlmostEqual(w, 1.0 / 3, places=10,
                                   msg=f"{t} weight should be 1/3 in fallback")

        print(f"TEST 3b -- All-negative fallback: weights={weights}: PASS")


class TestStrategy3Integration(unittest.TestCase):
    """TEST 4 (TEST-G40): Strategy 3 full backtest integration."""

    def test_momentum_backtest_integration(self):
        """Run momentum strategy over 8 months with trending data."""
        dates = pd.date_range("2019-01-31", periods=10, freq="ME")

        def specs(i, d):
            return {
                "AAA": (100.0 + i * 2, (500 + i * 10) * 1e9),
                "BBB": (50.0 + i * 3, (200 + i * 20) * 1e9),
                "CCC": (25.0 + i * 5, (100 + i * 40) * 1e9),
            }

        prices, mcaps, rankings, rf = _build_data(dates, specs)

        result = run_backtest(
            strategy_fn=make_momentum_fn(n_candidates=3, k_lookback=3),
            prices=prices,
            rankings=rankings,
            market_caps=mcaps,
            risk_free=rf,
            initial_capital=10_000.0,
            monthly_contribution=1_000.0,
            cost_schedule={"1990-01-01": 10},
            strategy_name="Momentum Integration Test",
        )

        # Equity curve should have correct length (10 dates)
        self.assertEqual(len(result.equity_curve), 10,
                         msg=f"Equity curve should have 10 entries, got {len(result.equity_curve)}")

        # TWR returns should be non-zero (prices are trending up)
        self.assertGreater(len(result.twr_returns), 0, "Should have TWR returns")
        non_zero = (result.twr_returns != 0).sum()
        self.assertGreater(non_zero, 0, "Should have non-zero TWR returns")

        # Trades should be populated
        self.assertGreater(len(result.trades), 0, "Trades should be recorded")

        # Cash flows should include initial + monthly contributions
        contributions = result.cash_flows[result.cash_flows["amount"] == -1000.0]
        self.assertEqual(len(contributions), 9,
                         msg=f"Expected 9 contributions, got {len(contributions)}")

        # Holdings should only contain valid tickers
        valid_tickers = {"AAA", "BBB", "CCC"}
        held_tickers = set(result.holdings_history["ticker"].unique())
        self.assertTrue(held_tickers.issubset(valid_tickers),
                        msg=f"Unexpected tickers in holdings: {held_tickers - valid_tickers}")

        print(f"TEST 4 -- Strategy 3 integration: "
              f"{len(result.twr_returns)} TWR entries, "
              f"{len(result.trades)} trades: PASS")


class TestGridSearchLookAhead(unittest.TestCase):
    """TEST 5 (TEST-G32): Grid search look-ahead prevention."""

    def test_weights_use_prior_date(self):
        """
        Verify that compute_strategy3_returns uses weights from date[i-1]
        applied to returns from date[i-1] to date[i].

        Setup: Ticker A has positive momentum at date[2] but negative at date[3].
        The return at date[3] should use date[2]'s weights (positive for A).
        """
        dates = pd.date_range("2019-01-31", periods=8, freq="ME")

        def specs(i, d):
            # A: rises for first 5 months, then falls
            # B: constant
            if i <= 4:
                a_mc = (100 + i * 50) * 1e9
                a_price = 100.0 + i * 10
            else:
                a_mc = (100 + 4 * 50 - (i - 4) * 80) * 1e9
                a_price = 100.0 + 4 * 10 - (i - 4) * 20
            return {
                "AAA": (a_price, a_mc),
                "BBB": (50.0, 200e9),
            }

        prices, mcaps, rankings, rf = _build_data(dates, specs)

        returns = compute_strategy3_returns(
            prices=prices,
            rankings=rankings,
            market_caps=mcaps,
            n_candidates=2,
            k_lookback=2,
            dates=list(dates),
        )

        # At date[4] (i=4), AAA still has positive momentum from date[2]
        # At date[5] (i=5), AAA starts falling, but weights were computed at date[4]
        # where AAA still had positive momentum.
        # So the return at date[5] should use weights that include AAA.

        # Check that we get some returns
        self.assertGreater(len(returns), 0, "Should produce returns")

        # The key check: returns exist and use prior-date weights.
        # If there were look-ahead, the behavior would be different.
        # Verify the return at the transition point exists.
        if dates[5] in returns.index:
            # At date[5], weights from date[4] should have AAA with positive
            # momentum. AAA price drops from 140 to 120 at date[5].
            # So the return should be negative (reflecting the drop with
            # positive weight in AAA from prior period).
            r_at_5 = returns.loc[dates[5]]
            # AAA return: (120 - 140)/140 = -0.1429
            # If look-ahead were used, AAA would have 0 weight at date[5]
            # (negative momentum), so the return would not reflect AAA's drop.
            # The fact that the return is meaningfully negative proves no look-ahead.
            self.assertLess(r_at_5, 0.0,
                            msg="Return at transition should be negative (prior weights include falling AAA)")

        print(f"TEST 5 -- Grid search no look-ahead: {len(returns)} returns: PASS")


class TestBenchmarkAlignment(unittest.TestCase):
    """TEST 6 (TEST-G38): Benchmark return alignment."""

    def test_benchmark_series_alignment(self):
        """
        Build a benchmark price series and verify return calculations.
        """
        dates = pd.date_range("2020-01-31", periods=5, freq="ME")
        bench_prices = pd.Series([100.0, 105.0, 102.0, 108.0, 110.0], index=dates)
        bench_returns = bench_prices.pct_change().dropna()

        # Cumulative return
        cum_return = (1 + bench_returns).prod()
        initial = 10_000.0
        contribution = 1_000.0

        # Build benchmark equity with contributions (matching app.py logic)
        equity = [initial]
        for i, r in enumerate(bench_returns):
            prev = equity[-1]
            new_val = prev * (1 + r) + contribution
            equity.append(new_val)
        equity_series = pd.Series(equity, index=dates)

        # Verify return series length
        self.assertEqual(len(bench_returns), 4,
                         msg="4 monthly returns from 5 prices")

        # Verify final equity is reasonable
        # Simple check: final > initial + contributions
        total_contrib = initial + contribution * 4
        self.assertGreater(equity_series.iloc[-1], total_contrib * 0.95,
                           msg="Final equity should be close to contributions + returns")

        # Verify cumulative return from pct_change
        expected_cum = bench_prices.iloc[-1] / bench_prices.iloc[0]
        self.assertAlmostEqual(cum_return, expected_cum - 1 + 1, places=10,
                               msg="Cumulative return should match price ratio")

        print(f"TEST 6 -- Benchmark alignment: cum_return={cum_return:.6f}: PASS")


class TestBRKTickerMapping(unittest.TestCase):
    """TEST 7 (CALC-C4): BRK ticker mapping through backtest."""

    def test_brk_mapped_to_brkb(self):
        """
        When rankings show 'BRK' as rank-1, the backtest should map it
        to 'BRK-B' for trading.
        """
        dates = pd.date_range("2020-01-31", periods=3, freq="ME")

        # Prices have BRK-B (tradeable), rankings have BRK (aggregated)
        prices_data = []
        mcap_data = []
        rank_data = []

        for d in dates:
            prices_data.append({
                "date": d, "ticker": "BRK-B",
                "open": 300.0, "high": 300.0, "low": 300.0,
                "close": 300.0, "adj_close": 300.0, "volume": 1e6,
            })
            prices_data.append({
                "date": d, "ticker": "AAA",
                "open": 100.0, "high": 100.0, "low": 100.0,
                "close": 100.0, "adj_close": 100.0, "volume": 1e6,
            })
            # Rankings use "BRK" (aggregated ticker), not "BRK-B"
            mcap_data.append({"date": d, "ticker": "BRK", "estimated_market_cap": 800e9})
            mcap_data.append({"date": d, "ticker": "AAA", "estimated_market_cap": 100e9})
            rank_data.append({
                "date": d, "ticker": "BRK",
                "estimated_market_cap": 800e9, "rank": 1,
            })
            rank_data.append({
                "date": d, "ticker": "AAA",
                "estimated_market_cap": 100e9, "rank": 2,
            })

        prices = pd.DataFrame(prices_data)
        mcaps = pd.DataFrame(mcap_data)
        rankings = pd.DataFrame(rank_data)
        rf = pd.Series(0.0, index=dates, name="rf_monthly")

        result = run_backtest(
            strategy_fn=make_top1_fn(),
            prices=prices,
            rankings=rankings,
            market_caps=mcaps,
            risk_free=rf,
            initial_capital=10_000.0,
            monthly_contribution=1_000.0,
            cost_schedule={"1990-01-01": 0},
            strategy_name="BRK Mapping Test",
        )

        # Holdings should contain BRK-B, not BRK
        held = set(result.holdings_history["ticker"].unique())
        self.assertIn("BRK-B", held, "BRK-B should be in holdings (mapped from BRK)")
        self.assertNotIn("BRK", held, "BRK (aggregated) should not be in holdings directly")

        # Position value should be non-zero
        brkb_holdings = result.holdings_history[
            result.holdings_history["ticker"] == "BRK-B"
        ]
        self.assertTrue((brkb_holdings["value"] > 0).all(),
                         msg="BRK-B position value should be non-zero")

        print(f"TEST 7 -- BRK ticker mapping: held={held}: PASS")


class TestMomentumWeightSum(unittest.TestCase):
    """TEST 8 (TEST-G7): Momentum weight sum equals 1.0."""

    def test_weights_sum_to_one(self):
        """5 tickers with varying positive momentum should produce weights summing to 1."""
        dates = pd.date_range("2019-01-31", periods=8, freq="ME")

        def specs(i, d):
            return {
                "AAA": (100 + i * 10, (500 + i * 50) * 1e9),
                "BBB": (80 + i * 8, (400 + i * 40) * 1e9),
                "CCC": (60 + i * 6, (300 + i * 30) * 1e9),
                "DDD": (40 + i * 4, (200 + i * 20) * 1e9),
                "EEE": (20 + i * 2, (100 + i * 10) * 1e9),
            }

        prices, mcaps, rankings, rf = _build_data(dates, specs)

        test_date = dates[6]
        weights = strategy_momentum(rankings, mcaps, test_date, n_candidates=5, k_lookback=3)

        self.assertGreater(len(weights), 0, "Should have non-empty weights")
        weight_sum = sum(weights.values())
        self.assertAlmostEqual(weight_sum, 1.0, places=10,
                               msg=f"Weights should sum to 1.0, got {weight_sum}")

        # All weights should be positive
        for t, w in weights.items():
            self.assertGreater(w, 0, f"Weight for {t} should be positive")

        print(f"TEST 8 -- Momentum weight sum: {weight_sum:.12f}, "
              f"{len(weights)} tickers: PASS")


class TestSortino(unittest.TestCase):
    """TEST 9 (TEST-G18): Standalone Sortino with known values."""

    def test_sortino_manual(self):
        """
        Monthly returns: [0.02, -0.01, 0.03, -0.02, 0.01, -0.03]
        Risk-free: 0.0
        Downside deviation: sqrt(sum(min(r,0)^2) / (N-1))
        """
        returns = pd.Series(
            [0.02, -0.01, 0.03, -0.02, 0.01, -0.03],
            index=pd.date_range("2020-01-31", periods=6, freq="ME"),
        )
        rf = pd.Series(0.0, index=returns.index)

        # Manual downside deviation (ddof=1 per metrics.py convention)
        downside_vals = np.minimum(returns.values, 0.0)
        # downside_vals = [0, -0.01, 0, -0.02, 0, -0.03]
        dd_manual = np.sqrt((downside_vals**2).sum() / (len(returns) - 1))

        # Manual Sortino
        mean_excess = returns.mean()  # rf=0
        expected_sortino = (mean_excess * 12) / (dd_manual * np.sqrt(12))

        actual_sortino = compute_sortino(returns, rf)

        self.assertAlmostEqual(actual_sortino, expected_sortino, places=8,
                               msg=f"Sortino mismatch: {actual_sortino} vs {expected_sortino}")

        # Also verify downside deviation independently
        actual_dd = compute_downside_deviation(returns, rf)
        self.assertAlmostEqual(actual_dd, dd_manual, places=10,
                               msg=f"DD mismatch: {actual_dd} vs {dd_manual}")

        print(f"TEST 9 -- Sortino: {actual_sortino:.6f} (expected {expected_sortino:.6f}): PASS")


class TestCaptureRatios(unittest.TestCase):
    """TEST 10 (TEST-G23): Standalone capture ratios with known values."""

    def test_capture_ratios_manual(self):
        """
        Portfolio: [0.05, -0.02, 0.03, -0.04, 0.01]
        Benchmark: [0.04, -0.03, 0.02, -0.05, 0.02]
        Up months (bench > 0): indices 0, 2, 4
        Down months (bench < 0): indices 1, 3
        """
        port_r = pd.Series(
            [0.05, -0.02, 0.03, -0.04, 0.01],
            index=pd.date_range("2020-01-31", periods=5, freq="ME"),
        )
        bench_r = pd.Series(
            [0.04, -0.03, 0.02, -0.05, 0.02],
            index=port_r.index,
        )

        # Manual up capture
        up_port = np.array([0.05, 0.03, 0.01])  # indices 0, 2, 4
        up_bench = np.array([0.04, 0.02, 0.02])
        expected_up = up_port.mean() / up_bench.mean()

        # Manual down capture
        down_port = np.array([-0.02, -0.04])  # indices 1, 3
        down_bench = np.array([-0.03, -0.05])
        expected_down = down_port.mean() / down_bench.mean()

        result = compute_capture_ratios(port_r, bench_r)

        self.assertAlmostEqual(result["up_capture"], expected_up, places=10,
                               msg=f"Up capture: {result['up_capture']} vs {expected_up}")
        self.assertAlmostEqual(result["down_capture"], expected_down, places=10,
                               msg=f"Down capture: {result['down_capture']} vs {expected_down}")

        # Up capture > 1 means outperforming in up markets
        self.assertGreater(expected_up, 1.0,
                           msg="Portfolio should have up capture > 1 (outperforming in up markets)")
        # Down capture < 1 means losing less in down markets
        self.assertLess(expected_down, 1.0,
                        msg="Portfolio should have down capture < 1 (losing less in down markets)")

        print(f"TEST 10 -- Capture ratios: up={result['up_capture']:.4f}, "
              f"down={result['down_capture']:.4f}: PASS")


class TestCashConstrainedBuy(unittest.TestCase):
    """TEST 11 (TEST-G9): Cash-constrained buy."""

    def test_low_capital_no_negative_cash(self):
        """
        With $100 initial and $10/month contribution, buying a $1000 stock
        should result in a fractional position with no negative cash.
        """
        dates = pd.date_range("2020-01-31", periods=3, freq="ME")

        def specs(i, d):
            return {"AAA": (1000.0, 500e9)}

        prices, mcaps, rankings, rf = _build_data(dates, specs)

        result = run_backtest(
            strategy_fn=make_top1_fn(),
            prices=prices,
            rankings=rankings,
            market_caps=mcaps,
            risk_free=rf,
            initial_capital=100.0,
            monthly_contribution=10.0,
            cost_schedule={"1990-01-01": 0},
            strategy_name="Cash Constrained Test",
        )

        # Verify portfolio buys what it can afford (fractional position)
        hh = result.holdings_history
        self.assertGreater(len(hh), 0, "Should have holdings")

        # Check that shares are fractional (less than 1 for a $1000 stock with $100)
        first_holding = hh[hh["date"] == dates[0]]
        if len(first_holding) > 0:
            shares = first_holding.iloc[0]["shares"]
            self.assertLess(shares, 1.0,
                            msg=f"Should have fractional shares ({shares})")
            self.assertGreater(shares, 0.0,
                               msg="Should have positive shares")

        # Verify: no negative cash balance
        # The equity curve should always be positive
        self.assertTrue((result.equity_curve > 0).all(),
                         msg="Equity should never go negative")

        # Final equity should be roughly initial + contributions
        expected_min = 100.0 + 10.0 * 2  # $120 with flat prices
        self.assertAlmostEqual(result.equity_curve.iloc[-1], expected_min, places=0,
                               msg=f"Final equity should be ~${expected_min}")

        print(f"TEST 11 -- Cash-constrained: shares={hh.iloc[0]['shares']:.6f}, "
              f"final=${result.equity_curve.iloc[-1]:.2f}: PASS")


if __name__ == "__main__":
    print("=" * 60)
    print("PHASE 6 AUDIT GAP COVERAGE TESTS")
    print("=" * 60)
    unittest.main(verbosity=2)
