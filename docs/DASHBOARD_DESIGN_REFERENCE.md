# Dashboard Design Reference: Portfolio Backtest Dashboard

**Compiled:** 2026-03-17
**Purpose:** Implementable best practices for a Streamlit + Plotly portfolio backtest dashboard
**Scope:** Information architecture, metrics presentation, chart standards, Streamlit patterns, decision-support design

---

## 1. Information Architecture: Section Ordering

### Industry Standard: What Goes First

Based on how Bloomberg PORT, FactSet Portfolio Analytics, QuantConnect, and Portfolio Visualizer structure their reports, the consensus ordering is:

| Priority | Section | Rationale |
|----------|---------|-----------|
| 1 | **Summary KPI tiles** | 3-second scan: CAGR, Sharpe, MaxDD, final value. Bloomberg PORT leads with summary statistics at the top. |
| 2 | **Equity curve** (with drawdown subplot) | 30-second context: visual shape of returns over time. Every major platform places this immediately after KPIs. |
| 3 | **Strategy comparison table** | Side-by-side metrics for all strategies vs benchmarks. QuantConnect shows this as a tabular summary. |
| 4 | **Return distributions** | Monthly/annual return histograms or heatmaps. QuantConnect shows per-trade, per-day, per-month, per-year. |
| 5 | **Rolling statistics** | Rolling Sharpe, rolling beta over 6/12-month windows. Provides temporal context for stationarity. |
| 6 | **Risk analysis** | VaR/CVaR, drawdown analysis, crisis period overlays. QuantConnect dedicates a section to crisis events. |
| 7 | **Holdings / allocation** | Current and historical portfolio weights. Bloomberg PORT provides breakdown attributes. |
| 8 | **Grid search / optimization** | Walk-forward results, parameter sensitivity. This is research-level detail, not executive summary. |

### QuantConnect Report Structure (Canonical Reference)

QuantConnect's backtest report follows this exact order:
1. Summary statistics (top of report)
2. Cumulative returns chart
3. Returns per trade histogram
4. Daily returns bar chart
5. Monthly returns table
6. Annual returns bar chart
7. Rolling beta (6mo and 12mo)
8. Rolling Sharpe (6mo and 12mo)
9. Leverage over time
10. Long/short exposure by asset class
11. Crisis period performance charts
12. Project parameters

**Source:** [QuantConnect Report Documentation](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/report)

### Bloomberg PORT Structure

Bloomberg PORT organizes around tabs with a persistent control area:
- Portfolio summary (beginning/ending values, allocation, holdings, unrealized P&L)
- Risk-return analysis
- Performance attribution
- Top/bottom contributors
- Historical trend analysis of active risk
- Scenario analysis

