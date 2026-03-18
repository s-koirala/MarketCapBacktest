"""
app.py — Streamlit dashboard for MarketCapBacktest.

Single-page app with sidebar controls. Implements all charts and tables
with institutional-grade styling, tabbed layout, and consistent color palette.

Run: streamlit run scripts/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Ensure scripts dir is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    BENCHMARKS,
    COST_SCHEDULE_BPS,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_MONTHLY_CONTRIBUTION,
    RESULTS_DIR,
    STRATEGY3_K_LOOKBACK,
    STRATEGY3_N_CANDIDATES,
)
from backtest_engine import (
    BacktestResult,
    make_momentum_fn,
    make_top1_fn,
    make_topn_fn,
    run_backtest,
)
from metrics import (
    compute_annual_returns,
    compute_metrics,
    compute_twr,
)

# ---------------------------------------------------------------------------
# A. COLOR PALETTE
# ---------------------------------------------------------------------------

COLORS = {
    'strategy_1': '#1f77b4',   # Blue — Top-1
    'strategy_2': '#ff7f0e',   # Orange — Top-N Equal Weight
    'strategy_3': '#2ca02c',   # Green — Log-Momentum
    'sp500':      '#7f7f7f',   # Gray
    'nasdaq':     '#bcbd22',   # Olive
    'gold':       '#d4a84b',   # Gold
    'es':         '#9e9e9e',   # Light gray
    'positive':   '#2ca02c',
    'negative':   '#d62728',
    'grid':       '#e8e8e8',
}

# Map series names to colors (populated dynamically below)
COLOR_MAP = {}

FINANCIAL_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Inter, Arial, sans-serif", size=12, color="#333"),
    plot_bgcolor="white",
    paper_bgcolor="white",
    xaxis=dict(showgrid=False, showline=True, linecolor="#ccc", tickfont=dict(size=10)),
    yaxis=dict(showgrid=True, gridcolor="#e8e8e8", gridwidth=0.5, showline=False,
               tickfont=dict(size=10), zerolinecolor="#999", zerolinewidth=1),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                bgcolor="rgba(255,255,255,0)", font=dict(size=10)),
    margin=dict(l=60, r=20, t=40, b=40),
    hovermode="x unified",
)

METRIC_LABELS = {
    "cagr_twr": "CAGR (TWR)", "total_return_twr": "Total Return (TWR)",
    "cagr_mwr": "CAGR (MWR)", "xirr": "XIRR",
    "annualized_volatility": "Volatility (Ann.)",
    "sharpe_ratio": "Sharpe Ratio", "sortino_ratio": "Sortino Ratio",
    "calmar_ratio": "Calmar Ratio", "omega_ratio": "Omega Ratio",
    "max_drawdown": "Max Drawdown", "max_drawdown_duration_days": "Max DD Duration (days)",
    "ulcer_index": "Ulcer Index", "treynor_ratio": "Treynor Ratio",
    "var_95_historical": "VaR 95% (Hist.)", "cvar_95": "CVaR 95%",
    "var_99_historical": "VaR 99% (Hist.)", "cvar_99": "CVaR 99%",
    "var_95_cornish_fisher": "VaR 95% (C-F)", "var_99_cornish_fisher": "VaR 99% (C-F)",
    "var_95_bootstrap_ci_lower": "VaR 95% CI Lower", "var_95_bootstrap_ci_upper": "VaR 95% CI Upper",
    "var_99_bootstrap_ci_lower": "VaR 99% CI Lower", "var_99_bootstrap_ci_upper": "VaR 99% CI Upper",
    "alpha": "Alpha (Ann.)", "beta": "Beta",
    "tracking_error": "Tracking Error", "information_ratio": "Information Ratio",
    "up_capture": "Up Capture", "down_capture": "Down Capture",
    "hit_rate": "Hit Rate",
    "avg_turnover": "Avg Turnover", "avg_hhi": "Avg HHI", "avg_holdings": "Avg Holdings",
    "downside_deviation": "Downside Deviation",
    "ytd": "YTD", "qtd": "QTD", "mtd": "MTD",
}

FORMAT_MAP = {
    "total_return_twr": "{:.2%}", "cagr_twr": "{:.2%}", "xirr": "{:.2%}",
    "annualized_volatility": "{:.2%}", "max_drawdown": "{:.2%}",
    "max_drawdown_duration_days": "{:,.0f}",
    "sharpe_ratio": "{:.3f}", "sortino_ratio": "{:.3f}", "calmar_ratio": "{:.3f}",
    "omega_ratio": "{:.3f}", "information_ratio": "{:.3f}", "treynor_ratio": "{:.4f}",
    "alpha": "{:.4f}", "beta": "{:.3f}", "tracking_error": "{:.2%}",
    "up_capture": "{:.2f}", "down_capture": "{:.2f}", "hit_rate": "{:.2%}",
    "var_95_historical": "{:.2%}", "var_99_historical": "{:.2%}",
    "var_95_cornish_fisher": "{:.2%}", "var_99_cornish_fisher": "{:.2%}",
    "var_95_bootstrap_ci_lower": "{:.2%}", "var_95_bootstrap_ci_upper": "{:.2%}",
    "var_99_bootstrap_ci_lower": "{:.2%}", "var_99_bootstrap_ci_upper": "{:.2%}",
    "cvar_95": "{:.2%}", "cvar_99": "{:.2%}",
    "downside_deviation": "{:.4f}", "ulcer_index": "{:.2f}",
    "ytd": "{:.2%}", "qtd": "{:.2%}", "mtd": "{:.2%}",
    "avg_turnover": "{:.2%}", "avg_hhi": "{:.4f}", "avg_holdings": "{:.1f}",
}

# Metrics grouped by category for display
METRIC_GROUPS = {
    "Returns": ["cagr_twr", "total_return_twr", "xirr", "ytd", "qtd", "mtd"],
    "Risk": ["annualized_volatility", "max_drawdown", "max_drawdown_duration_days",
             "var_95_historical", "cvar_95", "var_99_historical", "cvar_99",
             "var_95_cornish_fisher", "var_99_cornish_fisher", "ulcer_index", "downside_deviation"],
    "Risk-Adjusted": ["sharpe_ratio", "sortino_ratio", "calmar_ratio", "omega_ratio", "treynor_ratio"],
    "Benchmark-Relative": ["alpha", "beta", "tracking_error", "information_ratio",
                           "up_capture", "down_capture", "hit_rate"],
    "Portfolio": ["avg_turnover", "avg_hhi", "avg_holdings"],
}

# Metrics where the benchmark's self-relative values should show "---"
BENCHMARK_SELF_RELATIVE_METRICS = {
    "alpha", "beta", "tracking_error", "information_ratio",
    "up_capture", "down_capture", "hit_rate", "treynor_ratio",
}

# Metrics where LOWER is better (for conditional formatting)
LOWER_IS_BETTER = {"max_drawdown", "max_drawdown_duration_days", "annualized_volatility",
                   "var_95_historical", "var_99_historical", "cvar_95", "cvar_99",
                   "var_95_cornish_fisher", "var_99_cornish_fisher",
                   "ulcer_index", "downside_deviation", "down_capture",
                   "var_95_bootstrap_ci_lower", "var_95_bootstrap_ci_upper",
                   "var_99_bootstrap_ci_lower", "var_99_bootstrap_ci_upper"}


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Market Cap Backtest", layout="wide")

# ---------------------------------------------------------------------------
# B. CUSTOM CSS
# ---------------------------------------------------------------------------
# SECURITY NOTE: This CSS block is static. Do NOT interpolate user input
# into this string — doing so would create an XSS vulnerability.
st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 12px 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    div[data-testid="stMetricLabel"] { font-size: 0.85rem; color: #6c757d; font-weight: 500; }
    div[data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; color: #212529; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 20px; font-weight: 500; }
    .dataframe { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

st.title("Market-Cap Weighted Portfolio Backtest")
st.caption(
    "Market cap estimates use current shares outstanding adjusted for splits only. "
    "Buybacks, secondary offerings, and corporate actions (mergers/spin-offs) are not reflected, "
    "which may cause historical ranking inaccuracies for companies with significant share count changes."
)

# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading market data...", ttl=3600)
def load_data():
    from data_fetcher import fetch_all
    from market_cap_estimator import estimate_market_caps, rank_by_market_cap
    data = fetch_all(use_cache=True)
    mcaps = estimate_market_caps(
        data["prices"], data["splits"], data["shares_outstanding"], data["delisted"]
    )
    rankings = rank_by_market_cap(mcaps)
    return data, mcaps, rankings

# Cache correctness requires strategy_name to be unique per strategy.
# The underscore-prefixed params (_strategy_fn, _prices, etc.) are excluded
# from the cache key; strategy_name differentiates cached results.
@st.cache_data(show_spinner="Running backtest...", max_entries=20, ttl=3600)
def run_cached_backtest(
    _strategy_fn, _prices, _rankings, _market_caps, _risk_free,
    initial_capital, monthly_contribution, cost_schedule,
    start_date, end_date, strategy_name,
):
    return run_backtest(
        strategy_fn=_strategy_fn, prices=_prices, rankings=_rankings,
        market_caps=_market_caps, risk_free=_risk_free,
        initial_capital=initial_capital, monthly_contribution=monthly_contribution,
        cost_schedule=cost_schedule, start_date=start_date, end_date=end_date,
        strategy_name=strategy_name,
    )

# ---------------------------------------------------------------------------
# Helper: clean TWR returns (drop init month if present)
# ---------------------------------------------------------------------------
def _clean_twr(twr: pd.Series) -> pd.Series:
    if len(twr) > 1 and twr.iloc[0] == 0:
        return twr.iloc[1:]
    return twr

# ---------------------------------------------------------------------------
# C. SIDEBAR CONTROLS
# ---------------------------------------------------------------------------

st.sidebar.header("Backtest Parameters")

import datetime

col_start, col_end = st.sidebar.columns(2)
start_date_input = col_start.date_input(
    "Start Date", value=datetime.date(1990, 1, 1),
    min_value=datetime.date(1990, 1, 1), max_value=datetime.date(2030, 12, 31),
)
end_date_input = col_end.date_input(
    "End Date", value=datetime.date.today(),
    min_value=datetime.date(1990, 1, 1), max_value=datetime.date(2030, 12, 31),
)

# Convert date_input values to the YYYY-MM strings the backtest engine expects
start_date = start_date_input.strftime("%Y-%m")
end_date = end_date_input.strftime("%Y-%m")

if start_date_input >= end_date_input:
    st.error("Start date must be before end date.")
    st.stop()

st.sidebar.subheader("Capital")
initial_capital = st.sidebar.number_input(
    "Starting Amount ($)", value=DEFAULT_INITIAL_CAPITAL, step=1000.0, min_value=0.0,
)
monthly_contribution = st.sidebar.number_input(
    "Monthly Addition ($)", value=DEFAULT_MONTHLY_CONTRIBUTION, step=100.0, min_value=0.0,
)

st.sidebar.header("Strategy Selection")
run_s1 = st.sidebar.checkbox("Strategy 1: Top-1 Market Cap", value=True)
run_s2 = st.sidebar.checkbox("Strategy 2: Top-N Equal Weight", value=True)
s2_n = st.sidebar.slider("Strategy 2: N", min_value=2, max_value=5, value=3) if run_s2 else 3
run_s3 = st.sidebar.checkbox("Strategy 3: Momentum-Weighted", value=False)
if run_s3:
    s3_use_optimized = st.sidebar.checkbox("Use optimized parameters", value=True)
    if s3_use_optimized:
        gs_path = RESULTS_DIR / "grid_search_results.csv"
        if gs_path.exists():
            gs = pd.read_csv(gs_path)
            selected = gs[gs.get("selected", False) == True]
            if not selected.empty:
                s3_n = int(selected.iloc[0]["n_candidates"])
                s3_k = int(selected.iloc[0]["k_lookback"])
                st.sidebar.info(f"Optimized: N={s3_n}, k={s3_k}")
            else:
                s3_n, s3_k = 5, 6
                st.sidebar.warning("No optimized params found. Using N=5, k=6.")
        else:
            s3_n, s3_k = 5, 6
            st.sidebar.warning("Grid search not run. Using N=5, k=6.")
    else:
        s3_n = st.sidebar.select_slider("N candidates", options=STRATEGY3_N_CANDIDATES, value=5)
        s3_k = st.sidebar.select_slider("k lookback (months)", options=STRATEGY3_K_LOOKBACK, value=6)
else:
    s3_n, s3_k = 5, 6

st.sidebar.header("Benchmarks")
bench_toggles = {}
for name in sorted(BENCHMARKS.keys()):
    bench_toggles[name] = st.sidebar.checkbox(name, value=(name == "S&P 500"))

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

try:
    data, mcaps, rankings = load_data()
except Exception as e:
    st.error(f"Failed to load market data: {e}")
    st.info("If running on Streamlit Cloud, ensure cached parquet files exist in the results/ directory. "
            "Run `python scripts/data_fetcher.py` locally to generate them, then commit to the repo.")
    st.stop()

# Data freshness indicator
manifest_path = RESULTS_DIR / "data_manifest.json"
if manifest_path.exists():
    import json
    with open(manifest_path) as f:
        manifest = json.load(f)
    if manifest:
        first_entry = next(iter(manifest.values()))
        fetch_date = first_entry.get("fetch_date", "unknown")
        st.sidebar.caption(f"Data cached: {fetch_date[:10]}")

rf = data["risk_free"]
if isinstance(rf, pd.DataFrame):
    rf = rf.set_index("date")["rf_monthly"] if "date" in rf.columns else rf.iloc[:, 0]

# ---------------------------------------------------------------------------
# Parse date range for filtering
# ---------------------------------------------------------------------------

start_ts = pd.Timestamp(f"{start_date}-01")
end_ts = pd.Timestamp(f"{end_date}-01") + pd.offsets.MonthEnd(0)

def _filter_to_range(s: pd.Series) -> pd.Series:
    """Filter a date-indexed series to the user's selected date range."""
    out = s
    if start_ts is not None:
        out = out[out.index >= start_ts]
    if end_ts is not None:
        out = out[out.index <= end_ts]
    return out

