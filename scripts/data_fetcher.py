"""
data_fetcher.py — Data acquisition for MarketCapBacktest.

Fetches price data, splits, shares outstanding from yfinance; risk-free rate
from FRED; and loads static delisted company data from CSV.

Produces cached parquet files in results/ with SHA-256 manifest.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from config import (
    ACTIVE_TICKERS,
    BENCHMARKS,
    BRK_A_TICKER,
    DATA_DIR,
    DATA_MANIFEST,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    DELISTED_CSV,
    FRED_RF_SERIES,
    RESULTS_DIR,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_dirs():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Price Data
# ---------------------------------------------------------------------------

def fetch_price_data(
    tickers: list[str],
    start: str = DEFAULT_START_DATE,
    end: str | None = DEFAULT_END_DATE,
    batch_size: int = 20,
    pause_sec: float = 1.0,
) -> pd.DataFrame:
    """
    Fetch OHLCV + adj_close for each ticker via yfinance.

    Returns DataFrame: [date, ticker, open, high, low, close, adj_close, volume]
    Resampled to month-end frequency.
    """
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    # yfinance wants YYYY-MM-DD
    start_dt = _parse_month_to_date(start)
    end_dt = end if "-" in end and len(end) > 7 else _parse_month_to_date(end, first=False)

    all_frames = []
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        logger.info("Fetching batch %d–%d: %s", i, i + len(batch), batch)
        try:
            data = yf.download(
                batch,
                start=start_dt,
                end=end_dt,
                auto_adjust=False,
                group_by="ticker",
                threads=True,
            )
        except Exception as e:
            logger.error("yfinance download failed for batch %s: %s", batch, e)
            continue

        for ticker in batch:
            try:
                if len(batch) == 1:
                    df_t = data.copy()
                else:
                    df_t = data[ticker].copy()
                df_t = df_t.dropna(subset=["Close"])
                if df_t.empty:
                    logger.warning("No data for %s", ticker)
                    continue
                df_t = df_t.reset_index()
                df_t = df_t.rename(columns={
                    "Date": "date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Adj Close": "adj_close",
                    "Volume": "volume",
                })
                # Handle MultiIndex columns from yfinance
                if hasattr(df_t.columns, 'droplevel'):
                    try:
                        df_t.columns = df_t.columns.droplevel(1)
                    except (IndexError, ValueError):
                        pass
                df_t["ticker"] = ticker
                # Resample to month-end
                df_t["date"] = pd.to_datetime(df_t["date"])
                df_t = df_t.set_index("date").resample("ME").last().dropna(subset=["close"]).reset_index()
                all_frames.append(df_t[["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"]])
            except Exception as e:
                logger.warning("Failed to process %s: %s", ticker, e)
                continue

        if i + batch_size < len(tickers):
            time.sleep(pause_sec)

    if not all_frames:
        raise RuntimeError("No price data fetched for any ticker.")

    result = pd.concat(all_frames, ignore_index=True)
    result = result.sort_values(["ticker", "date"]).reset_index(drop=True)
    return result


def _parse_month_to_date(s: str, first: bool = True) -> str:
    """Convert 'YYYY-MM' or 'YYYY-MM-DD' to full date string."""
    if len(s) == 7:  # YYYY-MM
        if first:
            return f"{s}-01"
        else:
            dt = pd.Timestamp(f"{s}-01") + pd.offsets.MonthEnd(0)
            return dt.strftime("%Y-%m-%d")
    return s


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------

def fetch_splits(tickers: list[str]) -> pd.DataFrame:
    """
    Fetch historical stock split data via yfinance.

    Returns DataFrame: [date, ticker, split_ratio]
    split_ratio > 1 means forward split (e.g., 4.0 for 4:1 split).
    split_ratio < 1 means reverse split (e.g., 0.125 for 1:8 reverse).
    """
    all_splits = []
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            splits = tk.splits
            if splits is not None and not splits.empty:
                df = splits.reset_index()
                df.columns = ["date", "split_ratio"]
                df["ticker"] = ticker
                df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
                all_splits.append(df[["date", "ticker", "split_ratio"]])
        except Exception as e:
            logger.warning("Failed to fetch splits for %s: %s", ticker, e)

    if not all_splits:
        return pd.DataFrame(columns=["date", "ticker", "split_ratio"])

    return pd.concat(all_splits, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Shares Outstanding
# ---------------------------------------------------------------------------

def fetch_shares_outstanding(tickers: list[str]) -> pd.DataFrame:
    """
    Fetch current shares outstanding for each ticker via yfinance.

    Returns DataFrame: [ticker, shares_outstanding]
    """
    records = []
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            info = tk.info
            shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            if shares is not None:
                records.append({"ticker": ticker, "shares_outstanding": int(shares)})
            else:
                logger.warning("No shares outstanding for %s", ticker)
        except Exception as e:
            logger.warning("Failed to fetch shares outstanding for %s: %s", ticker, e)

    if not records:
        raise RuntimeError("No shares outstanding data fetched.")

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Historical Shares Outstanding
# ---------------------------------------------------------------------------

def load_historical_shares() -> pd.DataFrame:
    """Load historical shares outstanding from CSV."""
    path = DATA_DIR / "historical_shares_outstanding.csv"
    if not path.exists():
        logger.warning("Historical shares CSV not found at %s", path)
        return pd.DataFrame(columns=["date", "ticker", "shares_outstanding"])
    df = pd.read_csv(path, parse_dates=["date"])
    return df[["date", "ticker", "shares_outstanding"]]


# ---------------------------------------------------------------------------
# Risk-Free Rate
# ---------------------------------------------------------------------------

def fetch_risk_free_rate(
    start: str = DEFAULT_START_DATE,
    end: str | None = DEFAULT_END_DATE,
) -> pd.Series:
    """
    Fetch 3-month Treasury rate from FRED via pandas_datareader, convert to
    monthly rate per §3.6: r_monthly = (1 + DGS3MO/100)^(1/12) - 1.

    Returns pd.Series indexed by month-end date, values are monthly decimal rates.
    """
    start_dt = _parse_month_to_date(start)
    end_dt = _parse_month_to_date(end or datetime.now().strftime("%Y-%m"), first=False)

    try:
        import pandas_datareader.data as web
        rf_daily = web.DataReader(FRED_RF_SERIES, "fred", start_dt, end_dt)
    except ImportError:
        logger.info("pandas_datareader not available, trying yfinance for ^IRX")
        # Fallback: use ^IRX (13-week T-bill) from yfinance
        irx = yf.download("^IRX", start=start_dt, end=end_dt, auto_adjust=False)
        if irx.empty:
            logger.warning("No risk-free rate data available. Using 0.")
            idx = pd.date_range(start_dt, end_dt, freq="ME")
            return pd.Series(0.0, index=idx, name="rf_monthly")
        rf_daily = irx[["Close"]].rename(columns={"Close": FRED_RF_SERIES})
    except Exception as e:
        logger.warning("FRED fetch failed: %s. Using 0.", e)
        idx = pd.date_range(start_dt, end_dt, freq="ME")
        return pd.Series(0.0, index=idx, name="rf_monthly")

    # Resample to monthly: last available observation per month
    rf_monthly_raw = rf_daily[FRED_RF_SERIES].resample("ME").last().dropna()

    # Convert annualized yield (%) to monthly decimal rate
    # r_monthly = (1 + DGS3MO / 100)^(1/12) - 1
    rf_monthly = (1 + rf_monthly_raw / 100) ** (1 / 12) - 1
    rf_monthly.name = "rf_monthly"
    return rf_monthly


# ---------------------------------------------------------------------------
# Delisted Data
# ---------------------------------------------------------------------------

def load_delisted_data() -> pd.DataFrame:
    """
    Load static monthly data for delisted companies.

    Returns DataFrame: [date, ticker, close, shares_outstanding]
    """
    if not DELISTED_CSV.exists():
        logger.warning("Delisted CSV not found at %s", DELISTED_CSV)
        return pd.DataFrame(columns=["date", "ticker", "close", "shares_outstanding"])

    df = pd.read_csv(DELISTED_CSV, parse_dates=["date"])
    required_cols = {"date", "ticker", "close", "shares_outstanding"}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"Delisted CSV missing columns: {required_cols - set(df.columns)}")

    return df


# ---------------------------------------------------------------------------
# Benchmark Data
# ---------------------------------------------------------------------------

def fetch_benchmark_data(
    start: str = DEFAULT_START_DATE,
    end: str | None = DEFAULT_END_DATE,
) -> pd.DataFrame:
    """
    Fetch benchmark price data using primary/fallback ticker chain.

    Returns DataFrame: [date, benchmark, adj_close]
    Resampled to month-end.
    """
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    start_dt = _parse_month_to_date(start)
    end_dt = end if len(end) > 7 else _parse_month_to_date(end, first=False)

    frames = []
    for name, cfg in BENCHMARKS.items():
        primary = cfg["primary"]

        df = _try_fetch_single(primary, start_dt, end_dt, name)

        # Standard yfinance fallback
        fallback = cfg.get("fallback")
        if df is None and fallback:
            logger.info("Primary %s failed for %s, trying fallback %s", primary, name, fallback)
            df = _try_fetch_single(fallback, start_dt, end_dt, name)

        # FRED fallback (Gold pre-2000 data quality issue)
        fallback_fred = cfg.get("fallback_fred")
        if df is None and fallback_fred:
            logger.info("Trying FRED fallback %s for %s", fallback_fred, name)
            df = _try_fetch_fred_benchmark(fallback_fred, start_dt, end_dt, name)

        # ETF fallback
        fallback_etf = cfg.get("fallback_etf")
        if df is None and fallback_etf:
            logger.info("Trying ETF fallback %s for %s", fallback_etf, name)
            df = _try_fetch_single(fallback_etf, start_dt, end_dt, name)

        if df is None:
            logger.warning("No benchmark data for %s", name)
            continue
        frames.append(df)

    if not frames:
        raise RuntimeError("No benchmark data fetched.")

    return pd.concat(frames, ignore_index=True).sort_values(["benchmark", "date"]).reset_index(drop=True)


def _try_fetch_single(ticker: str, start: str, end: str, label: str) -> pd.DataFrame | None:
    """Try fetching a single benchmark ticker."""
    try:
        data = yf.download(ticker, start=start, end=end, auto_adjust=False, threads=False)
        if data.empty:
            return None
        data = data.reset_index()
        # Handle potential MultiIndex columns
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(1)
        data = data.rename(columns={"Date": "date", "Adj Close": "adj_close"})
        data["date"] = pd.to_datetime(data["date"])
        monthly = data.set_index("date")[["adj_close"]].resample("ME").last().dropna().reset_index()
        monthly["benchmark"] = label
        return monthly[["date", "benchmark", "adj_close"]]
    except Exception as e:
        logger.warning("Failed to fetch %s (%s): %s", ticker, label, e)
        return None


def _try_fetch_fred_benchmark(
    series_id: str, start: str, end: str, label: str,
) -> pd.DataFrame | None:
    """Fetch a benchmark price series from FRED (e.g., GOLDAMGBD228NLBM for gold)."""
    try:
        import pandas_datareader.data as web
        data = web.DataReader(series_id, "fred", start, end)
        if data.empty:
            return None
        # FRED gold series is daily London PM fix in USD/troy oz
        monthly = data.resample("ME").last().dropna()
        monthly = monthly.reset_index()
        monthly.columns = ["date", "adj_close"]
        monthly["benchmark"] = label
        return monthly[["date", "benchmark", "adj_close"]]
    except Exception as e:
        logger.warning("FRED fetch failed for %s (%s): %s", series_id, label, e)
        return None


# ---------------------------------------------------------------------------
# Caching & Manifest
# ---------------------------------------------------------------------------

def save_with_manifest(df: pd.DataFrame, filename: str, description: str = ""):
    """Save DataFrame as parquet and update data manifest."""
    _ensure_dirs()
    path = RESULTS_DIR / filename
    df.to_parquet(path, index=False)

    manifest = {}
    if DATA_MANIFEST.exists():
        with open(DATA_MANIFEST) as f:
            manifest = json.load(f)

    manifest[filename] = {
        "sha256": _sha256(path),
        "fetch_date": datetime.now().isoformat(),
        "rows": len(df),
        "columns": list(df.columns),
        "description": description,
    }

    with open(DATA_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Saved %s (%d rows) and updated manifest.", filename, len(df))


def load_cached(filename: str, verify_hash: bool = True) -> pd.DataFrame | None:
    """Load a cached parquet file if it exists, optionally verifying SHA-256."""
    path = RESULTS_DIR / filename
    if not path.exists():
        return None

    if verify_hash and DATA_MANIFEST.exists():
        with open(DATA_MANIFEST) as f:
            manifest = json.load(f)
        entry = manifest.get(filename)
        if entry:
            actual_hash = _sha256(path)
            if actual_hash != entry["sha256"]:
                logger.warning(
                    "Cache hash mismatch for %s (expected %s, got %s). "
                    "File may be corrupted or stale. Invalidating cache.",
                    filename, entry["sha256"][:12], actual_hash[:12],
                )
                return None

    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def fetch_all(
    start: str = DEFAULT_START_DATE,
    end: str | None = DEFAULT_END_DATE,
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Fetch all data required for the backtest.

    Returns dict with keys:
        prices, splits, shares_outstanding, risk_free,
        delisted, benchmarks
    """
    _ensure_dirs()

    all_tickers = list(ACTIVE_TICKERS.keys()) + [BRK_A_TICKER]
    result = {}

    # --- Prices ---
    cache_name = "prices_monthly.parquet"
    cached = load_cached(cache_name) if use_cache else None
    if cached is not None:
        logger.info("Using cached price data (%d rows).", len(cached))
        result["prices"] = cached
    else:
        logger.info("Fetching price data for %d tickers...", len(all_tickers))
        prices = fetch_price_data(all_tickers, start, end)
        save_with_manifest(prices, cache_name, "Monthly OHLCV + adj_close for active tickers + BRK-A")
        result["prices"] = prices

    # --- Splits ---
    cache_name = "splits.parquet"
    cached = load_cached(cache_name) if use_cache else None
    if cached is not None:
        logger.info("Using cached splits data.")
        result["splits"] = cached
    else:
        logger.info("Fetching split history for %d tickers...", len(all_tickers))
        splits = fetch_splits(all_tickers)
        save_with_manifest(splits, cache_name, "Historical stock splits")
        result["splits"] = splits

    # --- Shares Outstanding ---
    cache_name = "shares_outstanding.parquet"
    cached = load_cached(cache_name) if use_cache else None
    if cached is not None:
        logger.info("Using cached shares outstanding.")
        result["shares_outstanding"] = cached
    else:
        logger.info("Fetching shares outstanding for %d tickers...", len(all_tickers))
        shares = fetch_shares_outstanding(all_tickers)
        save_with_manifest(shares, cache_name, "Current shares outstanding per ticker")
        result["shares_outstanding"] = shares

    # --- Risk-Free Rate ---
    cache_name = "risk_free.parquet"
    cached = load_cached(cache_name) if use_cache else None
    if cached is not None:
        logger.info("Using cached risk-free rate.")
        result["risk_free"] = cached.set_index("date")["rf_monthly"] if "date" in cached.columns else cached.iloc[:, 0]
    else:
        logger.info("Fetching risk-free rate...")
        rf = fetch_risk_free_rate(start, end)
        rf_df = rf.reset_index()
        rf_df.columns = ["date", "rf_monthly"]
        save_with_manifest(rf_df, cache_name, "Monthly risk-free rate (DGS3MO converted)")
        result["risk_free"] = rf

    # --- Delisted ---
    result["delisted"] = load_delisted_data()

    # --- Historical Shares Outstanding ---
    result["historical_shares"] = load_historical_shares()

    # --- Benchmarks ---
    cache_name = "benchmarks_monthly.parquet"
    cached = load_cached(cache_name) if use_cache else None
    if cached is not None:
        logger.info("Using cached benchmark data.")
        result["benchmarks"] = cached
    else:
        logger.info("Fetching benchmark data...")
        benchmarks = fetch_benchmark_data(start, end)
        save_with_manifest(benchmarks, cache_name, "Monthly benchmark adj_close")
        result["benchmarks"] = benchmarks

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    data = fetch_all(use_cache=False)
    for key, val in data.items():
        if isinstance(val, pd.DataFrame):
            print(f"{key}: {val.shape}")
        elif isinstance(val, pd.Series):
            print(f"{key}: {len(val)} months")
