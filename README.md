# MarketCapBacktest

Market-cap weighted portfolio backtest comparing three monthly-rebalancing strategies against benchmark indexes (S&P 500, Nasdaq 100, Gold, E-mini S&P proxy). $10K initial capital, $1K monthly contributions, configurable start date (earliest 1990-01). Institutional-grade performance metrics (TWR, MWR/XIRR, Sharpe, Sortino, Calmar, VaR/CVaR, Alpha/Beta). Streamlit dashboard with Plotly charts.

## Architecture

```
MarketCapBacktest/
├── scripts/
│   ├── config.py                  # Ticker universe, cost schedule, parameter grids
│   ├── data_fetcher.py            # yfinance + FRED acquisition, SHA-256 manifest
│   ├── market_cap_estimator.py    # Split-adjusted shares outstanding, BRK-A/B aggregation
│   ├── strategies.py              # Strategy 1 (top-1), 2 (top-N equal), 3 (log-momentum)
│   ├── backtest_engine.py         # Monthly rebalance loop, TWR, XIRR, trade log
│   ├── metrics.py                 # Risk-adjusted metrics, benchmark-relative metrics
│   ├── grid_search.py             # Walk-forward optimization, White's Reality Check
│   ├── app.py                     # Streamlit dashboard entry point
│   └── .streamlit/config.toml     # Light theme, headless server
├── data/
│   └── delisted_monthly.csv       # 609 rows: ENRNQ, WCOEQ, LEH, GMGMQ, MOB
├── results/                       # Cached parquet, manifest, grid search output
├── docs/                          # IMPLEMENTATION_PLAN.md, DASHBOARD_DESIGN_REFERENCE.md
├── audits/                        # 6 audit documents
├── .streamlit/
│   └── config.toml                # Root-level Streamlit config (for cloud deployment)
├── .python-version                # Python version pin for cloud platforms
├── requirements.txt               # Pinned dependencies
└── CLAUDE.md                      # Project ground truth, audit history, design decisions
```

Full architecture and design decisions are documented in `CLAUDE.md`.

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd scripts
streamlit run app.py
```

The dashboard opens at `http://localhost:8501`. Light theme is applied automatically via `.streamlit/config.toml`.

## Deployment

### Streamlit Community Cloud (recommended)

Primary deployment target. Free tier, no container configuration needed.

1. Push the repo to GitHub (public or private).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click "New app" and configure:
   - **Repository:** `<your-username>/MarketCapBacktest`
   - **Branch:** `main`
   - **Main file path:** `scripts/app.py`
   - **Python version:** Reads from `.python-version` at repo root (set to `3.10` or higher)
4. If the app requires API keys or secrets (e.g., a FRED API key for `fredapi`), add them under **Advanced settings > Secrets** using TOML format:
   ```toml
   FRED_API_KEY = "your_key_here"
   ```
   Access in code via `st.secrets["FRED_API_KEY"]`.
5. Click "Deploy". Streamlit installs from `requirements.txt` automatically.

The root-level `.streamlit/config.toml` applies theme and server settings on Community Cloud. The `scripts/.streamlit/config.toml` applies when running locally from the `scripts/` directory.

Resource limits on the free tier: 1 GB RAM, apps sleep after inactivity. Data-heavy operations (full grid search, large date ranges) may hit memory limits. Pre-compute and cache results in `results/` to mitigate.

### HuggingFace Spaces

Alternative free hosting via Gradio/Streamlit SDK.

1. Create a new Space at [huggingface.co/spaces](https://huggingface.co/new-space). Select **Streamlit** as the SDK.
2. Clone the Space repo and copy project files into it.
3. Add a top-level `app.py` that imports and runs `scripts/app.py`, or restructure to place the entry point at the root.
4. HuggingFace reads `requirements.txt` automatically. Ensure `.python-version` or a `runtime.txt` specifies the Python version.
5. Push to the Space repo. The app builds and deploys automatically.

Free tier: 2 vCPU, 16 GB RAM (more generous than Streamlit Cloud for compute). Apps sleep after 48h inactivity on free tier.

### Render

Free-tier web service with Docker support.

1. Create a `Dockerfile` at repo root:
   ```dockerfile
   FROM python:3.10-slim
   WORKDIR /app
   COPY . .
   RUN pip install --no-cache-dir -r requirements.txt
   EXPOSE 8501
   CMD ["streamlit", "run", "scripts/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
   ```
2. Create a new **Web Service** on [render.com](https://render.com), connect the GitHub repo, select Docker as the environment.
3. Set the instance type to Free. Free tier spins down after 15 minutes of inactivity; cold starts take ~30s.

### Railway

Railway offers $5/month free credit. Connect the GitHub repo, add a `Procfile`:

```
web: streamlit run scripts/app.py --server.port=$PORT --server.address=0.0.0.0
```

Credit is consumed by uptime, so the free tier may not cover a continuously running app.

## Data Pipeline

Fetch fresh market data and recompute artifacts:

```bash
cd scripts
python data_fetcher.py            # Fetch price data, splits, shares, risk-free rate -> parquet + manifest
python market_cap_estimator.py    # Estimate market caps, validate against checkpoint years
python grid_search.py             # 48-combo walk-forward optimization with White's Reality Check
```

Data is cached as parquet files in `results/` with SHA-256 checksums in `data_manifest.json`. The dashboard reads from these cached files; re-fetching is only needed to update to newer market data.

## Testing

```bash
cd scripts
python test_phase2.py             # 9/9  — backtest engine, strategies
python test_phase3.py             # 8/8  — metrics module
python test_phase4.py             # 5/5  — grid search, walk-forward
python test_phase6_audit.py       # 12/12 — dashboard audit regression tests
```

## Disclaimer

This is a backtesting tool for educational and research purposes. It is not financial advice. Past performance does not indicate future results. The market cap estimation method uses split-adjusted shares outstanding, which introduces error from buybacks and issuances (quantified in `CLAUDE.md` and audit documents). Transaction costs are modeled but slippage is not. Tax implications are not considered.
