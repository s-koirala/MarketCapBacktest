# Audit: IMPLEMENTATION_PLAN.md

**Date:** 2026-03-17
**Scope:** Critical review of `docs/IMPLEMENTATION_PLAN.md` for methodological correctness, parameter justification, data integrity risks, statistical validity, and implementation feasibility.
**Status:** Pre-implementation (all directories empty; plan-only stage)

---

## 1. DATA METHODOLOGY

### 1.1 Market Cap Approximation — CRITICAL FLAW

**Claim (§1.1):** `market_cap(t) ≈ adj_close(t) × shares_outstanding_current`

**Problem:** This is mathematically incorrect and the plan's own justification is wrong.

- **Adjusted close already incorporates split adjustments.** Multiplying `adj_close(t)` by `shares_outstanding_current` double-counts split adjustments. If a stock has had a 4:1 split, `adj_close` divides historical prices by 4, and `shares_outstanding_current` is 4× the historical count. Result: market cap estimate is correct *only* for the most recent date and systematically **understates** historical market cap for stocks with net share issuance and **distorts** rankings for stocks with differential split/issuance histories.
- **Correct formulation:** `market_cap(t) = close(t) × shares_outstanding(t)`. Since historical shares outstanding is unavailable via `yfinance`, the usable approximation is `market_cap(t) = close(t) × shares_outstanding_current / split_adjustment_factor(t)`. Alternatively: `adj_close(t) × shares_outstanding_current` *does* work **if and only if** the only corporate actions are splits (no buybacks, no issuances). The plan acknowledges buybacks/issuances exist but dismisses the impact without quantification.
- **Quantified impact:** Apple bought back ~$600B in shares 2013–2025 (~40% reduction in share count). GE underwent massive dilution then a 1:8 reverse split. Using current shares outstanding for GE in 2000 produces a market cap estimate roughly 1/8th of actual. This is not a rounding error — it produces **wrong rankings**.

**Recommendation:**
1. Use `unadjusted close × shares_outstanding_current`, then apply only split adjustment factors (available via `yfinance` `.splits` history) to normalize shares outstanding backward. This isolates splits from buybacks/issuances.
2. Alternatively, source historical market cap from a dataset that tracks it directly (e.g., Compustat via WRDS, Sharadar/Quandl, or Tiingo fundamentals). The plan should evaluate data source options rather than defaulting to a flawed free approximation.
3. At minimum, validate the approximation error by computing estimated vs. known market cap for the top-5 equities at each checkpoint year. Publish error bounds.

**Severity:** HIGH — Invalidates ranking accuracy, which is the foundational input to all three strategies.

### 1.2 Survivorship Bias — INCOMPLETE MITIGATION

**Claim (§7):** "Include known large-cap delistings with available price history up to delisting date."

**Problems:**
- The ticker universe in §1.1 contains **zero** delisted companies. Enron (2001, top-10 by market cap), WorldCom (2002), Lehman Brothers (2008, ~$45B market cap), General Motors (2009 pre-bankruptcy), Citigroup (near-delisting 2009 via reverse split) are listed as mitigations but none appear in the ticker list.
- `yfinance` does not reliably serve data for delisted tickers. Enron (`ENRNQ`), WorldCom (`WCOEQ`), old GM (`GMGMQ`) — these return empty or error from `yfinance`.
- Without these companies, Strategy 1 may never select them even though they were top-1 or top-5 by market cap in their era, producing historically inaccurate portfolio compositions.

**Recommendation:**
1. Source delisted company price data from an alternative provider or embed a static CSV of monthly closes for known large-cap delistings.
2. Explicitly enumerate delisted tickers in the universe table with IPO and delisting dates.
3. Handle delisting events in `backtest_engine.py`: forced liquidation at last traded price, reallocation at next rebalance.

**Severity:** MEDIUM-HIGH — Affects ranking accuracy in specific periods (2001-2002, 2008-2009) and introduces look-ahead survivorship bias.

### 1.3 Ticker Universe Completeness

