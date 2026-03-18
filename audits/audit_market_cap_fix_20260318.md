# Audit Report: Market Cap Estimation Fix Validation

**Date:** 2026-03-18
**Auditor:** Claude Opus 4.6 (1M context)
**Scope:** Validate corrected market cap estimation after split double-counting bug fix and historical shares outstanding data addition.
**Files reviewed:** `market_cap_estimator.py`, `data_fetcher.py`, `backtest_engine.py`, `config.py`, `data/historical_shares_outstanding.csv`

---

## Executive Summary

The historical shares outstanding fix partially improved market cap estimates for tickers with stable share counts (XOM, MSFT post-2009) but **introduced a new, severe regression** for tickers with large post-2009 stock splits (AAPL, GOOGL, AMZN). Additionally, the fix has **no effect on pre-2009 dates** (51% of all rows) because historical shares data only starts in June 2009.

**Checkpoint year validation: 2/8 pass** (2020, 2025 by alternate). Six checkpoint years still fail rank-1 matching.

**Critical finding:** The formula `split_adjusted_close * historical_shares` is mathematically incorrect. Historical shares are in pre-split units, while yfinance `close` is in post-split (current-basis) units. The two are on different split bases and cannot be directly multiplied.

---

## Task 1: Corrected Rankings Validation

### Top-10 Rankings at Each Checkpoint Year

#### 1990 (Rank-1 match: FAIL -- expected IBM, got T)

| Rank | Ticker | Est Mkt Cap ($B) |
|------|--------|----------------:|
| 1 | T | 74.0 |
| 2 | XOM | 53.9 |
| 3 | MOB | 50.4 |
| 4 | BAC | 41.0 |
| 5 | MRK | 35.3 |
| 6 | C | 33.2 |
| 7 | MO | 28.8 |
| 8 | IBM | 25.3 |
| 9 | PG | 25.3 |
| 10 | KO | 25.0 |

Known top-5 error:

| Ticker | Known ($B) | Estimated ($B) | Error % |
|--------|----------:|---------------:|--------:|
| IBM | 64 | 25.3 | -60.4% |
| XOM | 63 | 53.9 | -14.4% |
| GE | 58 | 24.0 | -58.6% |
| PG | 24 | 25.3 | +5.4% |
| MSFT | 6 | 7.8 | +29.3% |

#### 1995 (Rank-1 match: FAIL -- expected GE, got C)

| Rank | Ticker | Est Mkt Cap ($B) |
|------|--------|----------------:|
| 1 | C | 182.6 |
| 2 | T | 151.4 |
| 3 | BAC | 124.9 |
| 4 | XOM | 84.5 |
| 5 | MOB | 84.2 |

Known top-5 error:

| Ticker | Known ($B) | Estimated ($B) | Error % |
|--------|----------:|---------------:|--------:|
| GE | 120 | 60.3 | -49.7% |
| XOM | 100 | 84.5 | -15.5% |
| KO | 93 | 79.8 | -14.2% |
| MSFT | 46 | 40.7 | -11.5% |
| PG | 40 | 48.5 | +21.2% |

#### 2000 (Rank-1 match: FAIL -- expected GE, got C)

| Rank | Ticker | Est Mkt Cap ($B) |
|------|--------|----------------:|
| 1 | C | 893.2 |
| 2 | T | 252.5 |
| 3 | PFE | 248.2 |
| 4 | GE | 241.0 |
| 5 | MRK | 220.9 |

Known top-5 error:

| Ticker | Known ($B) | Estimated ($B) | Error % |
|--------|----------:|---------------:|--------:|
| GE | 475 | 241.0 | -49.3% |
| CSCO | 300 | 151.1 | -49.6% |
| XOM | 270 | 181.1 | -32.9% |
| WMT | 240 | 141.1 | -41.2% |
| MSFT | 230 | 161.0 | -30.0% |

#### 2005 (Rank-1 match: FAIL -- expected XOM, got C)

| Rank | Ticker | Est Mkt Cap ($B) |
|------|--------|----------------:|
| 1 | C | 848.9 |
| 2 | BAC | 331.2 |
| 3 | XOM | 234.0 |
| 4 | MSFT | 194.2 |
| 5 | GE | 176.2 |

Known top-5 error:

| Ticker | Known ($B) | Estimated ($B) | Error % |
|--------|----------:|---------------:|--------:|
| XOM | 370 | 234.0 | -36.7% |
| GE | 370 | 176.2 | -52.4% |
| MSFT | 280 | 194.2 | -30.6% |
| C | 245 | 848.9 | +246.5% |
| WMT | 200 | 124.3 | -37.8% |