# ---------------------------------------------------------------------------
# Run strategy backtests
# ---------------------------------------------------------------------------

strategy_results: dict[str, BacktestResult] = {}

if run_s1:
    strategy_results["Top-1"] = run_cached_backtest(
        make_top1_fn(), data["prices"], rankings, mcaps,
        data["risk_free"], initial_capital, monthly_contribution,
        COST_SCHEDULE_BPS, start_date, end_date, "Top-1 Market Cap",
    )
if run_s2:
    strategy_results[f"Top-{s2_n} EW"] = run_cached_backtest(
        make_topn_fn(s2_n), data["prices"], rankings, mcaps,
        data["risk_free"], initial_capital, monthly_contribution,
        COST_SCHEDULE_BPS, start_date, end_date, f"Top-{s2_n} Equal Weight",
    )
if run_s3:
    strategy_results[f"Momentum(N={s3_n},k={s3_k})"] = run_cached_backtest(
        make_momentum_fn(s3_n, s3_k), data["prices"], rankings, mcaps,
        data["risk_free"], initial_capital, monthly_contribution,
        COST_SCHEDULE_BPS, start_date, end_date,
        f"Momentum (N={s3_n}, k={s3_k})",
    )

if not strategy_results and not any(bench_toggles.values()):
    st.warning("Select at least one strategy or benchmark.")
    st.stop()

