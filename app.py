from dateutil.relativedelta import relativedelta
from datetime import datetime
import io
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st
from nsepython import equity_history
from nsetools import Nse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_class_contents(name: str, class_name: str) -> str:
    """Scrape the text inside the first tag with the given class on the
    Google Finance quote page for an NSE symbol."""
    url = f"https://www.google.com/finance/quote/{name}:NSE"
    try:
        page = requests.get(url, timeout=5).text
    except requests.RequestException:
        return ""
    soup = BeautifulSoup(page, features="lxml")
    t = str(soup.find_all(class_=class_name))
    if class_name in t:
        i = t.index(">") + 1
        t = t[i:]
        i = t.index("<")
        t = t[:i]
    else:
        t = ""
    return t


NSE_EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
_NSE_HEADERS = {"User-Agent": "Mozilla/5.0"}


@st.cache_data(ttl=3600)
def get_symbol_map() -> dict:
    """Get the NSE symbol -> company name map.

    Tries to download the current list from NSE first (so it stays fresh
    without needing manual updates); falls back to a bundled EQUITY_L.csv
    in the repo if the download fails (e.g. NSE blocking the request, no
    network access, etc.).
    """
    symbol_list = None

    try:
        resp = requests.get(NSE_EQUITY_LIST_URL, headers=_NSE_HEADERS, timeout=10)
        resp.raise_for_status()
        symbol_list = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        st.warning(
            f"Couldn't fetch the latest symbol list from NSE ({e}); "
            "falling back to the bundled EQUITY_L.csv."
        )

    if symbol_list is None:
        try:
            symbol_list = pd.read_csv("EQUITY_L.csv")
        except FileNotFoundError:
            st.error(
                "No symbol list available: the NSE download failed and there's "
                "no local EQUITY_L.csv bundled with the app. Add EQUITY_L.csv "
                "to the repo root as a fallback."
            )
            st.stop()

    symbol_list.columns = [c.strip() for c in symbol_list.columns]
    return dict(zip(symbol_list["SYMBOL"], symbol_list["NAME OF COMPANY"]))


# nsepython's raw NSE API response uses different column names across
# versions - normalize whichever set shows up to a consistent schema.
_COLUMN_ALIASES = {
    "CH_TIMESTAMP": "Date", "TIMESTAMP": "Date", "Date": "Date",
    "mTIMESTAMP": "Date",
    "CH_OPENING_PRICE": "Open", "Open": "Open", "OPEN": "Open",
    "CH_TRADE_HIGH_PRICE": "High", "High": "High", "HIGH": "High",
    "CH_TRADE_LOW_PRICE": "Low", "Low": "Low", "LOW": "Low",
    "CH_CLOSING_PRICE": "Close", "Close": "Close", "CLOSE": "Close",
    "CH_TOT_TRADED_QTY": "Volume", "Volume": "Volume", "VOLUME": "Volume",
    "TOTTRDQTY": "Volume",
    "CH_TOT_TRADED_VAL": "Turnover", "Turnover": "Turnover",
    "VWAP": "VWAP",
}


@st.cache_data(ttl=300)
def get_history(symbol: str, start, end) -> pd.DataFrame:
    """Fetch OHLCV history for an NSE symbol directly from NSE via
    nsepython's equity_history(). Dates must be dd-mm-YYYY strings."""
    start_str = start.strftime("%d-%m-%Y")
    end_str = end.strftime("%d-%m-%Y")
    try:
        raw = equity_history(symbol, "EQ", start_str, end_str)
    except Exception:
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.rename(columns={c: _COLUMN_ALIASES[c] for c in raw.columns if c in _COLUMN_ALIASES})

    if "Date" not in df.columns:
        return pd.DataFrame()

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()

    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "VWAP" not in df.columns and {"High", "Low", "Close"}.issubset(df.columns):
        # NSE's raw historical API doesn't always expose VWAP - approximate it
        df["VWAP"] = (df["High"] + df["Low"] + df["Close"]) / 3

    return df


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(page_title="NSE Stock Charts", layout="wide")
st.title("NSE STOCK CHARTS")

today_date = datetime.today()
symbol_map = get_symbol_map()

name = st.selectbox("Select stock symbol", symbol_map.keys())

st.write("Select chart to show")
col1, col2, col3, col4, col5, col6 = st.columns(6)

about_text = get_class_contents(name, "bLLb2d")

dur = st.selectbox(
    "Duration",
    ("Last Month", "Last Year", "Last 6 Months", "Last week"),
)

if dur == "Last Month":
    prev_date = today_date - relativedelta(months=1)
elif dur == "Last Year":
    prev_date = today_date - relativedelta(years=1)
elif dur == "Last 6 Months":
    prev_date = today_date - relativedelta(months=6)
else:  # Last week
    prev_date = today_date - relativedelta(days=7)

today_date_d = today_date.date()
prev_date_d = prev_date.date()

# ---------------------------------------------------------------------------
# Live price (single fetch + manual refresh, no blocking loop)
# ---------------------------------------------------------------------------
st.write("##### Live price:")
price_placeholder = st.empty()

if "live_price" not in st.session_state:
    st.session_state.live_price = get_class_contents(name, "YMlKec fxKbKc")

if st.button("🔄 Refresh price"):
    st.session_state.live_price = get_class_contents(name, "YMlKec fxKbKc")

price_placeholder.markdown(f"# {st.session_state.live_price or 'N/A'}")

st.title(symbol_map[name])

# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
chart_col = None
if col1.button("VWAP"):
    chart_col = "VWAP"
