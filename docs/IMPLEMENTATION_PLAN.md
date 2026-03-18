# Market-Cap Weighted Portfolio Backtest — Implementation Plan

## Objective

Backtest three monthly-rebalancing strategies that allocate a portfolio based on equity market capitalization rankings. Starting capital $10,000 with $1,000 monthly contributions. Configurable start date (earliest 1990-01). Compare against Gold, NQ, ES benchmarks. Surface institutional-grade performance metrics.

---

## 1. Data Requirements

### 1.1 Historical Market Capitalization

**Problem:** No single free API provides monthly market cap for US equities back to 1990.

**Solution — Split-Adjusted Shares Outstanding Method:**

The naive formula `adj_close(t) × shares_outstanding_current` is **incorrect** — it double-counts split adjustments (adjusted close already divides by the split factor; current shares outstanding already multiplies by it) and ignores the effect of buybacks and issuances on historical share counts. For example, Apple's ~$600B in buybacks (2013–2025) reduced share count by ~40%; GE's dilution + 1:8 reverse split makes current shares outstanding ~1/8th of the 2000 count. These distortions produce **wrong rankings**, not rounding errors.

**Correct formulation:**

$$\text{market\_cap}(t) = \text{close}(t) \times \text{shares\_outstanding\_backward}(t)$$

where:

$$\text{shares\_outstanding\_backward}(t) = \frac{\text{shares\_outstanding\_current}}{\text{cumulative\_split\_factor}(t \to \text{now})}$$

The cumulative split factor from date $t$ to present is computed from the full split history available via `yfinance` `.splits` attribute. This isolates split adjustments from buybacks/issuances, yielding a share count that is correct modulo non-split corporate actions.

**Residual error from buybacks/issuances:** This method still assumes shares outstanding (ex-splits) are constant over time. For stocks with significant buyback programs or dilution, the error grows with time distance from present. This error is **quantified** in the validation phase (see §1.3).

**Data source evaluation:**

| Source | Coverage | Cost | Historical Market Cap | Selected |
|--------|----------|------|----------------------|----------|
| `yfinance` (split-adjusted method above) | 1990–present | Free | Approximated; error bounded | **Primary** |
| Sharadar (Nasdaq Data Link) | 1986–present | ~$20/mo | Direct `marketcap` field | Recommended upgrade |
| Tiingo Fundamentals | 2000–present | Free tier limited | Direct | Insufficient pre-2000 coverage |
| Compustat via WRDS | 1960–present | Institutional license | Gold standard | Out of scope for this project |

The implementation uses `yfinance` as the primary source with the corrected split-adjusted method. If Sharadar access is available, `data_fetcher.py` will prefer it for direct market cap values and fall back to the `yfinance` approximation.

| Period | Method | Rationale |
|--------|--------|-----------|
| 1990–2000 | `yfinance` unadjusted close × split-adjusted shares outstanding + curated ranking overrides for checkpoint years | Pre-API era; split-adjusted method validated against known rankings. Where ranking conflicts with historical record, override with curated data. |
| 2000–present | `yfinance` unadjusted close × split-adjusted shares outstanding (or Sharadar direct market cap if available) | Denser ticker universe as IPOs occur. Split-adjusted method validated with published error bounds. |

**Ticker universe (enter at IPO / earliest available data, NOT at mega-cap date):**

Strategy 3 (momentum-weighted) requires equities to be in the universe *before* they reach the top — the signal is the rise itself. Therefore, universe entry = IPO date or earliest `yfinance` data availability.

**Active tickers:**

```
1990 (pre-existing): XOM, GE, IBM, WMT, KO, PG, JNJ, MRK, PFE, T, INTC,
                     MSFT, AAPL, ABT, MCD, MMM, BA, DD, CAT, DIS, HD, JPM,
                     BAC, C, PEP, MO, AMGN, ORCL, QCOM, CMCSA, LLY, UNH,
                     GILD, NFLX (use earliest yfinance availability for each)
1990:      CSCO (IPO Feb 1990)
1996:      BRK-B (IPO May 1996)
1999:      NVDA (IPO Jan 1999)
2004:      GOOGL (IPO Aug 2004)
2006:      MA (IPO May 2006)
2008:      V (IPO Mar 2008)
2010:      TSLA (IPO Jun 2010)
2012:      META (IPO May 2012), ABBV (spinoff Jan 2013)
2015:      AVGO, CRM, ADBE, PYPL (IPO Jul 2015)
```

**Berkshire Hathaway market cap aggregation:** BRK-A and BRK-B represent the same company. Total market cap = `BRK-A close × BRK-A shares outstanding + BRK-B close × BRK-B shares outstanding`. Pre-1996 (before BRK-B IPO), use BRK-A alone. `market_cap_estimator.py` aggregates both share classes into a single `BRK` entry for ranking. `backtest_engine.py` maps `BRK` back to `BRK-B` for trade execution via `RANKING_TO_TRADE = {"BRK": "BRK-B"}`.

**Delisted tickers (static CSV — `data/delisted_monthly.csv`):**

`yfinance` does not reliably serve data for delisted securities. Monthly close prices for the following companies are sourced from historical databases and embedded as a static CSV file with columns `[ticker, date, close, shares_outstanding]`.

