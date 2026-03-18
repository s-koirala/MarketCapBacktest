# Deployment Readiness Audit

**Date:** 2026-03-18
**Scope:** Data leakage, security, calculation correctness, production readiness
**Target Environment:** Streamlit Community Cloud (public deployment)
**Auditor:** Claude Opus 4.6

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 3     |
| HIGH     | 7     |
| MEDIUM   | 12    |
| LOW      | 9     |
| **Total**| **31**|

---

## CRITICAL Findings

### SEC-1: Benchmark Equity Curve Calculation Applies Contribution Before Market Return (app.py)

**Severity:** CRITICAL
**File:** `scripts/app.py`, lines 372-378
**Description:**
The benchmark equity curve in `app.py` applies the monthly contribution *after* the return, which means the contribution earns zero return in its contribution month:
```python
new_val = prev * (1 + r) + monthly_contribution
```
However, `generate_comparison_excel.py` lines 140-145 uses the same formula. Both are consistent, but the strategy backtest engine (backtest_engine.py) marks to market *before* contribution, then adds contribution, then rebalances. This means the strategy's contribution gets partially invested intramonth (via rebalancing), while the benchmark's contribution sits in cash for the month. This creates a systematic bias favoring strategies over benchmarks during bull markets and penalizing them during bear markets.

**Recommendation:** Document the asymmetry explicitly, or adjust the benchmark equity simulation to match the strategy's contribution timing (contribution added before rebalancing, so it participates in that month's return via allocation). This is already partially documented with the cost asymmetry notice (line 581-582) but the contribution-timing asymmetry is not mentioned.

---

### LEAK-1: Market Cap Estimation Uses Current Shares Outstanding Without Temporal Bounds (market_cap_estimator.py, data_fetcher.py)

**Severity:** CRITICAL
**File:** `scripts/data_fetcher.py` lines 187-209, `scripts/market_cap_estimator.py` lines 110-191
**Description:**
`fetch_shares_outstanding()` fetches the *current* (as of runtime) `sharesOutstanding` from yfinance's `.info` property. This single point-in-time value is then divided by cumulative split factors to estimate historical shares. The formula:

```
shares_backward(t) = shares_current / cum_split_factor(t -> now)
```

This only adjusts for splits, NOT for:
- Share buybacks (e.g., AAPL has repurchased ~40% of shares since 2013)
- Secondary offerings / dilution
- Mergers and spin-offs changing share count

The CLAUDE.md acknowledges this (Key Design Decision #1) and says error is "quantified at 8 checkpoint years," but for public deployment the magnitude of this error should be clearly communicated to users. A company like AAPL with massive buybacks will have its historical market cap systematically overestimated (fewer shares today than in 2015), potentially causing incorrect historical rankings.

**Recommendation:** Add a prominent disclaimer in the dashboard UI explaining that market cap estimates are approximate due to buyback/issuance effects. Consider showing the validation error table from `compute_estimation_error()` in the dashboard for transparency.

---

### SEC-2: No Rate Limiting or Error Recovery for yfinance API on Cloud (data_fetcher.py)

**Severity:** CRITICAL
**File:** `scripts/data_fetcher.py` lines 58-137
**Description:**
On Streamlit Community Cloud, the app calls `fetch_all(use_cache=True)` at startup. If cached parquet files don't exist in the `results/` directory (which they won't on first cloud deploy unless committed to the repo), the app will attempt to fetch data for 48+ tickers from yfinance. Problems:

1. **No retry logic** -- a single batch failure silently drops those tickers (line 91-92: `continue`).
2. **Rate limiting** -- yfinance may throttle/block Streamlit Cloud IPs. The 1-second pause between batches (line 129) is insufficient for shared cloud infrastructure.
3. **FRED dependency** -- `fetch_risk_free_rate()` requires `pandas_datareader` which may not be in `requirements.txt`, and falls back to `^IRX` via yfinance, then falls back to zeros. Silent zero risk-free rate corrupts all risk-adjusted metrics.
4. **No timeout** -- `yf.download()` can hang indefinitely on network issues.
5. **Memory** -- Fetching all tickers concurrently in cloud's limited RAM (1GB on Community Cloud free tier) could cause OOM.

**Recommendation:**
- Commit pre-built parquet cache files to the repo so cloud deployment never needs to fetch live data.
- Add exponential backoff retry logic.
- Add `yf.download(..., timeout=30)` if supported by the yfinance version.
- Add a clear error message in `app.py` if data loading fails, directing users to the data preparation step.