**Sources:**
- [Bloomberg PORT Help Guide](http://somfin.gmu.edu/courses/fnan311/PORT_guide.pdf)
- [Bloomberg Portfolio Analytics](https://www.bloomberg.com/professional/products/bloomberg-terminal/portfolio-analytics/)

---

## 2. Metrics Presentation

### GIPS Presentation Requirements

The Global Investment Performance Standards (GIPS 2020) require:

- **Composite returns:** Time-weighted returns (TWR) are mandatory. Money-weighted returns (MWR/IRR) required for closed-end funds.
- **Benchmark disclosure:** Every composite must have an appropriate total return benchmark. Custom benchmark components, weights, and rebalancing process must be disclosed.
- **Annualized returns:** Must be presented for periods of one year or longer. Returns for periods shorter than one year must NOT be annualized.
- **Risk measures:** 3-year annualized ex-post standard deviation (36 monthly returns) is required.
- **Gross and net returns:** Both must be presented; fee schedule disclosed.
- **Full disclosure:** Number of portfolios, composite assets, firm assets, internal dispersion.

**Sources:**
- [GIPS Standards 2020 (PDF)](https://www.gipsstandards.org/wp-content/uploads/2021/03/2020_gips_standards_firms.pdf)
- [CFA Institute GIPS Overview](https://rpc.cfainstitute.org/gips-standards)

### CFA Institute Performance Reporting Best Practices

Per CFA curriculum and CIPM standards:

**Metrics by audience:**

| Audience | Primary Metrics | Secondary Metrics |
|----------|----------------|-------------------|
| Portfolio Manager | Alpha, Information Ratio, Tracking Error, Attribution | Sector/factor exposures, position-level P&L |
| Risk Committee | VaR, CVaR, MaxDD, DD Duration, Beta, Volatility | Stress tests, tail risk, correlation matrix |
| Compliance/GIPS | TWR, MWR, Composite dispersion, Benchmark delta | Fee impact, trading costs, turnover |
| Client/Executive | CAGR, Total Return, Sharpe Ratio, MaxDD | Upside/downside capture, rolling returns |

**Key metrics hierarchy (most to least universal):**
1. Total return / CAGR
2. Sharpe Ratio
3. Maximum Drawdown (depth and duration)
4. Sortino Ratio
5. Alpha and Beta (vs benchmark)
6. Information Ratio
7. Calmar Ratio
8. Upside/Downside Capture
9. VaR / CVaR
10. Omega Ratio

**Sources:**
- [CFA Institute Portfolio Performance Evaluation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation)
- [Investment Performance Reporting Best Practices](https://waterloocap.com/investment-performance-reporting-guide/)

### Comparison Table Format

For a strategy-vs-benchmark comparison table, follow these conventions:

```
                    Strategy 1   Strategy 2   Strategy 3   S&P 500   NQ 100   Gold
CAGR                12.4%        10.8%        14.1%        10.2%     13.5%    7.8%
Sharpe Ratio        0.82         0.71         0.91         0.68      0.74     0.42
Max Drawdown       -28.3%       -22.1%       -35.7%       -33.9%   -37.2%  -18.5%
Sortino Ratio       1.24         1.08         1.37         0.95      1.02     0.61
Calmar Ratio        0.44         0.49         0.39         0.30      0.36     0.42
Volatility (ann.)  15.1%        14.2%        16.8%        15.0%     18.3%   14.2%
```

**Design rules:**
- Strategies on columns, metrics on rows (people scan left-to-right to compare)
- Bold the best value in each row
- Use conditional coloring: green for best, red for worst, neutral for middle
- Right-align all numbers; use consistent decimal places (2 for ratios, 1 for percentages)
- Group metrics: Return metrics first, then risk-adjusted, then risk, then benchmark-relative

---

## 3. Chart Best Practices for Finance

### Equity Curve Standards

**Log scale vs linear:**
- Use **log scale** for backtests spanning 10+ years. On a log chart, equal vertical distances represent equal percentage changes ($100K to $1M is the same distance as $1M to $10M). This prevents early periods from being visually compressed to nothing.
- Use **linear scale** for short periods (< 3 years) or when absolute dollar values matter.
- Best practice: offer a toggle between log and linear.

**Rebasing to 100:**
- When comparing multiple strategies/benchmarks, rebase all to a starting value of 100 (or $10,000 for a portfolio context). This is the industry standard for making heterogeneous starting values comparable.
- Formula: `rebased_value(t) = 100 * (1 + cumulative_return(t))`

**Drawdown subplot:**
- Always show drawdowns as a subplot directly below the equity curve, sharing the same x-axis.
- Display as a filled area chart (negative values), colored red or a muted red.
- Y-axis should show percentage (0% at top, deepest DD at bottom).
- Label the maximum drawdown point with its value and date range.

**Sources:**
- [Linear vs Logarithmic Charts (Allocate Smartly)](https://allocatesmartly.com/linear-vs-logarithmic-charts-when-log-is-better-and-when-neither-is-very-good/)
- [Equity Curve Best Practices (Quantified Strategies)](https://www.quantifiedstrategies.com/equity-curve/)
- [Rebasing Stock Prices to 100 (Financial Edge)](https://www.fe.training/free-resources/asset-management/rebasing-stock-prices-to-100/)

### Color Conventions

**Industry standard palette:**

| Element | Color | Hex (suggested) |
|---------|-------|-----------------|
| Strategy 1 (primary) | Deep blue | `#1f77b4` |
| Strategy 2 | Teal/cyan | `#17becf` |
| Strategy 3 | Purple | `#9467bd` |
| S&P 500 benchmark | Gray | `#7f7f7f` |
| Other benchmarks | Light gray variants | `#aec7e8`, `#c7c7c7` |
| Positive returns | Green | `#2ca02c` |
| Negative returns | Red | `#d62728` |
| Drawdown fill | Muted red | `#d62728` at 30% opacity |
| Neutral / informational | Blue | `#4a90d9` |

**Rules:**
- Strategies get saturated, distinct colors. Benchmarks get muted/gray tones. This visually communicates that strategies are the focus and benchmarks are reference.
- Never use red and green as the only differentiator (colorblind accessibility). Use shape/pattern as secondary encoding.
- For monthly return heatmaps: diverging colormap from red (negative) through white (zero) to green (positive).

**Sources:**
- [Portfolio Visualizer](https://www.portfoliovisualizer.com/backtest-portfolio)
- [AmiBroker Report Color Conventions](https://www.amibroker.com/guide/h_report.html)

### Axes Formatting

**X-axis (dates):**
- For multi-year backtests: show year labels only (e.g., "2000", "2005", "2010")
- For monthly views: "Jan 2020", "Feb 2020" format
- Avoid cluttered date labels; Plotly's `rangeslider` can replace dense x-axes

**Y-axis:**
- Use `tickformat='.0%'` for percentage axes (returns, drawdowns)
- Use `tickprefix='$'` and `tickformat=',.0f'` for dollar values
- For log scale: `type='log'` with tick values at powers of 10

**Gridlines:**
- Light gray horizontal gridlines only (`gridcolor='#e0e0e0'`). No vertical gridlines (Tufte principle: let data points imply the x-position).
- Zero line slightly emphasized for return charts (`zerolinecolor='#333'`, `zerolinewidth=1.5`)

### Edward Tufte Principles Applied

1. **Maximize data-ink ratio:** Remove chart borders, background colors, and unnecessary legends. Every pixel should encode data.
2. **Eliminate chartjunk:** No 3D effects, no gradient fills, no decorative elements. No moire patterns.
3. **Small multiples:** When comparing strategies, use identically-scaled subplots rather than overlaying too many lines on one chart.
4. **Sparklines:** Use inline mini-charts in tables (Tufte's invention) for rolling returns or drawdown profiles next to metric values.
5. **Data density:** Aim for high information density. A single equity curve chart should convey: growth trajectory, volatility regime, drawdown periods, benchmark comparison -- all without annotations cluttering the view.
6. **Graphical integrity:** The visual representation of numbers should be directly proportional to the numerical quantities represented. No truncated y-axes that exaggerate small changes.

**Sources:**
- [Tufte's Principles (The Double Think)](https://thedoublethink.com/tuftes-principles-for-visualizing-quantitative-information/)
- [GeeksforGeeks Tufte Principles](https://www.geeksforgeeks.org/data-visualization/mastering-tuftes-data-visualization-principles/)

### Plotly-Specific Implementation

```python
# Standard layout template for financial charts
FINANCIAL_LAYOUT = dict(
    template="plotly_white",           # Clean white background
    font=dict(family="Inter, Arial, sans-serif", size=12, color="#333"),
    plot_bgcolor="white",
    paper_bgcolor="white",
    xaxis=dict(
        showgrid=False,                # No vertical gridlines
        showline=True,
        linecolor="#ccc",
        tickfont=dict(size=10),
    ),
    yaxis=dict(
        showgrid=True,
        gridcolor="#e8e8e8",           # Subtle horizontal grid
        gridwidth=0.5,
        showline=False,
        tickfont=dict(size=10),
        zerolinecolor="#999",
        zerolinewidth=1,
    ),
    legend=dict(
        orientation="h",               # Horizontal legend below chart
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        bgcolor="rgba(255,255,255,0)",
        font=dict(size=10),
    ),
    margin=dict(l=60, r=20, t=40, b=40),
    hovermode="x unified",            # Crosshair hover for time series
)

# Equity curve with drawdown subplot
from plotly.subplots import make_subplots
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    row_heights=[0.75, 0.25],
)
# Row 1: equity curves (log scale option)
# Row 2: drawdown fill (inverted, red fill)
fig.update_yaxes(type="log", row=1, col=1)  # Optional log toggle
fig.update_yaxes(tickformat=".0%", row=2, col=1)
```

**Sources:**
- [Plotly Styling Documentation](https://plotly.com/python/styling-plotly-express/)
- [Plotly Axes Documentation](https://plotly.com/chart-studio-help/documentation/python/axes/)
- [FT-Style Plotly Visuals](https://medium.com/@romandogadin/style-your-visuals-like-the-financial-times-using-plotly-3e7f1d6e293d)

---

## 4. Streamlit Dashboard Patterns

### Layout Architecture

**Recommended structure for a multi-strategy backtest dashboard:**

```
Page Config: layout="wide", page_title, page_icon
│
├── Sidebar
│   ├── Strategy selection (multiselect)
│   ├── Date range picker
│   ├── Initial capital input
│   ├── Monthly contribution input
│   └── Advanced settings (expander)
│       ├── Transaction cost model
│       ├── Rebalance frequency
│       └── Benchmark selection
│
├── Main Area
│   ├── KPI Tiles Row (st.columns × 4-6 metrics)
│   │
│   ├── Tabs: ["Performance", "Risk", "Attribution", "Grid Search"]
│   │   ├── Tab 1: Performance
│   │   │   ├── Equity curve + drawdown subplot
│   │   │   ├── Monthly returns heatmap
│   │   │   └── Annual returns bar chart
│   │   ├── Tab 2: Risk
│   │   │   ├── Rolling Sharpe / Volatility
│   │   │   ├── VaR/CVaR display
│   │   │   └── Drawdown analysis table
│   │   ├── Tab 3: Comparison
│   │   │   ├── Full metrics table (strategies vs benchmarks)
│   │   │   └── Return distribution overlays
│   │   └── Tab 4: Grid Search
│   │       ├── Parameter heatmap
│   │       └── Walk-forward results
│   │
│   └── Footer: data freshness timestamp, disclaimers
```

**When to use each layout element:**

| Element | Use For | Avoid For |
|---------|---------|-----------|
| `st.tabs` | Primary navigation between major dashboard sections | More than 5-6 tabs (use pages instead) |
| `st.columns` | KPI tiles, side-by-side charts, metric cards | More than 4-5 columns (gets cramped) |
| `st.expander` | Advanced settings, methodology notes, detailed tables | Primary content users need to see |
| `st.sidebar` | Input controls, filters, configuration | Charts or large tables |
| `st.container` | Grouping related elements, applying borders | No specific avoid case |

**Sources:**
- [Streamlit Layouts API](https://docs.streamlit.io/develop/api-reference/layout)
- [Streamlit Layout Mastering (DEV)](https://dev.to/jamesbmour/streamlit-part-6-mastering-layouts-4hci)

### Performance Optimization

```python
# 1. Cache data loading (survives reruns, shared across sessions)
@st.cache_data(ttl=3600)  # 1-hour TTL
def load_backtest_data(start_date, end_date):
    """Cache the expensive data fetch + backtest computation."""
    # ... fetch and compute ...
    return results_df

# 2. Cache resource-heavy objects (models, connections)
@st.cache_resource
def get_database_connection():
    return create_connection()

# 3. Use session_state for user selections that should persist
if "selected_strategies" not in st.session_state:
    st.session_state.selected_strategies = ["Strategy 1", "Strategy 2"]

# 4. Avoid recomputing on every widget change
#    Use st.form() for batch inputs
with st.form("backtest_params"):
    start = st.date_input("Start Date")
    capital = st.number_input("Initial Capital")
    submitted = st.form_submit_button("Run Backtest")
    if submitted:
        # Only recompute when form is submitted
        results = run_backtest(start, capital)
```

**Key caching rules:**
- `st.cache_data` for DataFrames, dicts, lists (serializable data). Returns a copy each time (safe).
- `st.cache_resource` for database connections, ML models (non-serializable). Returns the same object (be careful with mutation).
- Avoid caching functions that depend on widget values unless those values are parameters -- otherwise Streamlit caches every permutation.
- For DataFrames under 100M rows, `st.cache_data` performs well.

**Sources:**
- [Streamlit Caching Overview](https://docs.streamlit.io/develop/concepts/architecture/caching)
- [st.cache_data Documentation](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)

### Professional Styling

```python
# 1. Page configuration
st.set_page_config(
    page_title="MarketCap Backtest",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. Custom CSS injection for professional look
st.markdown("""
<style>
    /* Remove default Streamlit padding */
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }

    /* Style metric cards */
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 12px 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }

    /* Metric label styling */
    div[data-testid="stMetricLabel"] {
        font-size: 0.85rem;
        color: #6c757d;
        font-weight: 500;
    }

    /* Metric value styling */
    div[data-testid="stMetricValue"] {
        font-size: 1.6rem;
        font-weight: 700;
        color: #212529;
    }

    /* Positive delta green, negative red (Streamlit default, but ensure) */
    div[data-testid="stMetricDelta"] svg { display: inline; }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 20px;
        font-weight: 500;
    }

    /* Table styling */
    .dataframe { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

# 3. Streamlit theme (.streamlit/config.toml)
# [theme]
# primaryColor = "#1f77b4"
# backgroundColor = "#ffffff"
# secondaryBackgroundColor = "#f8f9fa"
# textColor = "#212529"
# font = "sans serif"
```

**Additional styling options:**
- Use `streamlit-extras` library for `metric_cards` with `style_metric_cards()` for automatic card styling.
- Use `border=True` parameter on `st.metric()` for native bordered cards.
- For fully custom cards, use `st.markdown()` with HTML/CSS.

**Sources:**
- [Streamlit Metric Cards (streamlit-extras)](https://arnaudmiribel.github.io/streamlit-extras/extras/metric_cards/)
- [How to Style Streamlit Metrics (DEV Community)](https://dev.to/barrisam/how-to-style-streamlit-metrics-in-custom-css-4h14)
- [10 Essential Streamlit Design Tips](https://medium.com/@mihirs202/10-essential-streamlit-design-tips-building-professional-dashboards-that-dont-look-like-streamlit-1465e16bc4bf)
- [Minimalistic Streamlit Dashboard Guide](https://medium.com/data-science-collective/how-to-build-a-minimalistic-streamlit-dashboard-that-actually-looks-good-a-step-by-step-guide-ef5d803ae4a2)

---

## 5. Decision-Support Design

### The 3-30-300 Rule

Structure the dashboard so information is available at three levels of engagement:

| Level | Time | What the user gets | Implementation |
|-------|------|-------------------|----------------|
| **3 seconds** | Glance | Is performance good or bad? Which strategy wins? | KPI tiles with color-coded deltas at top of page |
| **30 seconds** | Scan | Shape of returns, drawdown severity, relative ranking | Equity curve + comparison table with conditional formatting |
| **300 seconds** | Analysis | Rolling statistics, parameter sensitivity, risk decomposition | Tabs for detailed risk analysis, grid search results |

### KPI Tile Design

```python
# Standard KPI row implementation
cols = st.columns(5)
metrics = [
    ("CAGR", "12.4%", "+2.2% vs S&P"),
    ("Sharpe", "0.82", "+0.14 vs S&P"),
    ("Max Drawdown", "-28.3%", "+5.6% vs S&P"),
    ("Final Value", "$847,231", None),
    ("Win Rate", "62.1%", None),
]
for col, (label, value, delta) in zip(cols, metrics):
    col.metric(label=label, value=value, delta=delta)
```

**KPI tile best practices:**
- 4-6 tiles maximum in one row. More than 6 creates cognitive overload.
- Each tile: label (small, gray), value (large, bold), delta/comparison (small, colored).
- Delta should always be relative to something meaningful (benchmark, previous period).
- Order tiles by importance: return first, then risk-adjusted, then risk.

### Conditional Formatting for Financial Tables

**Color scales for metrics tables:**

```python
import pandas as pd

def style_metrics_table(df):
    """Apply financial conditional formatting to a comparison table."""
    def color_positive_green(val):
        """Green for positive, red for negative."""
        if isinstance(val, (int, float)):
            color = '#2ca02c' if val > 0 else '#d62728' if val < 0 else '#333'
            return f'color: {color}'
        return ''

    def highlight_best(s):
        """Bold green background for best value in row."""
        if s.dtype in ['float64', 'int64']:
            # For most metrics, higher is better
            is_best = s == s.max()
            return ['background-color: #d4edda; font-weight: bold' if v else '' for v in is_best]
        return ['' for _ in s]

    def highlight_worst(s):
        """Light red background for worst value in row."""
        if s.dtype in ['float64', 'int64']:
            is_worst = s == s.min()
            return ['background-color: #f8d7da' if v else '' for v in is_worst]
        return ['' for _ in s]

    # For metrics where lower is better (MaxDD, Volatility), invert logic
    return (df.style
        .apply(highlight_best, axis=1)
        .format({
            'CAGR': '{:.1%}',
            'Sharpe': '{:.2f}',
            'MaxDD': '{:.1%}',
            'Volatility': '{:.1%}',
            'Sortino': '{:.2f}',
            'Calmar': '{:.2f}',
        })
    )
```

**Monthly returns heatmap:**

```python
def monthly_returns_heatmap(returns_series):
    """Create a monthly returns heatmap (rows=years, cols=months)."""
    monthly = returns_series.resample('M').apply(lambda x: (1+x).prod()-1)
    pivot = pd.DataFrame({
        'Year': monthly.index.year,
        'Month': monthly.index.month,
        'Return': monthly.values
    }).pivot(index='Year', columns='Month', values='Return')
    pivot.columns = ['Jan','Feb','Mar','Apr','May','Jun',
                     'Jul','Aug','Sep','Oct','Nov','Dec']

    import plotly.express as px
    fig = px.imshow(
        pivot.values,
        x=pivot.columns,
        y=pivot.index,
        color_continuous_scale='RdYlGn',  # Red-Yellow-Green diverging
        color_continuous_midpoint=0,
        aspect='auto',
        text_auto='.1%',
    )
    fig.update_layout(
        title="Monthly Returns (%)",
        coloraxis_colorbar=dict(title="Return", tickformat=".0%"),
    )
    return fig
```

### Traffic Light System for Quick Assessment

```python
def metric_traffic_light(value, thresholds):
    """
    Return a colored indicator based on thresholds.
    thresholds = {'green': 0.05, 'yellow': 0.0}
    Value >= green threshold -> green
    Value >= yellow threshold -> yellow
    Value < yellow threshold -> red
    """
    if value >= thresholds['green']:
        return "🟢"  # Or use colored HTML spans
    elif value >= thresholds['yellow']:
        return "🟡"
    else:
        return "🔴"

# Example thresholds for common metrics
METRIC_THRESHOLDS = {
    'sharpe':    {'green': 1.0, 'yellow': 0.5},
    'cagr':      {'green': 0.10, 'yellow': 0.05},
    'max_dd':    {'green': -0.15, 'yellow': -0.30},  # Less negative = better
    'sortino':   {'green': 1.5, 'yellow': 0.8},
    'calmar':    {'green': 0.5, 'yellow': 0.25},
}
```

### Making the Dashboard Scannable

**Visual hierarchy checklist:**

1. **Position high-impact KPIs top-left.** Users scan in an F-pattern (top-left to right, then down-left).
2. **Group metrics logically.** Return metrics together, risk metrics together, benchmark-relative together.
3. **Use consistent formatting throughout.** Same number of decimal places, same color scheme, same font sizes.
4. **Label everything.** No chart should require the user to guess what it shows. Title + subtitle + axis labels.
5. **Provide context with every number.** A Sharpe of 0.82 means nothing alone. Show it relative to the benchmark ("+0.14 vs S&P") or with a qualitative label.
6. **Use whitespace deliberately.** Generous margins between sections. Dense charts are fine; dense layouts are not.
7. **Progressive disclosure.** Summary first, detail on demand. Use expanders for methodology, detailed tables, raw data.

**Sources:**
- [Dashboard Design Best Practices (Toptal)](https://www.toptal.com/designers/data-visualization/dashboard-design-best-practices)
- [KPI Dashboard Guide (Domo)](https://www.domo.com/learn/article/kpi-dashboards)
- [25 Dashboard Design Principles (RIB Software)](https://www.rib-software.com/en/blogs/bi-dashboard-design-principles-best-practices)
- [Effective Dashboard Design (DataCamp)](https://www.datacamp.com/tutorial/dashboard-design-tutorial)
- [KPI Card Best Practices (Tabular Editor)](https://tabulareditor.com/blog/kpi-card-best-practices-dashboard-design)

---

## 6. Implementation Checklist for MarketCapBacktest Dashboard

Based on the above research, here is a prioritized implementation checklist:

### Must Have (Core)

- [ ] Wide layout with sidebar for inputs
- [ ] Top row: 5 KPI tiles (CAGR, Sharpe, MaxDD, Sortino, Final Value) with benchmark deltas
- [ ] Equity curve chart with drawdown subplot (shared x-axis, log scale toggle)
- [ ] Rebase all curves to 100 (or $10K) for comparison
- [ ] Strategy vs benchmark comparison table with conditional formatting
- [ ] Monthly returns heatmap (year x month grid, RdYlGn colormap)
- [ ] `st.cache_data` on all data loading and backtest computation
- [ ] Custom CSS for metric card styling
- [ ] Plotly white template with Tufte-inspired minimal gridlines

### Should Have (Professional Polish)

- [ ] Tabs for Performance / Risk / Comparison / Grid Search
- [ ] Rolling Sharpe and rolling volatility time series
- [ ] Annual returns bar chart (grouped: strategies + benchmarks)
- [ ] Drawdown analysis table (top 5 drawdowns: start, trough, recovery, depth, duration)
- [ ] `st.form()` for backtest parameter inputs (prevent rerun on every widget change)
- [ ] Horizontal legend above charts
- [ ] Consistent color palette across all charts (strategies = saturated, benchmarks = gray)

### Nice to Have (Delight)

- [ ] Sparklines in comparison table cells
- [ ] Traffic light indicators on KPI tiles
- [ ] Crisis period overlay charts (2000 dot-com, 2008 GFC, 2020 COVID)
- [ ] Return distribution histograms with kernel density overlay
- [ ] Parameter sensitivity heatmap for grid search
- [ ] Data freshness indicator in footer
- [ ] Export to PDF/CSV buttons
- [ ] `.streamlit/config.toml` theme file for brand consistency

---

## Appendix: Color Palette Reference

```python
# Recommended palette for MarketCapBacktest dashboard
COLORS = {
    # Strategies (saturated, distinct)
    'strategy_1': '#1f77b4',   # Blue — Top-1 Concentration
    'strategy_2': '#ff7f0e',   # Orange — Top-N Equal Weight
    'strategy_3': '#2ca02c',   # Green — Log-Momentum

    # Benchmarks (muted, recessive)
    'sp500':      '#7f7f7f',   # Gray
    'nasdaq':     '#bcbd22',   # Olive/yellow-green
    'gold':       '#d4a84b',   # Gold (literal)
    'es':         '#9e9e9e',   # Light gray

    # Semantic
    'positive':   '#2ca02c',   # Green
    'negative':   '#d62728',   # Red
    'neutral':    '#4a90d9',   # Blue
    'warning':    '#ff7f0e',   # Orange
    'background': '#f8f9fa',   # Light gray
    'text':       '#212529',   # Near-black
    'grid':       '#e8e8e8',   # Subtle gray
    'zero_line':  '#999999',   # Medium gray
}
```