#### 2010 (Rank-1 match: FAIL -- expected XOM, got C)

| Rank | Ticker | Est Mkt Cap ($B) |
|------|--------|----------------:|
| 1 | C | 1,374.1 |
| 2 | GE | 933.9 |
| 3 | XOM | 368.7 |
| 4 | MSFT | 238.8 |
| 5 | PG | 180.2 |

Known top-5 error:

| Ticker | Known ($B) | Estimated ($B) | Error % |
|--------|----------:|---------------:|--------:|
| XOM | 370 | 368.7 | -0.3% |
| AAPL | 300 | 10.6 | -96.5% |
| MSFT | 240 | 238.8 | -0.5% |
| BRK | 200 | 115.2 | -42.4% |
| GE | 195 | 933.9 | +378.9% |

#### 2015 (Rank-1 match: FAIL -- expected AAPL, got GE)

| Rank | Ticker | Est Mkt Cap ($B) |
|------|--------|----------------:|
| 1 | GE | 1,408.9 |
| 2 | BRK | 651.4 |
| 3 | MSFT | 443.2 |
| 4 | XOM | 324.5 |
| 5 | JNJ | 284.2 |

Known top-5 error:

| Ticker | Known ($B) | Estimated ($B) | Error % |
|--------|----------:|---------------:|--------:|
| AAPL | 586 | 146.7 | -75.0% |
| GOOGL | 528 | 26.8 | -94.9% |
| MSFT | 443 | 443.2 | +0.0% |
| BRK | 325 | 651.4 | +100.4% |
| XOM | 317 | 324.5 | +2.4% |

#### 2020 (Rank-1 match: PASS)

| Rank | Ticker | Est Mkt Cap ($B) |
|------|--------|----------------:|
| 1 | AAPL | 2,256.0 |
| 2 | MSFT | 1,681.6 |
| 3 | BRK | 1,087.2 |
| 4 | META | 597.4 |
| 5 | V | 482.2 |

Known top-5 error:

| Ticker | Known ($B) | Estimated ($B) | Error % |
|--------|----------:|---------------:|--------:|
| AAPL | 2,070 | 2,256.0 | +9.0% |
| MSFT | 1,680 | 1,681.6 | +0.1% |
| AMZN | 1,630 | 81.7 | -95.0% |
| GOOGL | 1,190 | 59.3 | -95.0% |
| META | 780 | 597.4 | -23.4% |

#### 2025 (Rank-1 match: PASS via alternate -- NVDA accepted)

| Rank | Ticker | Est Mkt Cap ($B) |
|------|--------|----------------:|
| 1 | NVDA | 4,540.7 |
| 2 | AAPL | 4,034.5 |
| 3 | GOOGL | 3,791.1 |
| 4 | MSFT | 3,594.8 |
| 5 | AMZN | 2,467.5 |

Known top-5 error:

| Ticker | Known ($B) | Estimated ($B) | Error % |
|--------|----------:|---------------:|--------:|
| AAPL | 3,400 | 4,034.5 | +18.7% |
| MSFT | 3,100 | 3,594.8 | +16.0% |
| NVDA | 2,800 | 4,540.7 | +62.2% |
| GOOGL | 2,200 | 3,791.1 | +72.3% |
| AMZN | 2,100 | 2,467.5 | +17.5% |

---

## Task 2: Top-1 Crash Drawdown Analysis

| Crisis | Period | Primary Holding | Max Drawdown | Drawdown Date | Start Value | Trough Value |
|--------|--------|----------------|-------------|---------------|------------|-------------|
| Dot-com Crash | 2000-03 to 2002-10 | C (Citigroup) | -41.8% | 2002-09 | $596,967 | $457,812 |
| GFC | 2007-10 to 2009-03 | C (Citigroup) | -76.0% | 2009-02 | $832,847 | $200,002 |
| COVID | 2020-01 to 2020-03 | MSFT | -6.9% | 2020-03 | $828,397 | $771,539 |
| 2022 Bear Market | 2022-01 to 2022-10 | AAPL | -21.4% | 2022-06 | $1,391,380 | $1,095,780 |

**Key observation:** The Top-1 strategy held C (Citigroup) as its primary holding during the dot-com and GFC periods because C was incorrectly ranked #1 due to the market cap estimation bug. The GFC drawdown of -76.0% is dominated by Citigroup's near-bankruptcy. In reality, the Top-1 strategy would have held GE (2000) or XOM (2005-2007), resulting in materially different performance characteristics.

---

## Task 3: Data Integrity Checks

### 3a. Negative values in historical_shares_outstanding.csv
**PASS** -- 0 negative values found.

