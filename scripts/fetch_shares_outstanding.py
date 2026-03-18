"""
fetch_shares_outstanding.py — Fetch historical shares outstanding from
SEC EDGAR XBRL API and yfinance, merge, and save to CSV.

Sources:
  1. SEC EDGAR XBRL companyfacts (EntityCommonStockSharesOutstanding)
  2. yfinance get_shares_full()

Output: data/historical_shares_outstanding.csv
Columns: date, ticker, shares_outstanding, source
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ACTIVE_TICKERS  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_CSV = DATA_DIR / "historical_shares_outstanding.csv"

HEADERS = {"User-Agent": "MarketCapBacktest research@example.com"}

# Build ticker list: all active + AMZN + BRK-A
TICKERS = sorted(set(list(ACTIVE_TICKERS.keys()) + ["AMZN", "BRK-A"]))
print(f"Tickers to fetch ({len(TICKERS)}): {TICKERS}\n")

# ===================================================================
# Step 1: Get ticker -> CIK mapping from SEC
# ===================================================================
print("=" * 60)
print("STEP 1: Fetching CIK mapping from SEC EDGAR")
print("=" * 60)

resp = requests.get(
    "https://www.sec.gov/files/company_tickers.json", headers=HEADERS
)
resp.raise_for_status()
tickers_map = resp.json()

# Build lookup: {ticker: cik_str}
# SEC uses dots instead of hyphens (BRK.B not BRK-B)
cik_lookup = {}
for entry in tickers_map.values():
    cik_lookup[entry["ticker"]] = entry["cik_str"]

# Print CIK resolution for our tickers
for ticker in TICKERS:
    sec_ticker = ticker.replace("-", ".")
    cik = cik_lookup.get(ticker) or cik_lookup.get(sec_ticker)
    status = f"CIK {cik}" if cik else "NOT FOUND"
    print(f"  {ticker:8s} -> {status}")

print()

# ===================================================================
# Step 2: Fetch EntityCommonStockSharesOutstanding from SEC EDGAR
# ===================================================================
print("=" * 60)
print("STEP 2: Fetching shares outstanding from SEC EDGAR XBRL API")
print("=" * 60)

sec_records = []
sec_errors = []

for ticker in TICKERS:
    sec_ticker = ticker.replace("-", ".")
    cik = cik_lookup.get(ticker) or cik_lookup.get(sec_ticker)
    if not cik:
        print(f"  {ticker:8s} -> No CIK found, skipping")
        sec_errors.append(ticker)
        continue

    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"

    try:
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code != 200:
            print(f"  {ticker:8s} -> HTTP {resp.status_code}")
            sec_errors.append(ticker)
            time.sleep(0.15)
            continue

        facts = resp.json()
        dei = facts.get("facts", {}).get("dei", {})
        shares_data = dei.get("EntityCommonStockSharesOutstanding", {})
        units = shares_data.get("units", {})
        shares_entries = units.get("shares", [])

        for entry in shares_entries:
            sec_records.append(
                {
                    "ticker": ticker,
                    "date": entry.get("end"),
                    "shares_outstanding": entry.get("val"),
                    "form": entry.get("form"),
                    "filed": entry.get("filed"),
                    "source": "sec_edgar",
                }
            )

        print(f"  {ticker:8s} -> {len(shares_entries)} entries")
    except Exception as e:
        print(f"  {ticker:8s} -> Error: {e}")
        sec_errors.append(ticker)

    time.sleep(0.12)  # Rate limit: ~8 req/sec

df_sec = pd.DataFrame(sec_records)
print(f"\nSEC EDGAR: {len(df_sec)} total records for {df_sec['ticker'].nunique()} tickers")
if sec_errors:
    print(f"SEC errors/missing: {sec_errors}")
print()

# ===================================================================
# Step 3: Clean and deduplicate SEC data
# ===================================================================
print("=" * 60)
print("STEP 3: Cleaning SEC EDGAR data")
print("=" * 60)

if len(df_sec) > 0:
    df_sec["date"] = pd.to_datetime(df_sec["date"], errors="coerce")
    df_sec["filed"] = pd.to_datetime(df_sec["filed"], errors="coerce")
    df_sec = df_sec.dropna(subset=["date", "shares_outstanding"])

    # Keep only 10-K and 10-Q forms (most reliable)
    reliable_forms = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
    df_sec_reliable = df_sec[df_sec["form"].isin(reliable_forms)].copy()
    print(f"  After filtering to 10-K/10-Q: {len(df_sec_reliable)} rows (was {len(df_sec)})")

    # If reliable forms are too sparse, also include other forms
    if len(df_sec_reliable) < len(df_sec) * 0.3:
        print("  Warning: <30% of data is 10-K/10-Q, keeping all forms")
        df_sec_clean = df_sec.copy()
    else:
        df_sec_clean = df_sec_reliable.copy()

    # For duplicate (ticker, date), keep the latest filing
    df_sec_clean = df_sec_clean.sort_values(["ticker", "date", "filed"])
    df_sec_clean = df_sec_clean.drop_duplicates(
        subset=["ticker", "date"], keep="last"
    )
    print(f"  After dedup: {len(df_sec_clean)} rows")
else:
    df_sec_clean = pd.DataFrame(
        columns=["ticker", "date", "shares_outstanding", "source"]
    )

print()

# ===================================================================
# Step 4: Fetch from yfinance get_shares_full()
# ===================================================================
print("=" * 60)
print("STEP 4: Fetching shares outstanding from yfinance")
print("=" * 60)

yf_records = []
yf_errors = []

for ticker in TICKERS:
    try:
        # yfinance uses hyphens for BRK-B, BRK-A
        t = yf.Ticker(ticker)
        shares = t.get_shares_full(start="2000-01-01")
        if shares is not None and len(shares) > 0:
            for dt, val in shares.items():
                yf_records.append(
                    {
                        "ticker": ticker,
                        "date": pd.Timestamp(dt),
                        "shares_outstanding": int(val),
                        "source": "yfinance",
                    }
                )
            print(f"  {ticker:8s} -> {len(shares)} entries")
        else:
            print(f"  {ticker:8s} -> No data")
    except Exception as e:
        print(f"  {ticker:8s} -> Error: {e}")
        yf_errors.append(ticker)
    time.sleep(0.5)

df_yf = pd.DataFrame(yf_records)
print(f"\nyfinance: {len(df_yf)} total records for {df_yf['ticker'].nunique() if len(df_yf) > 0 else 0} tickers")
if yf_errors:
    print(f"yfinance errors: {yf_errors}")
print()

# ===================================================================
# Step 5: Merge SEC + yfinance data
# ===================================================================
print("=" * 60)
print("STEP 5: Merging SEC EDGAR + yfinance data")
print("=" * 60)

# Prepare SEC data
if len(df_sec_clean) > 0:
    sec_final = df_sec_clean[["ticker", "date", "shares_outstanding", "source"]].copy()
else:
    sec_final = pd.DataFrame(columns=["ticker", "date", "shares_outstanding", "source"])

# Prepare yfinance data
if len(df_yf) > 0:
    yf_final = df_yf[["ticker", "date", "shares_outstanding", "source"]].copy()
else:
    yf_final = pd.DataFrame(columns=["ticker", "date", "shares_outstanding", "source"])

# Concatenate both sources
df_all = pd.concat([sec_final, yf_final], ignore_index=True)
df_all["date"] = pd.to_datetime(df_all["date"], utc=True).dt.tz_localize(None)
df_all = df_all.dropna(subset=["date", "shares_outstanding"])
df_all["shares_outstanding"] = df_all["shares_outstanding"].astype("int64")

print(f"  Combined raw records: {len(df_all)}")

# For each ticker, resample to month-end
# Prefer SEC data where both exist on same date
df_all["priority"] = df_all["source"].map({"sec_edgar": 0, "yfinance": 1})
df_all = df_all.sort_values(["ticker", "date", "priority"])
df_all = df_all.drop_duplicates(subset=["ticker", "date"], keep="first")
df_all = df_all.drop(columns=["priority"])

print(f"  After dedup (prefer SEC): {len(df_all)}")

# Resample to month-end with forward-fill within each ticker
monthly_frames = []
for ticker, grp in df_all.groupby("ticker"):
    grp = grp.set_index("date").sort_index()
    # Resample to month-end
    monthly = grp["shares_outstanding"].resample("ME").last()
    # Forward-fill gaps
    monthly = monthly.ffill()
    # Drop NaN (leading months before first observation)
    monthly = monthly.dropna()
    tmp = monthly.reset_index()
    tmp.columns = ["date", "shares_outstanding"]
    tmp["ticker"] = ticker
    # Determine predominant source for this ticker
    sec_count = (grp["source"] == "sec_edgar").sum() if "source" in grp.columns else 0
    yf_count = (grp["source"] == "yfinance").sum() if "source" in grp.columns else 0
    tmp["source"] = "sec_edgar" if sec_count >= yf_count else "yfinance"
    monthly_frames.append(tmp)

df_final = pd.concat(monthly_frames, ignore_index=True)
df_final = df_final[["date", "ticker", "shares_outstanding", "source"]]
df_final = df_final.sort_values(["ticker", "date"]).reset_index(drop=True)

print(f"  Final monthly rows: {len(df_final)}")
print()

# ===================================================================
# Step 6: Save and print summary
# ===================================================================
print("=" * 60)
print("STEP 6: Summary & Save")
print("=" * 60)

DATA_DIR.mkdir(parents=True, exist_ok=True)
df_final.to_csv(OUTPUT_CSV, index=False)
print(f"\nSaved to: {OUTPUT_CSV}")
print(f"Total rows: {len(df_final)}")
print(f"Tickers covered: {df_final['ticker'].nunique()}")
print(f"Date range: {df_final['date'].min()} to {df_final['date'].max()}")
print()

# Per-ticker summary
print(f"{'Ticker':<10} {'Source':<12} {'Start':<12} {'End':<12} {'Rows':>6}")
print("-" * 56)
for ticker in sorted(df_final["ticker"].unique()):
    sub = df_final[df_final["ticker"] == ticker]
    src = sub["source"].iloc[0]
    print(
        f"{ticker:<10} {src:<12} "
        f"{sub['date'].min().strftime('%Y-%m'):<12} "
        f"{sub['date'].max().strftime('%Y-%m'):<12} "
        f"{len(sub):>6}"
    )

# Tickers from our list with NO data
covered = set(df_final["ticker"].unique())
missing = set(TICKERS) - covered
if missing:
    print(f"\nWARNING: No data for these tickers: {sorted(missing)}")

print("\nDone.")
