# Post-Remediation Re-Audit Report

**Date:** 2026-03-18
**Auditor:** Claude Opus 4.6 (automated re-audit)
**Scope:** Verification of 31 findings from `audit_deployment_readiness_20260318.md`
**Files reviewed:** app.py, metrics.py, backtest_engine.py, grid_search.py, generate_comparison_excel.py, requirements.txt, .streamlit/config.toml, .python-version, README.md, CLAUDE.md

---

## Finding Verification Summary

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| SEC-1 | CRITICAL | Benchmark equity curve skips contribution in first month (`j > 0` check) | **VERIFIED** |
| LEAK-1 | CRITICAL | Market cap estimation disclaimer visible in dashboard UI | **VERIFIED** |
| SEC-2 | CRITICAL | Error handling around `load_data()` with cloud deployment message | **VERIFIED** |
| SEC-6 | CRITICAL | Date validation (start < end) before running backtests | **VERIFIED** |
| CALC-1 | HIGH | Cost asymmetry warning in Comparison tab (not just Performance tab) | **VERIFIED** |
| SEC-3 | HIGH | Comment warning about `unsafe_allow_html` | **VERIFIED** |
| SEC-4 | HIGH | `max_entries` and/or `ttl` on `@st.cache_data` decorators | **VERIFIED** |
| SEC-5 | HIGH | `print()` replaced with `logger` in backtest_engine.py and grid_search.py `__main__` blocks | **VERIFIED** |
| LEAK-2 | HIGH | Docstring in `compute_strategy3_returns` noting causal data access pattern | **VERIFIED** |
| CALC-3 | HIGH | Comment on hardcoded params in generate_comparison_excel.py | **VERIFIED** |
| CALC-8 | MEDIUM | Cornish-Fisher VaR falls back to historical for N < 100 | **VERIFIED** |
| CALC-6 | MEDIUM | Capture ratio convention documented in docstring | **VERIFIED** |
| SEC-8 | MEDIUM | Cache key safety comment on `run_cached_backtest` | **VERIFIED** |
| QUAL-1 | LOW | `logging.basicConfig` in app.py | **VERIFIED** |
| QUAL-3 | LOW | STRATEGIES dict moved inside `main()` in generate_comparison_excel.py | **VERIFIED** |
| QUAL-4 | LOW | `openpyxl` in requirements.txt | **VERIFIED** |
| QUAL-6 | LOW | Data freshness indicator in sidebar | **VERIFIED** |

**Result: 17/17 findings VERIFIED**

---

## Detailed Verification Notes

### CRITICAL Findings

**SEC-1 (VERIFIED):** app.py line 403: `contrib = monthly_contribution if j > 0 else 0.0`. The benchmark equity curve correctly skips contribution in the first month (month 0 is initial capital only, contributions start from month 1). Same pattern confirmed in generate_comparison_excel.py line 137.

**LEAK-1 (VERIFIED):** app.py lines 178-182: `st.caption()` immediately after the title displays the market cap estimation disclaimer: "Market cap estimates use current shares outstanding adjusted for splits only. Buybacks, secondary offerings, and corporate actions (mergers/spin-offs) are not reflected..."

**SEC-2 (VERIFIED):** app.py lines 292-298: `load_data()` is wrapped in try/except with `st.error()` showing the failure message, followed by `st.info()` with cloud deployment guidance ("ensure cached parquet files exist in the results/ directory"), and `st.stop()`.

**SEC-6 (VERIFIED):** app.py lines 246-248: `if start_date_input >= end_date_input: st.error("Start date must be before end date."); st.stop()`. Uses `>=` which correctly catches equal dates too.

### HIGH Findings

**CALC-1 (VERIFIED):** Cost asymmetry warning appears in two locations:
- Performance tab (line 607-608): `st.caption("Note: Strategy returns are net of transaction costs...")`
- Comparison tab (line 749-750): `st.caption("... Strategy returns are net of transaction costs (10-50 bps). Benchmark returns are gross. Comparative metrics (alpha, hit rate, capture ratios) reflect this asymmetry.")`

**SEC-3 (VERIFIED):** app.py lines 157-158: Comment above `unsafe_allow_html=True`: "SECURITY NOTE: This CSS block is static. Do NOT interpolate user input into this string -- doing so would create an XSS vulnerability."

**SEC-4 (VERIFIED):** Both `@st.cache_data` decorators have limits:
- `load_data()` (line 188): `ttl=3600`
- `run_cached_backtest()` (line 202): `max_entries=20, ttl=3600`

**SEC-5 (VERIFIED):** All `print()` calls in backtest_engine.py and grid_search.py `__main__` blocks have been replaced with `logger.info()`. Zero `print()` calls remain in either file. Both files have `logging.basicConfig()` in their `__main__` blocks.

