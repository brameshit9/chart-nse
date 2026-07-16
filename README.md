# NSE Stock Charts

A Streamlit app for browsing NSE (National Stock Exchange, India) stock
prices, charts (VWAP / Volume / Open / Close / High / Low), and a live
price snapshot scraped from Google Finance.

## What changed from the original script

- **`nsepy` → `nsepython`**: `nsepy` is unmaintained and fails to install /
  breaks against modern `pandas`. Historical OHLCV data now comes from
  `nsepython`'s `equity_history()`, which hits NSE's own historical-data
  API directly (no third-party proxy). Its raw column names have changed
  across versions, so `get_history()` normalizes them into a consistent
  `Open/High/Low/Close/Volume/VWAP` schema.
- **Removed the blocking `while True` live-price loop**: Streamlit reruns
  your whole script on each interaction, so an infinite loop inside it
  freezes the entire app (buttons stop responding). Live price is now
  fetched once per page load, with a "🔄 Refresh price" button to update
  it on demand.
- **Added caching** (`st.cache_data`) for the symbol list and price
  history to avoid re-downloading on every rerun.
- **Added an `.NS` suffix and NaN checks** so charts don't crash on
  missing data.

## Local setup

```bash
git clone <your-repo-url>
cd nse-stock-charts
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

You'll need an `EQUITY_L.csv` file (the NSE list of equities — symbol +
company name) in the project root **as a fallback only**. On each run the
app first tries to download the current list straight from NSE
(`https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv`, cached
for an hour); if that request fails for any reason (network restrictions,
NSE rate-limiting, etc.) it falls back to the bundled `EQUITY_L.csv`. If
neither is available the app stops with an error asking you to add the
file. You can still refresh your local copy manually from the
[NSE India website](https://www.nseindia.com/market-data/securities-available-for-trading)
if you want to update the fallback. It needs at least two columns:
`SYMBOL` and `NAME OF COMPANY`.

## NIFTY 50 live scanner

At the bottom of the app, **"Run NIFTY 50 live scan"** fetches a real-time
quote for each of the 50 constituents via `nsepython`'s `nse_eq()` (this
reuses the same NSE session that already works for `equity_history()`,
rather than opening a second session through a different library - that
mismatch was causing every quote to silently fail). It compares live LTP
to NSE's live VWAP and to an EMA9 (daily closes with the current LTP
appended as today's still-forming bar), buckets each stock as bullish
(LTP above both) or bearish (LTP below both), and renders a **candlestick
chart per stock** (Plotly) with VWAP and EMA9 overlaid, plus LTP/VWAP/EMA9
as live metrics.

If a scan comes back with 0 stocks in both groups, expand the "symbol(s)
failed to fetch" warning it shows - it now surfaces the actual error per
symbol instead of failing silently. The most common cause is NSE
rate-limiting or blocking the server's IP (common on cloud hosts); try
again after a minute, or run it locally where the source IP tends to be
less restricted.

**Important caveat on the charts:** NSE's free public API only provides
*daily* bars, not intraday candles. So while the chart looks like a
TradingView-style candlestick with a VWAP session line (each daily candle
+ that day's VWAP + EMA9), it isn't the same as an intraday chart built
from minute-by-minute ticks. For genuine intraday candles and a true
tick-built session VWAP, you'd need a broker API with market data access
(e.g. Zerodha Kite Connect, Upstox).

## Deploying

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit: NSE Stock Charts app"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

Make sure `EQUITY_L.csv` is committed too as a fallback (Streamlit Cloud
only has access to files in the repo, and NSE occasionally blocks
requests from cloud IPs) — see "Notes" below.

### 2. Deploy on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with
   GitHub.
2. Click **"New app"**.
3. Pick your repo, branch (`main`), and set the main file path to `app.py`.
4. Click **Deploy**.

Streamlit Cloud will install everything from `requirements.txt`
automatically. First boot can take a minute while `yfinance` and its
dependencies install.

## Notes / known limitations

- **Google Finance scraping is fragile.** Google can change its HTML
  class names (`YMlKec fxKbKc`, `bLLb2d`) at any time, which will silently
  break the live-price and "About" sections. If that happens, inspect the
  page source at `https://www.google.com/finance/quote/<SYMBOL>:NSE` and
  update the class names in `get_class_contents` calls in `app.py`.
- **VWAP is approximated** as `(High + Low + Close) / 3` if NSE's response
  doesn't include a VWAP field directly.
- **NSE sometimes rate-limits or blocks requests from cloud IPs**
  (including Streamlit Community Cloud), especially in bursts. `nsepython`
  handles session/cookie setup internally, but if `equity_history()` starts
  returning empty results in production, try adding a short delay between
  requests or a retry with backoff.
- Consider committing `EQUITY_L.csv` to the repo, or downloading it at
  startup from NSE if you want it to always be current (NSE occasionally
  blocks scripted requests, so a bundled CSV is more reliable for
  deployment).
