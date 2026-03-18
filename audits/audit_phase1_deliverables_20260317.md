# Audit: Phase 1 Deliverables

**Date:** 2026-03-17
**Scope:** Code-level audit of all Phase 1 files: `config.py`, `data_fetcher.py`, `market_cap_estimator.py`, `delisted_monthly.csv`, `requirements.txt`
**Environment:** Python 3.9.13 on Windows 11

---

## CRITICAL FINDINGS (Block Phase 2)

### C1. Python 3.9 Incompatibility — Both Core Modules Fail to Import

**Files:** `data_fetcher.py`, `market_cap_estimator.py`
**Severity:** CRITICAL

Both files use PEP 604 (`str | None`) and PEP 585 (`list[str]`, `dict[str, ...]`) type hint syntax that requires Python 3.10+. The environment runs Python 3.9.13. Neither file has `from __future__ import annotations`.

**Result:** Both modules raise `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` on import. No code in these files can execute.

**Affected locations in `data_fetcher.py`:**
- Line 68: `end: str | None = DEFAULT_END_DATE`
- Line 225: `end: str | None = DEFAULT_END_DATE`
- Line 291: `end: str | None = DEFAULT_END_DATE`
- Line 325: `-> pd.DataFrame | None`
- Line 388: `end: str | None = DEFAULT_END_DATE`
- Line 66: `tickers: list[str]`
- Line 162: `tickers: list[str]`
- Line 194: `tickers: list[str]`
- Line 390: `-> dict[str, pd.DataFrame]`

**Affected locations in `market_cap_estimator.py`:**
- Line 316: `known_market_caps: dict[int, dict[str, float]] | None = None`

**Fix (preferred):** Upgrade the environment to Python 3.12+ (current stable: 3.12.9 or 3.13.2 as of March 2026). Python 3.9 reached end-of-life in October 2025 and no longer receives security patches. Upgrading resolves C1 natively, aligns with the `requirements.txt` dependency versions (several of which have dropped 3.9 support in recent releases), and eliminates the need for `from __future__ import annotations` workarounds.

**Fix (interim, if upgrade is deferred):** Add `from __future__ import annotations` as the first import in both files. This makes all annotations strings at parse time, deferring evaluation and bypassing the 3.10+ requirement. Alternatively, replace with `Optional[str]`, `List[str]`, `Dict[str, ...]` from `typing`.

---

### C2. Gold Benchmark FRED Fallback Is Dead Code

**File:** `data_fetcher.py` lines 306-317; `config.py` lines 107-113
**Severity:** HIGH

The Gold benchmark config uses keys `fallback_fred` and `fallback_etf`:
```python
"Gold": {
    "primary": "GC=F",
    "fallback_fred": "GOLDAMGBD228NLBM",
    "fallback_etf": "GLD",
    ...
}
```

But `fetch_benchmark_data()` reads `cfg.get("fallback")` — a key that does not exist in the Gold config. The FRED London PM fix and GLD ETF fallbacks are **never tried**. If `GC=F` returns bad data pre-2000 (a known issue per the plan), there is no fallback.

The other three benchmarks use the `"fallback"` key correctly and are unaffected.

**Fix:** Either rename Gold's config keys to match the fetch code, or extend `fetch_benchmark_data()` to check `fallback_fred` and `fallback_etf` keys with appropriate FRED fetching logic.

---

### C3. Non-Month-End Dates in Delisted CSV Cause Join Mismatches

**File:** `data/delisted_monthly.csv`
**Severity:** HIGH

Two entries have dates that are not month-end:
- Line 137: `LEH,2008-09-15,0.21,694000000` (Lehman filed bankruptcy Sept 15)
- Line 287: `GMGMQ,2009-06-01,0.75,610000000` (GM filed bankruptcy June 1)

All active-ticker data is resampled to month-end dates. `market_cap_estimator.py` line 133 concatenates delisted data with active data without resampling the delisted frame. When rankings are computed for September 2008 month-end, the LEH entry at Sept 15 will not match. Same for GMGMQ at June 2009.

**Result:** LEH and GMGMQ will be **absent from rankings** at their final (delisting) months. The forced-liquidation event specified in the plan cannot trigger correctly.

