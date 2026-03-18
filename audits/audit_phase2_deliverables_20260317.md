# Audit: Phase 2 Deliverables

**Date:** 2026-03-17
**Scope:** Code-level audit of `strategies.py`, `backtest_engine.py`, `test_phase2.py` against implementation plan §2, §2.4, §2.5, §3.0
**Test execution:** 6/6 PASS confirmed via independent run

---

## CRITICAL FINDINGS

### C1. Modified Dietz TWR Day-Weight Factor W Is Incorrect

**File:** `backtest_engine.py` lines 393-404
**Severity:** HIGH — Systematically biases all risk-adjusted metrics

The `_record_twr` function hardcodes `W = 1.0`:

```python
denominator = prev_value + contribution * 1.0
r = (portfolio_value - prev_value - contribution) / denominator
```

W = 1.0 means the contribution is treated as if it had **full-period exposure**, i.e., the contribution arrived at the **start** of the return period. But the actual execution order in the backtest loop is:

1. Mark-to-market at current month-end prices (returns already earned)
2. Check delistings
3. **Add contribution** (at current month-end)
4. Rebalance
5. Record portfolio value

The contribution arrives at the **end** of the period, after returns have been realized. W should be **approximately 0** (zero exposure during the period).

**Quantified impact:**

For a month with true return $r$, starting value $V$, and contribution $C$:
- With W=1: reported return = $\frac{V(1+r) + C - V - C}{V + C} = \frac{Vr}{V + C}$
- With W=0: reported return = $\frac{V(1+r) + C - V - C}{V} = r$

The bias is $r \cdot \frac{C}{V + C}$. For early months ($V$ = $10K, $C$ = $1K), this is ~9% of the true return. For a +10% month, the reported return is 9.33% instead of 10.0% — a 67 bps error. The bias decays as the portfolio grows (contribution becomes a smaller fraction), but it is systematic and directional: positive returns are understated, negative returns are understated (in absolute terms).

All downstream metrics (Sharpe, Sortino, Calmar, Alpha, Beta, etc.) inherit this bias.

**Fix:** Set W = 0.0 (contribution at end of period, zero exposure):
```python
denominator = prev_value + contribution * 0.0  # i.e., just prev_value
```

Or, more cleanly: compute TWR using `portfolio_value_before_cf` (line 208, already computed but unused for TWR):
```python
r = (portfolio_value_before_cf - prev_portfolio_value) / prev_portfolio_value
```

This is pure TWR — no Modified Dietz adjustment needed since cash flows are excluded from the measurement window entirely. Set `prev_portfolio_value = portfolio_value` (post-trade, post-contribution) for the next period's starting value.

**Note:** The current tests do not catch this bug because they use flat prices (0% returns), where both W=0 and W=1 yield the same result.

---

### C2. Delisting Liquidation Followed by Immediate Rebuy in Delist Month

**File:** `backtest_engine.py` lines 212-228
**Severity:** MEDIUM-HIGH