# ---------------------------------------------------------------------------
# Build benchmark return series (filtered to date range)
# ---------------------------------------------------------------------------

bench_returns_dict: dict[str, pd.Series] = {}
bench_data = data.get("benchmarks")
if bench_data is not None and not bench_data.empty:
    for name, enabled in bench_toggles.items():
        if not enabled:
            continue
        b = bench_data[bench_data["benchmark"] == name].copy()
        if b.empty:
            continue
        b = b.set_index("date").sort_index()
        b["return"] = b["adj_close"].pct_change()
        ret = b["return"].dropna()
        ret = _filter_to_range(ret)
        if not ret.empty:
            bench_returns_dict[name] = ret

# ---------------------------------------------------------------------------
# Unified return series dict: strategies + benchmarks
# ---------------------------------------------------------------------------

all_twr: dict[str, pd.Series] = {}
all_equity: dict[str, pd.Series] = {}
is_benchmark: dict[str, bool] = {}

for name, res in strategy_results.items():
    twr = _clean_twr(res.twr_returns)
    all_twr[name] = twr
    all_equity[name] = res.equity_curve
    is_benchmark[name] = False

for bname, bret in bench_returns_dict.items():
    all_twr[bname] = bret
    values = [initial_capital]
    for j, r in enumerate(bret.values):
        prev = values[-1]
        contrib = monthly_contribution if j > 0 else 0.0
        new_val = prev * (1 + r) + contrib
        values.append(new_val)
    bench_eq = pd.Series(values[1:], index=bret.index, name=bname)
    all_equity[bname] = bench_eq
    is_benchmark[bname] = True