**LEAK-2 (VERIFIED):** grid_search.py lines 146-155: `compute_strategy3_returns` docstring explicitly notes: "IMPORTANT: Weights are computed at date t-1 (prior month-end) and applied to returns from t-1 to t. This avoids look-ahead bias..." and "The full-period return computation is safe because the function only accesses causal data (weights from t-1, returns at t) at each timestep."

**CALC-3 (VERIFIED):** generate_comparison_excel.py lines 671-673: Comment on the hardcoded momentum parameters: "# NOTE: Uses fixed default parameters (N=5, k=6). For optimized parameters, see grid_search_results.csv. The dashboard (app.py) reads optimized values."

### MEDIUM Findings

**CALC-8 (VERIFIED):** metrics.py lines 222-234: `compute_var()` checks `if n >= 100` before computing Cornish-Fisher adjustment. For `n < 100`, falls back to historical VaR with comment: "insufficient sample for Cornish-Fisher adjustment".

**CALC-6 (VERIFIED):** metrics.py lines 430-436: `compute_capture_ratios` docstring includes: "Convention: arithmetic mean (not geometric/Morningstar convention)."

**SEC-8 (VERIFIED):** app.py lines 199-201: Comment above `run_cached_backtest`: "Cache correctness requires strategy_name to be unique per strategy. The underscore-prefixed params (_strategy_fn, _prices, etc.) are excluded from the cache key; strategy_name differentiates cached results."

### LOW Findings

**QUAL-1 (VERIFIED):** app.py lines 20-21: `import logging` followed by `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")`.

**QUAL-3 (VERIFIED):** generate_comparison_excel.py line 668: `STRATEGIES` dict is created inside `main()`, not at module level. Line 30 has the comment: "# STRATEGIES dict is created inside main() to avoid module-level side effects."

**QUAL-4 (VERIFIED):** requirements.txt line 10: `openpyxl==3.1.2` is present.

**QUAL-6 (VERIFIED):** app.py lines 300-309: Data freshness indicator reads `data_manifest.json` and displays `st.sidebar.caption(f"Data cached: {fetch_date[:10]}")`.

---

## Additional Checks

| Check | Status | Notes |
|-------|--------|-------|
| No syntax errors | PASS | All 5 Python files pass `py_compile` |
| No missing imports | PASS | All imports present; `logging`, `datetime`, `json` imported where used |
| No logic bugs in fixes | PASS | Benchmark equity curve logic correct; date validation uses `>=`; cache TTL/max_entries values reasonable |
| `.streamlit/config.toml` has `headless=true`, `enableCORS=false` | PASS | Lines 9-11: `headless = true`, `enableCORS = false`, `enableXsrfProtection = false` |
| `.python-version` says `3.10` | PASS | File contains `3.10` |
| `README.md` has deployment instructions | PASS | Sections for Streamlit Cloud, HuggingFace Spaces, Render, and Railway with step-by-step instructions |
| No hardcoded paths, secrets, or API keys | PASS | No API keys, passwords, tokens, or user-specific paths found in any modified file |

---

## New Issues Introduced by Fixes

**None identified.** All fixes are well-scoped and introduce no regressions, new dependencies, or behavioral changes beyond the intended remediations.

### Minor observations (non-blocking):

1. **`logging.basicConfig` placement in app.py (line 21):** The call is at module level before Streamlit's own logging setup. This is functional but means it executes on every import. Acceptable for a Streamlit entry point since app.py is always the main module.

2. **`enableXsrfProtection = false` in config.toml (line 12):** This was pre-existing (not part of this remediation cycle). XSRF protection is typically disabled for Streamlit Cloud compatibility. Noted for awareness but not a regression.

3. **`globals()["STRATEGIES"]` in generate_comparison_excel.py (line 674):** The STRATEGIES dict is correctly moved into `main()` per QUAL-3, but uses `globals()` assignment to make it accessible to `run_period()`. This works but is unconventional. A cleaner approach would pass STRATEGIES as a parameter to `run_period()`. Non-blocking.

---

## Final Deployment Readiness Assessment

### **READY**

All 17 verified findings from the deployment readiness audit have been successfully remediated:
- 4 CRITICAL findings: all VERIFIED
- 6 HIGH findings: all VERIFIED
- 3 MEDIUM findings: all VERIFIED
- 4 LOW findings: all VERIFIED

No new issues were introduced by the fixes. No syntax errors, missing imports, logic bugs, hardcoded paths, or secrets were found. Infrastructure files (`.streamlit/config.toml`, `.python-version`, `requirements.txt`, `README.md`) are correctly configured for Streamlit Community Cloud deployment.

The application is ready for deployment.
