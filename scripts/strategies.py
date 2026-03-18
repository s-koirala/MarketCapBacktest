"""
strategies.py — Strategy implementations for MarketCapBacktest.

Each strategy function takes ranking/market-cap data and a rebalance date,
and returns a dict of {ticker: weight} representing the target portfolio
allocation at that date.

Strategy 1: Top-1 Market Cap (100% concentration)
Strategy 2: Top-N Equal Weight
Strategy 3: Log-Momentum Weighted (anticipatory)

Ref: Jegadeesh & Titman (1993), Asness, Moskowitz & Pedersen (2013).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def strategy_top1(
    rankings: pd.DataFrame,
    date: pd.Timestamp,
) -> dict[str, float]:
    """
    Strategy 1: Allocate 100% to the rank-1 equity by market cap.

    Parameters
    ----------
    rankings : DataFrame [date, ticker, estimated_market_cap, rank]
    date : rebalance date (month-end)

    Returns
    -------
    {ticker: 1.0} for the rank-1 equity, or empty dict if no data.
    """
    row = rankings[(rankings["date"] == date) & (rankings["rank"] == 1)]
    if row.empty:
        logger.warning("No rank-1 equity found for %s", date)
        return {}
    ticker = row.iloc[0]["ticker"]
    return {ticker: 1.0}


def strategy_topn_equal(
    rankings: pd.DataFrame,
    date: pd.Timestamp,
    n: int,
) -> dict[str, float]:
    """
    Strategy 2: Equal-weight allocation to top-N equities by market cap.

    Parameters
    ----------
    rankings : DataFrame [date, ticker, estimated_market_cap, rank]
    date : rebalance date (month-end)
    n : number of top equities to hold

    Returns
    -------
    {ticker: 1/n} for each of the top-n equities.
    """
    date_data = rankings[(rankings["date"] == date) & (rankings["rank"] <= n)]
    if date_data.empty:
        logger.warning("No equities found for top-%d at %s", n, date)
        return {}

    tickers = date_data.sort_values("rank")["ticker"].tolist()
    actual_n = len(tickers)
    if actual_n < n:
        logger.warning(
            "Only %d equities available for top-%d at %s", actual_n, n, date
        )
    weight = 1.0 / actual_n
    return {t: weight for t in tickers}


def strategy_momentum(
    rankings: pd.DataFrame,
    market_caps: pd.DataFrame,
    date: pd.Timestamp,
    n_candidates: int,
    k_lookback: int,
) -> dict[str, float]:
    """
    Strategy 3: Log-momentum weighted allocation.

    Weights are proportional to max(mu_i, 0) where:
        mu_i(t) = log(M_i(t) / M_i(t - k))

    If all candidates have non-positive momentum, falls back to equal weight.

    Design note: when only one candidate has positive momentum, the strategy
    allocates 100% to that single ticker. This is intentional — the momentum
    signal is treated as the primary allocation driver. A minimum-weight floor
    or blending with equal weight was considered but rejected: it would dilute
    the momentum signal that is the strategy's raison d'etre. The grid search
    (§2) evaluates N_candidates from 3-10; higher N naturally increases the
    probability of multiple positive-momentum candidates and thus implicit
    diversification.

    Parameters
    ----------
    rankings : DataFrame [date, ticker, estimated_market_cap, rank]
    market_caps : DataFrame [date, ticker, estimated_market_cap]
    date : rebalance date (month-end)
    n_candidates : number of top equities to consider
    k_lookback : momentum lookback in months

    Returns
    -------
    {ticker: weight} with weights summing to 1.0.
    """
    # Get top-N candidates at this date
    candidates = rankings[
        (rankings["date"] == date) & (rankings["rank"] <= n_candidates)
    ]
    if candidates.empty:
        logger.warning("No candidates for momentum at %s", date)
        return {}

    tickers = candidates.sort_values("rank")["ticker"].tolist()

    # Compute lookback date
    lookback_date = date - pd.DateOffset(months=k_lookback)

    # Get market caps at current and lookback dates
    current_mc = market_caps[market_caps["date"] == date].set_index("ticker")[
        "estimated_market_cap"
    ]
    # Find closest available date to lookback target
    available_dates = market_caps["date"].unique()
    past_dates = available_dates[available_dates <= lookback_date]
    if len(past_dates) == 0:
        # Not enough history for lookback — fall back to equal weight
        logger.info(
            "Insufficient history for %d-month lookback at %s. "
            "Falling back to equal weight.",
            k_lookback, date,
        )
        w = 1.0 / len(tickers)
        return {t: w for t in tickers}

    actual_lookback_date = past_dates.max()
    past_mc = market_caps[market_caps["date"] == actual_lookback_date].set_index(
        "ticker"
    )["estimated_market_cap"]

    # Compute log-momentum for each candidate
    scores = {}
    for ticker in tickers:
        mc_now = current_mc.get(ticker)
        mc_past = past_mc.get(ticker)
        if mc_now is None or mc_past is None or mc_past <= 0 or mc_now <= 0:
            scores[ticker] = 0.0
            continue
        mu = np.log(mc_now / mc_past)
        scores[ticker] = max(mu, 0.0)

    total_score = sum(scores.values())

    # All-negative-momentum fallback: equal weight
    if total_score <= 0:
        logger.info(
            "All-negative-momentum at %s (n=%d, k=%d). "
            "Falling back to equal weight.",
            date, n_candidates, k_lookback,
        )
        w = 1.0 / len(tickers)
        return {t: w for t in tickers}

    # Normalize to portfolio weights
    return {t: s / total_score for t, s in scores.items() if s > 0}