if not all_twr:
    st.warning("No data to display for the selected date range.")
    st.stop()

# ---------------------------------------------------------------------------
# Build COLOR_MAP dynamically
# ---------------------------------------------------------------------------

_strategy_color_list = [COLORS['strategy_1'], COLORS['strategy_2'], COLORS['strategy_3']]
_bench_color_map = {
    'S&P 500': COLORS['sp500'],
    'Nasdaq 100': COLORS['nasdaq'],
    'NQ': COLORS['nasdaq'],
    'Gold': COLORS['gold'],
    'ES': COLORS['es'],
}

_strat_idx = 0
for name in all_twr:
    if not is_benchmark.get(name, False):
        COLOR_MAP[name] = _strategy_color_list[_strat_idx % len(_strategy_color_list)]
        _strat_idx += 1
    else:
        COLOR_MAP[name] = _bench_color_map.get(name, '#999999')

# ---------------------------------------------------------------------------
# Compute metrics for ALL series (strategies + benchmarks)
# ---------------------------------------------------------------------------

primary_bench_key = None
for bname in bench_returns_dict:
    primary_bench_key = bname
    break
primary_bench_returns = bench_returns_dict.get(primary_bench_key, pd.Series(dtype=float)) if primary_bench_key else pd.Series(dtype=float)

all_metrics: dict[str, dict] = {}
for name, twr in all_twr.items():
    if twr.empty:
        continue
    eq = all_equity.get(name, (1 + twr).cumprod())

    # D. FIX XIRR CASH FLOWS
    if name in strategy_results:
        cf = strategy_results[name].cash_flows
    else:
        # Benchmark: build full monthly cash flow series
        cf_rows = [{"date": twr.index[0], "amount": -initial_capital}]
        for d in twr.index[1:]:
            cf_rows.append({"date": d, "amount": -monthly_contribution})
        cf_rows.append({"date": twr.index[-1], "amount": eq.iloc[-1]})
        cf = pd.DataFrame(cf_rows)

    hh = strategy_results[name].holdings_history if name in strategy_results else None
    bench_for_metric = primary_bench_returns if not is_benchmark.get(name) else pd.Series(dtype=float)
    m = compute_metrics(
        twr_returns=twr, cash_flows=cf, equity_curve=eq,
        benchmark_returns=bench_for_metric, risk_free=rf,
        holdings_history=hh,
    )
    all_metrics[name] = m

# ---------------------------------------------------------------------------
# Helper: line style for benchmarks vs strategies
# ---------------------------------------------------------------------------
def _line_kwargs(name: str) -> dict:
    color = COLOR_MAP.get(name, '#333')
    if is_benchmark.get(name, False):
        return dict(line=dict(dash="dash", width=1.5, color=color))
    return dict(line=dict(width=2, color=color))

# ---------------------------------------------------------------------------
# Helpers for applying consistent layout
# ---------------------------------------------------------------------------
def _apply_layout(fig, height=500, **kwargs):
    """Apply FINANCIAL_LAYOUT plus any overrides to a figure."""
    layout = {**FINANCIAL_LAYOUT, "height": height}
    layout.update(kwargs)
    fig.update_layout(**layout)
    return fig

# =========================================================================
# E.1 KPI TILES ROW
# =========================================================================

# Use the first selected strategy's metrics for KPIs
first_strat_name = next((n for n in all_twr if not is_benchmark.get(n)), None)
sp500_metrics = all_metrics.get("S&P 500", {})

if first_strat_name and first_strat_name in all_metrics:
    m = all_metrics[first_strat_name]
    kpi_cols = st.columns(5)

    # CAGR
    cagr_val = m.get("cagr_twr", 0)
    cagr_delta = None
    if sp500_metrics:
        cagr_delta = f"{(cagr_val - sp500_metrics.get('cagr_twr', 0)):.1%} vs S&P"
    kpi_cols[0].metric("CAGR (TWR)", f"{cagr_val:.1%}", delta=cagr_delta)

    # Sharpe
    sharpe_val = m.get("sharpe_ratio", 0)
    sharpe_delta = None
    if sp500_metrics:
        sharpe_delta = f"{(sharpe_val - sp500_metrics.get('sharpe_ratio', 0)):+.2f} vs S&P"
    kpi_cols[1].metric("Sharpe Ratio", f"{sharpe_val:.2f}", delta=sharpe_delta)

    # Max Drawdown
    dd_val = m.get("max_drawdown", 0)
    dd_delta = None
    if sp500_metrics:
        dd_delta = f"{(dd_val - sp500_metrics.get('max_drawdown', 0)):+.1%} vs S&P"
    kpi_cols[2].metric("Max Drawdown", f"{dd_val:.1%}", delta=dd_delta, delta_color="inverse")

    # Sortino
    sortino_val = m.get("sortino_ratio", 0)
    sortino_delta = None
    if sp500_metrics:
        sortino_delta = f"{(sortino_val - sp500_metrics.get('sortino_ratio', 0)):+.2f} vs S&P"
    kpi_cols[3].metric("Sortino Ratio", f"{sortino_val:.2f}", delta=sortino_delta)

    # Final Value
    eq = all_equity.get(first_strat_name)
    final_val = eq.iloc[-1] if eq is not None and len(eq) > 0 else 0
    kpi_cols[4].metric("Final Value", f"${final_val:,.0f}")

# =========================================================================
# E.1b STRATEGY DEFINITIONS
# =========================================================================

with st.expander("Strategy Definitions", expanded=False):
    st.markdown("""
**Top-1 Market Cap** — Invests 100% in the single largest company by market capitalization. Rebalances monthly.

**Top-N Equal Weight** — Invests equally across the top N companies by market cap. Rebalances monthly to maintain equal weights.

**Log-Momentum** — Ranks top N companies by market cap, then scores each by log momentum
`log(M(t) / M(t-k))` where M is market cap and k is the lookback period in months.
Allocates proportionally to positive momentum scores.
If only one company has positive momentum, it receives 100%.
If none have positive momentum, falls back to equal weight across all N candidates.
""")