---

## HIGH Findings

### CALC-1: Benchmark Returns Are Gross While Strategy Returns Are Net (Systematic Comparison Bias)

**Severity:** HIGH
**File:** `scripts/app.py` lines 346-354, `scripts/backtest_engine.py` lines 271-336
**Description:**
Strategy returns include time-varying transaction costs (10-50 bps round-trip), but benchmark returns are computed as simple `pct_change()` on adj_close prices -- i.e., gross returns with zero transaction costs. All comparative metrics (alpha, beta, information ratio, hit rate, capture ratios) are computed against these gross benchmark returns.

For a 35-year backtest, even 10 bps/month of cost drag compounds significantly. The caption on line 581-582 mentions this but only in the Performance tab. The full metrics comparison table and KPI deltas (e.g., "vs S&P") do not carry this caveat.

This is documented as item D-C1 in CLAUDE.md "Nice to Have" but for public deployment it is a HIGH issue since users will draw incorrect conclusions about strategy alpha.

**Recommendation:** Either (a) apply a cost estimate to benchmark returns for fair comparison, or (b) add prominent warnings next to every comparative metric indicating the asymmetry.

---

### SEC-3: Streamlit `unsafe_allow_html=True` with Static Content (app.py)

**Severity:** HIGH
**File:** `scripts/app.py` line 171
**Description:**
`st.markdown(..., unsafe_allow_html=True)` is used for custom CSS styling. While the HTML content is static (no user input), this disables Streamlit's XSS protection for this markdown block. Currently safe because the CSS string is hardcoded, but if any dynamic content is ever concatenated into this string, it would create an XSS vulnerability.

**Recommendation:** This is acceptable for static CSS but should be documented as a security-sensitive pattern. Add a comment warning future developers not to interpolate user input into this block.

---

### CALC-2: Downside Deviation Uses ddof=1 While Plan Specifies ddof=0 (metrics.py)