if col2.button("VOLUME"):
    chart_col = "Volume"
if col3.button("OPEN"):
    chart_col = "Open"
if col4.button("CLOSE"):
    chart_col = "Close"
if col5.button("HIGH"):
    chart_col = "High"
if col6.button("LOW"):
    chart_col = "Low"

if chart_col:
    stock = get_history(symbol=name, start=prev_date_d, end=today_date_d)
    if stock.empty:
        st.warning("No data returned for this symbol/date range.")
    else:
        st.write(f"# {chart_col.upper()}")
        st.line_chart(stock[chart_col])

if about_text:
    st.write("# ABOUT")
    st.write(about_text)

# ---------------------------------------------------------------------------
# NIFTY 50 Scanner: price vs VWAP & EMA9
# ---------------------------------------------------------------------------
# NOTE: NIFTY 50 constituents change periodically (index reshuffles happen
# roughly every 6 months) - update this list if it drifts from the official
# composition at nseindia.com/products-services/indices-nifty50-index.
NIFTY_50_SYMBOLS = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BPCL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC", "INDUSINDBK",
    "INFY", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "NTPC", "NESTLEIND", "ONGC", "POWERGRID",
    "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN", "SUNPHARMA",
    "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM",
    "TITAN", "TRENT", "ULTRACEMCO", "WIPRO", "LTIM",
]


def add_ema(df: pd.DataFrame, span: int = 9) -> pd.DataFrame:
    df = df.copy()
    df["EMA9"] = df["Close"].ewm(span=span, adjust=False).mean()
    return df


@st.cache_resource
def get_nse_client():
    return Nse()


@st.cache_data(ttl=15)
def get_live_quote(symbol: str):
    """Real-time NSE quote: last traded price, today's VWAP, day OHLC.
    Cached for 15s so a full 50-stock scan doesn't hammer NSE, while still
    staying close to live."""
    nse = get_nse_client()
    try:
        return nse.get_quote(symbol)
    except Exception:
        return None


@st.cache_data(ttl=15)
def get_live_ema9(symbol: str, ltp: float):
    """EMA9 built from ~2 months of daily closes with today's live price
    appended as the most recent (still-forming) bar - gives an EMA9 value
    that reflects the current live tick rather than yesterday's close."""
    hist_start = (datetime.today() - relativedelta(months=2)).date()
    hist_end = datetime.today().date()
    hist = get_history(symbol=symbol, start=hist_start, end=hist_end)
    if hist.empty or "Close" not in hist.columns:
        return None, None
    closes = hist["Close"].tolist()
    closes.append(ltp)
    series = pd.Series(closes)
    ema = series.ewm(span=9, adjust=False).mean()
    return ema.iloc[-1], hist


st.write("---")
st.header("NIFTY 50 Scanner: Live Price vs VWAP & EMA9")
st.caption(
    "Classifies each NIFTY 50 stock using its real-time last traded price "
    "(LTP) against NSE's live intraday VWAP: bullish if LTP is above both "
    "VWAP and EMA9, bearish if below both. EMA9 is computed from recent "
    "daily closes with the current LTP appended as today's still-forming "
    "bar, so it reflects the live price. Quotes are cached for 15 seconds "
    "- re-run the scan to refresh."
)

if st.button("Run NIFTY 50 live scan"):
    above_stocks = {}
    below_stocks = {}

    progress = st.progress(0.0, text="Fetching live quotes...")
    for i, sym in enumerate(NIFTY_50_SYMBOLS):
        quote = get_live_quote(sym)
        progress.progress((i + 1) / len(NIFTY_50_SYMBOLS), text=f"Fetching {sym}...")
        if not quote:
            continue

        ltp = quote.get("lastPrice")
        vwap = quote.get("vwap")
        if ltp is None or vwap is None:
            continue

        ema9, hist = get_live_ema9(sym, ltp)
        if ema9 is None:
            continue

        entry = {"ltp": ltp, "vwap": vwap, "ema9": ema9, "hist": hist}
        if ltp > vwap and ltp > ema9:
            above_stocks[sym] = entry
        elif ltp < vwap and ltp < ema9:
            below_stocks[sym] = entry
    progress.empty()

    st.session_state.scan_above = above_stocks
    st.session_state.scan_below = below_stocks


def render_group(stocks: dict):
    for sym, data in stocks.items():
        st.write(f"**{sym}**")
        c1, c2, c3 = st.columns(3)
        c1.metric("LTP", f"₹{data['ltp']:.2f}")
        c2.metric("VWAP", f"₹{data['vwap']:.2f}")
        c3.metric("EMA9", f"₹{data['ema9']:.2f}")

        chart_df = data["hist"][["Close"]].copy()
        today_ts = pd.Timestamp(datetime.today().date())
        chart_df.loc[today_ts, "Close"] = data["ltp"]
        chart_df = chart_df.sort_index()
        chart_df["EMA9"] = chart_df["Close"].ewm(span=9, adjust=False).mean()
        st.line_chart(chart_df[["Close", "EMA9"]])


if "scan_above" in st.session_state or "scan_below" in st.session_state:
    above_stocks = st.session_state.get("scan_above", {})
    below_stocks = st.session_state.get("scan_below", {})

    st.subheader(f"📈 LTP above VWAP & EMA9 ({len(above_stocks)})")
    if above_stocks:
        render_group(above_stocks)
    else:
        st.write("No stocks currently in this group.")

    st.subheader(f"📉 LTP below VWAP & EMA9 ({len(below_stocks)})")
    if below_stocks:
        render_group(below_stocks)
    else:
        st.write("No stocks currently in this group.")