# =========================================================================
# E.2 TABBED LAYOUT
# =========================================================================

tab_perf, tab_risk, tab_compare, tab_detail, tab_holdings = st.tabs(
    ["Performance", "Risk", "Comparison", "Details", "Holdings"]
)

strat_names = list(strategy_results.keys())

# =========================================================================
# TAB: Performance
# =========================================================================
with tab_perf:
    # --- Equity curve + Drawdown as subplots ---
    st.subheader("Equity Curve & Drawdown")

    log_scale = st.checkbox("Log scale (equity curve)", value=True, key="log_toggle")

    fig_eq_dd = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
        subplot_titles=("Portfolio Value", "Drawdown"),
    )

    for name, eq in all_equity.items():
        color = COLOR_MAP.get(name, '#333')
        dash = "dash" if is_benchmark.get(name, False) else None
        width = 1.5 if is_benchmark.get(name, False) else 2
        fig_eq_dd.add_trace(go.Scatter(
            x=eq.index, y=eq.values, mode="lines", name=name,
            line=dict(color=color, dash=dash, width=width),
            legendgroup=name, showlegend=True,
        ), row=1, col=1)

    for name, twr in all_twr.items():
        if twr.empty:
            continue
        eq_twr = (1 + twr).cumprod()
        dd = (eq_twr - eq_twr.cummax()) / eq_twr.cummax()
        color = COLOR_MAP.get(name, '#333')
        fig_eq_dd.add_trace(go.Scatter(
            x=dd.index, y=dd.values, mode="lines", name=name,
            line=dict(color=color, width=1),
            fill="tozeroy",
            fillcolor=f"rgba({int(color[1:3], 16)},{int(color[3:5], 16)},{int(color[5:7], 16)},0.15)",
            legendgroup=name, showlegend=False,
        ), row=2, col=1)

    if log_scale:
        fig_eq_dd.update_yaxes(type="log", row=1, col=1)
    fig_eq_dd.update_yaxes(title_text="Portfolio Value ($)", tickprefix="$", tickformat=",.0f", row=1, col=1)
    fig_eq_dd.update_yaxes(title_text="Drawdown", tickformat=".0%", row=2, col=1)
    fig_eq_dd.update_xaxes(tickformat="%Y", row=2, col=1)
    _apply_layout(fig_eq_dd, height=650)
    st.plotly_chart(fig_eq_dd, width="stretch")

    # H. BENCHMARK COST ASYMMETRY NOTICE
    st.caption("Note: Strategy returns are net of transaction costs (10-50 bps time-varying). "
               "Benchmark returns are gross (no transaction costs applied).")

    # --- Monthly Returns Heatmap ---
    st.subheader("Monthly Returns Heatmap")
    hm_options = list(all_twr.keys())
    heatmap_selection = st.selectbox("Series for heatmap", hm_options, key="hm_sel")
    ret_sel = all_twr.get(heatmap_selection, pd.Series(dtype=float))

    if not ret_sel.empty:
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        hm_df = pd.DataFrame({
            "year": ret_sel.index.year, "month": ret_sel.index.month,
            "return": ret_sel.values * 100,
        })
        hm_pivot = hm_df.pivot_table(index="year", columns="month", values="return", aggfunc="mean")
        hm_pivot.columns = [month_names[int(c) - 1] for c in hm_pivot.columns]

        fig_hm = px.imshow(
            hm_pivot, color_continuous_scale="RdYlGn", aspect="auto",
            labels=dict(color="Return (%)"),
        )
        fig_hm.update_layout(height=max(400, len(hm_pivot) * 28))
        _apply_layout(fig_hm, height=max(400, len(hm_pivot) * 28))
        st.plotly_chart(fig_hm, width="stretch")

    # --- Annual Returns Table ---
    st.subheader("Annual Returns")
    annual_data = {}
    for name, twr in all_twr.items():
        if not twr.empty:
            annual_data[name] = compute_annual_returns(twr)

    if annual_data:
        annual_df = pd.DataFrame(annual_data)
        annual_df.index.name = "Year"
        # Add average row
        avg_row = annual_df.mean()
        avg_row.name = "Average"
        annual_df = pd.concat([annual_df, avg_row.to_frame().T])
        st.dataframe(
            annual_df.style.format("{:.2%}"),
            width="stretch",
        )