**Severity:** HIGH
**File:** `scripts/metrics.py` lines 257-274
**Description:**
The `compute_downside_deviation()` function uses `n - 1` (Bessel's correction / ddof=1) in the denominator, while the implementation plan specifies `1/N` (population divisor). The docstring acknowledges this discrepancy and states it's for "consistency with Sharpe ratio's use of std(ddof=1)." However, this is a non-standard convention for downside deviation. The Sortino ratio literature (Sortino & van der Meer, 1991) uses `1/N` (population divisor).

For N=420 months, the impact is ~0.1%, which is within tolerance. But for shorter periods (e.g., user selects 2020-2026 = 72 months), the effect grows to ~0.7%.

**Recommendation:** Document the convention explicitly in the dashboard. Alternatively, use ddof=0 for downside deviation to match standard Sortino ratio literature, accepting the inconsistency with Sharpe's ddof=1.

---

### LEAK-2: Grid Search Computes Full Return Series Before Fold Slicing (grid_search.py)

**Severity:** HIGH
**File:** `scripts/grid_search.py` lines 131-196, 437-440
**Description:**
`compute_strategy3_returns()` is called once with ALL dates (line 438-440), producing a single full-period return series. This series is then sliced by fold boundaries via `compute_oos_sharpe()`. The return computation itself uses `strategy_momentum()` which accesses `market_caps` at `prev_date` for weights -- this is correct and avoids look-ahead within each month.

However, the `ticker_returns = price_pivot.pct_change()` on line 161 computes returns for ALL periods including future test periods. Since the strategy function only accesses `rankings` and `market_caps` at `prev_date` (not the returns matrix), this is NOT a look-ahead bug. The returns matrix is simply a lookup table indexed by date.

The training period is documented as a "temporal buffer" (grid_search.py docstring, line 396) not used for parameter fitting. This is correct for the non-parametric momentum strategy.

**Status:** Confirmed NO look-ahead bias. The fold generation (line 86) has an assertion `train_end < test_start`. Weights use t-1 data, returns use t data. The architecture is sound.

**Recommendation:** No code change needed. However, add a docstring to `compute_strategy3_returns()` explicitly stating that the full-period computation is safe because the function only accesses causal data at each timestep.

---

### SEC-4: Session State Memory Accumulation (app.py)

**Severity:** HIGH
**File:** `scripts/app.py` lines 179-202, 310-330
**Description:**
`@st.cache_data` is used for both `load_data()` and `run_cached_backtest()`. On Streamlit Community Cloud with multiple concurrent users:

1. Each unique combination of parameters creates a new cache entry. With configurable start_date, end_date, initial_capital, monthly_contribution, s2_n, s3_n, s3_k, the cache key space is enormous.
2. `BacktestResult` objects contain full DataFrames (equity_curve, twr_returns, trades, holdings_history). For a 35-year backtest, `holdings_history` alone can be thousands of rows per strategy.
3. Cache eviction is handled by Streamlit's LRU mechanism, but the default max size may be insufficient.

On the free Community Cloud tier (1GB RAM), this could lead to OOM crashes with multiple concurrent users.

**Recommendation:**
- Add `max_entries` parameter to `@st.cache_data` decorators to limit cache size.
- Consider using `ttl` parameter to expire stale cache entries.
- Profile memory usage of a single backtest run to estimate concurrent user capacity.

---

### CALC-3: generate_comparison_excel.py Hardcodes Strategy 3 Parameters (generate_comparison_excel.py)

**Severity:** HIGH
**File:** `scripts/generate_comparison_excel.py` line 33
**Description:**
`make_momentum_fn(5, 6)` is hardcoded at module level. If the grid search selects different optimal parameters, the Excel comparison will use stale/wrong parameters. The dashboard (`app.py`) correctly reads from `grid_search_results.csv` for optimized parameters.

**Recommendation:** Read the selected parameters from `grid_search_results.csv` (same logic as app.py lines 250-263) or accept and document that the Excel generator uses fixed default parameters.

---

### SEC-5: `print()` Statements in Production Code

**Severity:** HIGH
**File:** `scripts/backtest_engine.py` lines 497-507, `scripts/generate_comparison_excel.py` lines 672-746
**Description:**
Multiple `print()` statements remain in `__main__` blocks and in `generate_comparison_excel.py`'s `main()` function. While `__main__` blocks don't execute when imported, the `generate_comparison_excel.py` prints could leak information if run on the server.

More importantly, `backtest_engine.py` uses `logger.info()` and `logger.debug()` correctly within the core loop, but the CLI section uses `print()`. In a cloud environment, print output goes to container logs which may be accessible.

**Recommendation:** Replace all `print()` with `logger.info()` calls. Configure logging level appropriately for cloud deployment.

---

## MEDIUM Findings

### CALC-4: XIRR 365.25 Day Convention Creates Small Systematic Bias (metrics.py)

**Severity:** MEDIUM
**File:** `scripts/metrics.py` lines 60-104
**Description:**
The XIRR implementation uses 365.25 days/year (line 87). This is documented as standard XIRR convention with ~2 bps bias. The `brentq` solver bracket of [-0.99, 10.0] (line 94) caps the search at 1000% annualized return. For crypto-like returns this could fail, but for equity portfolios this is adequate.

The wider fallback bracket [-0.9999, 100.0] (line 99) handles edge cases.

**Recommendation:** Acceptable for production. No change needed.

---

### CALC-5: Rolling Returns Use `.rolling().apply(lambda x: x.prod())` Instead of Vectorized (metrics.py)

**Severity:** MEDIUM
**File:** `scripts/metrics.py` lines 128-133
**Description:**
The rolling return calculation at line 128-129 uses a lambda with `raw=True`, which is reasonably efficient. However, for 420+ months * multiple series, a fully vectorized approach using `np.exp(np.log1p(returns).rolling(w).sum())` would be faster.

**Recommendation:** Low priority. Current implementation is correct; optimize only if performance is an issue.

---

### CALC-6: Capture Ratios Use Arithmetic Mean (Not Geometric) (metrics.py)

**Severity:** MEDIUM
**File:** `scripts/metrics.py` lines 426-449
**Description:**
Up/down capture ratios use arithmetic mean of monthly returns:
```python
up_capture = up_months["port"].mean() / up_months["bench"].mean()
```
The geometric convention (used by Morningstar) would be:
```python
up_capture = ((1 + up_months["port"]).prod()) ** (1/len(up_months)) / ((1 + up_months["bench"]).prod()) ** (1/len(up_months))
```
Both conventions exist in practice. This is documented as item CALC-M8 in CLAUDE.md.

**Recommendation:** Document the convention (arithmetic) in the dashboard metric tooltip or footnote.

---

### CALC-7: CVaR Uses Inclusive Inequality (metrics.py)

**Severity:** MEDIUM
**File:** `scripts/metrics.py` lines 249-254
**Description:**
`compute_cvar()` filters with `monthly_returns <= var` (inclusive). Some implementations use strict `<`. For discrete distributions with many observations at exactly the VaR quantile, this can slightly overcount the tail. For continuous monthly returns, the practical difference is negligible.

**Recommendation:** Acceptable. Document convention.

---

### CALC-8: Cornish-Fisher VaR Uses Sample Skewness/Kurtosis (metrics.py)

**Severity:** MEDIUM
**File:** `scripts/metrics.py` lines 220-230
**Description:**
`stats.skew()` and `stats.kurtosis()` use sample estimates by default (bias=True in older scipy, bias correction varies by version). For shorter periods (user selects 2020-2026 = 72 months), sample skewness and kurtosis estimates have high variance, making the Cornish-Fisher adjustment unreliable.

**Recommendation:** Add a minimum sample size check (e.g., N >= 100) before applying Cornish-Fisher; fall back to historical VaR for smaller samples.

---

### SEC-6: No Input Validation on Date Range (app.py)

**Severity:** MEDIUM
**File:** `scripts/app.py` lines 220-232
**Description:**
`st.date_input` provides min/max bounds (1990-01-01 to 2030-12-31), which prevents extreme values. However, if `start_date > end_date`, the backtest engine will return an empty date list and raise `ValueError("No rebalance dates in the specified range.")` on backtest_engine.py line 190. The `app.py` wraps data loading in try/except (line 279-284) but does not validate date ordering before running backtests.

**Recommendation:** Add validation: `if start_date_input >= end_date_input: st.error(...); st.stop()`.

---

### LEAK-3: Delisted CSV Contains No Sensitive Data (CLEAN)

**Severity:** MEDIUM (informational)
**File:** `data/delisted_monthly.csv`
**Description:**
Reviewed all 611 lines. Contains only: ticker, date, close (price), shares_outstanding. All data is publicly available market data for 5 delisted companies (ENRNQ, WCOEQ, LEH, GMGMQ, MOB). No PII, no credentials, no proprietary data.

**Status:** CLEAN. Safe for public deployment.

---

### SEC-7: File Paths Use Relative Resolution -- No Hardcoded User Paths

**Severity:** MEDIUM (informational)
**File:** `scripts/config.py` lines 13-17
**Description:**
All paths use `Path(__file__).resolve().parent.parent`, producing relative paths from the script location. No hardcoded Windows usernames or absolute paths exist in any Python file.

**Status:** CLEAN. Safe for public deployment.

---

### CALC-9: Strategy Momentum Lookback Date Uses DateOffset (strategies.py)

**Severity:** MEDIUM
**File:** `scripts/strategies.py` lines 128, 136-147
**Description:**
`lookback_date = date - pd.DateOffset(months=k_lookback)` computes the target lookback date, then finds the closest available date `<= lookback_date` (line 136-147). This is correct but means the actual lookback period can vary by a few days depending on month lengths. For k=1, the lookback is approximately 1 month; for k=12, approximately 12 months. The `past_dates.max()` selection ensures no future data is used.

**Recommendation:** Acceptable. The approach is standard for monthly-frequency strategies.

---

### CALC-10: Backtest Engine Uses adj_close for Position Valuation (backtest_engine.py)

**Severity:** MEDIUM
**File:** `scripts/backtest_engine.py` lines 171-178
**Description:**
The engine uses `adj_close` (split- and dividend-adjusted) for position valuation and return tracking (line 172-174), but uses unadjusted `close` for delisting liquidation (line 175-178). The market_cap_estimator uses unadjusted `close` for market cap calculation (to avoid double-counting splits with the split factor).

This is correct: adj_close properly accounts for total return including dividends for portfolio valuation, while unadjusted close is appropriate for market cap estimation (where you need the actual traded price times shares).

**Status:** Confirmed correct. No change needed.

---

### SEC-8: `@st.cache_data` With Unhashable Function Arguments (app.py)

**Severity:** MEDIUM
**File:** `scripts/app.py` lines 190-202
**Description:**
`run_cached_backtest()` accepts `_strategy_fn` (a closure) and `_prices` (a DataFrame) as underscore-prefixed parameters. Streamlit treats underscore-prefixed parameters as unhashable and excludes them from the cache key. This means if the strategy function changes but other parameters stay the same, the cache will return stale results.

In practice, strategy functions are created fresh on each rerun via `make_top1_fn()` etc., and the other parameters (initial_capital, monthly_contribution, etc.) form a sufficient cache key. But if a user toggles between Strategy 1 and Strategy 3 with identical capital parameters, the cache could theoretically return wrong results.

However, `strategy_name` IS part of the cache key and differs between strategies, so this is actually safe.

**Status:** Safe due to `strategy_name` in cache key. But fragile -- if someone renames strategies identically, caching would break.

**Recommendation:** Add a comment explaining why `strategy_name` must be unique per strategy for cache correctness.

---

### CALC-11: Benchmark Equity Curve in app.py Does Not Include Initial Capital in First Period (app.py)

**Severity:** MEDIUM
**File:** `scripts/app.py` lines 372-378
**Description:**
The benchmark equity construction starts with `values = [initial_capital]` and iterates:
```python
for r in bret.values:
    prev = values[-1]
    new_val = prev * (1 + r) + monthly_contribution
    values.append(new_val)
bench_eq = pd.Series(values[1:], index=bret.index, name=bname)
```
The first period applies the return to `initial_capital` and adds `monthly_contribution`, but `generate_comparison_excel.py` line 141 adds `contrib = 1000.0 if j > 0 else 0.0` -- no contribution in the first period. The dashboard code adds the contribution every period including the first return period, creating a systematic difference between the dashboard and the Excel output.

**Recommendation:** Align the contribution timing between `app.py` and `generate_comparison_excel.py`. The Excel version's approach (no contribution in month 0) matches the strategy backtest engine's approach (line 224: `contribution = monthly_contribution if i > 0 else 0.0`).

---

## LOW Findings

### QUAL-1: No Logging Configuration for Cloud Deployment

**Severity:** LOW
**File:** All Python files
**Description:**
All modules use `logging.getLogger(__name__)` but only configure logging in `__main__` blocks via `logging.basicConfig()`. When run under Streamlit, no logging configuration is set, so all `logger.info/warning/error` calls are silently dropped (default WARNING level). This means cache validation warnings, data quality issues, and delist liquidation events are invisible to the cloud operator.

**Recommendation:** Add logging configuration in `app.py` (e.g., `logging.basicConfig(level=logging.INFO)`) or use Streamlit's built-in logging integration.

---

### QUAL-2: FutureWarning from groupby.apply (metrics.py)

**Severity:** LOW
**File:** `scripts/metrics.py` line 139
**Description:**
`(1 + monthly_returns).groupby(monthly_returns.index.year).prod()` may trigger a pandas FutureWarning about the default value of `group_keys` in newer pandas versions. This is documented as Phase 3 L3 in CLAUDE.md.

**Recommendation:** Suppress or fix before deployment to avoid warning messages in cloud logs.

---

### QUAL-3: `generate_comparison_excel.py` Creates Strategies at Module Level

**Severity:** LOW
**File:** `scripts/generate_comparison_excel.py` lines 31-34
**Description:**
Strategy functions are created at import time via `make_momentum_fn(5, 6)` at module scope. If this module is imported (not just run as `__main__`), it triggers imports of `strategies.py` and potentially `backtest_engine.py`. This is a minor concern since the module is only used as a standalone script.

**Recommendation:** Move strategy creation inside `main()` to avoid side effects on import.

---

### QUAL-4: No `requirements.txt` Verification

**Severity:** LOW
**File:** (Not in scope but referenced)
**Description:**
The audit scope doesn't include `requirements.txt`, but the code imports `openpyxl` (generate_comparison_excel.py), `pandas_datareader` (data_fetcher.py), `scipy` (metrics.py), `plotly` (app.py), and `yfinance`. All must be pinned in requirements.txt for reproducible cloud deployment.

**Recommendation:** Verify requirements.txt includes all transitive dependencies with pinned versions.

---

### QUAL-5: Streamlit Config File Location

**Severity:** LOW
**File:** `scripts/.streamlit/config.toml` (referenced in CLAUDE.md)
**Description:**
The `.streamlit/config.toml` is in `scripts/.streamlit/`, which is correct if Streamlit is launched from the `scripts/` directory. On Streamlit Community Cloud, the app is typically launched from the repo root, which would look for `.streamlit/config.toml` at the root level.

**Recommendation:** Verify the config.toml location matches the Streamlit Cloud app configuration. May need to be at repo root level.

---

### QUAL-6: No Health Check Endpoint

**Severity:** LOW
**File:** `scripts/app.py`
**Description:**
There is no lightweight health check or status indicator in the dashboard. If data loading fails silently (e.g., cache corruption), the user sees `st.stop()` with an error message but no diagnostic information.

**Recommendation:** Add a sidebar status indicator showing data freshness (last fetch date from manifest) and cache health.

---

### QUAL-7: DataFrame `.iterrows()` Used in Excel Generator

**Severity:** LOW
**File:** `scripts/generate_comparison_excel.py` lines 382, 451, 512
**Description:**
`.iterrows()` is used extensively in `write_holdings_sheet()` and `write_period_sheet()`. For the data volumes in this application (hundreds to low thousands of rows), this is acceptable. For significantly larger datasets it would be slow.

**Recommendation:** No change needed for current scale.

---

### QUAL-8: Dead Import in app.py

**Severity:** LOW
**File:** `scripts/app.py` line 15
**Description:**
`import plotly.express as px` is imported but only used once (line 600-603 for `px.imshow`). Minor dead-weight import but not harmful.

**Recommendation:** No action needed.

---

### QUAL-9: Thread Safety of Mutable Module-Level Dicts (app.py)

**Severity:** LOW
**File:** `scripts/app.py` lines 64, 310, 360-363, 416
**Description:**
Module-level mutable dicts (`COLOR_MAP`, `all_twr`, `all_equity`, `is_benchmark`, `all_metrics`) are populated during each Streamlit script rerun. Streamlit reruns scripts top-to-bottom for each user interaction, and Streamlit handles user isolation via separate script contexts. These mutable dicts are rebuilt each run and are not shared across users.

**Status:** Safe under Streamlit's execution model. Each user gets an independent script execution context.

---

## Findings NOT Present (Verified Clean)

| Check | Status |
|-------|--------|
| Hardcoded API keys / tokens | CLEAN -- no API keys found anywhere |
| Hardcoded credentials | CLEAN -- yfinance and FRED use public unauthenticated APIs |
| Secrets in config.py | CLEAN -- only constants, no secrets |
| Windows usernames in paths | CLEAN -- all paths relative via `Path(__file__)` |
| Data written to public locations | CLEAN -- writes only to `results/` directory |
| CORS/XSRF misconfig | N/A -- Streamlit handles this internally |
| User input not sanitized | CLEAN -- all inputs via Streamlit widgets (bounded) |
| Survivorship bias | HANDLED -- 5 delisted tickers with 609 rows of historical data |
| TWR formula correctness | CORRECT -- `r = (V_before_cf - V_prev) / V_prev` (pure TWR) |
| Grid search look-ahead | CORRECT -- weights at t-1, returns at t; assertion on fold boundaries |
| Transaction cost formula | CORRECT -- `cost_bps / 20000` per leg (half round-trip) |
| Market cap formula | CORRECT -- `close(t) * shares_current / cum_split_factor(t->now)` using unadjusted close |
| Sharpe formula | CORRECT -- `(mean_excess / std_excess) * sqrt(12)`, ddof=1 |
| Sortino formula | CORRECT -- `(mean_excess * 12) / (downside_dev * sqrt(12))` |
| Calmar formula | CORRECT -- `CAGR / |MaxDD|`, uses TWR equity for MaxDD |

---

## Recommendations for Deployment

### Must-Do Before Deploy

1. **Commit cached parquet files** to the repo so cloud deployment doesn't need live API access (SEC-2).
2. **Verify `.streamlit/config.toml` location** matches Cloud deployment expectations (QUAL-5).
3. **Add start > end date validation** in sidebar (SEC-6).
4. **Fix benchmark equity contribution timing** in app.py to skip first month, matching backtest engine and Excel generator (CALC-11).

### Should-Do

5. Add market cap estimation accuracy disclaimer to the dashboard UI (LEAK-1).
6. Add cost asymmetry warning to the Comparison tab metrics table, not just Performance tab (CALC-1).
7. Configure logging for cloud environment (QUAL-1).
8. Add `max_entries` to `@st.cache_data` decorators (SEC-4).

### Nice-to-Have

9. Add Cornish-Fisher minimum sample size check (CALC-8).
10. Document capture ratio convention in metric tooltips (CALC-6).
11. Replace remaining `print()` with logger calls (SEC-5).

---

*End of audit.*