| Ticker | Company | Approx. Peak Market Cap | Delisting Date | Delisting Event |
|--------|---------|------------------------|----------------|-----------------|
| ENRNQ | Enron | ~$70B (2000) | 2001-12 | Bankruptcy |
| WCOEQ | WorldCom/MCI | ~$180B (1999) | 2002-07 | Bankruptcy |
| LEH | Lehman Brothers | ~$45B (2007) | 2008-09 | Bankruptcy |
| GMGMQ | General Motors (old) | ~$55B (2000) | 2009-06 | Bankruptcy |
| MOB | Mobil Corp | ~$60B (1998) | 1999-11 | Merger with Exxon |

**Delisting handling in `backtest_engine.py`:** On the delisting date, force-liquidate the position at the last traded price. Proceeds are held as cash and reallocated at the next rebalance date.

**Note:** Actual entry dates for active tickers will be determined programmatically by `yfinance` data availability — the above are approximate. The `data_fetcher.py` script will query each ticker and set entry date = first valid monthly close. Delisted ticker entry dates are set from the static CSV.

### 1.2 Benchmark Data

All sourced via `yfinance` with explicit fallback chains and coverage documentation:

| Benchmark | Primary Ticker | Fallback | Coverage | Notes |
|-----------|---------------|----------|----------|-------|
| S&P 500 | `^GSPC` | `SPY` (post-1993) | 1990–present | Index ticker preferred for full coverage |
| Nasdaq 100 | `^NDX` | None pre-1985; `QQQ` post-1999 for validation | 1985–present | **Pre-1985: benchmark unavailable; omit from comparison** |
| E-mini S&P | `SPY` (proxy) | `ES=F` where available | 1993–present | SPY preferred over futures for cleaner data |
| Gold | `GC=F` | FRED `GOLDAMGBD228NLBM` (London PM fix) pre-2000; `GLD` post-2004 for validation | 1990–present via FRED fallback | `GC=F` has known data quality issues pre-2000 in `yfinance` |

**Handling unavailable benchmark periods:** When a benchmark's data does not cover the full backtest range, the benchmark line starts at its earliest available date. Metrics comparing strategy vs. benchmark are computed only over the overlapping period. The dashboard labels coverage start dates on each benchmark curve.

### 1.3 Data Validation

**Market cap approximation error quantification:**
- For each checkpoint year (1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025), compute estimated market cap for the top-5 equities using the split-adjusted method.
- Compare against known historical market cap values sourced from SEC filings, Bloomberg terminal snapshots, or Compustat summary data.
- Compute and publish: absolute error ($B), relative error (%), and whether the error changes the ranking.
- **Acceptance threshold:** Estimated rank-1 must match actual rank-1 for at least 6 of 8 checkpoint years. Rank-1/rank-2 market cap gap must exceed the method's estimated error for the ranking to be considered reliable at that checkpoint.

**Ranking accuracy validation:**
- Cross-check top-1 market cap holder each year against Wikipedia "List of public corporations by market capitalization" and Fortune 500 archives.
- Verify delisted companies appear in rankings during their active periods (e.g., Enron in top-10 by 2000, Lehman in top-20 by 2007).

**Data completeness:**
- Log any ticker with missing monthly data points. Flag tickers exceeding a completeness threshold derived from the universe: threshold = `max(2, 0.01 × total_months_in_range)` missing observations. (Rationale: allows 1% missingness or 2 months, whichever is larger, to accommodate short-lived data gaps without flagging tickers that are otherwise well-covered.)
- For flagged tickers, forward-fill gaps of ≤2 months; drop ticker from ranking for longer gaps.

---

## 2. Strategy Definitions

### Strategy 1: Top-1 Market Cap (100% Concentration)

```
At each rebalance date (1st trading day of month):
  1. Rank universe by estimated market cap
  2. Allocate 100% to rank-1 equity
  3. If rank-1 changes, sell prior holding, buy new holding
  4. Add $1,000 contribution to portfolio
```

**Parameters:** None tunable (deterministic).

### Strategy 2: Top-N Equal Weight (N ∈ {2, 3, 4, 5})

```
At each rebalance date:
  1. Rank universe by estimated market cap
  2. Allocate 1/N to each of top-N equities
  3. Rebalance positions to equal weight
  4. Add $1,000 contribution
```

**Parameters:** N ∈ {2, 3, 4, 5} — grid search over this set. No optimization needed; exhaustive evaluation of 4 values.

### Strategy 3: Momentum-Weighted Market Cap (Anticipatory)

The core idea: weight allocation toward equities *gaining* market cap rank momentum, capturing rising challengers before they overtake the incumbent leader.

**Literature basis:** Cross-sectional momentum in equities is well-documented (Jegadeesh & Titman, 1993, "Returns to Buying Winners and Selling Losers"; Asness, Moskowitz & Pedersen, 2013, "Value and Momentum Everywhere"). This strategy adapts the momentum factor to market cap growth rather than price returns, applied to a concentrated mega-cap universe.

**Formulation:**

Let $M_i(t)$ = estimated market cap of equity $i$ at time $t$.

Define log market cap momentum:

$$\mu_i(t) = \log\left(\frac{M_i(t)}{M_i(t-k)}\right)$$

This is the continuously compounded growth rate in market cap over $k$ months. Log-ratio is used rather than percent change to (a) symmetrize gains and losses, (b) avoid the relative-size conflation of the naive $M_i/M_1 \times \Delta M_i$ formulation, which systematically suppresses challengers and favors the incumbent leader.

