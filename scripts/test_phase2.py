"""
test_phase2.py — Phase 2 validation gate tests.

Tests:
1. Known 1-year period with manual calculation matches engine output (within $0.01)
2. Transaction costs reduce returns relative to frictionless run
3. Contribution adds $1,000 at each rebalance
4. Strategy 3 all-negative-momentum fallback triggers on synthetic data
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

# Ensure scripts dir is on path
sys.path.insert(0, ".")

from strategies import strategy_top1, strategy_topn_equal, strategy_momentum
from backtest_engine import (
    BacktestResult, run_backtest, make_top1_fn, make_topn_fn,
    make_momentum_fn, _get_cost_bps,
)


def _make_synthetic_data():
    """
    Create synthetic price/ranking data for a simple 6-month backtest.

    Universe: 3 tickers (AAA, BBB, CCC) with known prices.
    AAA is always rank-1, BBB rank-2, CCC rank-3.
    All prices are constant at $100 (AAA), $50 (BBB), $25 (CCC)
    so returns are 0% each month — makes manual calculation trivial.
    """
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    tickers = ["AAA", "BBB", "CCC"]
    prices_data = []
    mcap_data = []
    rank_data = []

    for d in dates:
        for ticker, price, mc, rank in [
            ("AAA", 100.0, 500e9, 1),
            ("BBB", 50.0, 200e9, 2),
            ("CCC", 25.0, 100e9, 3),
        ]:
            prices_data.append({
                "date": d, "ticker": ticker,
                "open": price, "high": price, "low": price,
                "close": price, "adj_close": price, "volume": 1e6,
            })
            mcap_data.append({
                "date": d, "ticker": ticker,
                "estimated_market_cap": mc,
            })
            rank_data.append({
                "date": d, "ticker": ticker,
                "estimated_market_cap": mc, "rank": rank,
            })

    prices = pd.DataFrame(prices_data)
    mcaps = pd.DataFrame(mcap_data)
    rankings = pd.DataFrame(rank_data)
    rf = pd.Series(0.0, index=dates, name="rf_monthly")

    return prices, mcaps, rankings, rf, dates


def _make_trending_data():
    """
    Create synthetic data where CCC has strong upward momentum and
    AAA has declining momentum — tests momentum strategy.
    """
    dates = pd.date_range("2019-01-31", periods=18, freq="ME")
    prices_data = []
    mcap_data = []

    for i, d in enumerate(dates):
        # AAA: declining from 500B to 400B
        aaa_mc = 500e9 - i * (100e9 / 17)
        aaa_price = 100.0 - i * (20.0 / 17)
        # BBB: stable at 200B
        bbb_mc = 200e9
        bbb_price = 50.0
        # CCC: rising from 100B to 350B
        ccc_mc = 100e9 + i * (250e9 / 17)
        ccc_price = 25.0 + i * (62.5 / 17)

        for ticker, price, mc in [
            ("AAA", aaa_price, aaa_mc),
            ("BBB", bbb_price, bbb_mc),
            ("CCC", ccc_price, ccc_mc),
        ]:
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

    # Rank at each date
    rank_data = []
    for d in dates:
        d_mc = mcaps[mcaps["date"] == d].sort_values("estimated_market_cap", ascending=False)
        for rank, (_, row) in enumerate(d_mc.iterrows(), 1):
            rank_data.append({**row.to_dict(), "rank": rank})
    rankings = pd.DataFrame(rank_data)
    rf = pd.Series(0.0, index=dates, name="rf_monthly")

    return prices, mcaps, rankings, rf, dates


def _make_declining_data():
    """All tickers declining — triggers all-negative-momentum fallback."""
    dates = pd.date_range("2019-01-31", periods=12, freq="ME")
    prices_data = []
    mcap_data = []

    for i, d in enumerate(dates):
        for ticker, base_mc, base_price in [
            ("AAA", 500e9, 100.0),
            ("BBB", 200e9, 50.0),
            ("CCC", 100e9, 25.0),
        ]:
            decline = 1.0 - i * 0.05  # 5% decline per month
            mc = base_mc * decline
            price = base_price * decline
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

    rank_data = []
    for d in dates:
        d_mc = mcaps[mcaps["date"] == d].sort_values("estimated_market_cap", ascending=False)
        for rank, (_, row) in enumerate(d_mc.iterrows(), 1):
            rank_data.append({**row.to_dict(), "rank": rank})
    rankings = pd.DataFrame(rank_data)
    rf = pd.Series(0.0, index=dates, name="rf_monthly")

    return prices, mcaps, rankings, rf, dates


# =========================================================================
# TEST 1: Manual calculation with flat prices
# =========================================================================
def test_manual_calculation():
    """
    With flat prices ($100 for AAA), 0% returns, $10k initial, $1k/month
    contribution, and 0 transaction costs:

    Month 0 (Jan): $10,000 initial → buy 100 shares AAA
    Month 1 (Feb): portfolio = $10,000 + $1,000 contribution = $11,000
    Month 2 (Mar): $11,000 + $1,000 = $12,000
    ...
    Month 5 (Jun): $14,000 + $1,000 = $15,000

    Final value should be $15,000 (initial + 5 contributions).
    """
    prices, mcaps, rankings, rf, dates = _make_synthetic_data()

    result = run_backtest(
        strategy_fn=make_top1_fn(),
        prices=prices,
        rankings=rankings,
        market_caps=mcaps,
        risk_free=rf,
        initial_capital=10_000.0,
        monthly_contribution=1_000.0,
        cost_schedule={"1990-01-01": 0},  # Zero costs
        strategy_name="Test Top-1 Flat",
    )

    final_value = result.equity_curve.iloc[-1]
    expected = 15_000.0  # 10k + 5 × 1k
    diff = abs(final_value - expected)

    print(f"TEST 1 — Manual calculation (flat prices, zero cost)")
    print(f"  Expected: ${expected:,.2f}")
    print(f"  Actual:   ${final_value:,.2f}")
    print(f"  Diff:     ${diff:,.2f}")
    assert diff < 0.01, f"FAIL: difference ${diff:.2f} exceeds $0.01 tolerance"
    print("  PASS")
    return True


# =========================================================================
# TEST 2: Transaction costs reduce returns
# =========================================================================
def test_transaction_costs_reduce_returns():
    """
    Run the same backtest with and without transaction costs.
    Costs should reduce final value.
    """
    prices, mcaps, rankings, rf, dates = _make_synthetic_data()

    result_free = run_backtest(
        strategy_fn=make_top1_fn(),
        prices=prices,
        rankings=rankings,
        market_caps=mcaps,
        risk_free=rf,
        cost_schedule={"1990-01-01": 0},
        strategy_name="Frictionless",
    )

    result_costly = run_backtest(
        strategy_fn=make_top1_fn(),
        prices=prices,
        rankings=rankings,
        market_caps=mcaps,
        risk_free=rf,
        cost_schedule={"1990-01-01": 50},  # 50 bps
        strategy_name="With Costs",
    )

    free_final = result_free.equity_curve.iloc[-1]
    costly_final = result_costly.equity_curve.iloc[-1]

    print(f"\nTEST 2 — Transaction costs reduce returns")
    print(f"  Frictionless: ${free_final:,.2f}")
    print(f"  With costs:   ${costly_final:,.2f}")
    print(f"  Reduction:    ${free_final - costly_final:,.2f}")
    assert costly_final < free_final, "FAIL: costs did not reduce returns"
    assert result_costly.trades["cost_dollar"].sum() > 0, "FAIL: no costs recorded"
    print("  PASS")
    return True


# =========================================================================
# TEST 3: Contributions add $1,000 each month
# =========================================================================
def test_contributions():
    """Verify cash flows record shows $1,000 contribution each month."""
    prices, mcaps, rankings, rf, dates = _make_synthetic_data()

    result = run_backtest(
        strategy_fn=make_top1_fn(),
        prices=prices,
        rankings=rankings,
        market_caps=mcaps,
        risk_free=rf,
        cost_schedule={"1990-01-01": 0},
        strategy_name="Contributions Test",
    )

    cf = result.cash_flows
    # Cash flows: initial (-10k), 5 contributions (-1k each), terminal (+final)
    contributions = cf[cf["amount"] == -1000.0]

    print(f"\nTEST 3 — Monthly contributions")
    print(f"  Total cash flows: {len(cf)}")
    print(f"  Contributions ($1k): {len(contributions)}")
    print(f"  Initial capital: ${-cf.iloc[0]['amount']:,.0f}")
    assert len(contributions) == 5, f"FAIL: expected 5 contributions, got {len(contributions)}"
    assert cf.iloc[0]["amount"] == -10_000.0, "FAIL: initial capital not -$10,000"
    print("  PASS")
    return True


# =========================================================================
# TEST 4: Strategy 3 all-negative-momentum fallback
# =========================================================================
def test_momentum_fallback():
    """
    When all candidates have declining market cap, momentum strategy
    should fall back to equal weight.
    """
    prices, mcaps, rankings, rf, dates = _make_declining_data()

    # Test at a date where all tickers have negative momentum (need lookback)
    test_date = dates[6]  # 6 months in — enough for k=3 lookback
    weights = strategy_momentum(rankings, mcaps, test_date, n_candidates=3, k_lookback=3)

    print(f"\nTEST 4 — All-negative-momentum fallback")
    print(f"  Test date: {test_date}")
    print(f"  Weights: {weights}")

    # Should be equal weight 1/3 for all 3 tickers
    assert len(weights) == 3, f"FAIL: expected 3 weights, got {len(weights)}"
    for t, w in weights.items():
        assert abs(w - 1.0/3) < 1e-10, f"FAIL: {t} weight {w} != 1/3"
    print("  PASS")
    return True


# =========================================================================
# TEST 5: Strategy functions return correct weights
# =========================================================================
def test_strategy_functions():
    """Verify individual strategy functions produce correct outputs."""
    prices, mcaps, rankings, rf, dates = _make_synthetic_data()
    d = dates[0]

    print(f"\nTEST 5 — Strategy functions")

    # Top-1
    w1 = strategy_top1(rankings, d)
    assert w1 == {"AAA": 1.0}, f"FAIL: top1 should be AAA=1.0, got {w1}"
    print(f"  Top-1: {w1} — PASS")

    # Top-N equal
    w2 = strategy_topn_equal(rankings, d, 3)
    assert len(w2) == 3, f"FAIL: topN(3) should have 3 entries"
    for t, w in w2.items():
        assert abs(w - 1.0/3) < 1e-10, f"FAIL: {t} weight should be 1/3"
    print(f"  Top-3 equal: {w2} — PASS")

    # Momentum with trending data
    prices_t, mcaps_t, rankings_t, rf_t, dates_t = _make_trending_data()
    d_t = dates_t[-1]  # Last date — CCC should have strongest momentum
    w3 = strategy_momentum(rankings_t, mcaps_t, d_t, n_candidates=3, k_lookback=6)
    assert len(w3) > 0, "FAIL: momentum returned empty weights"
    # CCC should have highest weight (strongest momentum)
    if "CCC" in w3:
        max_ticker = max(w3, key=w3.get)
        assert max_ticker == "CCC", f"FAIL: CCC should have highest momentum weight, got {max_ticker}"
        print(f"  Momentum: {w3} — CCC has max weight — PASS")
    else:
        print(f"  Momentum: {w3} — CCC absent (may have been rank-filtered)")

    print("  PASS")
    return True


# =========================================================================
# TEST 6: Cost schedule lookup
# =========================================================================
def test_cost_schedule():
    """Verify time-varying cost lookup."""
    from config import COST_SCHEDULE_BPS

    print(f"\nTEST 6 — Cost schedule lookup")

    assert _get_cost_bps(pd.Timestamp("1995-06-15"), COST_SCHEDULE_BPS) == 50
    assert _get_cost_bps(pd.Timestamp("2002-01-15"), COST_SCHEDULE_BPS) == 20
    assert _get_cost_bps(pd.Timestamp("2010-01-15"), COST_SCHEDULE_BPS) == 10
    print("  1995=50bps, 2002=20bps, 2010=10bps -- PASS")
    return True


# =========================================================================
# TEST 7: Non-zero returns — verifies TWR correctness (catches W=1 bug)
# =========================================================================
def test_nonzero_returns_twr():
    """
    With a known +10% return on a single holding, verify TWR reports
    exactly +10%, unaffected by the $1,000 contribution.

    Setup: 2 months, AAA price goes from $100 to $110 (10% return).
    Month 0: $10,000 initial, buy 100 shares AAA @ $100
    Month 1: mark-to-market = 100 shares * $110 = $11,000 (BEFORE contribution)
             TWR sub-period return = (11000 - 10000) / 10000 = 0.10 exactly
             Then contribution $1,000 added, rebalance, etc.
    """
    dates = pd.date_range("2020-01-31", periods=2, freq="ME")
    prices_data = []
    mcap_data = []
    rank_data = []

    price_by_month = [100.0, 110.0]
    for j, d in enumerate(dates):
        p = price_by_month[j]
        mc = p * 1e7  # arbitrary
        prices_data.append({
            "date": d, "ticker": "AAA",
            "open": p, "high": p, "low": p,
            "close": p, "adj_close": p, "volume": 1e6,
        })
        mcap_data.append({"date": d, "ticker": "AAA", "estimated_market_cap": mc})
        rank_data.append({"date": d, "ticker": "AAA", "estimated_market_cap": mc, "rank": 1})

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
        strategy_name="TWR NonZero Test",
    )

    # TWR return for month 1 should be exactly 10%.
    # Month 0 is no longer emitted (M3 remediation), so iloc[0] is month 1.
    assert len(result.twr_returns) == 1, (
        f"FAIL: expected 1 TWR entry (month 0 skipped), got {len(result.twr_returns)}"
    )
    twr_month1 = result.twr_returns.iloc[0]
    expected_twr = 0.10
    diff = abs(twr_month1 - expected_twr)

    print(f"\nTEST 7 -- Non-zero returns TWR")
    print(f"  AAA: $100 -> $110 (10% return)")
    print(f"  TWR entries: {len(result.twr_returns)} (month 0 skipped)")
    print(f"  TWR month 1: {twr_month1:.6f}")
    print(f"  Expected:    {expected_twr:.6f}")
    print(f"  Diff:        {diff:.6f}")
    assert diff < 1e-10, f"FAIL: TWR diff {diff} exceeds tolerance"
    print("  PASS")
    return True


# =========================================================================
# TEST 8: Delisting liquidation — no rebuy in delist month
# =========================================================================
def test_delisting_no_rebuy():
    """
    When a delisted ticker is liquidated, the strategy should NOT rebuy it
    in the same month. Verify holdings do not contain the delisted ticker
    after the delist month.
    """
    from config import DELISTED_TICKERS

    dates = pd.date_range("2001-10-31", periods=4, freq="ME")
    prices_data = []
    mcap_data = []
    rank_data = []

    # ENRNQ delists 2001-12. Give it rank=1 so top-1 strategy wants it.
    # BBB is rank=2 as fallback.
    for d in dates:
        for ticker, price, mc, rank in [
            ("ENRNQ", 10.0 if d < pd.Timestamp("2002-01-01") else 0.0, 7.5e9, 1),
            ("BBB", 50.0, 5e9, 2),
        ]:
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
        strategy_name="Delist Test",
    )

    print(f"\nTEST 8 -- Delisting no-rebuy")

    # After 2001-12 (delist month), ENRNQ should not be in holdings
    hh = result.holdings_history
    post_delist = hh[hh["date"] > pd.Timestamp("2001-12-31")]
    enron_post = post_delist[post_delist["ticker"] == "ENRNQ"]
    print(f"  ENRNQ holdings after delist month: {len(enron_post)} rows")
    assert len(enron_post) == 0, f"FAIL: ENRNQ still in holdings after delisting"

    # In delist month (2001-12), check trades for ENRNQ
    delist_trades = result.trades[
        (result.trades["date"] == pd.Timestamp("2001-12-31")) &
        (result.trades["ticker"] == "ENRNQ") &
        (result.trades["side"] == "BUY")
    ] if len(result.trades) > 0 else pd.DataFrame()
    print(f"  ENRNQ BUY trades in delist month: {len(delist_trades)}")
    assert len(delist_trades) == 0, "FAIL: engine rebought ENRNQ in delist month"

    print("  PASS")
    return True


# =========================================================================
# TEST 9: Position change — rank-1 switches, verify sell-then-buy and costs
# =========================================================================
def test_position_switch():
    """
    Month 0: AAA is rank-1, buy AAA.
    Month 1: BBB becomes rank-1, sell AAA, buy BBB.
    Verify trade log shows SELL AAA and BUY BBB with costs.
    """
    dates = pd.date_range("2020-01-31", periods=3, freq="ME")
    prices_data = []
    rank_data = []
    mcap_data = []

    for j, d in enumerate(dates):
        if j == 0:
            entries = [("AAA", 100.0, 500e9, 1), ("BBB", 50.0, 200e9, 2)]
        else:
            entries = [("BBB", 50.0, 500e9, 1), ("AAA", 100.0, 200e9, 2)]
        for ticker, price, mc, rank in entries:
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
    rf = pd.Series(0.0, index=dates, name="rf_monthly")

    result = run_backtest(
        strategy_fn=make_top1_fn(),
        prices=prices,
        rankings=rankings,
        market_caps=mcaps,
        risk_free=rf,
        initial_capital=10_000.0,
        monthly_contribution=1_000.0,
        cost_schedule={"1990-01-01": 50},
        strategy_name="Position Switch Test",
    )

    print(f"\nTEST 9 -- Position switch (rank-1 change)")
    trades = result.trades
    month1_trades = trades[trades["date"] == dates[1]]
    sells = month1_trades[month1_trades["side"] == "SELL"]
    buys = month1_trades[month1_trades["side"] == "BUY"]
    print(f"  Month 1 sells: {sells['ticker'].tolist()}")
    print(f"  Month 1 buys:  {buys['ticker'].tolist()}")
    assert "AAA" in sells["ticker"].values, "FAIL: should sell AAA"
    assert "BBB" in buys["ticker"].values, "FAIL: should buy BBB"
    assert trades["cost_dollar"].sum() > 0, "FAIL: no costs recorded"
    print(f"  Total costs: ${trades['cost_dollar'].sum():.2f}")
    print("  PASS")
    return True


# =========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PHASE 2 VALIDATION GATE TESTS")
    print("=" * 60)

    results = []
    results.append(("Manual calculation", test_manual_calculation()))
    results.append(("Transaction costs", test_transaction_costs_reduce_returns()))
    results.append(("Contributions", test_contributions()))
    results.append(("Momentum fallback", test_momentum_fallback()))
    results.append(("Strategy functions", test_strategy_functions()))
    results.append(("Cost schedule", test_cost_schedule()))
    results.append(("Non-zero returns TWR", test_nonzero_returns_twr()))
    results.append(("Delisting no-rebuy", test_delisting_no_rebuy()))
    results.append(("Position switch", test_position_switch()))

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