**Fix:** Either (a) change the CSV dates to month-end (`2008-09-30`, `2009-06-30`), or (b) add month-end resampling of the delisted DataFrame in `estimate_market_caps()` before concatenation.

---

### C4. Missing 3 of 8 Checkpoint Years in Error Quantification

**File:** `market_cap_estimator.py` lines 332-339
**Severity:** HIGH

`compute_estimation_error()` default `known_market_caps` covers only 5 years: 2000, 2005, 2010, 2015, 2020.

Missing:
- **1990:** IBM ~$64B, XOM ~$63B, GE ~$58B, MSFT ~$6B, PG ~$24B
- **1995:** GE ~$120B, XOM ~$100B, KO ~$93B, MSFT ~$46B, PG ~$40B
- **2025:** AAPL ~$3,400B, MSFT ~$3,100B, NVDA ~$2,800B, GOOGL ~$2,200B, AMZN ~$2,100B

The plan (§1.3, §6 Phase 1 gate, §8 acceptance criteria) requires error bounds at **all 8 checkpoint years**. Phase 1 validation gate cannot be satisfied.

**Fix:** Add entries for 1990, 1995, and 2025 to the default `known_market_caps` dict.

---

## MEDIUM FINDINGS

### M1. Cache Loads Without Hash Verification

**File:** `data_fetcher.py` lines 374-379
**Severity:** MEDIUM

`load_cached()` checks file existence and loads unconditionally. SHA-256 hashes are written by `save_with_manifest()` but never verified on read. The plan (§5.3) specifies cache invalidation via `data_hash`. A corrupted or stale cache will produce incorrect results silently.

**Impact:** Operational correctness risk. If yfinance data is re-fetched (correcting a corporate action, for example), old cached data may persist and be used.

---

### M2. `compute_cumulative_split_factor` Performance — O(T * D) Python Loop

**File:** `market_cap_estimator.py` lines 58-67
**Severity:** MEDIUM

Nested Python loop: 48 tickers × 420 dates = ~20,160 iterations, each filtering a DataFrame and calling `.prod()`. Estimated runtime: 5-30 seconds. Tolerable for the current universe but will not scale. A vectorized approach (build a cumulative product series per ticker, merge on date) would be 10-100x faster.

Not a correctness issue; flagged for implementation quality.

---

### M3. Truthiness Bug in `gap_pct` Calculation

**File:** `market_cap_estimator.py` line 281
**Severity:** MEDIUM

```python
gap_pct = ((mc1 - mc2) / mc1 * 100) if (mc1 and mc2 and not np.isnan(mc1) and not np.isnan(mc2)) else np.nan
```

`if mc1` evaluates to `False` when `mc1 == 0.0`. If the #1 market cap were zero (collapsed stock), this silently produces NaN instead of flagging the error. More practically, if `mc2 == 0.0`, the gap should be 100% but will be reported as NaN.

**Fix:** Replace `(mc1 and mc2)` with `(mc1 is not None and mc2 is not None)`, or check against NaN only since the values come from a DataFrame (already float, never None).

---

### M4. WCOEQ Shares Outstanding Understated (~33%)

**File:** `data/delisted_monthly.csv`
**Severity:** MEDIUM

CSV uses 1,780,000,000 shares throughout for WorldCom. This appears to be the pre-MCI-merger basic share count. After the MCI merger completed (Sept 1998), WorldCom's total shares outstanding were approximately 2.65 billion (including merger shares and convertible preferred). Peak market cap at $61.63 × 1.78B = $109.7B; actual peak was ~$163-180B.

The plan itself states WCOEQ peak as "~$180B (1999)". The CSV data produces $115B peak — a 36% understatement.

**Impact:** WorldCom will be under-ranked during 1999 when it should have been a top-5 company, reducing the quality of survivorship-bias mitigation.

---

### M5. Delisted Tickers Missing Historical Depth

**File:** `data/delisted_monthly.csv`
**Severity:** MEDIUM

| Ticker | CSV Start | Actual Significance Start | Missing Years |
|--------|-----------|--------------------------|---------------|
| LEH | 2005-01 | ~1994 (IPO) | 11 years |
| MOB | 1996-01 | 1990+ (top-10 all decade) | 6 years |
| ENRNQ | 1999-01 | ~1990 (became major 1990s) | 9 years |