Portfolio weights (for top-N candidates by current market cap):

$$w_i(t) = \frac{\max(\mu_i(t), 0)}{\sum_{j \in \text{top-N}} \max(\mu_j(t), 0)}$$

**All-negative-momentum fallback:** When $\max(\mu_j(t), 0) = 0$ for all $j$ in the top-N (i.e., all candidates have negative or zero momentum — typically during broad market downturns), the denominator is zero. Fallback: allocate equal weight $1/N$ to all top-N candidates. This is explicitly handled in `strategies.py` and logged when triggered.

**Parameters to grid search:**
- `N_candidates` ∈ {3, 4, 5, 6, 7, 8, 9, 10} — how many equities to consider (full enumeration from minimum viable to practical maximum, eliminating arbitrary gaps in the prior {3,5,7,10} grid)
- `k_lookback` ∈ {1, 2, 3, 6, 9, 12} months — momentum lookback window (expanded from {1,3,6,12} to include 2 and 9 months; Jegadeesh & Titman (1993) found significant returns for formation periods of 3–12 months with no monotonic pattern, justifying dense sampling in this range)
- Total grid: 8 × 6 = 48 combinations

**Selection criterion — walk-forward validation with sliding window:**

The prior expanding-window approach is replaced with a sliding (fixed-length) window to avoid non-stationarity bias (early folds training on 1-2 years vs. later folds on 20+). Procedure:

1. **Training window:** 60 months (5 years). Selected as the minimum window providing sufficient data for stable Sharpe estimation while allowing enough test folds over the 1990-2025 period.
2. **Test window:** 36 months (3 years). With monthly rebalancing, this yields 36 observations per fold — sufficient for Sharpe ratio standard error ≈ $1/\sqrt{36} \approx 0.17$ (vs. 0.29 with 12-month windows).
3. **Step size:** 12 months. Each fold advances the window by 1 year, providing overlapping test coverage.
4. **Fold count:** With 420 months total, 60-month train, 36-month test, 12-month step: approximately 27 folds.

For each parameter set, compute out-of-sample Sharpe ratio per fold. Report mean ± std across folds.

**Multiple-testing correction:** With 48 parameter combinations, the probability of selecting a spuriously best parameter set is non-trivial. Apply **White's Reality Check** (White, 2000, "A Reality Check for Data Snooping") via stationary bootstrap (Politis & Romano, 1994) with 1000 bootstrap replications. Report the Reality Check p-value for the best parameter set. If $p > 0.10$, no parameter set is significantly better than the benchmark (equal-weight top-5) and Strategy 3 should default to equal weight.

**Parameter selection:** Select the parameter set with the highest mean out-of-sample Sharpe that also passes the Reality Check ($p \leq 0.10$). Report full results table for all 48 combinations.

### 2.4 Transaction Cost Model

Transaction costs are **integrated into the core backtest loop**, not treated as a post-hoc sensitivity adjustment. Every trade (buy or sell) incurs a cost deducted from the portfolio value at the time of execution.

**Time-varying round-trip cost schedule:**

| Period | Round-Trip Cost (bps) | Rationale |
|--------|----------------------|-----------|
| 1990–2000 | 50 | Pre-decimalization: NYSE/NASDAQ tick sizes of $1/8 to $1/16 resulted in effective spreads of 25–100+ bps for mid-cap equities. 50 bps is conservative for mega-caps. (Ref: SEC "Report on the Practice of Preferencing", 1997; Jones, 2002, "A Century of Stock Market Liquidity and Trading Costs") |
| 2001–2004 | 20 | Decimalization (April 2001) compressed spreads to ~5-10 bps for large-caps; 20 bps round-trip includes market impact and commission. |
| 2005–present | 10 | Electronic trading, Reg NMS (2005), zero-commission brokerages (2019). 10 bps captures residual spread + minor slippage. |

**Implementation:** `backtest_engine.py` applies cost as: `trade_value × cost_bps / 20000` for each leg (half of round-trip cost per leg, so that a complete buy+sell cycle incurs the full round-trip cost of `cost_bps / 10000`). The cost schedule is defined in `config.py` and is configurable for sensitivity analysis.

**Sensitivity analysis:** In addition to the base case, run backtests at 0 bps (frictionless) and 2× the base schedule to bound the impact of cost assumptions on reported metrics.

### 2.5 Rebalancing Mechanics

**Contribution timing:** Monthly $1,000 contribution is added to the portfolio **at the rebalance date** (1st trading day of month), **before** new target weights are computed and trades are executed. This means contributions are immediately invested according to the new allocation.

**Fractional shares:** Allowed. This is a backtesting simplification — real execution would round to whole shares, but the dollar impact is negligible at the portfolio scale ($10K+ investing in mega-caps with share prices $50–$500).

**Rebalance execution:** All sells execute first (at close price), then all buys execute (at close price), then transaction costs are deducted. This avoids requiring margin or leverage to rebalance.

---

## 3. Performance Metrics

Institutional-grade metrics matching Bloomberg PORT, TradingView, and managed account reporting.

### 3.0 Return Methodology — TWR vs. MWR

The portfolio receives $1,000 monthly contributions. Standard return and risk-adjusted metrics assume no external cash flows. Without specifying the return methodology, metrics like CAGR and Sharpe ratio are undefined.

**Two return series are computed:**