# =========================================================================
# TAB: Risk
# =========================================================================
with tab_risk:
    # --- Rolling 12-Month Sharpe ---
    st.subheader("Rolling 12-Month Sharpe Ratio")
    fig_rs = go.Figure()
    for name, twr in all_twr.items():
        if len(twr) < 12:
            continue
        rf_aligned = rf.reindex(twr.index).fillna(0)
        excess = twr - rf_aligned
        rolling_sharpe = (
            (excess.rolling(12).mean() / excess.rolling(12).std(ddof=1)) * np.sqrt(12)
        ).dropna()
        color = COLOR_MAP.get(name, '#333')
        dash = "dash" if is_benchmark.get(name, False) else None
        fig_rs.add_trace(go.Scatter(
            x=rolling_sharpe.index, y=rolling_sharpe.values, mode="lines",
            name=name, line=dict(color=color, dash=dash, width=1.5 if dash else 2),
        ))

    fig_rs.update_yaxes(title="Sharpe Ratio")
    fig_rs.update_xaxes(tickformat="%Y")
    _apply_layout(fig_rs, height=400)
    st.plotly_chart(fig_rs, width="stretch")

    # --- Return Distribution with VaR/CVaR for ALL strategies ---
    st.subheader("Return Distribution")
    fig_dist = go.Figure()
    for name, twr in all_twr.items():
        if twr.empty:
            continue
        color = COLOR_MAP.get(name, '#333')
        fig_dist.add_trace(go.Histogram(
            x=twr.values * 100, name=name, opacity=0.6, nbinsx=50,
            marker_color=color,
        ))

    # VaR/CVaR markers for ALL strategies (not just first)
    var_colors_used = []
    for name in all_twr:
        if is_benchmark.get(name):
            continue
        m = all_metrics.get(name, {})
        var95 = m.get("var_95_historical", 0) * 100
        cvar95 = m.get("cvar_95", 0) * 100
        color = COLOR_MAP.get(name, '#333')
        if var95 != 0:
            fig_dist.add_vline(
                x=var95, line_dash="dash", line_color=color,
                annotation_text=f"VaR95 {name}: {var95:.1f}%",
                annotation_font_size=9,
            )
        if cvar95 != 0:
            fig_dist.add_vline(
                x=cvar95, line_dash="dot", line_color=color,
                annotation_text=f"CVaR95 {name}: {cvar95:.1f}%",
                annotation_font_size=9,
            )

    fig_dist.update_xaxes(title="Monthly Return (%)")
    fig_dist.update_yaxes(title="Count")
    _apply_layout(fig_dist, height=400, barmode="overlay")
    st.plotly_chart(fig_dist, width="stretch")

    # --- Rolling Benchmark Correlation ---
    if bench_returns_dict and strat_names:
        st.subheader("Rolling 12-Month Benchmark Correlation")
        corr_strategy = st.selectbox("Strategy for correlation", strat_names, key="corr")
        ret_corr = all_twr.get(corr_strategy, pd.Series(dtype=float))

        fig_corr = go.Figure()
        for bname, bret in bench_returns_dict.items():
            aligned = pd.DataFrame({"strat": ret_corr, "bench": bret}).dropna()
            if len(aligned) < 12:
                continue
            rolling_corr = aligned["strat"].rolling(12).corr(aligned["bench"]).dropna()
            color = COLOR_MAP.get(bname, '#999')
            fig_corr.add_trace(go.Scatter(
                x=rolling_corr.index, y=rolling_corr.values, mode="lines",
                name=bname, line=dict(color=color),
            ))

        fig_corr.update_yaxes(title="Correlation", range=[-1, 1])
        fig_corr.update_xaxes(tickformat="%Y")
        _apply_layout(fig_corr, height=400)
        st.plotly_chart(fig_corr, width="stretch")