### 3b. Duplicate (date, ticker) pairs
**PASS** -- 0 duplicates found.

### 3c. Historical shares merge statistics

| Metric | Value |
|--------|-------|
| Total rows in CSV | 9,183 |
| Unique tickers | 49 |
| Date range | 2009-06-30 to 2026-03-31 |
| Total active price rows | 18,755 |
| Rows with historical override | 9,183 (49.0%) |
| Rows with fallback (current shares) | 9,572 (51.0%) |

The merge is mechanically working: 49% of rows get historical shares overrides. However, as documented in Task 4, the override formula itself is incorrect.

### 3d. Citigroup (C) rank-1 check (2005-2015)

| Year | Rank-1 | C Rank | Status |
|------|--------|--------|--------|
| 2005 | C ($849B) | 1 | **FAIL** |
| 2006 | C ($974B) | 1 | **FAIL** |
| 2007 | C ($515B) | 1 | **FAIL** |
| 2008 | XOM ($333B) | 8 | OK |
| 2009 | GE ($774B) | 2 | OK |
| 2010 | C ($1,374B) | 1 | **FAIL** |
| 2011 | QCOM ($91,950B) | 20 | OK (but QCOM at $92T is absurd) |
| 2012 | GE ($1,055B) | 15 | OK |
| 2013-2015 | GE | 14-17 | OK |

**C is still ranked #1 in 2005-2007 and 2010.** The historical shares fix did not resolve this because:
- Pre-2009: no historical shares data exists, fallback to current shares
- 2010: historical shares show ~29B shares (post-bailout dilution), but the split-adjusted close already incorporates the 2011 reverse split, creating a mismatch

**Additional anomaly: QCOM ranked #1 in 2011 at $92 trillion** -- this is clearly a data error (likely a split-adjustment issue with the QCOM 2004 special distribution).

---

## Task 4: Remaining Issues Analysis

### 4a. Checkpoint Years That Still Fail (6 of 8)

| Year | Expected Rank-1 | Actual Rank-1 | Root Cause |
|------|----------------|---------------|------------|
| 1990 | IBM | T | Pre-2009 fallback: T has 7.0B current shares (post AT&T splits/mergers); IBM has 0.94B |
| 1995 | GE | C | Pre-2009 fallback: C overestimated due to reverse split + dilution |
| 2000 | GE | C | Same as 1995 |
| 2005 | XOM | C | Same as 1995 |
| 2010 | XOM | C | Historical shares show post-bailout 29B shares * split-adj close = massive overestimate |
| 2015 | AAPL | GE | GE overestimated (current 1.05B shares, but had 10B+ pre-reverse-split); AAPL underestimated due to split-basis mismatch |

### 4b. Error Magnitude Summary

| Metric | Current (After Fix) |
|--------|-------------------|
| Total comparisons | 40 |
| Mean absolute error | 52.2% |
| Median absolute error | 34.8% |
| Max overestimate | +378.9% (GE 2010) |
| Max underestimate | -96.5% (AAPL 2010) |
| Checkpoint years passing | 2/8 |

### 4c. BEFORE/AFTER Comparison Table

| Year | Ticker | Known ($B) | Before Fix ($B) | Before Err% | After Fix ($B) | After Err% | Impact |
|------|--------|----------:|---------------:|------------:|---------------:|-----------:|--------|
| 1990 | IBM | 64 | 25.3 | -60.4% | 25.3 | -60.4% | NO CHANGE |
| 1990 | XOM | 63 | 53.9 | -14.4% | 53.9 | -14.4% | NO CHANGE |
| 1990 | GE | 58 | 24.0 | -58.6% | 24.0 | -58.6% | NO CHANGE |
| 1995 | GE | 120 | 60.3 | -49.7% | 60.3 | -49.7% | NO CHANGE |
| 2000 | GE | 475 | 241.0 | -49.3% | 241.0 | -49.3% | NO CHANGE |
| 2005 | C | 245 | 848.9 | +246.5% | 848.9 | +246.5% | NO CHANGE |
| 2010 | XOM | 370 | 304.7 | -17.7% | 368.7 | -0.3% | **IMPROVED** |
| 2010 | MSFT | 240 | 207.2 | -13.6% | 238.8 | -0.5% | **IMPROVED** |
| 2010 | AAPL | 300 | 169.1 | -43.6% | 10.6 | -96.5% | **REGRESSION** |
| 2015 | MSFT | 443 | 412.0 | -7.0% | 443.2 | +0.0% | **IMPROVED** |
| 2015 | AAPL | 586 | 386.3 | -34.1% | 146.7 | -75.0% | **REGRESSION** |
| 2015 | GOOGL | 528 | 226.5 | -57.1% | 26.8 | -94.9% | **REGRESSION** |
| 2020 | MSFT | 1,680 | 1,651.6 | -1.7% | 1,681.6 | +0.1% | **IMPROVED** |
| 2020 | AAPL | 2,070 | 1,948.0 | -5.9% | 2,256.0 | +9.0% | MIXED |
| 2020 | AMZN | 1,630 | 1,748.1 | +7.2% | 81.7 | -95.0% | **REGRESSION** |
| 2025 | AAPL | 3,400 | 3,991.2 | +17.4% | 4,034.5 | +18.7% | SLIGHTLY WORSE |
| 2025 | NVDA | 2,800 | 4,531.9 | +61.9% | 4,540.7 | +62.2% | NO CHANGE |

