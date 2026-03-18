"""
config.py — Central configuration for MarketCapBacktest.

All constants, ticker universe, cost schedule, parameter grids, and ticker
mappings live here. No magic numbers in other modules.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
AUDITS_DIR = PROJECT_ROOT / "audits"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

DELISTED_CSV = DATA_DIR / "delisted_monthly.csv"
DATA_MANIFEST = RESULTS_DIR / "data_manifest.json"

# ---------------------------------------------------------------------------
# Ticker Universe — Active
# ---------------------------------------------------------------------------
# Entry date is approximate; data_fetcher.py determines actual entry from
# first valid yfinance monthly close.
#
# Format: {ticker: approximate_earliest_year}
ACTIVE_TICKERS = {
    # 1990 pre-existing
    "XOM": 1990, "GE": 1990, "IBM": 1990, "WMT": 1990, "KO": 1990,
    "PG": 1990, "JNJ": 1990, "MRK": 1990, "PFE": 1990, "T": 1990,
    "INTC": 1990, "MSFT": 1990, "AAPL": 1990, "ABT": 1990, "MCD": 1990,
    "MMM": 1990, "BA": 1990, "DD": 1990, "CAT": 1990, "DIS": 1990,
    "HD": 1990, "JPM": 1990, "BAC": 1990, "C": 1990, "PEP": 1990,
    "MO": 1990, "AMGN": 1990, "ORCL": 1990, "QCOM": 1991, "CMCSA": 1990,
    "LLY": 1990, "UNH": 1990, "GILD": 1992, "NFLX": 2002,
    # IPO / earliest data post-1990
    "CSCO": 1990,    # IPO Feb 1990
    "BRK-B": 1996,   # IPO May 1996
    "AMZN": 1997,     # IPO May 1997
    "NVDA": 1999,     # IPO Jan 1999
    "GOOGL": 2004,    # IPO Aug 2004
    "MA": 2006,       # IPO May 2006
    "V": 2008,        # IPO Mar 2008
    "TSLA": 2010,     # IPO Jun 2010
    "META": 2012,     # IPO May 2012
    "ABBV": 2013,     # Spinoff from ABT Jan 2013
    "AVGO": 2009,     # IPO Aug 2009
    "CRM": 2004,      # IPO Jun 2004
    "ADBE": 1990,     # Pre-existing, data available
    "PYPL": 2015,     # IPO Jul 2015
}

# BRK-A is used for market cap aggregation only, not as a separate portfolio
# holding. BRK-B is the tradable instrument.
BRK_A_TICKER = "BRK-A"

# ---------------------------------------------------------------------------
# Delisted Tickers
# ---------------------------------------------------------------------------
# These are loaded from data/delisted_monthly.csv. Listing here for reference.
DELISTED_TICKERS = {
    "ENRNQ": {"company": "Enron", "delist_date": "2001-12"},
    "WCOEQ": {"company": "WorldCom/MCI", "delist_date": "2002-07"},
    "LEH": {"company": "Lehman Brothers", "delist_date": "2008-09"},
    "GMGMQ": {"company": "General Motors (old)", "delist_date": "2009-06"},
    "MOB": {"company": "Mobil Corp", "delist_date": "1999-11"},
}

# ---------------------------------------------------------------------------
# Ticker Mappings — Corporate Actions
# ---------------------------------------------------------------------------
# old_ticker -> current_ticker for mergers, renames, etc.
# Used by data_fetcher to resolve historical references.
TICKER_RENAMES = {
    "FB": "META",
    # MOB merged into XOM — handled via delisted CSV; XOM continues.
}

# Spin-offs: parent -> child, effective date
SPINOFFS = {
    "ABBV": {"parent": "ABT", "effective": "2013-01-02"},
}

# ---------------------------------------------------------------------------
# Benchmark Configuration
# ---------------------------------------------------------------------------
# Each benchmark has a primary ticker, a fallback, and a coverage note.
BENCHMARKS = {
    "S&P 500": {
        "primary": "^GSPC",
        "fallback": "SPY",
        "coverage_start": "1990-01",
    },
    "Nasdaq 100": {
        "primary": "^NDX",
        "fallback": "QQQ",
        "coverage_start": "1985-01",
        "note": "Pre-1985 unavailable; omit from comparison.",
    },
    "E-mini S&P": {
        "primary": "SPY",
        "fallback": "ES=F",
        "coverage_start": "1993-01",
        "note": "SPY as proxy; cleaner data than ES=F.",
    },
    "Gold": {
        "primary": "GC=F",
        "fallback_fred": "GOLDAMGBD228NLBM",
        "fallback_etf": "GLD",
        "coverage_start": "1990-01",
        "note": "GC=F has data quality issues pre-2000; FRED London PM fix as fallback.",
    },
}

# ---------------------------------------------------------------------------
# Transaction Cost Schedule (round-trip, basis points)
# ---------------------------------------------------------------------------
# Keys are period start dates; cost applies from that date until the next key.
# Ref: SEC market structure studies; Jones (2002) "A Century of Stock Market
# Liquidity and Trading Costs".
COST_SCHEDULE_BPS = {
    "1990-01-01": 50,  # Pre-decimalization
    "2001-04-01": 20,  # Decimalization (Apr 2001)
    "2005-01-01": 10,  # Reg NMS era + electronic trading
}

# Sensitivity multipliers for cost analysis
COST_SENSITIVITY_MULTIPLIERS = [0.0, 1.0, 2.0]  # 0×, 1× (base), 2× base

# ---------------------------------------------------------------------------
# Backtest Defaults
# ---------------------------------------------------------------------------
DEFAULT_INITIAL_CAPITAL = 10_000.0
DEFAULT_MONTHLY_CONTRIBUTION = 1_000.0
DEFAULT_START_DATE = "1990-01"
DEFAULT_END_DATE = None  # None = latest available

# Fractional shares allowed (backtesting simplification).
FRACTIONAL_SHARES = True

# ---------------------------------------------------------------------------
# Strategy 2 Parameters
# ---------------------------------------------------------------------------
STRATEGY2_N_VALUES = [2, 3, 4, 5]  # Exhaustive; no optimization needed.

# ---------------------------------------------------------------------------
# Strategy 3 Parameters — Grid Search
# ---------------------------------------------------------------------------
# N_candidates: full enumeration 3..10 (eliminates arbitrary gaps in {3,5,7,10})
STRATEGY3_N_CANDIDATES = [3, 4, 5, 6, 7, 8, 9, 10]

# k_lookback months: expanded from {1,3,6,12} to include 2 and 9.
# Jegadeesh & Titman (1993) found significant returns for formation periods
# 3-12 months with no monotonic pattern, justifying dense sampling.
STRATEGY3_K_LOOKBACK = [1, 2, 3, 6, 9, 12]

# Total grid: 8 × 6 = 48 combinations

# ---------------------------------------------------------------------------
# Walk-Forward Validation Parameters
# ---------------------------------------------------------------------------
WF_TRAIN_MONTHS = 60   # 5-year sliding window
WF_TEST_MONTHS = 36    # 3-year test; SE(Sharpe) ≈ 1/√36 ≈ 0.17
WF_STEP_MONTHS = 12    # 1-year step

# White's Reality Check
WRC_BOOTSTRAP_REPS = 1000
WRC_SIGNIFICANCE = 0.10  # p > 0.10 → no parameter set beats benchmark

# ---------------------------------------------------------------------------
# Risk-Free Rate
# ---------------------------------------------------------------------------
FRED_RF_SERIES = "DGS3MO"  # 3-Month Treasury Constant Maturity Rate

# ---------------------------------------------------------------------------
# Data Validation
# ---------------------------------------------------------------------------
# Checkpoint years for market cap ranking verification.
CHECKPOINT_YEARS = [1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025]

# Missing data threshold: max(2, 0.01 × total_months).
# Forward-fill gaps ≤ this many months; drop ticker for longer gaps.
MAX_FFILL_MONTHS = 2

# ---------------------------------------------------------------------------
# Metric Validation Tolerances
# ---------------------------------------------------------------------------
# Sharpe: max(0.1% relative, 0.001 absolute)
METRIC_TOL_SHARPE_REL = 0.001
METRIC_TOL_SHARPE_ABS = 0.001
# CAGR, MaxDD: max(0.1% relative, 0.01%)
METRIC_TOL_RETURN_REL = 0.001
METRIC_TOL_RETURN_ABS = 0.0001

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
DEFAULT_RANDOM_SEED = 42
ALTERNATIVE_SEEDS = [7, 123, 9999]  # For seed-sensitivity checks