1. **Time-Weighted Return (TWR):** Removes the effect of external cash flows. Computed via pure TWR: each month's sub-period return is calculated as $r_t = (V_{before\_cf,t} - V_{end,t-1}) / V_{end,t-1}$, where $V_{before\_cf,t}$ is the portfolio value marked-to-market *before* any cash flows (contributions) are applied. No Modified Dietz W-factor is needed because contributions arrive at period end with zero exposure during the sub-period. Sub-period returns are geometrically linked: $TWR = \prod(1 + r_t) - 1$. **Used for:** all risk-adjusted metrics (Sharpe, Sortino, Calmar, Information Ratio, Alpha, Beta, etc.) and benchmark comparison, as TWR isolates manager/strategy skill from capital timing.

2. **Money-Weighted Return (MWR / XIRR):** Reflects the actual investor experience including the timing and magnitude of contributions. Computed as the internal rate of return (IRR) that equates the present value of all cash flows (initial capital + monthly contributions) to the terminal portfolio value. Solved via `scipy.optimize.brentq` or `numpy.irr`. **Used for:** investor-experience reporting, dollar-weighted performance summary.

**Both TWR and MWR are reported in the dashboard and metrics tables.** Risk-adjusted metrics use TWR exclusively.

### 3.1 Return Metrics
| Metric | Formula/Method |
|--------|---------------|
| Total Return (TWR) | Geometrically linked pure TWR sub-period returns |
| Total Return (MWR) | XIRR of all cash flows |
| CAGR (TWR) | $(1 + TWR)^{1/Y} - 1$ |
| CAGR (MWR) | Annualized XIRR |
| MTD / QTD / YTD | Sub-period TWR returns |
| Rolling Returns | 1Y, 3Y, 5Y rolling annualized TWR |
| Monthly Return Distribution | Histogram + percentiles of TWR monthly sub-period returns |

### 3.2 Risk Metrics
| Metric | Formula/Method |
|--------|---------------|
| Annualized Volatility | $\sigma_{monthly} \times \sqrt{12}$ (assumes i.i.d. monthly returns — standard industry convention; note: violated by volatility clustering and autocorrelation in practice) |
| Max Drawdown | $\max_t \left( \frac{\text{Peak}(t) - V(t)}{\text{Peak}(t)} \right)$ computed on TWR equity curve $V(t) = \prod_{i=1}^{t}(1 + r_i)$ — **not** raw dollar equity (which would understate drawdowns due to contribution dampening) |
| Max Drawdown Duration | Calendar days peak-to-recovery |
| VaR (95%, 99%) | Historical percentile of TWR monthly returns. **Supplemented with:** Cornish-Fisher expansion VaR (adjusts for skewness and kurtosis) and bootstrap 95% CI on the VaR estimate (1000 replications). With ~420 monthly observations, 99% historical VaR is the 4th-worst month — the CI quantifies this estimation uncertainty. |
| CVaR / Expected Shortfall | Mean of returns below VaR threshold |
| Downside Deviation | $\sqrt{\frac{1}{N}\sum \min(r_i - r_f, 0)^2}$ |
| Ulcer Index | RMS of percentage drawdowns |

### 3.3 Risk-Adjusted Metrics
| Metric | Formula/Method |
|--------|---------------|
| Sharpe Ratio | $(R_p - R_f) / \sigma_p$, annualized, $R_f$ = 3-month T-bill |
| Sortino Ratio | $(R_p - R_f) / \sigma_{down}$ |
| Calmar Ratio | $CAGR / \|MaxDD\|$ |
| Omega Ratio | Discrete formulation: $\Omega(r_f) = \frac{\sum_i \max(r_i - r_f, 0)}{\sum_i \max(r_f - r_i, 0)}$ (equivalent to the integral form but unambiguous for implementation) |
| Information Ratio | $(R_p - R_b) / \text{TE}$ vs S&P 500 |
| Treynor Ratio | $(R_p - R_f) / \beta$ |

