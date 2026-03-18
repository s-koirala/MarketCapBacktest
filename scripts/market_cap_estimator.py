"""
market_cap_estimator.py — Market cap estimation and ranking engine.

Uses split-adjusted close from yfinance × actual historical shares outstanding:
    market_cap(t) = close_split_adjusted(t) × shares_outstanding(t)

Historical shares outstanding are sourced from SEC EDGAR + yfinance
get_shares_full() (2009+). For dates without historical shares data, falls
back to current shares outstanding (valid because yfinance close is already
split-adjusted, so close × current_shares gives correct current-basis market cap).

BRK-A and BRK-B are aggregated into a single 'BRK' entry for ranking.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import BRK_A_TICKER, CHECKPOINT_YEARS, DELISTED_TICKERS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core: Split-Adjusted Shares Outstanding
# ---------------------------------------------------------------------------

def compute_cumulative_split_factor(
    splits: pd.DataFrame,
    shares: pd.DataFrame,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Compute cumulative split factor from each date to present for each ticker.

    The cumulative split factor at date t is the product of all split ratios
    from t to the most recent date. For example, if a stock had a 4:1 split
    on 2020-08-31, then for any date before that split:
        cumulative_split_factor = 4.0
    and for dates after:
        cumulative_split_factor = 1.0

    Parameters
    ----------
    splits : DataFrame with [date, ticker, split_ratio]
    shares : DataFrame with [ticker, shares_outstanding]  (current)
    date_range : DatetimeIndex of month-end dates

    Returns
    -------
    DataFrame with [date, ticker, cum_split_factor]
    """
    tickers = shares["ticker"].unique()
    frames = []

    for ticker in tickers:
        tk_splits = splits[splits["ticker"] == ticker].sort_values("date")

        if tk_splits.empty:
            # No splits — factor is 1.0 for all dates
            df = pd.DataFrame({"date": date_range, "ticker": ticker, "cum_split_factor": 1.0})
            frames.append(df)
            continue

        # Vectorized: for each date, cumulative split factor = product of all
        # split ratios occurring AFTER that date.
        #
        # Build a reverse cumulative product: at the latest date, factor = 1.0.
        # Moving backward, each split multiplies the factor.
        #
        # 1) Create a series of split ratios at their dates
        # 2) Compute reverse cumulative product
        # 3) For each month-end, look up the factor (next split boundary)
        split_dates = tk_splits["date"].values
        split_ratios = tk_splits["split_ratio"].values

        # Total product of all splits (factor at the very beginning of time)
        total_product = split_ratios.prod()

        # For each date in date_range, the factor is the product of splits
        # that occur strictly after that date.
        # Equivalent: total_product / product_of_splits_on_or_before(date)
        #
        # Vectorize using searchsorted: find how many splits are on or before each date
        date_arr = date_range.values
        # Number of splits on or before each date
        idx = np.searchsorted(split_dates, date_arr, side="right")

        # Cumulative product of split ratios (prefix product)
        cum_prod = np.ones(len(split_ratios) + 1)
        for i, r in enumerate(split_ratios):
            cum_prod[i + 1] = cum_prod[i] * r

        # Factor at each date = total_product / cum_prod[idx]
        factors = total_product / cum_prod[idx]

        df = pd.DataFrame({
            "date": date_range,
            "ticker": ticker,
            "cum_split_factor": factors,
        })
        frames.append(df)

    return pd.concat(frames, ignore_index=True)