These companies were significant market-cap names before the CSV coverage begins. During missing periods, they will be absent from rankings entirely — partially undermining the survivorship-bias mitigation that was the purpose of including them.

Practical impact is limited because LEH and ENRNQ were not top-5 before their coverage starts. MOB was top-10 in 1990-1995 and its absence there is the most significant gap.

---

### M6. KNOWN_RANK1 Has 2005: "GE" — Debatable

**File:** `market_cap_estimator.py` line 214
**Severity:** LOW-MEDIUM

Most published sources list XOM as #1 by market cap at year-end 2005 (~$370B) following the post-Katrina oil price surge. GE was close (~$370B) and was #1 for much of 2005. The `KNOWN_RANK1_ALT` dict includes `2005: ["XOM"]`, so the validation will accept either. Functionally non-blocking but the primary entry should arguably be XOM.

---

### M7. `requirements.txt` Missing `numpy-financial`

**File:** `requirements.txt`
**Severity:** MEDIUM (Phase 3 blocker, not Phase 1)

The plan (§3.0, §6 Phase 3 gate) specifies MWR validation against `numpy_financial.irr`. Package absent from requirements. Not needed until Phase 3, but should be added to the pinned dependency list now per the plan's §5.1 intent to have a complete lockfile.

---

## LOW FINDINGS

### L1. `_month_end_resample` Helper Is Dead Code

**File:** `data_fetcher.py` lines 53-58
**Severity:** LOW

Defined but never called. Inline resampling at line 130 does the same job. Dead code.

---

### L2. NFLX `approximate_earliest_year` Is 1990; IPO Was 2002

**File:** `config.py` line 37
**Severity:** LOW

`"NFLX": 1990`. Netflix IPO was May 2002. yfinance will return no data before then. The `data_fetcher.py` determines actual entry from first valid close, so this causes no functional error — just 12 years of wasted API calls. Similarly, `QCOM` is listed as 1990 but IPO'd in 1991.

---

### L3. `fredapi` in Requirements But Not Used

**File:** `requirements.txt` line 5
**Severity:** LOW

`fredapi==0.5.2` is listed but the code uses `pandas_datareader` (not `fredapi`) for FRED data. Superfluous dependency. Not harmful.

---

### L4. Config AVGO/CRM Dates Differ From Plan But Are More Accurate

**File:** `config.py` lines 48-49
**Severity:** INFORMATIONAL

AVGO listed as 2009 (config) vs 2015 (plan). AVGO IPO'd August 2009. Config is correct; plan's grouping was approximate. Same for CRM: config 2004, plan 2015. CRM IPO'd June 2004. No issue — config is more accurate.

---

## SUMMARY

| # | Finding | Severity | Blocks Phase 2? |
|---|---------|----------|-----------------|
| C1 | Python 3.9 type hint incompatibility — modules cannot import | CRITICAL | YES |
| C2 | Gold benchmark FRED fallback is dead code | HIGH | YES |
| C3 | Non-month-end delisted dates cause join mismatches | HIGH | YES |
| C4 | 3 of 8 checkpoint years missing from error quantification | HIGH | YES |
| M1 | Cache loads without hash verification | MEDIUM | No |
| M2 | Split factor computation O(T*D) Python loop | MEDIUM | No |
| M3 | Truthiness bug in gap_pct | MEDIUM | No |
| M4 | WCOEQ shares outstanding understated 33% | MEDIUM | No |
| M5 | Delisted tickers missing historical depth (MOB, LEH, ENRNQ) | MEDIUM | No |
| M6 | 2005 rank-1 debatable (GE vs XOM) | LOW-MEDIUM | No |
| M7 | Missing `numpy-financial` in requirements | MEDIUM | No (Phase 3) |
| L1 | Dead code `_month_end_resample` | LOW | No |
| L2 | NFLX approximate_earliest_year misleading | LOW | No |
| L3 | `fredapi` unused dependency | LOW | No |
| L4 | AVGO/CRM dates differ from plan (config is more accurate) | INFO | No |

**Phase 1 status: BLOCKED.** Findings C1-C4 must be resolved before proceeding. C1 is the most severe — no code can execute at all on the target Python version.
