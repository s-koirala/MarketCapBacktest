"""
backtest_engine.py — Core backtesting loop for MarketCapBacktest.

Implements:
- Monthly rebalancing with configurable strategy function
- $1,000 monthly contributions added BEFORE new allocation (per §2.5)
- Fractional shares (backtesting simplification)
- Time-varying transaction costs integrated into the core loop (per §2.4)
- Delisting forced-liquidation at last traded price
- TWR (modified Dietz) sub-period return tracking for metrics
- Trade logging for turnover analysis
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from config import (
    COST_SCHEDULE_BPS,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_MONTHLY_CONTRIBUTION,
    DELISTED_TICKERS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result Container
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    """Container for backtest output."""
    # Equity curve: month-end portfolio values (index = date)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    # TWR monthly sub-period returns (index = date)
    twr_returns: pd.Series = field(default_factory=pd.Series)
    # Cash flows: [date, amount] for MWR/XIRR calculation
    cash_flows: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Trade log: [date, ticker, side, shares, price, cost_bps, cost_dollar]
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Holdings at each date: [date, ticker, shares, value, weight]
    holdings_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Strategy name for labeling
    strategy_name: str = ""


# ---------------------------------------------------------------------------
# Transaction Cost Lookup
# ---------------------------------------------------------------------------

def _get_cost_bps(date: pd.Timestamp, cost_schedule: dict[str, float]) -> float:
    """
    Look up the applicable round-trip transaction cost (bps) for a given date.

    The schedule is a dict of {period_start_date_str: cost_bps}.
    Returns the cost for the latest period that starts on or before `date`.
    """
    applicable = None
    for start_str, bps in sorted(cost_schedule.items()):
        if pd.Timestamp(start_str) <= date:
            applicable = bps
    return applicable if applicable is not None else 0.0


# ---------------------------------------------------------------------------
# Delisting Detection
# ---------------------------------------------------------------------------

def _check_delistings(
    holdings: dict[str, float],
    date: pd.Timestamp,
    prices_at_date: dict[str, float],
) -> tuple[dict[str, float], float]:
    """
    Check for delisted tickers in current holdings. Force-liquidate at last
    traded price. Return updated holdings and cash proceeds.

    Parameters
    ----------
    holdings : {ticker: shares}
    date : current date
    prices_at_date : {ticker: close_price}

    Returns
    -------
    (updated_holdings, cash_from_liquidation)
    """
    cash = 0.0
    to_remove = []

    for ticker, shares in holdings.items():
        delist_info = DELISTED_TICKERS.get(ticker)
        if delist_info is None:
            continue
        delist_date = pd.Timestamp(delist_info["delist_date"])
        # Force-liquidate if we're at or past the delisting month
        if date >= delist_date:
            price = prices_at_date.get(ticker, 0.0)
            proceeds = shares * price
            cash += proceeds
            to_remove.append(ticker)
            logger.info(
                "Delisting liquidation: %s at %s, %.2f shares @ $%.2f = $%.2f",
                ticker, date.strftime("%Y-%m"), shares, price, proceeds,
            )

    updated = {t: s for t, s in holdings.items() if t not in to_remove}
    return updated, cash


# ---------------------------------------------------------------------------
# Core Backtest
# ---------------------------------------------------------------------------

def run_backtest(
    strategy_fn: Callable,
    prices: pd.DataFrame,
    rankings: pd.DataFrame,
    market_caps: pd.DataFrame,
    risk_free: pd.Series,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    monthly_contribution: float = DEFAULT_MONTHLY_CONTRIBUTION,
    cost_schedule: dict[str, float] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    strategy_name: str = "",
) -> BacktestResult:
    """
    Run a monthly-rebalancing backtest.

    Execution order per month (§2.5):
        1. Mark-to-market existing holdings at current prices
        2. Check for delistings; force-liquidate if needed
        3. Add monthly contribution
        4. Call strategy_fn to get target weights
        5. Execute sells first, then buys (avoids requiring margin)
        6. Deduct transaction costs
        7. Record TWR sub-period return, equity curve, trades

    Parameters
    ----------
    strategy_fn : callable(rankings, market_caps, date) -> {ticker: weight}
        Strategy function. Accepts rankings, market_caps, and date.
        Returns target weights.
    prices : DataFrame [date, ticker, ..., adj_close, close]
        adj_close used for return calculation and position valuation.
    rankings : DataFrame [date, ticker, estimated_market_cap, rank]
    market_caps : DataFrame [date, ticker, estimated_market_cap]
    risk_free : Series indexed by month-end date
    initial_capital : starting cash
    monthly_contribution : added each month before rebalance
    cost_schedule : {period_start: cost_bps} or None for default
    start_date : first rebalance date (YYYY-MM or YYYY-MM-DD)
    end_date : last rebalance date
    strategy_name : label for results

    Returns
    -------
    BacktestResult
    """
    if cost_schedule is None:
        cost_schedule = COST_SCHEDULE_BPS

    # --- Prepare price lookup ---
    # Use adj_close for valuation and return tracking
    price_pivot = prices.pivot_table(
        index="date", columns="ticker", values="adj_close", aggfunc="last"
    )
    # Also need unadjusted close for delisting liquidation values
    close_pivot = prices.pivot_table(
        index="date", columns="ticker", values="close", aggfunc="last"
    )

    # Determine rebalance dates
    all_dates = sorted(price_pivot.index)
    if start_date:
        start_ts = pd.Timestamp(start_date)
        all_dates = [d for d in all_dates if d >= start_ts]
    if end_date:
        end_ts = pd.Timestamp(end_date)
        all_dates = [d for d in all_dates if d <= end_ts]

    if not all_dates:
        raise ValueError("No rebalance dates in the specified range.")

    # --- State ---
    cash = initial_capital
    holdings = {}  # {ticker: shares}
    equity_values = []
    twr_returns = []
    cash_flow_records = [{"date": all_dates[0], "amount": -initial_capital}]
    trade_records = []
    holdings_records = []

    prev_portfolio_value = initial_capital

    # Map aggregated ranking tickers to tradeable tickers.
    # market_cap_estimator aggregates BRK-A + BRK-B into "BRK" for ranking,
    # but only "BRK-B" (the liquid, lower-priced share class) has price data.
    RANKING_TO_TRADE = {"BRK": "BRK-B"}

    for i, date in enumerate(all_dates):
        prices_today = price_pivot.loc[date].dropna().to_dict()
        close_today = close_pivot.loc[date].dropna().to_dict() if date in close_pivot.index else {}

        # 1. Mark-to-market
        portfolio_value_before_cf = cash + sum(
            holdings.get(t, 0) * prices_today.get(t, 0) for t in holdings
        )

        # 2. Check delistings
        holdings_before_delist = set(holdings.keys())
        holdings, delist_cash = _check_delistings(holdings, date, close_today)
        cash += delist_cash
        delisted_this_month = holdings_before_delist - set(holdings.keys())

        # 3. Add contribution (except first month — initial capital already set)
        contribution = monthly_contribution if i > 0 else 0.0
        cash += contribution
        if contribution > 0:
            cash_flow_records.append({"date": date, "amount": -contribution})

        # Portfolio value after contribution, before trades
        portfolio_value_pre_trade = cash + sum(
            holdings.get(t, 0) * prices_today.get(t, 0) for t in holdings
        )

        # 4. Get target weights from strategy
        target_weights = strategy_fn(rankings, market_caps, date)

        target_weights = {RANKING_TO_TRADE.get(t, t): w for t, w in target_weights.items()}

        # Exclude tickers delisted this month — prevents rebuy after liquidation
        if delisted_this_month:
            for t in delisted_this_month:
                target_weights.pop(t, None)
            # Renormalize remaining weights
            total_w = sum(target_weights.values())
            if total_w > 0:
                target_weights = {t: w / total_w for t, w in target_weights.items()}

        if not target_weights:
            # No signal — hold cash
            equity_values.append({"date": date, "value": portfolio_value_pre_trade})
            _record_twr(
                twr_returns, date, portfolio_value_before_cf,
                prev_portfolio_value, i,
            )
            prev_portfolio_value = portfolio_value_pre_trade
            continue

        # 5. Compute trades: sells first, then buys
        target_values = {
            t: w * portfolio_value_pre_trade
            for t, w in target_weights.items()
            if t in prices_today
        }

        # Normalize if some tickers lack price data
        total_target = sum(target_values.values())
        if total_target > 0 and abs(total_target - portfolio_value_pre_trade) > 0.01:
            scale = portfolio_value_pre_trade / total_target
            target_values = {t: v * scale for t, v in target_values.items()}

        cost_bps = _get_cost_bps(date, cost_schedule)
        total_cost = 0.0

        # --- SELLS ---
        for ticker in list(holdings.keys()):
            current_shares = holdings[ticker]
            current_value = current_shares * prices_today.get(ticker, 0)
            target_value = target_values.get(ticker, 0.0)

            if current_value > target_value + 0.01:
                # Sell excess
                sell_value = current_value - target_value
                sell_shares = sell_value / prices_today[ticker] if prices_today.get(ticker, 0) > 0 else 0
                cost = sell_value * cost_bps / 20000  # Half round-trip on sell
                total_cost += cost
                cash += sell_value - cost
                holdings[ticker] = current_shares - sell_shares
                if holdings[ticker] < 1e-10:
                    del holdings[ticker]
                trade_records.append({
                    "date": date, "ticker": ticker, "side": "SELL",
                    "shares": sell_shares, "price": prices_today.get(ticker, 0),
                    "cost_bps": cost_bps / 2, "cost_dollar": cost,
                })
            elif ticker not in target_values:
                # Full exit
                if prices_today.get(ticker, 0) > 0:
                    sell_value = current_value
                    cost = sell_value * cost_bps / 20000
                    total_cost += cost
                    cash += sell_value - cost
                    trade_records.append({
                        "date": date, "ticker": ticker, "side": "SELL",
                        "shares": current_shares,
                        "price": prices_today.get(ticker, 0),
                        "cost_bps": cost_bps / 2, "cost_dollar": cost,
                    })
                del holdings[ticker]

        # --- BUYS ---
        for ticker, target_val in target_values.items():
            current_shares = holdings.get(ticker, 0)
            current_value = current_shares * prices_today.get(ticker, 0)

            if target_val > current_value + 0.01:
                buy_value = target_val - current_value
                if buy_value > cash:
                    logger.debug(
                        "Cash-constrained buy at %s: %s needs $%.2f, "
                        "only $%.2f available. Under-investing $%.2f.",
                        date.strftime("%Y-%m"), ticker, buy_value, cash,
                        buy_value - cash,
                    )
                    buy_value = cash
                cost = buy_value * cost_bps / 20000  # Half round-trip on buy
                total_cost += cost
                price = prices_today[ticker]
                if price > 0:
                    buy_shares = (buy_value - cost) / price
                    holdings[ticker] = current_shares + buy_shares
                    cash -= buy_value
                    trade_records.append({
                        "date": date, "ticker": ticker, "side": "BUY",
                        "shares": buy_shares, "price": price,
                        "cost_bps": cost_bps / 2, "cost_dollar": cost,
                    })

        # 6. Final portfolio value after trades and costs
        portfolio_value = cash + sum(
            holdings.get(t, 0) * prices_today.get(t, 0) for t in holdings
        )

        equity_values.append({"date": date, "value": portfolio_value})

        # 7. Pure TWR sub-period return.
        # Uses portfolio_value_before_cf (mark-to-market BEFORE contribution/
        # delistings/trades) as V_end, and prev_portfolio_value (post-trade
        # value from prior month) as V_start. This excludes cash flows from
        # the return measurement entirely — no Modified Dietz W factor needed.
        _record_twr(
            twr_returns, date, portfolio_value_before_cf,
            prev_portfolio_value, i,
        )
        # Next period's starting value is the post-trade, post-contribution value
        prev_portfolio_value = portfolio_value

        # Record holdings snapshot
        for ticker, shares in holdings.items():
            price = prices_today.get(ticker, 0)
            value = shares * price
            holdings_records.append({
                "date": date, "ticker": ticker, "shares": shares,
                "value": value,
                "weight": value / portfolio_value if portfolio_value > 0 else 0,
            })

    # --- Build result ---
    eq_df = pd.DataFrame(equity_values)
    equity_curve = pd.Series(eq_df["value"].values, index=eq_df["date"], name="portfolio_value")

    twr_series = pd.Series(
        [r["return"] for r in twr_returns],
        index=[r["date"] for r in twr_returns],
        name="twr_return",
    )

    cf_df = pd.DataFrame(cash_flow_records)
    # Add terminal value as positive cash flow for XIRR
    if not equity_values:
        terminal = 0.0
        terminal_date = all_dates[-1]
    else:
        terminal = equity_values[-1]["value"]
        terminal_date = equity_values[-1]["date"]
    cf_df = pd.concat([
        cf_df,
        pd.DataFrame([{"date": terminal_date, "amount": terminal}]),
    ], ignore_index=True)

    return BacktestResult(
        equity_curve=equity_curve,
        twr_returns=twr_series,
        cash_flows=cf_df,
        trades=pd.DataFrame(trade_records) if trade_records else pd.DataFrame(
            columns=["date", "ticker", "side", "shares", "price", "cost_bps", "cost_dollar"]
        ),
        holdings_history=pd.DataFrame(holdings_records) if holdings_records else pd.DataFrame(
            columns=["date", "ticker", "shares", "value", "weight"]
        ),
        strategy_name=strategy_name,
    )


def _record_twr(
    twr_list: list,
    date: pd.Timestamp,
    value_before_cf: float,
    prev_value: float,
    month_index: int,
):
    """
    Compute and record pure TWR sub-period return.

    r_t = (V_before_cf - V_prev) / V_prev

    where V_before_cf is the portfolio value at current prices BEFORE any
    contributions, delistings, or rebalancing (pure mark-to-market of
    positions held from the prior period). V_prev is the post-trade value
    from the prior month (includes prior contribution and rebalance).

    This isolates investment returns from cash flow effects entirely.
    No Modified Dietz W factor is needed.
    """
    if month_index == 0:
        # Skip initialization month — no return to measure.
        # metrics.py no longer needs to filter this out.
        return

    if prev_value <= 0:
        twr_list.append({"date": date, "return": 0.0})
        return

    r = (value_before_cf - prev_value) / prev_value
    twr_list.append({"date": date, "return": r})


# ---------------------------------------------------------------------------
# Strategy Wrapper Factory
# ---------------------------------------------------------------------------
# The backtest engine expects strategy_fn(rankings, market_caps, date).
# These wrappers adapt the individual strategy functions to that signature.

def make_top1_fn():
    """Create a strategy function for Strategy 1 (top-1)."""
    from strategies import strategy_top1
    def fn(rankings, market_caps, date):
        return strategy_top1(rankings, date)
    return fn


def make_topn_fn(n: int):
    """Create a strategy function for Strategy 2 (top-N equal weight)."""
    from strategies import strategy_topn_equal
    def fn(rankings, market_caps, date):
        return strategy_topn_equal(rankings, date, n)
    return fn


def make_momentum_fn(n_candidates: int, k_lookback: int):
    """Create a strategy function for Strategy 3 (log-momentum)."""
    from strategies import strategy_momentum
    def fn(rankings, market_caps, date):
        return strategy_momentum(rankings, market_caps, date, n_candidates, k_lookback)
    return fn


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

    # Run Strategy 1 as a quick test
    logger.info("Running Strategy 1 (Top-1) backtest...")
    result = run_backtest(
        strategy_fn=make_top1_fn(),
        prices=data["prices"],
        rankings=rankings,
        market_caps=mcaps,
        risk_free=data["risk_free"],
        strategy_name="Top-1 Market Cap",
    )

    print(f"\n=== {result.strategy_name} ===")
    print(f"Equity curve: {len(result.equity_curve)} months")
    print(f"Start: ${result.equity_curve.iloc[0]:,.2f}")
    print(f"End:   ${result.equity_curve.iloc[-1]:,.2f}")
    print(f"Trades: {len(result.trades)}")
    total_costs = result.trades["cost_dollar"].sum() if len(result.trades) > 0 else 0
    print(f"Total transaction costs: ${total_costs:,.2f}")
    print(f"TWR returns: {len(result.twr_returns)} months")
    if len(result.twr_returns) > 1:
        cum_twr = (1 + result.twr_returns).prod() - 1
        print(f"Cumulative TWR: {cum_twr:.2%}")