### 3.4 Benchmark-Relative Metrics
| Metric | Formula/Method |
|--------|---------------|
| Alpha (Jensen's) | $R_p - [R_f + \beta(R_m - R_f)]$ |
| Beta | $\text{Cov}(R_p, R_m) / \text{Var}(R_m)$ |
| Tracking Error | $\sigma(R_p - R_b)$, annualized |
| Up Capture Ratio | $\frac{\text{mean}(R_p | R_b > 0)}{\text{mean}(R_b | R_b > 0)}$ |
| Down Capture Ratio | $\frac{\text{mean}(R_p | R_b < 0)}{\text{mean}(R_b | R_b < 0)}$ |
| Hit Rate | % of months portfolio outperforms benchmark |

### 3.5 Portfolio Characteristics
| Metric | Description |
|--------|-------------|
| Turnover | Monthly average position change |
| Concentration (HHI) | Herfindahl-Hirschman Index of weights |
| # Holdings | Time series of position count |
| Sector Exposure | If data permits, sector breakdown over time |

### 3.6 Risk-Free Rate

Source from FRED (`DGS3MO` — 3-Month Treasury Constant Maturity Rate) via `fredapi` or `pandas_datareader`.

**Conversion to monthly rate:** `DGS3MO` is an annualized bond-equivalent yield expressed as a percentage. Convert to monthly continuously compounded rate:

$$r_{f,monthly} = (1 + \text{DGS3MO} / 100)^{1/12} - 1$$

**Not** $\text{DGS3MO} / 1200$ (simple division), which understates the monthly rate at high yield levels. For the daily rate used in modified Dietz sub-period calculations: $r_{f,daily} = (1 + \text{DGS3MO} / 100)^{1/252} - 1$.

Use the last available `DGS3MO` observation for each month as that month's risk-free rate.

---

## 4. Visualization

**Framework:** Streamlit dashboard. Single-page app with sidebar controls and tabbed layout.

**Design references:** Bloomberg PORT, FactSet, QuantConnect, GIPS standards, CFA Institute reporting guidelines, Tufte principles. See `docs/DASHBOARD_DESIGN_REFERENCE.md` for full best-practices documentation.

**Theme:** Forced light theme via `.streamlit/config.toml` (white background, near-black text, blue primary accent).

### 4.1 Controls (Sidebar)
- `st.date_input` date range picker (start date, end defaults to latest)
- Initial capital input (default $10,000)
- Monthly contribution input (default $1,000)
- Strategy selector (checkboxes for each strategy variant)
- Strategy 2 parameter: N slider (2–5)
- Strategy 3 parameters: N_candidates, k_lookback (or "use optimized")
- Benchmark toggles (Gold, NQ, ES, S&P 500) — sorted alphabetically

### 4.2 KPI Tiles Row
Five `st.metric()` cards displayed at the top of the page: CAGR, Sharpe, MaxDD, Sortino, Final Value. Each card shows the strategy value with benchmark delta. Custom CSS styling for metric cards.

### 4.3 Tabbed Layout

**Tab: Performance**
1. **Equity Curve + Drawdown** — Plotly subplots with shared x-axis (75/25 vertical split). Log scale toggle. Consistent color map: strategies use saturated colors, benchmarks use muted colors, applied via `FINANCIAL_LAYOUT` template.

**Tab: Risk**
2. **Rolling Sharpe** — 12-month rolling Sharpe ratio.
3. **Monthly Returns Heatmap** — Calendar heatmap (year × month) of returns.
4. **Return Distribution** — Histogram of monthly returns with VaR/CVaR markers.

**Tab: Comparison**
5. **Faceted Comparison Chart** — Replaces the prior mixed-scale grouped bar chart. Faceted by metric group for correct visual comparison.

**Tab: Details**
6. **Trade Log** — Full trade history table.
7. **Download Buttons** — Metrics CSV and equity curves CSV exports.
8. **Cost Asymmetry Caption** — Documents the transaction cost model applied.

### 4.4 Metrics Table
- Transposed layout: metrics as rows, strategies/benchmarks as columns
- Human-readable labels
- Grouped into 5 sections: Returns, Risk, Risk-Adjusted, Benchmark-Relative, Portfolio
- Conditional formatting (color-coded values)
- Benchmark self-relative metrics display "—" (not zero or NaN)

---

## 5. Implementation Architecture

```
MarketCapBacktest/
├── docs/
│   ├── IMPLEMENTATION_PLAN.md          ← this file
│   └── DASHBOARD_DESIGN_REFERENCE.md   # Best practices from Bloomberg, FactSet, QuantConnect, GIPS, CFA, Tufte
├── data/
│   └── delisted_monthly.csv            # Static data for delisted companies (609 rows)
├── scripts/
│   ├── config.py                       # Ticker universe, defaults, constants, cost schedule, grids
│   ├── data_fetcher.py                 # yfinance + FRED data acquisition, SHA-256 manifest
│   ├── market_cap_estimator.py         # Market cap ranking engine, BRK-A/B aggregation
│   ├── backtest_engine.py              # Core backtesting loop, TWR, XIRR cash flows, trade log
│   ├── strategies.py                   # Strategy 1/2/3 implementations
│   ├── metrics.py                      # All performance metric calculations
│   ├── grid_search.py                  # Walk-forward parameter optimization
│   ├── app.py                          # Streamlit dashboard (tabbed layout, KPI tiles, Plotly)
│   ├── test_phase2.py                  # 9/9 PASS
│   ├── test_phase3.py                  # 8/8 PASS
│   ├── test_phase4.py                  # 5/5 PASS
│   ├── test_phase5.py                  # Streamlit tests
│   └── test_phase6_audit.py            # 12/12 PASS — dashboard audit regression tests
├── .streamlit/
│   └── config.toml                     # Forced light theme configuration
├── results/
│   ├── grid_search_results.csv         # Parameter search output
│   ├── backtest_results.parquet        # Cached backtest runs
│   ├── data_manifest.json              # SHA-256 checksums of fetched data
│   └── figures/                        # Exported static charts
├── audits/
│   ├── audit_implementation_plan_20260317.md
│   ├── audit_phase1_20260317.md
│   ├── audit_phase2_20260317.md
│   ├── audit_phase3_20260317.md
│   ├── audit_phase4_20260317.md
│   └── audit_dashboard_consolidated_20260317.md  # 82 findings across 5 parallel audits
├── requirements.txt                    # Pinned dependencies (see §5.1)
```

### 5.1 Dependencies

`requirements.txt` with pinned versions for reproducibility:

```
yfinance==0.2.36
streamlit==1.41.1
plotly==5.24.1
pandas-datareader==0.10.0
fredapi==0.5.2
pandas==2.2.3
numpy==1.26.4
scipy==1.14.1
pyarrow==18.1.0
```

Pinned to latest stable as of 2026-03. Update only via explicit `pip-compile` or equivalent; never use unpinned `>=` in the lockfile.

### 5.2 Cross-Module Interfaces

Explicit function signatures for cross-module calls to prevent implementation drift:

```python
# data_fetcher.py
def fetch_price_data(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Returns DataFrame with columns: [date, ticker, open, high, low, close, adj_close, volume]"""

def fetch_splits(tickers: list[str]) -> pd.DataFrame:
    """Returns DataFrame with columns: [date, ticker, split_ratio]"""

def fetch_shares_outstanding(tickers: list[str]) -> pd.DataFrame:
    """Returns DataFrame with columns: [ticker, shares_outstanding]"""

def fetch_risk_free_rate(start: str, end: str) -> pd.Series:
    """Returns monthly risk-free rate series (DGS3MO converted via §3.6 formula)"""

def load_delisted_data() -> pd.DataFrame:
    """Returns DataFrame from data/delisted_monthly.csv: [date, ticker, close, shares_outstanding]"""

# market_cap_estimator.py
def estimate_market_caps(
    prices: pd.DataFrame,       # from fetch_price_data (unadjusted close used)
    splits: pd.DataFrame,       # from fetch_splits
    shares: pd.DataFrame,       # from fetch_shares_outstanding
    delisted: pd.DataFrame      # from load_delisted_data
) -> pd.DataFrame:
    """Returns DataFrame: [date, ticker, estimated_market_cap]"""

def rank_by_market_cap(market_caps: pd.DataFrame) -> pd.DataFrame:
    """Returns DataFrame: [date, ticker, market_cap, rank]"""

# strategies.py
def strategy_top1(rankings: pd.DataFrame, date: pd.Timestamp) -> dict[str, float]:
    """Returns {ticker: weight} for a single rebalance date"""

def strategy_topn_equal(rankings: pd.DataFrame, date: pd.Timestamp, n: int) -> dict[str, float]:
    """Returns {ticker: 1/n} for top-n equities"""

def strategy_momentum(
    rankings: pd.DataFrame, market_caps: pd.DataFrame,
    date: pd.Timestamp, n_candidates: int, k_lookback: int
) -> dict[str, float]:
    """Returns {ticker: weight} using log-momentum formulation"""

# backtest_engine.py
def run_backtest(
    strategy_fn: Callable,
    prices: pd.DataFrame,       # adj_close for returns
    rankings: pd.DataFrame,
    market_caps: pd.DataFrame,
    risk_free: pd.Series,
    initial_capital: float,
    monthly_contribution: float,
    cost_schedule: dict[str, float],  # {period_start: cost_bps}
    start_date: str,
    end_date: str
) -> BacktestResult:
    """Returns BacktestResult containing equity curve, trades, TWR series, cash flows"""

# metrics.py
def compute_metrics(
    twr_returns: pd.Series,     # monthly TWR sub-period returns
    cash_flows: pd.DataFrame,   # for MWR/XIRR calculation
    equity_curve: pd.Series,
    benchmark_returns: pd.Series,
    risk_free: pd.Series
) -> dict[str, float]:
    """Returns dict of all §3 metrics"""
```

### 5.3 Data Caching

- Cache raw price data to `results/` as parquet files (keyed by ticker + date range + **data fetch timestamp**).
- Recompute market cap rankings from cached prices on each run.
- Cache backtest results with hash of `(strategy_params, date_range, capital_config, data_hash)` as key. The `data_hash` is a SHA-256 of the input price data parquet file, ensuring cached results are invalidated when underlying data changes.
- Streamlit `@st.cache_data` for session-level memoization.

### 5.4 Reproducibility Artifacts

- `requirements.txt`: pinned dependencies (§5.1).
- `config.py`: all constants, ticker universe, cost schedule, parameter grids. No magic numbers in other modules.
- Data checksums: `data_fetcher.py` writes a `results/data_manifest.json` on each fetch containing `{filename: sha256_hash, fetch_date, ticker_count, date_range}`.
- Random seeds: grid search and bootstrap procedures use `numpy.random.default_rng(seed=42)` by default, configurable via `config.py`. Seed value 42 is arbitrary but fixed for reproducibility; results should be verified insensitive to seed choice by running with 3 alternative seeds.

---

## 6. Execution Sequence

| Phase | Task | Validation Gate |
|-------|------|-----------------|
| **Phase 1: Data** | Build `data_fetcher.py`, `market_cap_estimator.py`, `config.py`. Create `data/delisted_monthly.csv`. Implement split-adjusted shares outstanding method. | (1) Top-1 market cap matches historical record for ≥6 of 8 checkpoint years (1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025). (2) Publish error bounds (absolute $B, relative %) for top-5 at each checkpoint. (3) Delisted companies appear in rankings during active periods. (4) BRK-A/B aggregation produces correct total market cap. |
| **Phase 2: Backtest Core** | Build `backtest_engine.py`, `strategies.py`. Integrate transaction cost model. Implement contribution timing, fractional shares, delisting liquidation. | (1) Unit test: known 1-year period with manual calculation matches engine output within numerical precision ($0.01). (2) Transaction costs reduce returns relative to frictionless run. (3) Contribution adds $1,000 at each rebalance. (4) Strategy 3 all-negative-momentum fallback triggers correctly on synthetic data. |
| **Phase 3: Metrics** | Build `metrics.py`. Implement TWR (modified Dietz) and MWR (XIRR). | (1) Validate TWR Sharpe/MaxDD/CAGR against `quantstats` or `empyrical` on identical return series — tolerance: max(0.1% relative, 0.001 absolute) for Sharpe; max(0.1% relative, 0.01%) for CAGR and MaxDD. (2) MWR matches `numpy_financial.irr` on identical cash flows. (3) Risk-free rate conversion matches manual calculation. |
| **Phase 4: Grid Search** | Build `grid_search.py`. Implement sliding-window walk-forward, White's Reality Check. | (1) Walk-forward folds use strictly non-overlapping train/test periods. (2) No future data leaks into training window. (3) Reality Check p-value reported. (4) Full 48-combination results table generated. |
| **Phase 5: Visualization** | Build `app.py` Streamlit dashboard | All charts render; date picker dynamically updates all panels; TWR and MWR both displayed |
| **Phase 6: Audit** | Write validation docs in `audits/` | All gates passed; discrepancies documented with root cause. Market cap error bounds published. |
| **Phase 7: Dashboard Audit & Overhaul** | Full dashboard rewrite addressing audit findings. BRK ticker mapping fix, XIRR cash flow fix, MaxDD/Calmar/Ulcer confirmation, tabbed layout, KPI tiles, Plotly subplots, metrics table overhaul, trade log, CSV exports, light theme. 12/12 regression tests. | (1) `test_phase6_audit.py` 12/12 PASS. (2) BRK ranking maps to BRK-B for execution via `RANKING_TO_TRADE`. (3) XIRR uses full monthly cash flow series (not 2-point approximation). (4) MaxDD/Calmar/Ulcer confirmed using TWR equity curve. (5) Dashboard renders with tabbed layout, KPI tiles, consistent color map. |

---

## 7. Known Limitations & Mitigations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Split-adjusted shares outstanding ignores buybacks/issuances | Rank inaccuracy for equities with large buyback programs (AAPL, MSFT) or dilution (GE) | Quantified in §1.3 validation. Error bounds published per checkpoint year. Ranking overrides applied where validated ranking diverges. |
| Survivorship bias | Delisted companies absent from rankings in their active period | Mitigated via static CSV for 5 major delisted companies (§1.1). Remaining gap: mid-cap delistings not in universe; accepted as negligible for top-5/top-10 ranking. |
| Transaction costs | Overstates returns, especially Strategy 3 | **Integrated into core backtest loop** (see §2.4 below). Time-varying cost model applied to every trade. |
| Dividend reinvestment | Using adjusted close captures dividends for return calculation; unadjusted close used for market cap estimation | By design — dividends affect returns, not rankings. Price series usage is explicit: `adj_close` for returns, `close` for market cap. |
| yfinance data reliability | Occasional gaps, corporate action mishandling | Cross-validate against secondary source for outlier months (>50% monthly return). Forward-fill gaps ≤2 months; drop from ranking for longer gaps. |
| Slippage / price impact | Not modeled | Negligible for mega-cap equities at $10K–$500K portfolio scale. Stated assumption: zero slippage for the capital levels in this backtest. |
| Tax implications | Real after-tax returns will differ | Out of scope; noted in results. |
| Corporate actions (spin-offs, ticker changes, mergers) | Potential data discontinuities | `yfinance` adjusted data handles most cases. Explicit mapping in `config.py` for known events: FB→META, MOB→XOM (merger), ABT→ABBV (spin-off). `data_fetcher.py` resolves old tickers to current tickers via this mapping. |

---

## 8. Acceptance Criteria

1. Dashboard loads with default parameters in <10 seconds (excluding initial data fetch).
2. Equity curves for all 3 strategies + 4 benchmarks render correctly from any start date ≥ 1990-01. Benchmark curves start at their respective coverage dates.
3. All metrics in Section 3 computed and displayed, with both TWR and MWR variants.
4. Grid search for Strategy 3 completes in <5 minutes for full 48-combination parameter grid.
5. Audit documents confirm:
   - (a) Market cap rankings match historical record for ≥6 of 8 checkpoint years; error bounds published for all checkpoints.
   - (b) TWR-based Sharpe matches independent library within max(0.1% relative, 0.001 absolute). CAGR and MaxDD match within max(0.1% relative, 0.01%). Tolerance justified by: pure TWR sub-period linking introduces rounding at ~1e-4 level; independent libraries may use slightly different annualization conventions.
   - (c) No look-ahead bias in walk-forward validation; verified by asserting training window end < test window start for every fold.
   - (d) White's Reality Check p-value reported for Strategy 3 parameter selection.
6. Transaction costs integrated; sensitivity analysis at 0 bps and 2× base shows bounded impact.
7. `requirements.txt` present with pinned versions. `data_manifest.json` generated on data fetch.

---

## 9. Revision History

| Date | Revision | Audit Finding(s) Addressed |
|------|----------|---------------------------|
| 2026-03-17 | **v2.0 — Post-audit revision.** Applied all remediations from `audits/audit_implementation_plan_20260317.md`. | F1–F14 |
| 2026-03-17 | **v2.1 — Phase 7: Dashboard Audit & Overhaul.** Full dashboard rewrite. BRK ticker mapping (CALC-C4), XIRR cash flow fix (CALC-M3), MaxDD/Calmar/Ulcer TWR confirmation (Phase 3 M5/M6/M7), tabbed layout with KPI tiles, Plotly subplots, metrics table overhaul, trade log, CSV exports, light theme. Corrected TWR description from Modified Dietz to pure TWR (Phase 2 C1). Updated §4 Visualization, §5 Architecture, §6 Execution Sequence. 12/12 regression tests in `test_phase6_audit.py`. | Phase 2 C1, Phase 3 M5/M6/M7, CALC-C4, CALC-M3 |

**v2.1 changes applied:**
1. **§3.0:** Corrected TWR description from Modified Dietz with W-factor to pure TWR using `portfolio_value_before_cf`. Contributions arrive at period end with zero exposure, so no day-weighting is needed.
2. **§4 (Visualization):** Complete rewrite reflecting dashboard overhaul — KPI tiles row, tabbed layout (Performance/Risk/Comparison/Details), equity curve + drawdown as Plotly subplots with shared x-axis, transposed metrics table with conditional formatting, faceted comparison chart, trade log, CSV download buttons, `st.date_input`, alphabetically sorted benchmarks, consistent color map (saturated strategies, muted benchmarks), forced light theme via `.streamlit/config.toml`.
3. **§5 (Architecture):** Added `docs/DASHBOARD_DESIGN_REFERENCE.md`, `test_phase6_audit.py`, `.streamlit/config.toml`, `audit_dashboard_consolidated_20260317.md`. Updated file descriptions to reflect current state.
4. **§6 (Execution Sequence):** Added Phase 7 with validation gates.
5. **BRK Ticker Mapping (CALC-C4):** `backtest_engine.py` now includes `RANKING_TO_TRADE = {"BRK": "BRK-B"}` — market cap estimator aggregates BRK-A + BRK-B into "BRK" for ranking, trading engine maps to BRK-B for execution.
6. **XIRR Cash Flow Fix (CALC-M3):** Dashboard uses `result.cash_flows` (full monthly series from backtest engine) for strategy XIRR. Benchmarks construct complete monthly cash flow series. Replaces prior 2-point (initial + terminal) approximation.
7. **Phase 3 M5/M6/M7 Confirmed Fixed:** MaxDD, Calmar, and Ulcer Index use TWR equity via `twr_equity = (1 + returns).cumprod()` in `compute_metrics`. These items are now closed.

**v2.0 changes applied:**
1. **§1.1 (F1):** Replaced flawed `adj_close × shares_outstanding_current` formula with split-adjusted shares outstanding method using unadjusted close. Added data source evaluation table. Documented residual error from buybacks/issuances.
2. **§1.1 (F4, F6):** Added 5 delisted companies as static CSV with delisting handling spec. Added LLY, UNH, GILD, NFLX to pre-existing universe. Specified BRK-A/B market cap aggregation across share classes.
3. **§1.2 (F12):** Replaced generic fallback statement with explicit fallback chain per benchmark, coverage periods, and handling of unavailable periods.
4. **§1.3 (F1, F7):** Added market cap approximation error quantification protocol. Replaced arbitrary 5% missing-data threshold with data-derived formula. Defined acceptance threshold for ranking accuracy.
5. **§2 Strategy 3 (F5, F10):** Replaced $M_i/M_1 \times \Delta M_i$ with log-momentum formulation $\log(M_i(t)/M_i(t-k))$ to eliminate incumbent-leader bias. Added all-negative-momentum fallback to equal weight. Cited Jegadeesh & Titman (1993), Asness et al. (2013).
6. **§2 Walk-forward (F3, F7):** Replaced expanding window with 60-month sliding window. Increased test window from 12 to 36 months. Added White's Reality Check for multiple-testing correction. Removed arbitrary 0.3 Sharpe std threshold. Expanded parameter grids: N_candidates from 4 to 8 values, k_lookback from 4 to 6 values (48 total combinations).
7. **§2.4 (F8):** New section. Integrated time-varying transaction cost model into core backtest loop (50 bps pre-2001, 20 bps 2001-2004, 10 bps 2005+). Added sensitivity analysis at 0 bps and 2× base.
8. **§2.5 (F9):** New section. Specified rebalancing mechanics: contribution timing (before allocation), fractional shares (allowed), execution order (sells → buys → costs).
9. **§3.0 (F2):** New section. Defined TWR (modified Dietz) and MWR (XIRR) return methodologies. TWR used for all risk-adjusted metrics; MWR for investor-experience reporting.
10. **§3.2 (F7):** Added i.i.d. assumption note to annualized volatility. Added Cornish-Fisher VaR and bootstrap CI to supplement historical VaR.
11. **§3.3:** Replaced integral Omega ratio with discrete formulation.
12. **§3.6 (F11):** Specified risk-free rate conversion formula: $(1 + DGS3MO/100)^{1/12} - 1$.
13. **§5 (F13, F14):** Added `data/delisted_monthly.csv` to directory structure. Added `requirements.txt` with pinned versions. Defined cross-module function signatures (§5.2). Added data cache versioning via SHA-256 hash. Added reproducibility artifacts: data manifest, random seeds, lockfile.
14. **§6:** Updated all validation gates to reflect new methods, tolerances, and acceptance criteria.
15. **§7 (F8, F13):** Rewrote limitations table to reflect resolved mitigations. Added slippage assumption, corporate action handling via ticker mapping, explicit price series usage (adj_close for returns, close for market cap).
16. **§8 (F7):** Updated acceptance criteria with justified metric tolerances, Reality Check requirement, and reproducibility checks.