# =========================================================================
# TAB: Comparison
# =========================================================================
with tab_compare:
    st.caption("⚠ Strategy returns are net of transaction costs (10-50 bps). Benchmark returns are gross. "
               "Comparative metrics (alpha, hit rate, capture ratios) reflect this asymmetry.")
    # --- Strategy Comparison: Faceted Subplots ---
    if len(all_metrics) > 1:
        st.subheader("Strategy & Benchmark Comparison")

        compare_keys = ["cagr_twr", "sharpe_ratio", "max_drawdown", "sortino_ratio", "calmar_ratio"]
        compare_labels = ["CAGR", "Sharpe", "Max DD", "Sortino", "Calmar"]

        fig_comp = make_subplots(
            rows=1, cols=len(compare_keys),
            subplot_titles=compare_labels,
        )

        series_names = list(all_metrics.keys())
        for si, sname in enumerate(series_names):
            m = all_metrics[sname]
            color = COLOR_MAP.get(sname, '#333')
            for ci, mk in enumerate(compare_keys):
                val = m.get(mk, 0)
                fig_comp.add_trace(go.Bar(
                    x=[sname], y=[val], name=sname,
                    marker_color=color,
                    showlegend=(ci == 0),
                    legendgroup=sname,
                ), row=1, col=ci + 1)

        for ci, mk in enumerate(compare_keys):
            fmt = ".1%" if mk in ("cagr_twr", "max_drawdown") else ".2f"
            fig_comp.update_yaxes(tickformat=fmt, row=1, col=ci + 1)

        _apply_layout(fig_comp, height=400)
        fig_comp.update_layout(barmode="group")
        st.plotly_chart(fig_comp, width="stretch")

    # --- Full Metrics Comparison Table (transposed: metrics as rows) ---
    st.subheader("Full Metrics Comparison")

    metrics_table = pd.DataFrame(all_metrics)  # columns = series names, rows = metric keys

    # For each group, show a sub-table in an expander
    for group_name, group_keys in METRIC_GROUPS.items():
        # Filter to keys that actually exist in the metrics
        available_keys = [k for k in group_keys if k in metrics_table.index]
        if not available_keys:
            continue

        with st.expander(group_name, expanded=True):
            sub_df = metrics_table.loc[available_keys].copy()

            # Rename index to human-readable labels
            sub_df.index = [METRIC_LABELS.get(k, k) for k in available_keys]

            # For benchmark columns, mask self-relative metrics with "---"
            for col in sub_df.columns:
                if is_benchmark.get(col, False):
                    for orig_key, label in zip(available_keys, sub_df.index):
                        if orig_key in BENCHMARK_SELF_RELATIVE_METRICS:
                            sub_df.at[label, col] = np.nan

            # Build format dict for styler using human-readable labels
            styler_format = {}
            for k in available_keys:
                label = METRIC_LABELS.get(k, k)
                if k in FORMAT_MAP:
                    styler_format[label] = FORMAT_MAP[k]

            # Style the sub-table
            def _highlight_best_worst(row):
                """Highlight best green, worst red per row."""
                numeric_vals = pd.to_numeric(row, errors='coerce')
                if numeric_vals.isna().all():
                    return [''] * len(row)

                # Determine the original metric key for this row
                row_label = row.name
                orig_key = None
                for k, v in METRIC_LABELS.items():
                    if v == row_label:
                        orig_key = k
                        break

                styles = [''] * len(row)
                valid = numeric_vals.dropna()
                if valid.empty:
                    return styles

                if orig_key and orig_key in LOWER_IS_BETTER:
                    best_val = valid.min()
                    worst_val = valid.max()
                else:
                    best_val = valid.max()
                    worst_val = valid.min()

                for i, (idx, val) in enumerate(numeric_vals.items()):
                    if pd.isna(val):
                        styles[i] = 'color: #999'
                    elif val == best_val and len(valid) > 1:
                        styles[i] = 'background-color: #d4edda; font-weight: bold'
                    elif val == worst_val and len(valid) > 1:
                        styles[i] = 'background-color: #f8d7da'
                return styles

            # Build the row-level format dict for Styler
            # Styler.format() expects column-keyed or a callable
            def _format_cell(val, key=None):
                if pd.isna(val):
                    return "---"
                fmt = FORMAT_MAP.get(key, "{:.4f}")
                try:
                    return fmt.format(val)
                except (ValueError, TypeError):
                    return str(val)

            # Apply formatting per row by building a formatted DataFrame
            display_sub = sub_df.copy()
            for i, orig_key in enumerate(available_keys):
                label = METRIC_LABELS.get(orig_key, orig_key)
                fmt = FORMAT_MAP.get(orig_key, "{:.4f}")
                for col in display_sub.columns:
                    val = display_sub.at[label, col]
                    if pd.isna(val):
                        pass  # Will be handled by styler
                    # keep numeric for sorting and highlighting

            styled = sub_df.style.apply(_highlight_best_worst, axis=1)

            # Apply format per-cell based on row
            def _row_formatter(row):
                orig_key = None
                for k, v in METRIC_LABELS.items():
                    if v == row.name:
                        orig_key = k
                        break
                fmt = FORMAT_MAP.get(orig_key, "{:.4f}") if orig_key else "{:.4f}"
                result = {}
                for col in row.index:
                    val = row[col]
                    if pd.isna(val):
                        result[col] = "---"
                    else:
                        try:
                            result[col] = fmt.format(val)
                        except (ValueError, TypeError):
                            result[col] = str(val)
                return pd.Series(result)

            # Use format with a dict mapping - build per column
            format_dict = {}
            for orig_key in available_keys:
                label = METRIC_LABELS.get(orig_key, orig_key)
                fmt = FORMAT_MAP.get(orig_key, "{:.4f}")

                def make_formatter(f):
                    def formatter(val):
                        if pd.isna(val):
                            return "---"
                        try:
                            return f.format(val)
                        except (ValueError, TypeError):
                            return str(val)
                    return formatter

                # Styler.format with subset (row selection)
                styled = styled.format(make_formatter(fmt), subset=(label, slice(None)))

            st.dataframe(styled, width="stretch")

    # G. DOWNLOAD BUTTONS
    st.subheader("Export Data")
    col1, col2 = st.columns(2)
    with col1:
        # Build full metrics display df for download
        full_metrics_df = pd.DataFrame(all_metrics)
        full_metrics_df.index = [METRIC_LABELS.get(k, k) for k in full_metrics_df.index]
        csv = full_metrics_df.to_csv()
        st.download_button("Download Metrics CSV", csv, "metrics.csv", "text/csv")
    with col2:
        eq_csv = pd.DataFrame(all_equity).to_csv()
        st.download_button("Download Equity Curves CSV", eq_csv, "equity_curves.csv", "text/csv")

# =========================================================================
# TAB: Details
# =========================================================================
with tab_detail:
    # --- Holdings Timeline (strategies only) ---
    if strat_names:
        st.subheader("Holdings Timeline")
        timeline_strategy = st.selectbox("Strategy for holdings timeline", strat_names, key="ht")
        hh = strategy_results[timeline_strategy].holdings_history

        if not hh.empty:
            hh_pivot = hh.pivot_table(
                index="date", columns="ticker", values="weight", aggfunc="sum"
            ).fillna(0)
            fig_ht = go.Figure()
            for col in hh_pivot.columns:
                fig_ht.add_trace(go.Scatter(
                    x=hh_pivot.index, y=hh_pivot[col].values * 100,
                    mode="lines", name=col, stackgroup="one",
                ))
            fig_ht.update_yaxes(title="Weight (%)", range=[0, 100])
            fig_ht.update_xaxes(tickformat="%Y")
            _apply_layout(fig_ht, height=400)
            st.plotly_chart(fig_ht, width="stretch")
        else:
            st.info("No holdings data available.")

    # --- Top 10 Best/Worst Months ---
    st.subheader("Top 10 Best / Worst Months")
    bw_selection = st.selectbox("Series for best/worst months", list(all_twr.keys()), key="bw")
    ret_bw = all_twr.get(bw_selection, pd.Series(dtype=float))

    if not ret_bw.empty:
        col_best, col_worst = st.columns(2)
        sorted_months = ret_bw.sort_values()
        with col_best:
            st.write("**Best Months**")
            best = sorted_months.tail(10).iloc[::-1]
            best_df = pd.DataFrame({"Date": best.index.strftime("%Y-%m"), "Return": best.values})
            best_df["Return"] = best_df["Return"].apply(lambda x: f"{x:.2%}")
            st.dataframe(best_df, width="stretch", hide_index=True)
        with col_worst:
            st.write("**Worst Months**")
            worst = sorted_months.head(10)
            worst_df = pd.DataFrame({"Date": worst.index.strftime("%Y-%m"), "Return": worst.values})
            worst_df["Return"] = worst_df["Return"].apply(lambda x: f"{x:.2%}")
            st.dataframe(worst_df, width="stretch", hide_index=True)

    # --- Final Holdings (strategies only) ---
    if strat_names:
        st.subheader("Final Holdings")
        for name, res in strategy_results.items():
            hh = res.holdings_history
            if hh.empty:
                continue
            last_date = hh["date"].max()
            final = hh[hh["date"] == last_date][["ticker", "shares", "value", "weight"]].copy()

            # Add total row
            total_row = pd.DataFrame([{
                "ticker": "TOTAL",
                "shares": final["shares"].sum(),
                "value": final["value"].sum(),
                "weight": final["weight"].sum(),
            }])
            final = pd.concat([final, total_row], ignore_index=True)

            final["weight"] = final["weight"].apply(lambda x: f"{x:.2%}")
            final["value"] = final["value"].apply(lambda x: f"${x:,.2f}")
            st.write(f"**{name}** (as of {last_date.strftime('%Y-%m')})")
            st.dataframe(final, width="stretch", hide_index=True)

    # --- Trade Log ---
    if strat_names:
        st.subheader("Trade Log")
        for name, res in strategy_results.items():
            if hasattr(res, 'trades') and res.trades is not None and len(res.trades) > 0:
                with st.expander(f"Trade Log: {name}"):
                    st.dataframe(res.trades, width="stretch")

