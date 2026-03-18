"""
metrics.py — Performance metric calculations for MarketCapBacktest.

Implements all metrics from IMPLEMENTATION_PLAN.md sections 3.0-3.6:
  - Return metrics (TWR, MWR/XIRR, CAGR, rolling)
  - Risk metrics (volatility, max drawdown, VaR/CVaR with Cornish-Fisher, Ulcer)
  - Risk-adjusted metrics (Sharpe, Sortino, Calmar, Omega, Information, Treynor)
  - Benchmark-relative metrics (Alpha, Beta, tracking error, capture ratios)
  - Portfolio characteristics (turnover, HHI, holdings count)

All risk-adjusted metrics use TWR returns exclusively.
MWR (XIRR) is computed separately for investor-experience reporting.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import optimize, stats

from config import DEFAULT_RANDOM_SEED

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 3.0 Return Methodology
# ---------------------------------------------------------------------------

def compute_twr(monthly_returns: pd.Series) -> float:
    """
    Compute cumulative Time-Weighted Return from geometrically linked
    sub-period returns.

    TWR = prod(1 + r_t) - 1
    """
    return (1 + monthly_returns).prod() - 1


def compute_cagr_twr(monthly_returns: pd.Series) -> float:
    """
    Compute CAGR from TWR monthly sub-period returns.

    CAGR = (1 + TWR)^(1/Y) - 1
    where Y = number of years = number of months / 12
    """
    twr = compute_twr(monthly_returns)
    n_months = len(monthly_returns)
    if n_months <= 0:
        return 0.0
    years = n_months / 12.0
    if years <= 0:
        return 0.0
    if twr <= -1.0:
        return -1.0
    return (1 + twr) ** (1 / years) - 1


def compute_xirr(cash_flows: pd.DataFrame) -> float:
    """
    Compute Money-Weighted Return (XIRR) from cash flows.

    cash_flows: DataFrame with columns [date, amount]
        Negative = outflow (investment), Positive = inflow (terminal value).

    Returns annualized IRR as a decimal.

    Day-count convention: 365.25 days/year (standard XIRR convention).
    This produces a small systematic bias (~2 bps on a 10% return) depending
    on whether the actual period spans leap years. This is expected behavior,
    not an error.
    """
    if cash_flows.empty or len(cash_flows) < 2:
        return 0.0

    cf = cash_flows.copy()
    cf["date"] = pd.to_datetime(cf["date"])
    cf = cf.sort_values("date").reset_index(drop=True)

    dates = cf["date"].values
    amounts = cf["amount"].values

    # Day offsets from first date
    d0 = dates[0]
    day_offsets = np.array([(d - d0) / np.timedelta64(1, "D") for d in dates])
    year_fractions = day_offsets / 365.25

    def npv(rate):
        return np.sum(amounts / (1 + rate) ** year_fractions)

    # Find IRR via Brent's method
    try:
        irr = optimize.brentq(npv, -0.99, 10.0, maxiter=1000)
    except ValueError:
        # Brent's method failed to find a root in [-0.99, 10]
        logger.warning("XIRR: brentq failed. Trying wider bracket.")
        try:
            irr = optimize.brentq(npv, -0.9999, 100.0, maxiter=2000)
        except ValueError:
            logger.warning("XIRR: could not find root. Returning 0.")
            return 0.0

    return irr


# ---------------------------------------------------------------------------
# 3.1 Return Metrics
# ---------------------------------------------------------------------------

def compute_rolling_returns(
    monthly_returns: pd.Series,
    windows: list[int] | None = None,
) -> dict[str, pd.Series]:
    """
    Compute rolling annualized TWR returns.

    windows: list of rolling window sizes in months (default: [12, 36, 60])
    Returns dict of {"1Y": series, "3Y": series, "5Y": series}
    """
    if windows is None:
        windows = [12, 36, 60]
    labels = {12: "1Y", 36: "3Y", 60: "5Y"}

    result = {}
    for w in windows:
        label = labels.get(w, f"{w}M")
        rolling_cum = (1 + monthly_returns).rolling(window=w).apply(
            lambda x: x.prod(), raw=True
        )
        # Annualize: (cum_return)^(12/w) - 1
        rolling_ann = rolling_cum ** (12.0 / w) - 1
        result[label] = rolling_ann
    return result


def compute_annual_returns(monthly_returns: pd.Series) -> pd.Series:
    """Compute calendar-year returns from monthly TWR returns."""
    grouped = (1 + monthly_returns).groupby(monthly_returns.index.year).prod() - 1
    grouped.index.name = "year"
    return grouped


# ---------------------------------------------------------------------------
# 3.2 Risk Metrics
# ---------------------------------------------------------------------------

def compute_annualized_volatility(monthly_returns: pd.Series) -> float:
    """sigma_monthly * sqrt(12). Assumes i.i.d. (industry convention)."""
    return monthly_returns.std(ddof=1) * np.sqrt(12)


def compute_max_drawdown(equity_curve: pd.Series) -> tuple[float, int]:
    """
    Compute max drawdown and max drawdown duration (calendar days).

    Returns (max_drawdown_pct, max_dd_duration_days).
    max_drawdown_pct is negative (e.g., -0.35 for 35% drawdown).
    """
    if equity_curve.empty:
        return 0.0, 0

    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_dd = drawdown.min()

    # Duration: longest peak-to-recovery period
    in_dd = drawdown < 0
    max_duration_days = 0
    current_start = None

    for i, (date, is_dd) in enumerate(in_dd.items()):
        if is_dd and current_start is None:
            current_start = date
        elif not is_dd and current_start is not None:
            duration = (date - current_start).days
            max_duration_days = max(max_duration_days, duration)
            current_start = None

    # If still in drawdown at the end
    if current_start is not None:
        duration = (equity_curve.index[-1] - current_start).days
        max_duration_days = max(max_duration_days, duration)

    return max_dd, max_duration_days


def compute_max_drawdown_from_returns(monthly_returns: pd.Series) -> float:
    """Compute max drawdown from TWR return series (for validation)."""
    equity = (1 + monthly_returns).cumprod()
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return drawdown.min()


def compute_var(
    monthly_returns: pd.Series,
    confidence: float = 0.95,
    seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, float]:
    """
    Compute Value-at-Risk using historical, Cornish-Fisher, and bootstrap methods.

    Returns dict with keys:
        historical_var, cornish_fisher_var, bootstrap_ci_lower, bootstrap_ci_upper
    """
    alpha = 1 - confidence
    n = len(monthly_returns)
    if n < 5:
        return {
            "historical_var": 0.0,
            "cornish_fisher_var": 0.0,
            "bootstrap_ci_lower": 0.0,
            "bootstrap_ci_upper": 0.0,
        }

    # Historical VaR
    hist_var = np.percentile(monthly_returns, alpha * 100)

    # Cornish-Fisher VaR — requires sufficient sample size for reliable
    # skewness/kurtosis estimates. Fall back to historical for N < 100.
    if n >= 100:
        z = stats.norm.ppf(alpha)
        s = stats.skew(monthly_returns)
        k = stats.kurtosis(monthly_returns)  # excess kurtosis
        z_cf = (
            z
            + (z**2 - 1) * s / 6
            + (z**3 - 3 * z) * k / 24
            - (2 * z**3 - 5 * z) * s**2 / 36
        )
        cf_var = monthly_returns.mean() + z_cf * monthly_returns.std(ddof=1)
    else:
        cf_var = hist_var  # insufficient sample for Cornish-Fisher adjustment

    # Bootstrap 95% CI on historical VaR
    rng = np.random.default_rng(seed)
    bootstrap_vars = []
    for _ in range(1000):
        sample = rng.choice(monthly_returns.values, size=n, replace=True)
        bootstrap_vars.append(np.percentile(sample, alpha * 100))
    ci_lower = np.percentile(bootstrap_vars, 2.5)
    ci_upper = np.percentile(bootstrap_vars, 97.5)

    return {
        "historical_var": hist_var,
        "cornish_fisher_var": cf_var,
        "bootstrap_ci_lower": ci_lower,
        "bootstrap_ci_upper": ci_upper,
    }


def compute_cvar(monthly_returns: pd.Series, confidence: float = 0.95) -> float:
    """CVaR / Expected Shortfall: mean of returns below VaR threshold."""
    alpha = 1 - confidence
    var = np.percentile(monthly_returns, alpha * 100)
    tail = monthly_returns[monthly_returns <= var]
    return tail.mean() if len(tail) > 0 else var


def compute_downside_deviation(
    monthly_returns: pd.Series, risk_free: pd.Series,
) -> float:
    """
    sqrt(1/(N-1) * sum(min(r_i - rf_i, 0)^2))

    Uses ddof=1 (Bessel's correction) for consistency with Sharpe ratio's
    use of std(ddof=1). The plan §3.2 specifies 1/N (population divisor),
    but we use 1/(N-1) to maintain consistent treatment across all
    risk-adjusted ratios. For N=420, the difference is ~0.1%.
    """
    rf_aligned = risk_free.reindex(monthly_returns.index).fillna(0)
    excess = monthly_returns - rf_aligned
    downside = np.minimum(excess, 0)
    n = len(downside)
    if n <= 1:
        return 0.0
    return np.sqrt((downside**2).sum() / (n - 1))


def compute_ulcer_index(equity_curve: pd.Series) -> float:
    """RMS of percentage drawdowns."""
    if equity_curve.empty:
        return 0.0
    running_max = equity_curve.cummax()
    pct_dd = (equity_curve - running_max) / running_max * 100
    return np.sqrt((pct_dd**2).mean())


# ---------------------------------------------------------------------------
# 3.3 Risk-Adjusted Metrics
# ---------------------------------------------------------------------------

def compute_sharpe(
    monthly_returns: pd.Series, risk_free: pd.Series,
) -> float:
    """
    Annualized Sharpe = (mean_excess_monthly * 12) / (std_excess_monthly * sqrt(12))
                      = mean_excess_monthly / std_excess_monthly * sqrt(12)
    """
    rf_aligned = risk_free.reindex(monthly_returns.index).fillna(0)
    excess = monthly_returns - rf_aligned
    if excess.std(ddof=1) == 0:
        return 0.0
    return (excess.mean() / excess.std(ddof=1)) * np.sqrt(12)


def compute_sortino(
    monthly_returns: pd.Series, risk_free: pd.Series,
) -> float:
    """Annualized Sortino = (mean_excess * 12) / (downside_dev * sqrt(12))"""
    rf_aligned = risk_free.reindex(monthly_returns.index).fillna(0)
    excess = monthly_returns - rf_aligned
    dd = compute_downside_deviation(monthly_returns, risk_free)
    if dd == 0:
        return 0.0
    return (excess.mean() * 12) / (dd * np.sqrt(12))


def compute_calmar(
    monthly_returns: pd.Series, equity_curve: pd.Series,
) -> float:
    """CAGR / |MaxDD|"""
    cagr = compute_cagr_twr(monthly_returns)
    max_dd, _ = compute_max_drawdown(equity_curve)
    if max_dd == 0:
        return 0.0
    return cagr / abs(max_dd)


def compute_omega(
    monthly_returns: pd.Series, risk_free: pd.Series,
) -> float:
    """
    Discrete Omega ratio:
        sum(max(r_i - rf, 0)) / sum(max(rf - r_i, 0))
    """
    rf_aligned = risk_free.reindex(monthly_returns.index).fillna(0)
    excess = monthly_returns - rf_aligned
    gains = np.maximum(excess, 0).sum()
    losses = np.maximum(-excess, 0).sum()
    if losses == 0:
        return np.inf if gains > 0 else 1.0
    return gains / losses


def compute_information_ratio(
    monthly_returns: pd.Series, benchmark_returns: pd.Series,
) -> float:
    """(R_p - R_b) / TE, annualized."""
    aligned = pd.DataFrame({
        "port": monthly_returns, "bench": benchmark_returns
    }).dropna()
    if aligned.empty or len(aligned) < 2:
        return 0.0
    active = aligned["port"] - aligned["bench"]
    te = active.std(ddof=1)
    if te == 0:
        return 0.0
    return (active.mean() / te) * np.sqrt(12)


def compute_treynor(
    monthly_returns: pd.Series,
    risk_free: pd.Series,
    benchmark_returns: pd.Series,
) -> float:
    """(R_p - R_f) / beta, annualized."""
    beta = compute_beta(monthly_returns, benchmark_returns)
    if beta == 0:
        return 0.0
    rf_aligned = risk_free.reindex(monthly_returns.index).fillna(0)
    excess = monthly_returns - rf_aligned
    return (excess.mean() * 12) / beta


# ---------------------------------------------------------------------------
# 3.4 Benchmark-Relative Metrics
# ---------------------------------------------------------------------------

def compute_beta(
    monthly_returns: pd.Series, benchmark_returns: pd.Series,
) -> float:
    """Cov(R_p, R_m) / Var(R_m)"""
    aligned = pd.DataFrame({
        "port": monthly_returns, "bench": benchmark_returns
    }).dropna()
    if aligned.empty or len(aligned) < 2:
        return 0.0
    cov = aligned["port"].cov(aligned["bench"])
    var_b = aligned["bench"].var(ddof=1)
    if var_b == 0:
        return 0.0
    return cov / var_b


def compute_alpha(
    monthly_returns: pd.Series,
    risk_free: pd.Series,
    benchmark_returns: pd.Series,
) -> float:
    """Jensen's Alpha = R_p - [R_f + beta * (R_m - R_f)], annualized."""
    beta = compute_beta(monthly_returns, benchmark_returns)
    aligned = pd.DataFrame({
        "port": monthly_returns,
        "bench": benchmark_returns,
        "rf": risk_free.reindex(monthly_returns.index).fillna(0),
    }).dropna()
    if aligned.empty:
        return 0.0
    excess_p = aligned["port"] - aligned["rf"]
    excess_b = aligned["bench"] - aligned["rf"]
    alpha_monthly = excess_p.mean() - beta * excess_b.mean()
    return alpha_monthly * 12


def compute_tracking_error(
    monthly_returns: pd.Series, benchmark_returns: pd.Series,
) -> float:
    """sigma(R_p - R_b), annualized."""
    aligned = pd.DataFrame({
        "port": monthly_returns, "bench": benchmark_returns
    }).dropna()
    if aligned.empty or len(aligned) < 2:
        return 0.0
    active = aligned["port"] - aligned["bench"]
    return active.std(ddof=1) * np.sqrt(12)


def compute_capture_ratios(
    monthly_returns: pd.Series, benchmark_returns: pd.Series,
) -> dict[str, float]:
    """Up and Down capture ratios.

    Convention: arithmetic mean (not geometric/Morningstar convention).
    """
    aligned = pd.DataFrame({
        "port": monthly_returns, "bench": benchmark_returns
    }).dropna()
    if aligned.empty:
        return {"up_capture": 0.0, "down_capture": 0.0}

    up_months = aligned[aligned["bench"] > 0]
    down_months = aligned[aligned["bench"] < 0]

    up_capture = (
        up_months["port"].mean() / up_months["bench"].mean()
        if len(up_months) > 0 and up_months["bench"].mean() != 0
        else 0.0
    )
    down_capture = (
        down_months["port"].mean() / down_months["bench"].mean()
        if len(down_months) > 0 and down_months["bench"].mean() != 0
        else 0.0
    )
    return {"up_capture": up_capture, "down_capture": down_capture}


def compute_hit_rate(
    monthly_returns: pd.Series, benchmark_returns: pd.Series,
) -> float:
    """% of months portfolio outperforms benchmark."""
    aligned = pd.DataFrame({
        "port": monthly_returns, "bench": benchmark_returns
    }).dropna()
    if aligned.empty:
        return 0.0
    return (aligned["port"] > aligned["bench"]).mean()


# ---------------------------------------------------------------------------
# 3.5 Portfolio Characteristics
# ---------------------------------------------------------------------------

def compute_turnover(holdings_history: pd.DataFrame) -> float:
    """
    Monthly average position change (absolute weight change / 2).
    """
    if holdings_history.empty:
        return 0.0

    dates = sorted(holdings_history["date"].unique())
    if len(dates) < 2:
        return 0.0

    turnovers = []
    for i in range(1, len(dates)):
        prev_date = dates[i - 1]
        curr_date = dates[i]

        prev_w = holdings_history[holdings_history["date"] == prev_date].set_index("ticker")["weight"]
        curr_w = holdings_history[holdings_history["date"] == curr_date].set_index("ticker")["weight"]

        all_tickers = set(prev_w.index) | set(curr_w.index)
        weight_changes = sum(
            abs(curr_w.get(t, 0) - prev_w.get(t, 0)) for t in all_tickers
        )
        turnovers.append(weight_changes / 2.0)

    return np.mean(turnovers) if turnovers else 0.0


def compute_hhi(holdings_history: pd.DataFrame) -> pd.Series:
    """
    Herfindahl-Hirschman Index of portfolio weights at each date.
    HHI = sum(w_i^2). Range: 1/N (equal weight) to 1.0 (single stock).
    """
    if holdings_history.empty:
        return pd.Series(dtype=float)

    return holdings_history.groupby("date")["weight"].agg(lambda w: (w**2).sum())


def compute_holdings_count(holdings_history: pd.DataFrame) -> pd.Series:
    """Number of positions at each date."""
    if holdings_history.empty:
        return pd.Series(dtype=int)
    return holdings_history.groupby("date")["ticker"].nunique()


# ---------------------------------------------------------------------------
# Aggregate: compute_metrics
# ---------------------------------------------------------------------------

def compute_metrics(
    twr_returns: pd.Series,
    cash_flows: pd.DataFrame,
    equity_curve: pd.Series,
    benchmark_returns: pd.Series,
    risk_free: pd.Series,
    holdings_history: pd.DataFrame | None = None,
) -> dict[str, float]:
    """
    Compute all section 3 metrics.

    Parameters
    ----------
    twr_returns : monthly TWR sub-period returns (index = date)
    cash_flows : DataFrame [date, amount] for XIRR
    equity_curve : portfolio value time series (index = date)
    benchmark_returns : monthly benchmark returns (index = date)
    risk_free : monthly risk-free rate (index = date)
    holdings_history : DataFrame [date, ticker, shares, value, weight]

    Returns
    -------
    dict of metric_name -> value
    """
    # Filter out initialization month emitted by backtest engine.
    # The engine marks it with _is_init=True (see M3 remediation).
    # Fallback: drop first month if exactly 0.0 and it's the first entry.
    returns = twr_returns
    if hasattr(returns, 'attrs') and returns.attrs.get("has_init_month"):
        returns = returns.iloc[1:]
    elif len(returns) > 0 and returns.iloc[0] == 0.0 and len(returns) > 1:
        returns = returns.iloc[1:]

    metrics = {}

    # --- Construct TWR equity curve for drawdown-related metrics ---
    # This isolates investment returns from contribution cash flows (M5/M6/M7).
    # Dollar equity_curve includes contributions and understates drawdowns.
    twr_equity = (1 + returns).cumprod()
    twr_equity.name = "twr_equity"

    # --- 3.1 Return Metrics ---
    metrics["total_return_twr"] = compute_twr(returns)
    metrics["cagr_twr"] = compute_cagr_twr(returns)
    metrics["xirr"] = compute_xirr(cash_flows)

    # MTD / QTD / YTD (plan §3.1)
    if len(returns) > 0:
        last_date = returns.index[-1]
        # YTD: returns in the current year
        ytd_returns = returns[returns.index.year == last_date.year]
        metrics["ytd"] = compute_twr(ytd_returns)
        # QTD: returns in the current quarter
        current_q = (last_date.month - 1) // 3
        qtd_returns = returns[
            (returns.index.year == last_date.year) &
            (((returns.index.month - 1) // 3) == current_q)
        ]
        metrics["qtd"] = compute_twr(qtd_returns)
        # MTD: return for the current month
        mtd_returns = returns[
            (returns.index.year == last_date.year) &
            (returns.index.month == last_date.month)
        ]
        metrics["mtd"] = compute_twr(mtd_returns)

    # --- 3.2 Risk Metrics ---
    metrics["annualized_volatility"] = compute_annualized_volatility(returns)

    # MaxDD and duration from TWR equity curve (not dollar equity curve)
    max_dd, max_dd_days = compute_max_drawdown(twr_equity)
    metrics["max_drawdown"] = max_dd
    metrics["max_drawdown_duration_days"] = max_dd_days

    var95 = compute_var(returns, confidence=0.95)
    var99 = compute_var(returns, confidence=0.99)
    metrics["var_95_historical"] = var95["historical_var"]
    metrics["var_95_cornish_fisher"] = var95["cornish_fisher_var"]
    metrics["var_95_bootstrap_ci_lower"] = var95["bootstrap_ci_lower"]
    metrics["var_95_bootstrap_ci_upper"] = var95["bootstrap_ci_upper"]
    metrics["var_99_historical"] = var99["historical_var"]
    metrics["var_99_cornish_fisher"] = var99["cornish_fisher_var"]
    metrics["var_99_bootstrap_ci_lower"] = var99["bootstrap_ci_lower"]
    metrics["var_99_bootstrap_ci_upper"] = var99["bootstrap_ci_upper"]

    metrics["cvar_95"] = compute_cvar(returns, confidence=0.95)
    metrics["cvar_99"] = compute_cvar(returns, confidence=0.99)
    metrics["downside_deviation"] = compute_downside_deviation(returns, risk_free)

    # Ulcer Index from TWR equity curve (not dollar equity curve)
    metrics["ulcer_index"] = compute_ulcer_index(twr_equity)

    # --- 3.3 Risk-Adjusted Metrics ---
    metrics["sharpe_ratio"] = compute_sharpe(returns, risk_free)
    metrics["sortino_ratio"] = compute_sortino(returns, risk_free)

    # Calmar uses TWR equity curve for MaxDD (not dollar equity curve)
    metrics["calmar_ratio"] = compute_calmar(returns, twr_equity)

    metrics["omega_ratio"] = compute_omega(returns, risk_free)
    metrics["information_ratio"] = compute_information_ratio(returns, benchmark_returns)
    metrics["treynor_ratio"] = compute_treynor(returns, risk_free, benchmark_returns)

    # --- 3.4 Benchmark-Relative Metrics ---
    metrics["alpha"] = compute_alpha(returns, risk_free, benchmark_returns)
    metrics["beta"] = compute_beta(returns, benchmark_returns)
    metrics["tracking_error"] = compute_tracking_error(returns, benchmark_returns)
    capture = compute_capture_ratios(returns, benchmark_returns)
    metrics["up_capture"] = capture["up_capture"]
    metrics["down_capture"] = capture["down_capture"]
    metrics["hit_rate"] = compute_hit_rate(returns, benchmark_returns)

    # --- 3.5 Portfolio Characteristics ---
    if holdings_history is not None and not holdings_history.empty:
        metrics["avg_turnover"] = compute_turnover(holdings_history)
        hhi = compute_hhi(holdings_history)
        metrics["avg_hhi"] = hhi.mean() if len(hhi) > 0 else 0.0
        hcount = compute_holdings_count(holdings_history)
        metrics["avg_holdings"] = hcount.mean() if len(hcount) > 0 else 0.0

    return metrics


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Quick validation with synthetic data
    np.random.seed(DEFAULT_RANDOM_SEED)
    n = 60
    dates = pd.date_range("2020-01-31", periods=n, freq="ME")
    monthly_r = pd.Series(np.random.normal(0.008, 0.04, n), index=dates)
    equity = (1 + monthly_r).cumprod() * 10000
    bench_r = pd.Series(np.random.normal(0.007, 0.035, n), index=dates)
    rf = pd.Series(0.003, index=dates)

    cf = pd.DataFrame([
        {"date": dates[0], "amount": -10000},
        *[{"date": d, "amount": -1000} for d in dates[1:]],
        {"date": dates[-1], "amount": equity.iloc[-1]},
    ])

    m = compute_metrics(monthly_r, cf, equity, bench_r, rf)
    print("=== Metrics (synthetic 5yr data) ===")
    for k, v in sorted(m.items()):
        if isinstance(v, float):
            print(f"  {k}: {v:.6f}")
        else:
            print(f"  {k}: {v}")