**Rank-1 comparison:**

| Year | Before Fix | After Fix | Expected | Status |
|------|-----------|----------|----------|--------|
| 1990 | T | T | IBM | FAIL (both) |
| 1995 | C | C | GE | FAIL (both) |
| 2000 | C | C | GE | FAIL (both) |
| 2005 | C | C | XOM | FAIL (both) |
| 2010 | XOM | C | XOM | **REGRESSION** (was correct before fix) |
| 2015 | MSFT | GE | AAPL | FAIL (both, different wrong answer) |
| 2020 | AAPL | AAPL | AAPL | PASS (both) |
| 2025 | NVDA | NVDA | AAPL | PASS via alt (both) |

### 4d. New Regressions Introduced by the Fix

**CRITICAL: The historical shares fix caused 5 new regressions:**

1. **AAPL 2010**: Error went from -43.6% to -96.5%. Historical shares (917M pre-split) multiplied by split-adjusted close gives 1/28th of correct market cap.
2. **AAPL 2015**: Error went from -34.1% to -75.0%. Same root cause (7:1 split in 2014 not accounted for in share count).
3. **GOOGL 2015**: Error went from -57.1% to -94.9%. GOOGL had 20:1 split in 2022; historical shares are pre-split.
4. **AMZN 2020**: Error went from +7.2% to -95.0%. AMZN had 20:1 split in 2022; historical shares are pre-split.
5. **2010 Rank-1**: Was XOM (correct), now C (incorrect). The historical shares for C in 2010 show ~29B (post-bailout dilution), but this is the actual share count -- the error is that `close` is split-adjusted by the 2011 reverse, inflating the price 10x, so the product is 10x the correct market cap.

---

## Root Cause Analysis

### The Fundamental Formula Error

The market cap estimator's docstring states:

> market_cap(t) = close_split_adjusted(t) x shares_outstanding(t)

This is **only correct when `shares_outstanding(t)` is also on the split-adjusted (current) basis**. Specifically:

- yfinance `close` = `actual_close(t) / cumulative_split_factor(t)` (current-basis, post-all-splits)
- Current shares outstanding = actual shares today (post-all-splits)
- Historical shares from CSV = actual shares at time t (pre-future-splits)

Therefore:

| Shares Source | Formula | Result |
|--------------|---------|--------|
| Current shares | close_adj x current_shares = (P/SF) x (S_now) | Correct **only if** S_now = S(t) x SF -- i.e., share count changed only due to splits |
| Historical shares | close_adj x hist_shares = (P/SF) x S(t) | **WRONG** -- off by factor SF |
| Historical shares (corrected) | close_adj x hist_shares x SF | Correct |

Where SF = cumulative split factor = product of all splits from time t to present.

### Two Distinct Failure Modes

**Failure Mode 1: Split-basis mismatch (historical shares fix regression)**
- Affects: AAPL, GOOGL, AMZN, TSLA, NVDA (tickers with large post-2009 splits)
- Cause: Historical shares are pre-split, close is post-split. Product is off by cumulative split factor.
- AAPL example (2010): close_adj=$11.52, hist_shares=917M, product=$10.6B. Correct: $11.52 x 917M x 28 = $296B.
- Severity: Up to 28x underestimate (96.5% error for AAPL 2010)

**Failure Mode 2: Dilution/buyback not captured by splits (pre-existing)**
- Affects: C, GE, T, BAC, IBM (tickers with large non-split share count changes)
- Cause: Current shares differ from historical shares for reasons other than splits (bailout dilutions, buybacks, mergers, spinoffs). Neither current-shares-fallback nor split-adjustment can correct this.
- C example (2005): Actual shares ~5B, current shares 1.75B. Split-adjusted close inflates price by 10x (reverse split). Product: ~$485 x 1.75B = $849B vs actual $245B.
- GE example (2010): Actual shares ~10.6B, current shares 1.05B. Multiple reverse splits inflate price. Product is ~5x overestimate.
- Severity: Up to 3.8x overestimate (378.9% error for GE 2010)