# =========================================================================
# TAB: Holdings
# =========================================================================
with tab_holdings:
    if not strat_names:
        st.info("Select at least one strategy to view holdings.")
    else:
        # -----------------------------------------------------------------
        # A. Current Holdings (most recent date)
        # -----------------------------------------------------------------
        st.subheader("Current Holdings")

        # Show strategies side-by-side using columns
        num_strats = len(strategy_results)
        cols = st.columns(min(num_strats, 3))

        for idx, (name, res) in enumerate(strategy_results.items()):
            col = cols[idx % min(num_strats, 3)]
            hh = res.holdings_history
            if hh.empty:
                col.warning(f"{name}: No holdings data.")
                continue

            last_date = hh["date"].max()
            current = hh[hh["date"] == last_date][["ticker", "shares", "value", "weight"]].copy()
            total_value = current["value"].sum()

            with col:
                st.markdown(f"**{name}**")
                st.caption(f"As of {last_date.strftime('%Y-%m')}")

                display_current = current.copy()
                # Add total row
                total_row = pd.DataFrame([{
                    "ticker": "TOTAL",
                    "shares": display_current["shares"].sum(),
                    "value": total_value,
                    "weight": display_current["weight"].sum(),
                }])
                display_current = pd.concat([display_current, total_row], ignore_index=True)

                display_current["value"] = display_current["value"].apply(lambda x: f"${x:,.2f}")
                display_current["weight"] = display_current["weight"].apply(lambda x: f"{x:.2%}")
                display_current.columns = ["Ticker", "Shares", "Value ($)", "Weight (%)"]
                st.dataframe(display_current, width="stretch", hide_index=True)
                st.metric("Total Portfolio Value", f"${total_value:,.0f}")

        # -----------------------------------------------------------------
        # B. Complete Holdings Timeline
        # -----------------------------------------------------------------
        st.subheader("Complete Holdings Timeline")

        for name, res in strategy_results.items():
            hh = res.holdings_history
            if hh.empty:
                continue

            with st.expander(f"Holdings Timeline: {name}", expanded=False):
                timeline_df = hh.copy()
                timeline_df["date"] = timeline_df["date"].dt.strftime("%Y-%m")
                timeline_df["value"] = timeline_df["value"].apply(lambda x: f"${x:,.2f}")
                timeline_df["weight"] = timeline_df["weight"].apply(lambda x: f"{x:.2%}")
                timeline_df["shares"] = timeline_df["shares"].apply(lambda x: f"{x:,.4f}")
                timeline_df.columns = ["Date", "Ticker", "Shares", "Value ($)", "Weight (%)"]
                st.dataframe(timeline_df, width="stretch", hide_index=True)

        # -----------------------------------------------------------------
        # C. Holdings Change Log
        # -----------------------------------------------------------------
        st.subheader("Holdings Change Log")

        for name, res in strategy_results.items():
            hh = res.holdings_history
            if hh.empty:
                continue

            with st.expander(f"Change Log: {name}", expanded=False):
                # Build per-date weight lookup: {date: {ticker: weight}}
                dates = sorted(hh["date"].unique())
                weight_by_date = {}
                for d in dates:
                    rows = hh[hh["date"] == d]
                    weight_by_date[d] = dict(zip(rows["ticker"], rows["weight"]))

                change_records = []
                for i_d in range(1, len(dates)):
                    prev_date = dates[i_d - 1]
                    curr_date = dates[i_d]
                    prev_weights = weight_by_date[prev_date]
                    curr_weights = weight_by_date[curr_date]

                    all_tickers_change = set(prev_weights.keys()) | set(curr_weights.keys())

                    for ticker in sorted(all_tickers_change):
                        old_w = prev_weights.get(ticker, 0.0)
                        new_w = curr_weights.get(ticker, 0.0)

                        if old_w == 0 and new_w > 0:
                            action = "NEW"
                        elif old_w > 0 and new_w == 0:
                            action = "EXIT"
                        elif abs(new_w - old_w) > 0.01:
                            action = "REBALANCE"
                        else:
                            continue  # No significant change

                        change_records.append({
                            "Date": curr_date.strftime("%Y-%m"),
                            "Ticker": ticker,
                            "Action": action,
                            "Old Weight": f"{old_w:.2%}",
                            "New Weight": f"{new_w:.2%}",
                        })

                if change_records:
                    change_df = pd.DataFrame(change_records)
                    st.dataframe(change_df, width="stretch", hide_index=True)
                else:
                    st.info("No significant position changes detected.")
