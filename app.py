from dateutil.relativedelta import relativedelta
from datetime import datetime
import io
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st
from nsepython import equity_history


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