### Why `close_adj x current_shares` Worked Better (Before Fix)

For tickers where share count changes were **predominantly due to splits** (not dilution/buybacks), the formula `close_adj x current_shares` is approximately correct because:

```
close_adj x current_shares = (P_actual / SF) x (S_actual x SF) = P_actual x S_actual
```

The split factor cancels out. This is why AAPL, GOOGL, and AMZN were more accurate *before* the fix -- the cancelation was doing the right thing. The fix broke this by substituting pre-split historical shares that don't have the SF multiplier.

For tickers with large non-split share count changes (C, GE), neither formula works because `current_shares != S_actual(t) x SF`.

---

## Recommendations

### P0 (Must Fix): Correct the historical shares formula

The historical shares override in `estimate_market_caps()` must multiply by the cumulative split factor:

```python
# Current (WRONG):
active["estimated_market_cap"] = active["close"] * active["backward_shares"]

# Where backward_shares = hist_shares (when available)
# This is: (P/SF) * S(t) -- off by 1/SF

# Corrected:
# When using historical shares, multiply by cum_split_factor to convert
# pre-split share counts to current-split-basis:
active["estimated_market_cap"] = active["close"] * active["backward_shares"] * active["cum_split_factor"]
# But ONLY for rows using historical shares. For current-shares fallback,
# the factor should NOT be applied (it would double-count).
```

Specifically:

```python
# For historical shares rows:
#   mc = close_adj * hist_shares * cum_split_factor
#   = (P/SF) * S(t) * SF = P * S(t)  [CORRECT]
#
# For current shares fallback rows:
#   mc = close_adj * current_shares * 1.0
#   = (P/SF) * S_current  [approximately correct if buybacks/dilution are small]
```

### P1 (Should Fix): Extend historical shares pre-2009

The 51% of rows using current-shares fallback (pre-June 2009) cannot be corrected without historical share count data. Options:
1. Source SEC EDGAR 10-K/10-Q filings for pre-2009 share counts for the 10-15 most impactful tickers (C, GE, T, BAC, IBM, XOM).
2. Use `adj_close` (which includes dividend adjustments) instead of `close` for a slightly different but potentially more stable estimation basis.
3. Accept pre-2009 inaccuracy and document the limitation.

### P2 (Should Fix): Investigate anomalous data points

- QCOM ranked #1 in 2011 at $91,950B -- clearly a data error. Investigate split/shares data for QCOM.
- GE at $1,409B in 2015 (actual ~$295B) -- 4.8x overestimate due to reverse split history.

### P3 (Should Document): Known limitations

Update CLAUDE.md Key Design Decisions to note:
- Market cap estimates are accurate to within ~20% for tickers with stable share counts
- Tickers with bailout dilutions (C, GE), major mergers (T), or no pre-2009 data have errors exceeding 50%
- Backtest results for pre-2010 periods should be interpreted with this caveat

---

## Appendix: Data Integrity Summary

| Check | Result |
|-------|--------|
| Negative shares_outstanding values | 0 (PASS) |
| Duplicate (date, ticker) pairs | 0 (PASS) |
| Historical shares CSV rows | 9,183 |
| Historical shares tickers | 49 |
| Historical shares date range | 2009-06 to 2026-03 |
| Merge: rows with historical override | 9,183 (49.0%) |
| Merge: rows with current-shares fallback | 9,572 (51.0%) |
| C ranked #1 in 2005-2007 | YES (FAIL) |
| C ranked #1 in 2010 | YES (FAIL, new regression) |
| C ranked #1 in 2011-2015 | NO (OK) |

---

## Appendix: Crash Drawdown Analysis (Top-1 Strategy)

| Crisis | Period | Holding | Max Drawdown | Note |
|--------|--------|---------|-------------|------|
| Dot-com | 2000-03 to 2002-10 | C | -41.8% | C incorrectly ranked #1; actual holding would have been GE |
| GFC | 2007-10 to 2009-03 | C | -76.0% | C correctly was a large-cap but was massively overestimated |
| COVID | 2020-01 to 2020-03 | MSFT | -6.9% | Rank-1 was AAPL; MSFT close second -- plausible |
| 2022 Bear | 2022-01 to 2022-10 | AAPL | -21.4% | Correct holding |

---

*Report generated 2026-03-18. Audit script: `scripts/run_audit_20260318.py`.*
*Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>*