Execution order at each rebalance:
1. **Delisting check** (line 213): if ticker is past delist date, force-liquidate
2. **Strategy call** (line 228): strategy may still return weights for the delisted ticker (it's still in rankings at its final month)
3. **Trades** (lines 256-312): engine buys the delisted ticker back

In the delisting month, the engine liquidates then re-purchases the same stock. In the subsequent month, the stock has no price data (`prices_today.get(ticker, 0) = 0`), so:
- The sell branch (line 279): `sell_value = current_value = shares × 0 = 0`, no proceeds
- The position becomes a phantom holding with zero value, never removed

**Result:** (a) Unnecessary transaction costs in the delist month (sell + buy), (b) phantom holdings with zero value pollute `holdings_history` indefinitely, (c) HHI and holdings-count metrics are inflated.

**Fix:** After delisting liquidation, exclude delisted tickers from strategy weights before trade execution:
```python
# After line 213:
delisted_this_month = set(holdings.keys()) - set(updated_holdings.keys())
# After line 228:
for t in delisted_this_month:
    target_weights.pop(t, None)
```

---

## MEDIUM FINDINGS

### M1. Plan-vs-Code Discrepancy: Transaction Cost Formula

**File:** `backtest_engine.py` lines 266, 281, 301
**Plan reference:** §2.4 line 198

The plan states: "applies cost as: `trade_value × cost_bps / 10000` for each leg (buy and sell)"

The code applies: `trade_value × cost_bps / 20000` per leg.

Since `COST_SCHEDULE_BPS` defines **round-trip** costs, the per-leg cost should be half: `cost_bps / 2 / 10000 = cost_bps / 20000`. **The code is correct; the plan text is wrong.** If taken literally, the plan would double-count costs (50 bps per leg × 2 legs = 100 bps total, not the intended 50 bps round-trip).

**Fix:** Correct the plan text to: "applies cost as: `trade_value × cost_bps / 20000` for each leg (half of round-trip cost per leg)"

**Severity:** MEDIUM — Documentation error. Risk of future implementers interpreting the plan literally and introducing a bug.

---

### M2. Strategy 3 Can Produce 100% Concentration in a Single Ticker

**File:** `strategies.py` line 167
**Severity:** MEDIUM (design concern)

When only one candidate has positive momentum, the momentum strategy allocates 100% to that single ticker. Confirmed in test 5: trending data produces `{'CCC': 1.0}`.

The plan (§2) specifies N_candidates up to 10, with the clear intent of diversification across top-N. But the momentum weighting can collapse to single-stock concentration whenever exactly one ticker has positive momentum. This is not a bug per the formula, but contradicts the diversification intent of using N_candidates > 1.

**Recommendation:** Consider a minimum weight floor or blending with equal weight (e.g., `w_final = 0.5 * w_momentum + 0.5 * w_equal`). Document the decision either way.

---

### M3. `portfolio_value_before_cf` Computed But Not Used for TWR

**File:** `backtest_engine.py` line 208
**Severity:** MEDIUM (related to C1)

`portfolio_value_before_cf` captures the portfolio value at current prices BEFORE contribution, delisting, or rebalancing. This is the correct V_end for a pure TWR sub-period return. It is computed every iteration but never passed to the TWR function. Instead, `portfolio_value` (post-trades, post-contribution) is used.

This variable should be used for TWR computation per the fix described in C1.

---

### M4. Buy Logic Cash Constraint Creates Silent Under-Investment

**File:** `backtest_engine.py` lines 299-300
**Severity:** MEDIUM

```python
if buy_value > cash:
    buy_value = cash  # Can't buy more than available cash
```

When cash is insufficient to buy the full target allocation, the buy is silently capped. This can happen when multiple buys are processed sequentially and earlier buys consume the available cash. No warning is logged and no tracking of the under-allocation occurs. The portfolio may drift significantly from target weights without any indicator.

**Fix:** Log a warning when cash-constrained, and optionally track the deviation from target weights in the result.

---

## LOW FINDINGS

### L1. Tests Use Only Flat or Uniformly Trending Prices

**File:** `test_phase2.py`
**Severity:** LOW — Testing gap

All synthetic data uses constant prices (0% returns) or uniform linear trends. Missing test scenarios:

| Missing scenario | Why it matters |
|-----------------|---------------|
| Price changes with non-zero returns | Verifies TWR correctness (would have caught C1) |
| Delisting liquidation | Verifies forced sale mechanics (would have caught C2) |
| Strategy 2 via backtest engine | Strategy 2 is only unit-tested, not integration-tested |
| Multi-ticker rebalance with limited cash | Verifies buy-ordering fairness |
| Position changes (rank-1 switches from AAA to BBB) | Verifies sell-then-buy ordering and cost accounting |

**Recommendation:** Add a test with known non-zero returns and manually computed expected TWR to verify the TWR calculation. This is the single highest-value test addition, as it would expose C1.

---

### L2. Strategy Wrapper Factory Uses Circular Import

**File:** `backtest_engine.py` lines 413-434
**Severity:** LOW

`make_top1_fn`, `make_topn_fn`, `make_momentum_fn` import from `strategies` inside the function body to avoid circular import. This works but is fragile. If `strategies.py` is renamed or refactored, the error surfaces at runtime (when the wrapper is first called), not at import time.

---

### L3. Missing `from __future__ import annotations` Note for Python 3.9

**File:** `strategies.py` line 14; `backtest_engine.py` line 13
**Severity:** INFORMATIONAL

Both files correctly include `from __future__ import annotations`. Consistent with Phase 1 remediation.

---

## IMPLEMENTATION PLAN COMPLIANCE CHECK

| Plan Requirement (§2, §2.4, §2.5, §3.0) | Code Status | Finding |
|------------------------------------------|-------------|---------|
| Strategy 1: 100% to rank-1 | Implemented correctly | OK |
| Strategy 2: 1/N to top-N | Implemented correctly | OK |
| Strategy 3: log-momentum $\mu_i = \log(M_i(t)/M_i(t-k))$ | Implemented correctly at [strategies.py:151](scripts/strategies.py#L151) | OK |
| Strategy 3: $w_i = \max(\mu_i, 0) / \sum \max(\mu_j, 0)$ | Implemented correctly at [strategies.py:152-167](scripts/strategies.py#L152-L167) | OK |
| Strategy 3: all-negative fallback to 1/N | Implemented and tested | OK |
| Contribution timing: before allocation | Implemented at [backtest_engine.py:217-218](scripts/backtest_engine.py#L217-L218) | OK |
| Fractional shares: allowed | Implemented (no rounding anywhere) | OK |
| Execution order: sells first, then buys | Implemented at [backtest_engine.py:256-312](scripts/backtest_engine.py#L256-L312) | OK |
| Transaction costs: integrated, time-varying | Implemented with `_get_cost_bps` lookup | OK |
| Cost per leg: half of round-trip | Code correct; **plan text wrong** | M1 |
| Delisting: force-liquidate, hold cash, reallocate next rebalance | Liquidation works; **rebuy bug in delist month** | C2 |
| TWR: Modified Dietz sub-period returns | Implemented but **W factor incorrect** | C1 |
| XIRR: cash flows with correct signs | Initial negative, contributions negative, terminal positive | OK |
| Trade logging | All fields recorded | OK |

---

## PHASE 2 VALIDATION GATE ASSESSMENT

| Gate | Test | Result | Finding |
|------|------|--------|---------|
| (1) Manual calc matches within $0.01 | Test 1: flat prices | PASS | C1 masked by 0% returns |
| (2) Transaction costs reduce returns | Test 2: with vs without | PASS | OK |
| (3) Contribution adds $1K at each rebalance | Test 3: cash flow records | PASS | OK |
| (4) All-negative-momentum fallback | Test 4: declining data | PASS | OK |

**Gate (1) passes but does not verify correctness with non-zero returns.** The flat-price test is a degenerate case where any W value produces the same result. A supplementary test with known returns (e.g., +10% month) would expose the W=1 bug.

---

## SUMMARY

| # | Finding | Severity | Blocks Phase 3? |
|---|---------|----------|-----------------|
| C1 | Modified Dietz W=1 is incorrect; should be W=0 | HIGH | YES — all risk-adjusted metrics are biased |
| C2 | Delisting liquidation + immediate rebuy in delist month | MEDIUM-HIGH | No (edge case, minor cost impact) |
| M1 | Plan text says cost/10000 per leg; should be cost/20000 | MEDIUM | No (code is correct) |
| M2 | Momentum strategy can collapse to 100% single-stock | MEDIUM | No (design question) |
| M3 | `portfolio_value_before_cf` unused for TWR | MEDIUM | Part of C1 fix |
| M4 | Silent under-investment when cash-constrained | MEDIUM | No |
| L1 | Tests lack non-zero-return scenarios | LOW | No (but would catch C1) |
| L2 | Circular import workaround | LOW | No |

**C1 must be resolved before Phase 3.** TWR returns feed directly into Sharpe, Sortino, Calmar, Alpha, Beta, and all risk-adjusted metrics. With W=1, positive returns are systematically understated by approximately `contribution / (portfolio_value + contribution)`, which is ~9% relative error in early months.