def estimate_market_caps(
    prices: pd.DataFrame,
    splits: pd.DataFrame,
    shares: pd.DataFrame,
    delisted: pd.DataFrame,
    historical_shares: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Estimate historical market capitalization for all tickers.

    For active tickers:
        market_cap(t) = close_split_adjusted(t) × shares_outstanding(t)

    The ``close`` column from yfinance is already split-adjusted, so we
    multiply by actual historical shares outstanding where available (from
    SEC EDGAR / yfinance get_shares_full).  For dates without historical
    shares data, we fall back to current shares outstanding — this is valid
    because both close and current shares are on the same split-adjusted
    basis.

    For delisted tickers:
        market_cap(t) = close(t) × shares_outstanding(t)  [from static CSV]

    For BRK: aggregates BRK-A and BRK-B into single 'BRK' entry.

    Parameters
    ----------
    prices : DataFrame [date, ticker, open, high, low, close, adj_close, volume]
    splits : DataFrame [date, ticker, split_ratio]
    shares : DataFrame [ticker, shares_outstanding]
    delisted : DataFrame [date, ticker, close, shares_outstanding]
    historical_shares : DataFrame [date, ticker, shares_outstanding] or None
        Historical shares outstanding from CSV. When provided, overrides the
        current-shares fallback for dates/tickers where data exists.

    Returns
    -------
    DataFrame [date, ticker, estimated_market_cap]
    """
    all_dates = sorted(prices["date"].unique())
    date_index = pd.DatetimeIndex(all_dates)

    # --- Active tickers ---
    logger.info("Computing cumulative split factors for %d tickers...", len(shares))
    csf = compute_cumulative_split_factor(splits, shares, date_index)

    # Merge prices (split-adjusted close) with split factors and current shares
    active = prices[["date", "ticker", "close"]].merge(
        csf, on=["date", "ticker"], how="inner"
    ).merge(
        shares, on="ticker", how="inner"
    )

    # Default: close is split-adjusted from yfinance, so use current shares
    # directly (no split factor needed — both are in current-split-basis).
    active["backward_shares"] = active["shares_outstanding"]

    # Override with historical shares where available (fixes buyback/dilution error).
    if historical_shares is not None and not historical_shares.empty:
        hist = historical_shares[["date", "ticker", "shares_outstanding"]].copy()
        hist = hist.rename(columns={"shares_outstanding": "hist_shares"})
        active = active.merge(hist, on=["date", "ticker"], how="left")
        mask = active["hist_shares"].notna()
        active.loc[mask, "backward_shares"] = active.loc[mask, "hist_shares"]
        active = active.drop(columns=["hist_shares"])
        logger.info(
            "Historical shares override: %d of %d rows (%.1f%%)",
            mask.sum(), len(active), 100.0 * mask.sum() / len(active),
        )

    active["estimated_market_cap"] = active["close"] * active["backward_shares"]

    result_active = active[["date", "ticker", "estimated_market_cap"]].copy()

    # --- BRK aggregation ---
    result_active = _aggregate_brk(result_active)

    # --- Delisted tickers ---
    result_delisted = pd.DataFrame(columns=["date", "ticker", "estimated_market_cap"])
    if not delisted.empty:
        delisted_mc = delisted.copy()
        delisted_mc["date"] = pd.to_datetime(delisted_mc["date"])
        # Snap dates to month-end to match active ticker resampling.
        # Prevents join mismatches from mid-month dates (e.g., bankruptcy filings).
        delisted_mc["date"] = delisted_mc["date"] + pd.offsets.MonthEnd(0)
        delisted_mc["estimated_market_cap"] = delisted_mc["close"] * delisted_mc["shares_outstanding"]
        # Deduplicate: if snapping creates two rows for same ticker+month, keep last
        delisted_mc = delisted_mc.drop_duplicates(subset=["date", "ticker"], keep="last")
        result_delisted = delisted_mc[["date", "ticker", "estimated_market_cap"]]
        logger.info(
            "Added %d delisted market cap observations for %s.",
            len(result_delisted),
            result_delisted["ticker"].unique().tolist(),
        )

    result = pd.concat([result_active, result_delisted], ignore_index=True)
    result = result.sort_values(["date", "estimated_market_cap"], ascending=[True, False])
    result = result.reset_index(drop=True)

    logger.info(
        "Estimated market caps: %d observations, %d unique tickers, %s to %s.",
        len(result),
        result["ticker"].nunique(),
        result["date"].min().strftime("%Y-%m"),
        result["date"].max().strftime("%Y-%m"),
    )

    return result


def _aggregate_brk(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate BRK-A and BRK-B market caps into a single 'BRK' entry.

    Total BRK market cap = BRK-A market cap + BRK-B market cap.
    For dates before BRK-B IPO (1996-05), use BRK-A alone.
    Remove individual BRK-A / BRK-B rows from output.
    """
    brk_a = df[df["ticker"] == BRK_A_TICKER].copy()
    brk_b = df[df["ticker"] == "BRK-B"].copy()

    if brk_a.empty and brk_b.empty:
        return df

    # Merge on date
    brk_a = brk_a.rename(columns={"estimated_market_cap": "mc_a"}).drop(columns=["ticker"])
    brk_b = brk_b.rename(columns={"estimated_market_cap": "mc_b"}).drop(columns=["ticker"])

    brk_merged = brk_a.merge(brk_b, on="date", how="outer")
    brk_merged["mc_a"] = brk_merged["mc_a"].fillna(0)
    brk_merged["mc_b"] = brk_merged["mc_b"].fillna(0)
    brk_merged["estimated_market_cap"] = brk_merged["mc_a"] + brk_merged["mc_b"]
    brk_merged["ticker"] = "BRK"

    # Remove individual BRK-A and BRK-B rows
    df_filtered = df[~df["ticker"].isin([BRK_A_TICKER, "BRK-B"])].copy()

    brk_result = brk_merged[["date", "ticker", "estimated_market_cap"]]
    return pd.concat([df_filtered, brk_result], ignore_index=True)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def rank_by_market_cap(market_caps: pd.DataFrame) -> pd.DataFrame:
    """
    Rank tickers by estimated market cap at each date.

    Parameters
    ----------
    market_caps : DataFrame [date, ticker, estimated_market_cap]

    Returns
    -------
    DataFrame [date, ticker, estimated_market_cap, rank]
        rank=1 is the largest market cap.
    """
    df = market_caps.copy()
    df["rank"] = df.groupby("date")["estimated_market_cap"].rank(
        ascending=False, method="min"
    ).astype(int)
    return df.sort_values(["date", "rank"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Known historical #1 market cap holders for checkpoint validation.
# Sources: Wikipedia "List of public corporations by market capitalization",
# Fortune 500 archives, financial media consensus.
KNOWN_RANK1 = {
    1990: "IBM",       # IBM was #1 or #2 (~$64B), contested with XOM
    1995: "GE",        # GE overtook during mid-90s bull market
    2000: "GE",        # GE peaked at ~$600B Jan 2000; MSFT close second
    2005: "XOM",       # XOM ~$370B post-Katrina oil surge; GE close second
    2010: "XOM",       # XOM ~$370B post-GFC
    2015: "AAPL",      # AAPL first to ~$700B+
    2020: "AAPL",      # AAPL ~$2T
    2025: "AAPL",      # AAPL ~$3.4T (MSFT, NVDA close)
}

# Acceptable alternatives (rank-1 was contested in some years)
KNOWN_RANK1_ALT = {
    1990: ["XOM", "GE"],
    2000: ["MSFT"],
    2005: ["GE"],
    2025: ["MSFT", "NVDA"],
}


def validate_rankings(rankings: pd.DataFrame) -> pd.DataFrame:
    """
    Validate rank-1 at each checkpoint year against known historical record.

    Returns DataFrame with validation results:
        [year, expected_rank1, actual_rank1, actual_rank1_mc, rank2_ticker,
         rank2_mc, gap_pct, match]
    """
    results = []
    for year in CHECKPOINT_YEARS:
        # Find the last month-end in December of the checkpoint year
        # (or closest available date)
        year_data = rankings[
            (rankings["date"].dt.year == year) &
            (rankings["date"].dt.month == 12)
        ]
        if year_data.empty:
            # Try last available month in the year
            year_data = rankings[rankings["date"].dt.year == year]
            if year_data.empty:
                results.append({
                    "year": year,
                    "expected_rank1": KNOWN_RANK1.get(year, "?"),
                    "actual_rank1": "NO DATA",
                    "actual_rank1_mc": np.nan,
                    "rank2_ticker": "NO DATA",
                    "rank2_mc": np.nan,
                    "gap_pct": np.nan,
                    "match": False,
                })
                continue
            last_date = year_data["date"].max()
            year_data = year_data[year_data["date"] == last_date]

        rank1_row = year_data[year_data["rank"] == 1]
        rank2_row = year_data[year_data["rank"] == 2]

        if rank1_row.empty:
            actual_r1 = "NO DATA"
            mc1 = np.nan
        else:
            actual_r1 = rank1_row.iloc[0]["ticker"]
            mc1 = rank1_row.iloc[0]["estimated_market_cap"]

        if rank2_row.empty:
            r2_ticker = "NO DATA"
            mc2 = np.nan
        else:
            r2_ticker = rank2_row.iloc[0]["ticker"]
            mc2 = rank2_row.iloc[0]["estimated_market_cap"]

        gap_pct = (
            ((mc1 - mc2) / mc1 * 100)
            if (not np.isnan(mc1) and not np.isnan(mc2) and mc1 != 0)
            else np.nan
        )

        expected = KNOWN_RANK1.get(year, "?")
        alts = KNOWN_RANK1_ALT.get(year, [])
        match = (actual_r1 == expected) or (actual_r1 in alts)

        results.append({
            "year": year,
            "expected_rank1": expected,
            "actual_rank1": actual_r1,
            "actual_rank1_mc_B": mc1 / 1e9 if not np.isnan(mc1) else np.nan,
            "rank2_ticker": r2_ticker,
            "rank2_mc_B": mc2 / 1e9 if not np.isnan(mc2) else np.nan,
            "gap_pct": gap_pct,
            "match": match,
        })

    result_df = pd.DataFrame(results)
    matches = result_df["match"].sum()
    total = len(CHECKPOINT_YEARS)
    logger.info(
        "Checkpoint validation: %d/%d matches (threshold: ≥6).",
        matches, total,
    )
    if matches < 6:
        logger.warning(
            "VALIDATION FAILED: Only %d/%d checkpoint years match. "
            "Review market cap estimation method and data.",
            matches, total,
        )
    return result_df


def compute_estimation_error(
    rankings: pd.DataFrame,
    known_market_caps: dict[int, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """
    Compute estimation error for top-5 at each checkpoint year against known values.

    Parameters
    ----------
    known_market_caps : dict mapping year -> {ticker: market_cap_in_billions}
        If None, uses hardcoded approximate values from public sources.

    Returns
    -------
    DataFrame [year, ticker, estimated_mc_B, known_mc_B, abs_error_B, rel_error_pct, rank_change]
    """
    # Approximate known market caps ($B) from public sources.
    # These are year-end approximate values for validation only.
    if known_market_caps is None:
        # Approximate year-end market caps ($B) from SEC filings, Fortune 500,
        # and financial media consensus. For validation only.
        known_market_caps = {
            1990: {"IBM": 64, "XOM": 63, "GE": 58, "PG": 24, "MSFT": 6},
            1995: {"GE": 120, "XOM": 100, "KO": 93, "MSFT": 46, "PG": 40},
            2000: {"GE": 475, "MSFT": 230, "CSCO": 300, "XOM": 270, "WMT": 240},
            2005: {"XOM": 370, "GE": 370, "MSFT": 280, "C": 245, "WMT": 200},
            2010: {"XOM": 370, "AAPL": 300, "MSFT": 240, "BRK": 200, "GE": 195},
            2015: {"AAPL": 586, "GOOGL": 528, "MSFT": 443, "BRK": 325, "XOM": 317},
            2020: {"AAPL": 2070, "MSFT": 1680, "AMZN": 1630, "GOOGL": 1190, "META": 780},
            2025: {"AAPL": 3400, "MSFT": 3100, "NVDA": 2800, "GOOGL": 2200, "AMZN": 2100},
        }

    results = []
    for year, known in known_market_caps.items():
        year_data = rankings[
            (rankings["date"].dt.year == year) &
            (rankings["date"].dt.month == 12)
        ]
        if year_data.empty:
            year_data = rankings[rankings["date"].dt.year == year]
            if year_data.empty:
                continue
        last_date = year_data["date"].max()
        year_data = year_data[year_data["date"] == last_date]

        for ticker, known_mc_b in known.items():
            row = year_data[year_data["ticker"] == ticker]
            if row.empty:
                est_mc_b = np.nan
            else:
                est_mc_b = row.iloc[0]["estimated_market_cap"] / 1e9

            abs_err = est_mc_b - known_mc_b if not np.isnan(est_mc_b) else np.nan
            rel_err = (abs_err / known_mc_b * 100) if not np.isnan(abs_err) else np.nan

            results.append({
                "year": year,
                "ticker": ticker,
                "estimated_mc_B": round(est_mc_b, 1) if not np.isnan(est_mc_b) else np.nan,
                "known_mc_B": known_mc_b,
                "abs_error_B": round(abs_err, 1) if not np.isnan(abs_err) else np.nan,
                "rel_error_pct": round(rel_err, 1) if not np.isnan(rel_err) else np.nan,
            })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Data Completeness Check
# ---------------------------------------------------------------------------

def check_data_completeness(
    prices: pd.DataFrame,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Check each ticker for missing monthly observations.

    Threshold: max(2, 0.01 × total_months_in_range).
    Tickers exceeding this are flagged.

    Returns DataFrame [ticker, total_months_expected, months_present,
                       months_missing, threshold, flagged]
    """
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end) if end else prices["date"].max()
    total_months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month) + 1
    threshold = max(2, int(0.01 * total_months))

    results = []
    for ticker in prices["ticker"].unique():
        tk_data = prices[prices["ticker"] == ticker]
        first_date = tk_data["date"].min()
        # Only count months from ticker's first available date
        tk_expected = (end_dt.year - first_date.year) * 12 + (end_dt.month - first_date.month) + 1
        present = len(tk_data)
        missing = max(0, tk_expected - present)

        results.append({
            "ticker": ticker,
            "first_date": first_date.strftime("%Y-%m"),
            "total_months_expected": tk_expected,
            "months_present": present,
            "months_missing": missing,
            "threshold": threshold,
            "flagged": missing > threshold,
        })

    result_df = pd.DataFrame(results)
    flagged = result_df[result_df["flagged"]]
    if not flagged.empty:
        logger.warning(
            "Flagged tickers for missing data (>%d months): %s",
            threshold,
            flagged["ticker"].tolist(),
        )
    return result_df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from data_fetcher import fetch_all

    logger.info("Fetching all data...")
    data = fetch_all(use_cache=True)

    logger.info("Estimating market caps...")
    mcaps = estimate_market_caps(
        data["prices"], data["splits"], data["shares_outstanding"], data["delisted"],
        historical_shares=data.get("historical_shares"),
    )

    logger.info("Ranking...")
    rankings = rank_by_market_cap(mcaps)

    logger.info("Validating rankings at checkpoints...")
    validation = validate_rankings(rankings)
    print("\n=== Checkpoint Validation ===")
    print(validation.to_string(index=False))

    logger.info("Computing estimation errors...")
    errors = compute_estimation_error(rankings)
    if not errors.empty:
        print("\n=== Estimation Error (top-5, selected years) ===")
        print(errors.to_string(index=False))

    logger.info("Checking data completeness...")
    completeness = check_data_completeness(data["prices"], "1990-01", None)
    flagged = completeness[completeness["flagged"]]
    if not flagged.empty:
        print("\n=== Flagged Tickers (missing data) ===")
        print(flagged.to_string(index=False))
    else:
        print("\n=== No tickers flagged for missing data ===")