**Missing from universe (were top-10 US market cap at some point 1990–2025):**
- Exxon Mobil pre-merger as Mobil (MOB)
- Cisco was #1 market cap briefly in 2000 — correctly included
- Walmart, P&G — correctly included
- **Berkshire Hathaway Class A (BRK-A):** BRK-B is listed (IPO 1996) but BRK-A has been a top-5 market cap stock since the early 1990s. BRK-A data goes back further and represents the actual market cap better (B shares are a small fraction of total capitalization, but `yfinance` market cap for BRK-B alone understates Berkshire's total market cap).
- **Eli Lilly (LLY):** Top-10 market cap 2023-2025; absent from universe.
- **Taiwan Semiconductor (TSM):** Top-10 global market cap; if US-listed ADRs are in scope, should be included.
- **Broadcom (AVGO):** Listed as entering in 2015 but was #8 US market cap by 2024.

**Recommendation:** The universe should be constructed from a historical constituents list (e.g., S&P 500 historical membership) rather than hand-curated. At minimum, add LLY and verify BRK market cap calculation accounts for both share classes.

**Severity:** MEDIUM — Missing equities can cause incorrect rankings, especially in recent years.

### 1.4 Benchmark Data Gaps

- `GC=F` (gold futures) continuous contract via `yfinance` has known data quality issues pre-2000.
- `NQ=F` (Nasdaq futures) launched 1999; pre-1999 benchmark comparison is undefined.
- Plan does not specify how benchmark comparisons handle periods where benchmark data is unavailable.

**Recommendation:** Define explicit fallback chain and document coverage periods. For pre-1999 NQ, use `^NDX` (Nasdaq-100 index). For pre-2004 gold, use `GC=F` with documented caveats or source from FRED (`GOLDAMGBD228NLBM`).

**Severity:** LOW — Affects benchmark display, not strategy logic.

---

## 2. STRATEGY METHODOLOGY

### 2.1 Strategy 3: Momentum Score — MATHEMATICAL REVIEW

**Formula (§2):**
$$s_i(t) = \frac{M_i(t)}{M_1(t)} \times \Delta M_i(t)$$

**Issues:**

1. **Relative size × momentum conflation.** The score multiplies relative market cap by momentum. This means a $3T company with 5% momentum scores identically to a $300B company with 50% momentum. The plan's stated goal is to "capture momentum of rising challengers" — but the relative-size multiplier suppresses small-cap challengers. A pure momentum ranking or a log-ratio formulation would better capture the intended signal.

2. **Rank-1 self-reference.** When $i = 1$ (the current #1), $M_i(t)/M_1(t) = 1$, so $s_1(t) = \Delta M_1(t)$. For challengers, $M_i(t)/M_1(t) < 1$ dampens their score. This systematically **favors the incumbent leader**, directly contradicting the stated "anticipatory" intent.

3. **Zero-weight redistribution.** "Negative-momentum equities receive zero weight; their allocation redistributes pro-rata." This creates an unstated regime dependency: in broad market downturns where all top-N have negative momentum, the denominator is zero. The plan does not handle this edge case.

**Recommendation:**
1. Consider alternative formulations:
   - Pure momentum ranking: $w_i \propto \max(\Delta M_i(t), 0)$
   - Log-ratio momentum: $s_i(t) = \log(M_i(t)/M_i(t-k))$
   - Rank-weighted momentum: weight by momentum rank rather than raw values
2. Add explicit handling for all-negative-momentum periods (e.g., fall back to equal weight or hold cash).
3. Document the mathematical rationale for the chosen formulation with reference to momentum factor literature (Jegadeesh & Titman 1993; Asness et al. 2013 "Value and Momentum Everywhere").

**Severity:** MEDIUM — Strategy may not express intended signal; edge cases unhandled.

### 2.2 Strategy 3: Walk-Forward Validation

**Claim (§2):** "Walk-forward validation (train on expanding window, test on next 12 months, step forward 12 months)."

**Issues:**

1. **Expanding window introduces non-stationarity bias.** Early folds train on 1-2 years; later folds on 20+ years. Performance estimates are not comparable across folds. Sliding (fixed-length) window is more appropriate for non-stationary financial data unless there is a specific reason to prefer expanding windows (cite if so).

2. **12-month test period with monthly rebalancing** = 12 observations per fold. With 16 parameter combinations and ~30 folds (1990-2025), the selection criterion has low statistical power. Sharpe ratio estimated from 12 monthly returns has standard error ≈ $1/\sqrt{12} \approx 0.29$, meaning the stability filter (std < 0.3) may exclude nearly all parameter sets or none, depending on the distribution.

3. **No multiple-testing correction.** Selecting the best of 16 parameter sets without adjusting for multiple comparisons inflates the probability of selecting a parameter set that performs well by chance. Apply Hansen's Superior Predictive Ability (SPA) test or Romano-Wolf stepdown procedure, or at minimum report the probability of false discovery.

4. **"Mean Sharpe with constraint that std < 0.3" — arbitrary threshold.** The 0.3 threshold is stated without justification. This should be derived from the data (e.g., bootstrap distribution of Sharpe standard deviation under the null).

**Recommendation:**
1. Use sliding window with window length selected via information criterion or stability analysis.
2. Increase test period to 24 or 36 months for more reliable Sharpe estimates, or use block bootstrap for inference.
3. Apply multiple-testing adjustment (White's Reality Check or SPA test).
4. Replace 0.3 threshold with a data-driven criterion or remove it entirely and report full results.

**Severity:** HIGH — Current validation framework is insufficient to distinguish skill from noise in parameter selection.

### 2.3 Transaction Cost Model

**Claim (§7):** "Add configurable cost model (default 10bps round-trip) as sensitivity parameter."

**Issues:**
- 10bps is reasonable for current large-cap equity trading but historically high (pre-decimalization spreads were 12.5-25 cents per share, equivalent to 25-100+ bps for some stocks).
- The plan lists this as a mitigation but does not integrate it into the backtest engine specification (§5). It is unclear whether costs are included in the base case or only as a sensitivity analysis.
- Strategy 3 with high turnover is most sensitive to cost assumptions.

**Recommendation:** Integrate transaction costs into the core backtest loop (not just sensitivity). Use a time-varying cost model: 50bps pre-2001, 20bps 2001-2005, 10bps 2005-present. Cite SEC market structure studies for calibration.

**Severity:** LOW-MEDIUM — Overstatement of returns, especially for Strategy 3.

---

## 3. METRICS METHODOLOGY

### 3.1 Sharpe Ratio with Contributions

**Problem not addressed:** The portfolio receives $1,000 monthly contributions. Standard Sharpe ratio assumes no external cash flows. With contributions, the portfolio return is ambiguous:

- **Time-weighted return (TWR):** Removes effect of cash flows; standard for benchmarking manager skill.
- **Money-weighted return (MWR/IRR):** Incorporates cash flows; reflects actual investor experience.

The plan does not specify which return methodology is used for metric calculation. Using simple $(V_{end}/V_{start}) - 1$ with contributions produces a meaningless number.

**Recommendation:**
1. Compute TWR using the modified Dietz method or daily sub-period linking for all risk-adjusted metrics.
2. Compute MWR (XIRR) separately for investor-experience reporting.
3. Document both in the metrics output.

**Severity:** HIGH — Metrics are undefined/incorrect without specifying the return calculation methodology in the presence of cash flows.

### 3.2 Annualized Volatility

**Formula (§3.2):** $\sigma_{monthly} \times \sqrt{12}$

This assumes monthly returns are i.i.d., which is violated in practice (volatility clustering, autocorrelation). Standard practice, but the plan should note this assumption and optionally compute GARCH-based annualization or use realized volatility from daily returns.

**Severity:** LOW — Industry convention; note assumption.

### 3.3 VaR/CVaR

**Method (§3.2):** "Historical percentile of monthly returns."

With ~420 monthly observations (1990-2025), 99% VaR is estimated from the 4th-worst month. This is a point estimate with high variance. Parametric VaR (normal or Cornish-Fisher expansion) or bootstrap confidence intervals should supplement.

**Severity:** LOW — Adequate for reporting with appropriate caveats.

### 3.4 Omega Ratio

**Formula (§3.3):** Integral formulation given.

Implementation note: Omega ratio computed from empirical distribution is straightforward but the integral notation may confuse the implementation. Equivalent discrete formula:

$$\Omega(r_f) = \frac{\sum \max(r_i - r_f, 0)}{\sum \max(r_f - r_i, 0)}$$

This should be specified to prevent implementation errors.

**Severity:** LOW — Clarification needed.

### 3.5 Risk-Free Rate

**Source (§3.6):** FRED `DGS3MO`.

`DGS3MO` is the daily 3-month constant maturity rate (annualized, bond-equivalent yield). Converting to monthly requires `r_monthly = (1 + DGS3MO/100)^(1/12) - 1`, not `DGS3MO / 12`. The plan does not specify the conversion method.

**Severity:** LOW — Common implementation error; specify formula.

---

## 4. ARCHITECTURE & IMPLEMENTATION

### 4.1 Module Separation

The plan separates `strategies.py` from `backtest_engine.py`. This is correct — strategy logic should be pluggable. However:

- `market_cap_estimator.py` and `data_fetcher.py` have an implicit dependency (estimator needs raw prices + shares outstanding from fetcher). Interface contract should be defined.
- `grid_search.py` depends on `backtest_engine.py`, `strategies.py`, and `metrics.py`. The plan does not specify whether grid search runs full backtests or operates on pre-computed return series.

**Recommendation:** Define explicit function signatures / interfaces in the plan for cross-module calls. This prevents implementation drift.

**Severity:** LOW — Architectural hygiene.

### 4.2 Caching Strategy

**Claim (§5.2):** Cache backtest results keyed by `(strategy_params, date_range, capital_config)`.

**Missing from cache key:** data version. If the underlying price data is updated (e.g., yfinance corrects a split adjustment), cached results become stale. Include a data hash or timestamp in the cache key.

**Severity:** LOW — Operational correctness.

### 4.3 Performance Target

**Claim (§8):** "Dashboard loads in <10 seconds." "Grid search completes in <5 minutes."

These are testable but ungrounded. With 16 parameter combinations × 35-year monthly backtest (420 steps), each requiring market cap ranking of ~50 tickers: total operations ≈ 16 × 420 × 50 log(50) ≈ 2M. This is trivially fast in pandas (sub-second). The 5-minute budget is extremely generous and suggests the plan may contemplate more expensive operations (daily data? Monte Carlo?) that are unspecified.

**Severity:** INFORMATIONAL — Targets are loose but non-blocking.

---

## 5. PARAMETER JUSTIFICATION VIOLATIONS

Per audit directive: "Zero arbitrary thresholds, hyperparameters, or magic numbers."

| Parameter | Value | Justification Provided | Status |
|-----------|-------|----------------------|--------|
| Monthly contribution | $1,000 | "Configurable" | OK — user input |
| Initial capital | $10,000 | "Configurable" | OK — user input |
| Strategy 2 N | {2,3,4,5} | "Exhaustive evaluation" | OK — full grid |
| Strategy 3 N_candidates | {3,5,7,10} | None | **VIOLATION** — Why not {3,4,5,...,15}? Grid gaps at 5→7 and 7→10 are arbitrary. |
| Strategy 3 k_lookback | {1,3,6,12} | None | **VIOLATION** — Standard momentum lookbacks, but should cite Jegadeesh & Titman (1993) or provide empirical basis. Excludes 2, 9 months without justification. |
| Walk-forward step | 12 months | None | **VIOLATION** — Arbitrary. Should test sensitivity to step size. |
| Walk-forward test window | 12 months | None | **VIOLATION** — See §2.2. |
| Sharpe std threshold | 0.3 | None | **VIOLATION** — See §2.2. |
| Transaction cost | 10bps | "Sensitivity parameter" | **PARTIAL** — Default value unjustified for historical periods. |
| Close-rank flag threshold | 10% | None (§7) | **VIOLATION** — Why 10% and not 5% or 20%? |
| Missing data flag | 5% | None (§1.3) | **VIOLATION** — Threshold not derived from data characteristics. |
| Metric tolerance | 1% (§8) | None | **VIOLATION** — Acceptance tolerance for metric validation should be justified by expected numerical precision. |

**Recommendation:** For each violation, either (a) expand the grid to full enumeration where feasible, (b) cite literature for conventional values, or (c) derive from data via preliminary analysis.

---

## 6. MISSING ELEMENTS

### 6.1 Rebalancing Mechanics
- The plan does not specify how monthly contributions interact with rebalancing. Is the $1,000 added before or after ranking? Does it get invested immediately at rebalance or held as cash until next rebalance?
- Partial shares: are fractional shares allowed? This matters for Strategy 2 with N=5 and small portfolio values early in the backtest.

### 6.2 Dividend Handling
- Plan states "adjusted close captures dividends." This is correct for total return calculation but creates an inconsistency: Strategies use adjusted close for returns but raw prices would be needed for market cap. The plan should clarify which price series is used where.

### 6.3 Slippage Model
- Transaction costs are mentioned but slippage (price impact) is not. For $10K starting capital trading mega-caps, slippage is negligible. But the plan should state this assumption explicitly.

### 6.4 Currency / Corporate Actions
- No handling specified for: spin-offs (e.g., ABBV from ABT — correctly noted in ticker list but no mechanical spec), ticker changes (FB→META), mergers (XOM absorbed Mobil).
- `yfinance` handles most of these via adjusted data, but the backtest engine needs to map old tickers to new tickers programmatically or via config.

### 6.5 Reproducibility Artifacts
- No random seed specification (grid search is deterministic, but if bootstrap or Monte Carlo is added later, seeds matter).
- No environment lockfile (`requirements.txt` with pinned versions or `pyproject.toml`).
- No data checksums for cached files.

---

## 7. SUMMARY OF FINDINGS

| # | Finding | Severity | Section |
|---|---------|----------|---------|
| F1 | Market cap approximation formula is flawed; double-counts split adjustments and ignores buybacks | HIGH | 1.1 |
| F2 | Return methodology undefined in presence of monthly contributions; metrics are meaningless without TWR/MWR specification | HIGH | 3.1 |
| F3 | Walk-forward validation lacks statistical rigor: low power, no multiple-testing correction, arbitrary stability threshold | HIGH | 2.2 |
| F4 | Survivorship bias mitigation is stated but not implemented in ticker universe | MEDIUM-HIGH | 1.2 |
| F5 | Strategy 3 momentum formula systematically favors incumbent leader, contradicting stated "anticipatory" design intent | MEDIUM | 2.1 |
| F6 | Ticker universe incomplete; missing LLY, BRK-A class issue, potentially TSM | MEDIUM | 1.3 |
| F7 | 11 parameter values violate zero-arbitrary-threshold directive | MEDIUM | 5 |
| F8 | Transaction costs not integrated into core backtest; default 10bps ahistorical | LOW-MEDIUM | 2.3 |
| F9 | Rebalancing mechanics underspecified (contribution timing, fractional shares) | LOW-MEDIUM | 6.1 |
| F10 | Edge case: all-negative-momentum period produces division by zero in Strategy 3 | LOW-MEDIUM | 2.1 |
| F11 | Risk-free rate conversion formula unspecified | LOW | 3.5 |
| F12 | Benchmark coverage gaps unaddressed for pre-1999/pre-2004 periods | LOW | 1.4 |
| F13 | Corporate action handling (spin-offs, ticker changes, mergers) unspecified | LOW | 6.4 |
| F14 | No reproducibility artifacts (lockfile, seeds, data checksums) | LOW | 6.5 |

**Findings F1, F2, F3 must be resolved before implementation begins.** The market cap approximation error (F1) is load-bearing — all downstream results depend on ranking accuracy. The return methodology gap (F2) means reported metrics are undefined. The validation framework weakness (F3) means Strategy 3 parameter selection cannot be trusted.

---

## 8. RECOMMENDED PLAN REVISIONS

1. **§1.1:** Replace market cap formula. Evaluate Sharadar, Tiingo, or WRDS as alternative data sources. If `yfinance`-only is a hard constraint, implement split-adjusted shares outstanding with explicit error bounds.
2. **§2 (Strategy 3):** Reformulate momentum score to match stated intent. Add all-negative-momentum fallback. Cite momentum factor literature.
3. **§2 (Walk-forward):** Switch to sliding window. Increase test period. Add multiple-testing correction. Replace 0.3 threshold with data-driven criterion.
4. **§3:** Add TWR/MWR specification. Specify risk-free rate conversion formula. Add discrete Omega ratio formula.
5. **§1.1 (Universe):** Add delisted companies as static data. Add LLY. Resolve BRK-A/B market cap aggregation.
6. **§5:** Add `requirements.txt` with pinned versions. Define cross-module interfaces.
7. **§7:** Integrate transaction costs into core loop with time-varying model.
8. **All arbitrary parameters:** Justify or expand grids per §5 table.
