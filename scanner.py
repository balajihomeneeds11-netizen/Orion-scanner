"""ORION 7-PILLARS + GPT POWER STOCKS scanner.

Research-inspired, rule-based NSE stock screener. It does not use an LLM or
claim predictive certainty. Yahoo Finance data may be delayed or incomplete.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import time
import urllib.request
from io import StringIO
from collections import defaultdict
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")
BATCH_SIZE = 25
INTRADAY_INTERVAL_MINUTES = 5
POWER_CANDIDATE_MIN_SCORE = 45
POWER_MAX_CARDS = 25

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Keep this list aligned with the current NSE individual-stock derivatives universe.
# NSE changes F&O eligibility periodically; verify against the official NSE list.
SYMBOLS = list(dict.fromkeys(("""
AARTIIND ABB ABBOTINDIA ABCAPITAL ABFRL ACC ADANIENT ADANIPORTS ALKEM
AMBUJACEM ANGELONE APOLLOHOSP APOLLOTYRE ASHOKLEY ASIANPAINT ASTRAL ATUL
AUBANK AUROPHARMA AXISBANK BAJAJ-AUTO BAJAJFINSV BAJFINANCE BALKRISIND
BALRAMCHIN BANDHANBNK BANKBARODA BATAINDIA BEL BERGEPAINT BHARATFORG BHEL
BPCL BHARTIARTL BIOCON BSOFT BOSCHLTD BRITANNIA CANFINHOME CANBK CHAMBLFERT
CHOLAFIN CIPLA COALINDIA COFORGE COLPAL CONCOR COROMANDEL CROMPTON CUMMINSIND
DABUR DALBHARAT DEEPAKNTR DELTACORP DIVISLAB DIXON DLF DRREDDY EICHERMOT
ESCORTS EXIDEIND FEDERALBNK GAIL GLENMARK GMRINFRA GNFC GODREJCP GODREJPROP
GRANULES GRASIM GUJGASLTD HAL HAVELLS HCLTECH HDFCAMC HDFCBANK HDFCLIFE
HEROMOTOCO HINDALCO HINDCOPPER HINDPETRO HINDUNILVR ICICIBANK ICICIGI
ICICIPRULI IDFC IDFCFIRSTB IEX IGL INDHOTEL INDIACEM INDIAMART INDIGO
INDUSINDBK INDUSTOWER INFY IOC IPCALAB IRCTC ITC JINDALSTEL JKCEMENT JSWSTEEL
JUBLFOOD KOTAKBANK LALPATHLAB LAURUSLABS LICHSGFIN LT LTIM LTF LUPIN M&M
M&MFIN MANAPPURAM MARICO MARUTI MCX METROPOLIS MFSL MGL MOTHERSON MPHASIS MRF
MUTHOOTFIN NATIONALUM NAUKRI NAVINFLUOR NESTLEIND NMDC NTPC OBEROIRLTY OFSS
ONGC PAGEIND PEL PERSISTENT PETRONET PFC PIDILITIND PIIND PNB POLYCAB
POONAWALLA POWERGRID PVRINOX RAMCOCEM RBLBANK RECLTD RELIANCE SAIL SBICARD
SBILIFE SBIN SHREECEM SHRIRAMFIN SIEMENS SRF SUNPHARMA SUNTV SYNGENE TATACHEM
TATACOMM TATACONSUM TATAMOTORS TATAPOWER TATASTEEL TCS TECHM TITAN TORNTPHARM
TRENT TVSMOTOR UBL ULTRACEMCO UNIONBANK UPL VEDL VOLTAS WIPRO ZEEL ZYDUSLIFE
360ONE ADANIENSOL ADANIGREEN ADANIPOWER APLAPOLLO AMBER ANANDRATHI CUB
INTELLECT LTTS MCDOWELL-N RAIN WHIRLPOOL
""").split()))
# Built-in fallback list preserves the original scanner symbols and adds several newer names.
# The official NSE page is attempted at runtime; fallback keeps scanning when NSE blocks requests.
STATIC_SYMBOLS = SYMBOLS
NSE_UNDERLYINGS_URL = "https://www.nseindia.com/static/products-services/equity-derivatives-list-underlyings-information"
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTYFPI"}


def load_official_fno_symbols(fallback: list[str]) -> tuple[list[str], str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        req = urllib.request.Request(NSE_UNDERLYINGS_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="replace")
        tables = pd.read_html(StringIO(html))
        found: set[str] = set()
        for table in tables:
            cols = list(table.columns)
            sym_col = next((col for col in cols if "SYMBOL" in str(col).upper()), None)
            if sym_col is None:
                continue
            for value in table[sym_col].dropna().astype(str):
                symbol = value.strip().upper()
                if re.fullmatch(r"[A-Z0-9&.\-]{1,25}", symbol) and symbol not in INDEX_UNDERLYINGS:
                    found.add(symbol)
        # Reject partial/error pages instead of replacing the fallback with a small list.
        if len(found) >= 100:
            ordered = sorted(found)
            print(f"Universe source: NSE official underlyings page ({len(ordered)} symbols)")
            return ordered, "NSE official underlyings page"
        print(f"Official NSE page returned only {len(found)} valid symbols; using static fallback.")
    except Exception as exc:
        print(f"Unable to refresh NSE F&O universe ({exc}); using static fallback.")
    return list(dict.fromkeys(fallback)), "built-in fallback list (verify against NSE)"


SYMBOLS, UNIVERSE_SOURCE = load_official_fno_symbols(STATIC_SYMBOLS)
YF_SYMBOLS = {s: f"{s}.NS" for s in SYMBOLS}

SECTOR_MAP = {
    **{s: "Banking" for s in "HDFCBANK ICICIBANK SBIN AXISBANK KOTAKBANK INDUSINDBK FEDERALBNK BANDHANBNK IDFCFIRSTB RBLBANK AUBANK BANKBARODA CANBK PNB UNIONBANK BANKINDIA CUB INDIANB".split()},
    **{s: "IT" for s in "TCS INFY HCLTECH WIPRO TECHM LTIM COFORGE PERSISTENT MPHASIS BSOFT OFSS NAUKRI LTTS INTELLECT KPITTECH TATAELXSI ECLERX FSL".split()},
    **{s: "Auto" for s in "TATAMOTORS MARUTI M&M BAJAJ-AUTO HEROMOTOCO EICHERMOT TVSMOTOR ASHOKLEY BHARATFORG BALKRISIND APOLLOTYRE MRF MOTHERSON BOSCHLTD EXIDEIND SONACOMS UNOMINDA TIINDIA".split()},
    **{s: "Energy" for s in "RELIANCE ONGC BPCL IOC HINDPETRO GAIL IGL MGL NTPC POWERGRID TATAPOWER PETRONET TORNTPOWER AEGISLOG".split()},
    **{s: "Metals" for s in "TATASTEEL JSWSTEEL JINDALSTEL SAIL HINDALCO VEDL NATIONALUM HINDCOPPER NMDC COALINDIA".split()},
    **{s: "Pharma" for s in "SUNPHARMA DRREDDY CIPLA DIVISLAB LUPIN AUROPHARMA ALKEM TORNTPHARM GLENMARK ZYDUSLIFE BIOCON LAURUSLABS GRANULES IPCALAB".split()},
    **{s: "FMCG" for s in "HINDUNILVR ITC NESTLEIND BRITANNIA TATACONSUM DABUR MARICO GODREJCP COLPAL UBL MCDOWELL-N VBL".split()},
    **{s: "Finance" for s in "BAJFINANCE BAJAJFINSV CHOLAFIN SHRIRAMFIN MUTHOOTFIN M&MFIN LICHSGFIN RECLTD PFC MANAPPURAM SBICARD POONAWALLA MFSL HDFCAMC HDFCLIFE ICICIGI ICICIPRULI JIOFIN IIFL KFINTECH CDSL CDSL BSE ANGELONE 360ONE".split()},
    **{s: "Infra" for s in "LT ADANIPORTS CONCOR DLF GODREJPROP OBEROIRLTY PHOENIXLTD PRESTIGE NBCC RVNL HUDCO".split()},
    **{s: "Defense" for s in "BEL HAL BDL GRSE MAZDOCK COCHINSHIP".split()},
    **{s: "Durables" for s in "DIXON POLYCAB HAVELLS CROMPTON VOLTAS WHIRLPOOL AMBER KAYNES".split()},
    **{s: "Chemicals" for s in "AARTIIND ATUL DEEPAKNTR CHAMBLFERT COROMANDEL GNFC GUJGASLTD NAVINFLUOR SRF UPL PIIND PIDILITIND AETHER CHEMPLAST FINPIPE FINCABLES".split()},
    **{s: "Telecom" for s in "INDUSTOWER IDEA BHARTIARTL".split()},
    **{s: "Hotels" for s in "INDHOTEL".split()},
}

# Reference lot sizes are kept only for backward-compatible display.
# They must be verified against current exchange contract specifications.
LOT_SIZES = {
    "RELIANCE": 250, "HDFCBANK": 550, "ICICIBANK": 700, "SBIN": 750,
    "AXISBANK": 625, "KOTAKBANK": 400, "TCS": 175, "INFY": 400,
    "HCLTECH": 350, "WIPRO": 1500, "TECHM": 600, "LTIM": 150,
    "COFORGE": 150, "TATAMOTORS": 550, "MARUTI": 50, "M&M": 350,
    "TATASTEEL": 5500, "VEDL": 1150, "HINDALCO": 1400,
    "MANAPPURAM": 3000, "DIXON": 50, "COCHINSHIP": 350, "PAYTM": 500,
    "ONGC": 3850, "ASTRAL": 275, "INDUSTOWER": 1700, "MPHASIS": 275,
    "BHARTIARTL": 475, "BEL": 2850, "HAL": 150, "PNB": 8000,
    "ZYDUSLIFE": 900, "ANGELONE": 250, "INDHOTEL": 1000, "ICICIGI": 250
}


def send_telegram_alert(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}).encode()
        with urlopen(Request(url, data=payload), timeout=10) as response:
            response.read()
    except Exception as exc:
        print(f"Telegram dispatch error: {exc}")


def to_ist_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    idx = pd.DatetimeIndex(pd.to_datetime(out.index))
    if idx.tz is None:
        idx = idx.tz_localize(IST)
    else:
        idx = idx.tz_convert(IST)
    out.index = idx
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def clean_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        return pd.DataFrame()
    out.columns = [str(c).title() for c in out.columns]
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(out.columns):
        return pd.DataFrame()
    out = out[required].copy()
    for col in required:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    out["Volume"] = out["Volume"].fillna(0).clip(lower=0)
    out = to_ist_index(out)
    return out


def extract_ticker_frame(batch: pd.DataFrame, yf_symbol: str) -> pd.DataFrame:
    if batch is None or batch.empty:
        return pd.DataFrame()
    piece = batch
    if isinstance(batch.columns, pd.MultiIndex):
        levels = [batch.columns.get_level_values(i) for i in range(batch.columns.nlevels)]
        found = False
        for level_no, labels in enumerate(levels):
            if yf_symbol in labels:
                try:
                    piece = batch.xs(yf_symbol, axis=1, level=level_no, drop_level=True)
                    found = True
                    break
                except Exception:
                    continue
        if not found:
            # yfinance sometimes omits the ticker suffix in batch column labels.
            short = yf_symbol.replace(".NS", "")
            for level_no, labels in enumerate(levels):
                if short in labels:
                    try:
                        piece = batch.xs(short, axis=1, level=level_no, drop_level=True)
                        found = True
                        break
                    except Exception:
                        continue
        if not found:
            return pd.DataFrame()
    return clean_ohlcv(piece)


def yf_download_batch(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    try:
        return yf.download(
            tickers=tickers,
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
            multi_level_index=True,
            timeout=25,
        )
    except TypeError:
        # Compatibility with an older yfinance version.
        return yf.download(
            tickers=tickers, period=period, interval=interval,
            group_by="ticker", auto_adjust=False, progress=False, threads=True,
        )


def download_universe(symbols: list[str]) -> tuple[dict, dict]:
    daily_data: dict[str, pd.DataFrame] = {}
    intraday_data: dict[str, pd.DataFrame] = {}
    yf_tickers = [YF_SYMBOLS[s] for s in symbols]
    for start in range(0, len(yf_tickers), BATCH_SIZE):
        batch_tickers = yf_tickers[start:start + BATCH_SIZE]
        print(f"Downloading batch {start + 1}-{start + len(batch_tickers)} of {len(yf_tickers)} symbols...")
        try:
            daily_batch = yf_download_batch(batch_tickers, "1y", "1d")
        except Exception as exc:
            print(f"Daily batch error: {exc}")
            daily_batch = pd.DataFrame()
        try:
            intra_batch = yf_download_batch(batch_tickers, "5d", "5m")
        except Exception as exc:
            print(f"Intraday batch error: {exc}")
            intra_batch = pd.DataFrame()
        for original, ticker in zip(symbols[start:start + BATCH_SIZE], batch_tickers):
            daily_data[original] = extract_ticker_frame(daily_batch, ticker)
            intraday_data[original] = extract_ticker_frame(intra_batch, ticker)
        time.sleep(0.15)
    return daily_data, intraday_data


def download_single(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        data = yf.download(symbol, period=period, interval=interval, auto_adjust=False,
                           progress=False, multi_level_index=False, timeout=25)
    except TypeError:
        data = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)
    except Exception as exc:
        print(f"Download error {symbol}: {exc}")
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        required = {"Open", "High", "Low", "Close", "Volume"}
        flattened = None
        for level_no in range(data.columns.nlevels):
            labels = {str(v).title() for v in data.columns.get_level_values(level_no)}
            if required.issubset(labels):
                flattened = data.copy()
                flattened.columns = data.columns.get_level_values(level_no)
                break
        if flattened is None:
            return pd.DataFrame()
        data = flattened
    return clean_ohlcv(data)


def remove_incomplete_5m_bars(frame: pd.DataFrame, now: dt.datetime) -> pd.DataFrame:
    frame = to_ist_index(frame)
    if frame.empty:
        return frame
    latest_day = max(frame.index.date)
    if latest_day == now.astimezone(IST).date():
        cutoff = pd.Timestamp(now.astimezone(IST))
        completed = frame.index + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES) <= cutoff
        frame = frame.loc[completed]
    return frame


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def pct_change(new: float, old: float) -> float:
    return ((new / old) - 1.0) * 100.0 if old and math.isfinite(old) else 0.0


def calc_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).rolling(length, min_periods=length).mean()
    loss = (-change.clip(upper=0)).rolling(length, min_periods=length).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # If no losses over the period, RSI is conventionally 100; if no gains, 0.
    rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
    rsi = rsi.mask((gain == 0) & (loss > 0), 0.0)
    return rsi


def calc_adx(frame: pd.DataFrame, length: int = 14) -> tuple[float, float, float]:
    if len(frame) < length + 2:
        return 0.0, 0.0, 0.0
    high, low, close = frame["High"], frame["Low"], frame["Close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=frame.index)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(length, min_periods=length).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.rolling(length, min_periods=length).mean() / atr
    minus_di = 100 * minus_dm.rolling(length, min_periods=length).mean() / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    adx = dx.rolling(length, min_periods=length).mean()
    return safe_float(adx.iloc[-1]), safe_float(plus_di.iloc[-1]), safe_float(minus_di.iloc[-1])


def calc_atr_daily(daily: pd.DataFrame) -> float:
    if len(daily) < 15:
        return 0.0
    previous_close = daily["Close"].shift(1)
    tr = pd.concat([
        daily["High"] - daily["Low"],
        (daily["High"] - previous_close).abs(),
        (daily["Low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    return safe_float(tr.rolling(14, min_periods=14).mean().iloc[-1])


def relative_volume_by_time(all_intraday: pd.DataFrame, session_date: dt.date, session_bars: pd.DataFrame) -> tuple[float, dict[int, float]]:
    """Cumulative volume vs median cumulative volume at the same 5m bar number."""
    if all_intraday.empty or session_bars.empty:
        return 1.0, {}
    work = all_intraday.copy()
    work["_date"] = list(work.index.date)
    work["_bar_no"] = work.groupby("_date").cumcount()
    work["_cum_vol"] = work.groupby("_date")["Volume"].cumsum()
    hist = work[work["_date"] != session_date]
    if hist.empty:
        # With no prior intraday sessions, score conservatively as neutral RVOL.
        return 1.0, {}
    medians = hist.groupby("_bar_no")["_cum_vol"].median().to_dict()
    todays_cum = session_bars["Volume"].cumsum()
    series: dict[int, float] = {}
    for i, value in enumerate(todays_cum.tolist()):
        baseline = safe_float(medians.get(i, 0.0))
        series[i] = value / baseline if baseline > 0 else 1.0
    current_index = len(session_bars) - 1
    return safe_float(series.get(current_index, 1.0), 1.0), series


def rvol_for_prefix(prefix: pd.DataFrame, bar_no: int, historical_rvol_map: dict[int, float]) -> float:
    # This is derived from cumulative volume at the same time-of-day across prior sessions.
    # The map above represents the full current-session cumulative RVOL curve; to avoid
    # future leakage for historical timestamps, use the current prefix cum-volume ratio
    # against the precomputed historical baseline at this bar number.
    return safe_float(historical_rvol_map.get(bar_no, 1.0), 1.0)


def historical_rvol_curve(all_intraday: pd.DataFrame, session_date: dt.date) -> dict[int, float]:
    if all_intraday.empty:
        return {}
    work = all_intraday.copy()
    work["_date"] = list(work.index.date)
    work["_bar_no"] = work.groupby("_date").cumcount()
    work["_cum_vol"] = work.groupby("_date")["Volume"].cumsum()
    hist = work[work["_date"] != session_date]
    if hist.empty:
        return {}
    return {int(k): safe_float(v) for k, v in hist.groupby("_bar_no")["_cum_vol"].median().items()}


def current_rvol(prefix: pd.DataFrame, bar_no: int, historical_baselines: dict[int, float]) -> float:
    baseline = safe_float(historical_baselines.get(bar_no, 0.0))
    cum_volume = safe_float(prefix["Volume"].sum())
    return cum_volume / baseline if baseline > 0 else 1.0


def get_daily_history_before(daily: pd.DataFrame, session_date: dt.date) -> pd.DataFrame:
    if daily.empty:
        return daily
    return daily.loc[[d < session_date for d in daily.index.date]].copy()


def build_market_context(daily_all: pd.DataFrame, session_date: dt.date) -> dict:
    hist = get_daily_history_before(daily_all, session_date)
    if len(hist) < 15:
        return {}
    prev = hist.iloc[-1]
    atr = calc_atr_daily(hist)
    prev_close = safe_float(prev["Close"])
    prev_open = safe_float(prev["Open"])
    pdh = safe_float(prev["High"])
    pdl = safe_float(prev["Low"])
    high_52w = safe_float(hist["High"].tail(252).max())
    pivot = (pdh + pdl + prev_close) / 3.0
    bc = (pdh + pdl) / 2.0
    tc = 2.0 * pivot - bc
    cpr_width_pct = abs(tc - bc) / pivot * 100.0 if pivot > 0 else 0.0
    recent_ranges = (hist["High"] - hist["Low"]).tail(7)
    is_nr7 = bool(len(recent_ranges) >= 7 and recent_ranges.iloc[-1] <= recent_ranges.min())
    day_ranges = hist["High"] - hist["Low"]
    traded_value_cr = (hist["Close"] * hist["Volume"]).tail(20) / 10_000_000.0
    avg_turnover_cr = safe_float(traded_value_cr.median())
    daily_close = hist["Close"]
    ema20 = safe_float(daily_close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = safe_float(daily_close.ewm(span=50, adjust=False).mean().iloc[-1])
    prior_day_bullish = bool(prev_close > prev_open and prev_open > 0 and (prev_close / prev_open - 1) >= 0.008)
    return {
        "hist": hist,
        "prevClose": prev_close, "prevOpen": prev_open,
        "pdh": pdh, "pdl": pdl, "atr": atr, "high52w": high_52w,
        "cprWidthPct": cpr_width_pct, "isNarrowCPR": bool(cpr_width_pct <= 0.18),
        "isNR7": is_nr7, "avgTurnoverCr": avg_turnover_cr,
        "dailyEma20": ema20, "dailyEma50": ema50,
        "prevDayBullish": prior_day_bullish,
    }


def calculate_snapshot(symbol: str, daily_raw: pd.DataFrame, intra_raw: pd.DataFrame,
                       now: dt.datetime, nifty_daily: pd.DataFrame,
                       nifty_intraday: pd.DataFrame) -> Optional[dict]:
    daily = clean_ohlcv(daily_raw)
    intra = remove_incomplete_5m_bars(clean_ohlcv(intra_raw), now)
    if daily.empty or intra.empty:
        return None
    session_date = max(intra.index.date)
    all_intraday = intra.copy()
    today = all_intraday.loc[[d == session_date for d in all_intraday.index.date]].copy()
    context = build_market_context(daily, session_date)
    if not context or len(today) < 2:
        return None

    # Use completed 5-minute bars only. Data timestamps are converted to India time above.
    open_day = safe_float(today["Open"].iloc[0])
    close = safe_float(today["Close"].iloc[-1])
    high_day = safe_float(today["High"].max())
    low_day = safe_float(today["Low"].min())
    if min(open_day, close, low_day, context["prevClose"]) <= 0:
        return None

    prev_close = context["prevClose"]
    change_pct = pct_change(close, prev_close)
    session_return_pct = pct_change(close, open_day)
    gap_pct = pct_change(open_day, prev_close)
    today_range = max(0.0, high_day - low_day)
    atr = context["atr"] or max(today_range, close * 0.01)
    atr_used_pct = (today_range / atr * 100.0) if atr > 0 else 0.0
    fuel_left_pct = max(0.0, 100.0 - atr_used_pct)

    # Conventional price-volume VWAP uses the typical price (H+L+C)/3.
    typical = (today["High"] + today["Low"] + today["Close"]) / 3.0
    cum_vol = today["Volume"].cumsum()
    vwap_series = (typical * today["Volume"]).cumsum() / cum_vol.replace(0, np.nan)
    vwap_series = vwap_series.ffill().fillna(today["Close"])
    vwap = safe_float(vwap_series.iloc[-1], close)

    # First three completed 5-minute bars define a 15-minute opening range.
    orb_ready = len(today) >= 4
    or_slice = today.iloc[:3]
    orb_high_15 = safe_float(or_slice["High"].max()) if len(or_slice) >= 3 else 0.0
    orb_low_15 = safe_float(or_slice["Low"].min()) if len(or_slice) >= 3 else 0.0
    orb_high_5 = safe_float(today["High"].iloc[0])
    orb_low_5 = safe_float(today["Low"].iloc[0])
    breakout_up = bool(orb_ready and close > orb_high_15)
    breakout_down = bool(orb_ready and close < orb_low_15)

    rsi_series = calc_rsi(today["Close"])
    rsi = safe_float(rsi_series.iloc[-1], 50.0)
    ema9_series = today["Close"].ewm(span=9, adjust=False).mean()
    ema20_series = today["Close"].ewm(span=20, adjust=False).mean()
    ema9 = safe_float(ema9_series.iloc[-1], close)
    ema20 = safe_float(ema20_series.iloc[-1], close)
    adx, plus_di, minus_di = calc_adx(today)

    recent3_pct = pct_change(close, safe_float(today["Close"].iloc[-4])) if len(today) >= 4 else 0.0
    recent6_pct = pct_change(close, safe_float(today["Close"].iloc[-7])) if len(today) >= 7 else 0.0

    # Bollinger bandwidth is included for compression context (not as a standalone trade trigger).
    bb_width = 0.0
    bb_squeeze = False
    if len(today) >= 20:
        rolling_mean = today["Close"].rolling(20).mean()
        rolling_std = today["Close"].rolling(20).std(ddof=0)
        widths = (4 * rolling_std / rolling_mean.replace(0, np.nan)).dropna()
        if len(widths) >= 20:
            bb_width = safe_float(widths.iloc[-1])
            bb_squeeze = bool(bb_width <= safe_float(widths.tail(20).quantile(0.30)))

    historical_baselines = historical_rvol_curve(all_intraday, session_date)
    current_bar_no = len(today) - 1
    rvol = current_rvol(today, current_bar_no, historical_baselines)
    # If historical time-of-day data is missing, use neutral RVOL and flag it on the card.
    rvol_available = bool(current_bar_no in historical_baselines and historical_baselines[current_bar_no] > 0)

    # Current intraday Nifty change from previous completed daily close.
    nifty_move_pct = 0.0
    if not nifty_daily.empty and not nifty_intraday.empty:
        n_hist = get_daily_history_before(clean_ohlcv(nifty_daily), session_date)
        n_intra = remove_incomplete_5m_bars(clean_ohlcv(nifty_intraday), now)
        n_today = n_intra.loc[[d == session_date for d in n_intra.index.date]].copy() if not n_intra.empty else pd.DataFrame()
        if not n_hist.empty and not n_today.empty:
            n_prev = safe_float(n_hist["Close"].iloc[-1])
            if n_prev > 0:
                nifty_move_pct = pct_change(safe_float(n_today["Close"].iloc[-1]), n_prev)
    alpha = change_pct - nifty_move_pct

    range_tr = (today["High"] - today["Low"]).astype(float)
    expansion_ratio = 1.0
    if len(range_tr) >= 13:
        base = safe_float(range_tr.iloc[-13:-3].median())
        recent = safe_float(range_tr.iloc[-3:].mean())
        if base > 0:
            expansion_ratio = recent / base

    current_bar = today.iloc[-1]
    last_body_pct = abs(safe_float(current_bar["Close"]) - safe_float(current_bar["Open"])) / max(safe_float(current_bar["Open"]), 0.01) * 100
    current_bar_bull = bool(safe_float(current_bar["Close"]) > safe_float(current_bar["Open"]))
    current_bar_bear = bool(safe_float(current_bar["Close"]) < safe_float(current_bar["Open"]))
    day_close_location = (close - low_day) / today_range if today_range > 0 else 0.5
    near_day_high = bool((high_day - close) / high_day * 100 <= 0.35)
    near_day_low = bool((close - low_day) / low_day * 100 <= 0.35)

    high52w = context["high52w"]
    is_52w = bool(high52w > 0 and close >= high52w * 0.985)
    sector = SECTOR_MAP.get(symbol, "General")

    # Legacy scanner's first-candle ORB and same-day relative-volume calculation.
    avg_vol = safe_float(today["Volume"].mean())
    cur_vol_x = safe_float(current_bar["Volume"]) / avg_vol if avg_vol > 0 else 1.0
    morning = today.iloc[:min(12, len(today))]
    peak_vol_x = safe_float(morning["Volume"].max()) / avg_vol if avg_vol > 0 else 1.0
    legacy_vol_x = max(cur_vol_x, peak_vol_x)
    cum_vol_legacy = today["Volume"].cumsum()
    legacy_vwap = (today["Close"] * today["Volume"]).cumsum() / cum_vol_legacy.replace(0, np.nan)
    legacy_vwap = legacy_vwap.ffill().fillna(today["Close"])
    legacy_rsi = safe_float(calc_rsi(today["Close"]).iloc[-1], 50.0)

    # First daily row prior to the scan session provides the correct previous close/high/low.
    metrics = {
        "symbol": symbol, "sector": sector, "sessionDate": session_date.isoformat(),
        "today": today, "allIntraday": all_intraday, "context": context,
        "price": round(close, 2), "openDay": round(open_day, 2),
        "highDay": round(high_day, 2), "lowDay": round(low_day, 2),
        "pctChangeNum": round(change_pct, 2), "sessionReturnPct": round(session_return_pct, 2),
        "gapPct": round(gap_pct, 2), "niftyPct": round(nifty_move_pct, 2),
        "alphaNum": round(alpha, 2), "vwap": round(vwap, 2),
        "orbHigh15": round(orb_high_15, 2), "orbLow15": round(orb_low_15, 2),
        "orbReady": bool(orb_ready), "breakoutUp": breakout_up, "breakoutDown": breakout_down,
        "rsi": round(rsi, 1), "ema9": round(ema9, 2), "ema20": round(ema20, 2),
        "adx": round(adx, 1), "plusDI": round(plus_di, 1), "minusDI": round(minus_di, 1),
        "recent3Pct": round(recent3_pct, 2), "recent6Pct": round(recent6_pct, 2),
        "rvol": round(rvol, 2), "rvolAvailable": rvol_available,
        "expansionRatio": round(expansion_ratio, 2),
        "atr": round(atr, 2), "atrUsedPct": round(atr_used_pct, 1),
        "fuelLeftPct": round(fuel_left_pct, 1), "avgTurnoverCr": round(context["avgTurnoverCr"], 2),
        "isNarrowCPR": bool(context["isNarrowCPR"]), "isNR7": bool(context["isNR7"]),
        "is52W": bool(is_52w), "bbWidth": round(bb_width, 4), "bbSqueeze": bool(bb_squeeze),
        "closeLocation": round(day_close_location, 3), "nearDayHigh": near_day_high,
        "nearDayLow": near_day_low, "lastBodyPct": round(last_body_pct, 2),
        "lastBarBull": current_bar_bull, "lastBarBear": current_bar_bear,
        "legacyVolX": round(legacy_vol_x, 2), "legacyVwapSeries": legacy_vwap,
        "legacyRsi": round(legacy_rsi, 1), "orbHigh5": round(orb_high_5, 2), "orbLow5": round(orb_low_5, 2),
        "vwapSeries": vwap_series, "rsiSeries": rsi_series,
    }
    return metrics


def clamp_points(value: float, max_points: float) -> float:
    return max(0.0, min(max_points, value))


def directional_power_score(m: dict, side: str) -> tuple[int, dict]:
    """100-point explainable score. It is a ranking heuristic, not a win probability."""
    bull = side == "CE"
    rvol = m["rvol"]
    volume_pts = clamp_points((rvol - 0.8) * 7.5, 15) if (m["sessionReturnPct"] >= 0 if bull else m["sessionReturnPct"] <= 0) else 0

    # 20 points: 15m opening-range structure, previous-day level and price location.
    structure = 0.0
    if m["orbReady"]:
        if bull:
            structure += 9 if m["price"] > m["orbHigh15"] else (6 if m["orbHigh15"] > 0 and pct_change(m["orbHigh15"], m["price"]) <= 0.30 and m["price"] <= m["orbHigh15"] else 0)
            structure += 5 if m["price"] > m["context"]["pdh"] else (2 if pct_change(m["context"]["pdh"], m["price"]) <= 0.30 and m["price"] <= m["context"]["pdh"] else 0)
            structure += 3 if m["closeLocation"] >= 0.75 else (1.5 if m["closeLocation"] >= 0.60 else 0)
            structure += 3 if m["lastBarBull"] and m["lastBodyPct"] >= 0.15 else 0
        else:
            structure += 9 if m["price"] < m["orbLow15"] else (6 if m["orbLow15"] > 0 and pct_change(m["price"], m["orbLow15"]) <= 0.30 and m["price"] >= m["orbLow15"] else 0)
            structure += 5 if m["price"] < m["context"]["pdl"] else (2 if pct_change(m["price"], m["context"]["pdl"]) <= 0.30 and m["price"] >= m["context"]["pdl"] else 0)
            structure += 3 if m["closeLocation"] <= 0.25 else (1.5 if m["closeLocation"] <= 0.40 else 0)
            structure += 3 if m["lastBarBear"] and m["lastBodyPct"] >= 0.15 else 0
    structure_pts = clamp_points(structure, 20)

    # 15 points: direction of the move since prior close and recent 3/6-bar momentum.
    daily_move = m["pctChangeNum"] if bull else -m["pctChangeNum"]
    ret3 = m["recent3Pct"] if bull else -m["recent3Pct"]
    ret6 = m["recent6Pct"] if bull else -m["recent6Pct"]
    momentum_pts = 0.0
    if daily_move > 0:
        momentum_pts += min(5.0, daily_move * 3.0)
    if ret3 > 0:
        momentum_pts += min(5.0, ret3 * 5.0)
    if ret6 > 0:
        momentum_pts += min(5.0, ret6 * 2.5)
    momentum_pts = clamp_points(momentum_pts, 15)

    # 15 points: VWAP, intraday EMA alignment, RSI, and directional ADX confirmation.
    trend_pts = 0.0
    if (m["price"] > m["vwap"]) == bull:
        trend_pts += 5
    if (m["ema9"] > m["ema20"]) == bull:
        trend_pts += 5
    if (m["rsi"] >= 54) if bull else (m["rsi"] <= 46):
        trend_pts += 3
    directional_di = m["plusDI"] >= m["minusDI"] if bull else m["minusDI"] >= m["plusDI"]
    if m["adx"] >= 18 and directional_di:
        trend_pts += 2

    # 10 points: relative strength or weakness vs Nifty.
    alpha = m["alphaNum"] if bull else -m["alphaNum"]
    if alpha >= 0.75:
        rs_pts = 10
    elif alpha >= 0.40:
        rs_pts = 8
    elif alpha >= 0.15:
        rs_pts = 6
    elif alpha > 0:
        rs_pts = 3
    else:
        rs_pts = 0

    # 10 points: expanding 5m ranges without being already overextended versus daily ATR.
    expansion = m["expansionRatio"]
    expansion_pts = clamp_points((expansion - 0.75) * 4.0, 6)
    used = m["atrUsedPct"]
    if 15 <= used <= 65:
        range_pts = 4
    elif 5 <= used < 15 or 65 < used <= 85:
        range_pts = 2.5
    elif used < 5:
        range_pts = 1.5
    else:
        range_pts = 0
    volatility_pts = clamp_points(expansion_pts + range_pts, 10)

    # 5 points: prior-day coil (NR7) and narrow CPR; these are context, not triggers.
    coil_pts = (2.5 if m["isNR7"] else 0) + (2.5 if m["isNarrowCPR"] else 0)
    # Squeeze adds a small part of the same capped coil score, without exceeding 5.
    if m["bbSqueeze"]:
        coil_pts = min(5.0, coil_pts + 1.0)

    # 5 points: current candle close location and directional body.
    candle_pts = 0.0
    if bull:
        candle_pts += 2.5 if m["closeLocation"] >= 0.70 else (1.0 if m["closeLocation"] >= 0.55 else 0)
        candle_pts += 2.5 if m["lastBarBull"] and m["lastBodyPct"] >= 0.15 else 0
    else:
        candle_pts += 2.5 if m["closeLocation"] <= 0.30 else (1.0 if m["closeLocation"] <= 0.45 else 0)
        candle_pts += 2.5 if m["lastBarBear"] and m["lastBodyPct"] >= 0.15 else 0

    # 5 points: typical daily cash turnover as a liquidity proxy.
    turnover = m["avgTurnoverCr"]
    if turnover >= 50:
        liquidity_pts = 5
    elif turnover >= 20:
        liquidity_pts = 4
    elif turnover >= 10:
        liquidity_pts = 3
    elif turnover >= 5:
        liquidity_pts = 2
    elif turnover >= 2:
        liquidity_pts = 1
    else:
        liquidity_pts = 0

    parts = {
        "relativeVolume": round(volume_pts, 1),
        "structure": round(structure_pts, 1),
        "momentum": round(momentum_pts, 1),
        "trend": round(trend_pts, 1),
        "relativeStrength": round(rs_pts, 1),
        "volatility": round(volatility_pts, 1),
        "coil": round(coil_pts, 1),
        "candle": round(candle_pts, 1),
        "liquidity": round(liquidity_pts, 1),
    }
    return int(round(sum(parts.values()))), parts


def identify_power_setup(m: dict, bull_score: int, bear_score: int) -> Optional[dict]:
    if max(bull_score, bear_score) < POWER_CANDIDATE_MIN_SCORE:
        return None
    if bull_score == bear_score:
        # Avoid arbitrary bullish bias in ties.
        if m["price"] > m["vwap"] and m["recent3Pct"] > 0:
            side = "CE"
        elif m["price"] < m["vwap"] and m["recent3Pct"] < 0:
            side = "PE"
        else:
            return None
    else:
        side = "CE" if bull_score > bear_score else "PE"
    power_score = bull_score if side == "CE" else bear_score
    aligned = m["price"] > m["vwap"] if side == "CE" else m["price"] < m["vwap"]
    directional_momentum = m["recent3Pct"] > 0 if side == "CE" else m["recent3Pct"] < 0
    rvol_ok = m["rvol"] >= 1.15
    if side == "CE":
        breakout = bool(m["orbReady"] and (m["price"] > m["orbHigh15"] or m["price"] > m["context"]["pdh"]))
        near_level = bool(m["orbReady"] and m["orbHigh15"] > 0 and abs(pct_change(m["price"], m["orbHigh15"])) <= 0.30)
        trigger = (m["context"]["pdh"] if m["price"] > m["context"]["pdh"] else m["orbHigh15"]) if m["orbReady"] else None
        invalidation = m["orbLow15"] if m["orbReady"] else None
        near_pd = m["price"] > m["context"]["pdh"]
        close_location = m["closeLocation"]
    else:
        breakout = bool(m["orbReady"] and (m["price"] < m["orbLow15"] or m["price"] < m["context"]["pdl"]))
        near_level = bool(m["orbReady"] and m["orbLow15"] > 0 and abs(pct_change(m["price"], m["orbLow15"])) <= 0.30)
        trigger = (m["context"]["pdl"] if m["price"] < m["context"]["pdl"] else m["orbLow15"]) if m["orbReady"] else None
        invalidation = m["orbHigh15"] if m["orbReady"] else None
        near_pd = m["price"] < m["context"]["pdl"]
        close_location = m["closeLocation"]
    ema_aligned = m["ema9"] >= m["ema20"] if side == "CE" else m["ema9"] <= m["ema20"]
    confirmed = bool(breakout and aligned and directional_momentum and rvol_ok and ema_aligned)
    if not m["orbReady"]:
        status = "BUILDING OPENING RANGE"
    elif confirmed:
        status = "BREAKOUT CONFIRMED"
    elif near_level or (aligned and directional_momentum):
        status = "EARLY WATCH"
    else:
        status = "MOMENTUM WATCH"
    if m["atrUsedPct"] >= 90:
        risk_flag = "EXTENDED VS ATR"
    elif m["gapPct"] >= 1.0 and m["sessionReturnPct"] < -0.4:
        risk_flag = "GAP-UP FADE"
    elif m["gapPct"] <= -1.0 and m["sessionReturnPct"] > 0.4:
        risk_flag = "GAP-DOWN RECOVERY"
    elif m["avgTurnoverCr"] < 5:
        risk_flag = "CHECK LIQUIDITY"
    elif not m["rvolAvailable"]:
        risk_flag = "RVOL BASELINE LIMITED"
    else:
        risk_flag = "NORMAL"
    reasons = []
    if breakout:
        reasons.append("15m ORB / previous-day level break")
    elif near_level:
        reasons.append("Near 15m opening-range level")
    if aligned:
        reasons.append("VWAP aligned")
    if rvol_ok:
        reasons.append("Relative volume elevated")
    if directional_momentum:
        reasons.append("Recent momentum aligned")
    if m["isNR7"] or m["isNarrowCPR"] or m["bbSqueeze"]:
        reasons.append("Compression context")
    if m["alphaNum"] > 0.3 and side == "CE" or m["alphaNum"] < -0.3 and side == "PE":
        reasons.append("Relative strength vs Nifty")
    return {
        "symbol": m["symbol"], "type": side, "sector": m["sector"],
        "powerScore": power_score,
        "grade": "A+" if power_score >= 80 else ("A" if power_score >= 70 else ("B" if power_score >= 60 else "WATCH")),
        "status": status, "riskFlag": risk_flag,
        "detectTime": "PENDING" if not confirmed else "",  # filled with first confirmed time below
        "price": m["price"], "pctChange": f"{m['pctChangeNum']:+.2f}%",
        "sessionReturn": f"{m['sessionReturnPct']:+.2f}%", "gapPct": f"{m['gapPct']:+.2f}%",
        "alpha": f"{m['alphaNum']:+.2f}%", "rvol": round(m["rvol"], 2),
        "rvolAvailable": bool(m["rvolAvailable"]), "rsi": m["rsi"], "adx": m["adx"],
        "vwap": m["vwap"], "ema9": m["ema9"], "ema20": m["ema20"],
        "orbHigh": m["orbHigh15"] if m["orbReady"] else None,
        "orbLow": m["orbLow15"] if m["orbReady"] else None,
        "previousDayHigh": m["context"]["pdh"], "previousDayLow": m["context"]["pdl"],
        "atr": m["atr"], "atrUsedPct": m["atrUsedPct"], "fuelLeft": f"{m['fuelLeftPct']:.0f}%",
        "avgTurnoverCr": m["avgTurnoverCr"], "lotSize": LOT_SIZES.get(m["symbol"], None),
        "triggerLevel": round(trigger, 2) if trigger else None,
        "invalidationLevel": round(invalidation, 2) if invalidation else None,
        "reasons": reasons, "scoreBreakdown": {},
        "isNarrowCPR": m["isNarrowCPR"], "isNR7": m["isNR7"], "bbSqueeze": m["bbSqueeze"],
        "breakoutConfirmed": confirmed,
    }


def first_power_confirmation_time(m: dict, side: str, historical_baselines: dict[int, float]) -> Optional[str]:
    """First completed candle satisfying the confirmation rule; no future bars used."""
    today = m["today"]
    if len(today) < 4:
        return None
    or_high = safe_float(today["High"].iloc[:3].max())
    or_low = safe_float(today["Low"].iloc[:3].min())
    typical = (today["High"] + today["Low"] + today["Close"]) / 3.0
    vwap_all = (typical * today["Volume"]).cumsum() / today["Volume"].cumsum().replace(0, np.nan)
    vwap_all = vwap_all.ffill().fillna(today["Close"])
    closes = today["Close"]
    ema9 = closes.ewm(span=9, adjust=False).mean()
    ema20 = closes.ewm(span=20, adjust=False).mean()
    for i in range(3, len(today)):
        close = safe_float(closes.iloc[i])
        prefix = today.iloc[:i + 1]
        rvol = current_rvol(prefix, i, historical_baselines)
        ret3 = pct_change(close, safe_float(closes.iloc[i - 3]))
        if side == "CE":
            level_break = close > or_high or close > m["context"]["pdh"]
            ok = level_break and close > safe_float(vwap_all.iloc[i]) and rvol >= 1.15 and ret3 > 0 and safe_float(ema9.iloc[i]) >= safe_float(ema20.iloc[i])
        else:
            level_break = close < or_low or close < m["context"]["pdl"]
            ok = level_break and close < safe_float(vwap_all.iloc[i]) and rvol >= 1.15 and ret3 < 0 and safe_float(ema9.iloc[i]) <= safe_float(ema20.iloc[i])
        if ok:
            stamp = today.index[i]
            return stamp.tz_convert(IST).strftime("%H:%M") if stamp.tzinfo else stamp.strftime("%H:%M")
    return None


def classify_legacy_tier(m: dict, sector_strong: bool = False) -> Optional[dict]:
    close = m["price"]
    open_day = m["openDay"]
    prev_close = m["context"]["prevClose"]
    pdh = m["context"]["pdh"]
    pdl = m["context"]["pdl"]
    vwap = safe_float(m["legacyVwapSeries"].iloc[-1], close)
    pct = m["pctChangeNum"]
    high_day, low_day = m["highDay"], m["lowDay"]
    from_low = (close - low_day) / low_day * 100 if low_day > 0 else 0.0
    from_high = (high_day - close) / high_day * 100 if high_day > 0 else 0.0
    p = m["context"]
    p1 = bool(close > open_day and pct > 0)
    p2 = bool(close > vwap)
    p3 = bool(close > pdh)
    p4 = bool(close > m["orbHigh5"])
    p5 = bool(from_high <= 0.65)
    p6 = bool(m["legacyVolX"] >= 1.5)
    p7 = bool(m["legacyRsi"] >= 56)
    bull_score = sum([p1, p2, p3, p4, p5, p6, p7])
    b1 = bool(close < open_day and pct < 0)
    b2 = bool(close < vwap)
    b3 = bool(close < pdl)
    b4 = bool(close < m["orbLow5"])
    b5 = bool(from_low <= 0.65)
    b6 = bool(m["legacyVolX"] >= 1.5)
    b7 = bool(m["legacyRsi"] <= 44)
    bear_score = sum([b1, b2, b3, b4, b5, b6, b7])
    opened_low = bool(open_day > 0 and abs(open_day - low_day) / open_day <= 0.002 and close > open_day)
    is52w = m["is52W"]
    tier, side, ideal = None, "CE", False
    if ((opened_low and close > vwap and pct >= 0.8) or
        (close > m["orbHigh5"] and close > vwap and m["legacyVolX"] >= 3.2 and bull_score >= 5)):
        tier, side = "BRAHMASTRA", "CE"
    elif ((close > m["orbHigh5"] and close > vwap and bull_score >= 5 and pct >= 1.0) or
          (is52w and close > m["orbHigh5"] and pct >= 0.8)):
        tier, side = "EXPLOSIVE", "CE"
        ideal = bool(bull_score >= 6 and sector_strong)
    elif close > vwap and bull_score >= 4 and pct >= 0.5:
        tier, side = "STRONG", "CE"
    elif close < vwap and close < m["orbLow5"] and (bear_score >= 5 or pct <= -1.8):
        tier, side = "SHORT ZONE", "PE"
    elif close < vwap and bear_score >= 4 and pct <= -0.8:
        tier, side = "STRONG", "PE"
    elif bull_score >= 3 and pct >= 0.35 and m["legacyVolX"] >= 1.3:
        tier, side = "SPURT", "CE"
    elif bear_score >= 3 and pct <= -0.50 and m["legacyVolX"] >= 1.3:
        tier, side = "SPURT", "PE"
    if not tier:
        return None
    risk_sl = m["orbLow5"] if side == "CE" else m["orbHigh5"]
    risk = abs(close - risk_sl) if abs(close - risk_sl) > 0 else close * 0.008
    t1 = close + risk * 1.5 if side == "CE" else close - risk * 1.5
    is_rally = bool(side == "CE" and (pct >= 1.5 or (p3 and p2 and from_high <= 0.45 and (p["prevDayBullish"] or sector_strong))))
    is_drop = bool(side == "PE" and (pct <= -1.2 or (b3 and b2 and from_low <= 0.45)))
    fade_risk = bool(side == "CE" and from_high >= 0.85)
    score = bull_score if side == "CE" else bear_score
    # The historical percentage is deliberately labelled as a heuristic score, not probability.
    heuristic = min(96, 52 + score * 4 + (5 if p["isNarrowCPR"] else 0) + (5 if p["isNR7"] else 0) + (4 if m["fuelLeftPct"] >= 65 else 0) + (4 if sector_strong else 0) + (3 if (is_rally or is_drop) else 0))
    pillars = (
        [{"name": "Trend", "ok": p1}, {"name": "VWAP", "ok": p2}, {"name": "PDH", "ok": p3},
         {"name": "ORB", "ok": p4}, {"name": "Follow", "ok": p5}, {"name": "Vol", "ok": p6}, {"name": "RSI", "ok": p7}]
        if side == "CE" else
        [{"name": "Trend", "ok": b1}, {"name": "VWAP", "ok": b2}, {"name": "PDL", "ok": b3},
         {"name": "ORB", "ok": b4}, {"name": "Follow", "ok": b5}, {"name": "Vol", "ok": b6}, {"name": "RSI", "ok": b7}]
    )
    strike_step = 50 if close >= 500 else (20 if close >= 200 else 10)
    rounded_strike = int(round(close / strike_step) * strike_step)
    strike_label = f"{rounded_strike} {side} (approx)"
    return {
        "symbol": m["symbol"], "type": side, "tier": tier, "optionTag": "⚡ OPTION",
        "score": f"{score}/7", "numScore": int(score), "prob": f"{heuristic}% heuristic",
        "probScore": int(heuristic), "detectTime": "", "price": m["price"],
        "pctChange": f"{pct:+.2f}%", "absChange": abs(pct),
        "volumeX": f"{m['legacyVolX']:.2f}x", "numVol": m["legacyVolX"],
        "strike": strike_label, "lotSize": LOT_SIZES.get(m["symbol"], None),
        "sectorStatus": f"{m['sector']} {'🔥 STRONG' if sector_strong else '• WATCH'}",
        "watchBadge": "★★ MODERATE WATCH" if tier == "SPURT" else ("★★★ STRONG BUY WATCH" if side == "CE" else "★★★ STRONG SELL WATCH"),
        "candleInfo": f"body {m['lastBodyPct']:.2f}% • low ▲{from_low:.2f}% • high ▼{from_high:.2f}%",
        "is52W": bool(is52w), "isIdeal": bool(ideal), "isRally": bool(is_rally), "isDrop": bool(is_drop),
        "fadeRisk": bool(fade_risk), "openedAtLow": bool(opened_low),
        "isNarrowCPR": bool(p["isNarrowCPR"]), "isNR7": bool(p["isNR7"]),
        "fuelLeft": f"{m['fuelLeftPct']:.0f}%", "numFuel": m["fuelLeftPct"],
        "alpha": f"{m['alphaNum']:+.2f}%", "pillars": pillars, "sl": round(risk_sl, 2),
        "t1": round(t1, 2), "rsi": m["legacyRsi"],
    }


def legacy_signal_time(m: dict, final_tier: str, final_side: str, sector_strong: bool) -> str:
    """Find the first completed 5m candle where that tier and direction passed.

    This replays the legacy tier rules over each prefix of the day. It uses only bars
    up through that timestamp, not the final full-day high/low.
    """
    today = m["today"]
    prev_close = m["context"]["prevClose"]
    pdh, pdl = m["context"]["pdh"], m["context"]["pdl"]
    high52 = m["context"]["high52w"]
    for i in range(1, len(today)):
        prefix = today.iloc[:i + 1]
        close = safe_float(prefix["Close"].iloc[-1])
        open_day = safe_float(prefix["Open"].iloc[0])
        run_high = safe_float(prefix["High"].max())
        run_low = safe_float(prefix["Low"].min())
        if min(close, open_day, prev_close, run_low) <= 0:
            continue
        pct = pct_change(close, prev_close)
        typical = (prefix["High"] + prefix["Low"] + prefix["Close"]) / 3
        cum_v = prefix["Volume"].cumsum()
        vwap_s = (typical * prefix["Volume"]).cumsum() / cum_v.replace(0, np.nan)
        vwap = safe_float(vwap_s.iloc[-1], close)
        avg_v = safe_float(prefix["Volume"].mean())
        current_vx = safe_float(prefix["Volume"].iloc[-1]) / avg_v if avg_v > 0 else 1.0
        peak_vx = safe_float(prefix["Volume"].iloc[:min(12, len(prefix))].max()) / avg_v if avg_v > 0 else 1.0
        volx = max(current_vx, peak_vx)
        rsi_s = calc_rsi(prefix["Close"])
        rsi = safe_float(rsi_s.iloc[-1], 50.0)
        from_low = (close - run_low) / run_low * 100
        from_high = (run_high - close) / run_high * 100 if run_high > 0 else 0
        first_hi = safe_float(prefix["High"].iloc[0])
        first_lo = safe_float(prefix["Low"].iloc[0])
        p1, p2, p3 = close > open_day and pct > 0, close > vwap, close > pdh
        p4, p5, p6, p7 = close > first_hi, from_high <= 0.65, volx >= 1.5, rsi >= 56
        bull = sum([p1, p2, p3, p4, p5, p6, p7])
        b1, b2, b3 = close < open_day and pct < 0, close < vwap, close < pdl
        b4, b5, b6, b7 = close < first_lo, from_low <= 0.65, volx >= 1.5, rsi <= 44
        bear = sum([b1, b2, b3, b4, b5, b6, b7])
        opened_low = abs(open_day - run_low) / open_day <= 0.002 and close > open_day
        is52 = high52 > 0 and close >= high52 * 0.985
        tier, side = None, "CE"
        if ((opened_low and close > vwap and pct >= 0.8) or (close > first_hi and close > vwap and volx >= 3.2 and bull >= 5)):
            tier, side = "BRAHMASTRA", "CE"
        elif ((close > first_hi and close > vwap and bull >= 5 and pct >= 1.0) or (is52 and close > first_hi and pct >= 0.8)):
            tier, side = "EXPLOSIVE", "CE"
        elif close > vwap and bull >= 4 and pct >= 0.5:
            tier, side = "STRONG", "CE"
        elif close < vwap and close < first_lo and (bear >= 5 or pct <= -1.8):
            tier, side = "SHORT ZONE", "PE"
        elif close < vwap and bear >= 4 and pct <= -0.8:
            tier, side = "STRONG", "PE"
        elif bull >= 3 and pct >= 0.35 and volx >= 1.3:
            tier, side = "SPURT", "CE"
        elif bear >= 3 and pct <= -0.50 and volx >= 1.3:
            tier, side = "SPURT", "PE"
        if tier == final_tier and side == final_side:
            stamp = prefix.index[-1]
            return stamp.tz_convert(IST).strftime("%H:%M") if stamp.tzinfo else stamp.strftime("%H:%M")
    stamp = today.index[-1]
    return stamp.tz_convert(IST).strftime("%H:%M") if stamp.tzinfo else stamp.strftime("%H:%M")


def to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, (np.ndarray,)):
        return to_json_safe(value.tolist())
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main() -> None:
    now = dt.datetime.now(IST)
    current_ist_time = now.strftime("%I:%M %p")
    print(f"ORION scan started at {current_ist_time} IST for {len(SYMBOLS)} configured symbols")

    daily_data, intraday_data = download_universe(SYMBOLS)
    nifty_daily = download_single("^NSEI", "1y", "1d")
    nifty_intraday = download_single("^NSEI", "5d", "5m")

    snapshots: list[dict] = []
    for sym in SYMBOLS:
        try:
            metrics = calculate_snapshot(sym, daily_data.get(sym, pd.DataFrame()), intraday_data.get(sym, pd.DataFrame()), now, nifty_daily, nifty_intraday)
            if metrics:
                snapshots.append(metrics)
            else:
                print(f"SKIP {sym}: no usable daily/intraday data")
        except Exception as exc:
            print(f"ERROR analyzing {sym}: {type(exc).__name__}: {exc}")

    # Compute sector averages from the entire scanned set, avoiding ticker-order bias.
    sector_returns: dict[str, list[float]] = defaultdict(list)
    for m in snapshots:
        sector_returns[m["sector"]].append(m["sessionReturnPct"] / 100.0)
    sector_average = {sector: (sum(vals) / len(vals) if vals else 0.0) for sector, vals in sector_returns.items()}

    advances = sum(1 for m in snapshots if m["pctChangeNum"] >= 0)
    declines = sum(1 for m in snapshots if m["pctChangeNum"] < 0)
    if advances > declines * 1.5:
        sentiment = "STRONG BULLISH"
    elif advances >= declines:
        sentiment = "BULLISH"
    else:
        sentiment = "BEARISH"

    buckets = {name: [] for name in ["BRAHMASTRA", "EXPLOSIVE", "STRONG", "SPURT", "SHORT ZONE"]}
    gpt_power_stocks = []
    session_dates = []

    for m in snapshots:
        session_dates.append(m["sessionDate"])
        sector_avg = sector_average.get(m["sector"], 0.0)
        sector_strong = bool((m["pctChangeNum"] >= 0 and sector_avg > 0.0015) or (m["pctChangeNum"] < 0 and sector_avg < -0.0015))

        legacy = classify_legacy_tier(m, sector_strong)
        if legacy:
            legacy["detectTime"] = legacy_signal_time(m, legacy["tier"], legacy["type"], sector_strong)
            buckets[legacy["tier"]].append(legacy)

        bull_score, bull_parts = directional_power_score(m, "CE")
        bear_score, bear_parts = directional_power_score(m, "PE")
        power = identify_power_setup(m, bull_score, bear_score)
        if power:
            power["scoreBreakdown"] = bull_parts if power["type"] == "CE" else bear_parts
            baselines = historical_rvol_curve(m["allIntraday"], dt.date.fromisoformat(m["sessionDate"]))
            confirmation_time = first_power_confirmation_time(m, power["type"], baselines)
            if power["breakoutConfirmed"] and confirmation_time:
                power["detectTime"] = confirmation_time
            else:
                power["detectTime"] = "Not confirmed"
            power["sectorStatus"] = f"{m['sector']} {'🔥 STRONG' if sector_strong else '• WATCH'}"
            power["relativeStrength"] = round(m["alphaNum"], 2)
            power["marketSessionDate"] = m["sessionDate"]
            gpt_power_stocks.append(power)

    leaders: list[dict] = []
    for tier_name in ["BRAHMASTRA", "EXPLOSIVE", "STRONG", "SPURT", "SHORT ZONE"]:
        sorted_tier = sorted(buckets[tier_name], key=lambda x: (x["numScore"], x["numVol"], x["numFuel"], x["absChange"]), reverse=True)[:10]
        leaders.extend(sorted_tier)

    # Limit each symbol to its strongest directional record (identify_power_setup already returns one side).
    gpt_power_stocks.sort(key=lambda x: (x["powerScore"], x["rvol"], abs(float(x["pctChange"].replace("%", "")))), reverse=True)
    gpt_power_stocks = gpt_power_stocks[:POWER_MAX_CARDS]

    scan_session = max(session_dates) if session_dates else None
    status = "SESSION DATA AVAILABLE" if scan_session == now.date().isoformat() else "LAST AVAILABLE SESSION DATA"
    output = {
        "lastUpdated": current_ist_time,
        "scanGeneratedAt": now.isoformat(),
        "sessionDate": scan_session,
        "marketDataStatus": status,
        "marketDataNote": "Yahoo Finance data may be delayed. Verify quotes and order levels with your broker before trading.",
        "breadth": {"advances": int(advances), "declines": int(declines), "sentiment": sentiment},
        "leaders": leaders,
        "gptPowerStocks": gpt_power_stocks,
        "scanSummary": {
            "configuredSymbols": len(SYMBOLS), "symbolsWithData": len(snapshots),
            "universeSource": UNIVERSE_SOURCE,
            "legacySignals": len(leaders), "gptPowerCandidates": len(gpt_power_stocks),
            "powerScoreMeaning": "Relative ranking score out of 100; not a probability or guaranteed prediction."
        }
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(to_json_safe(output), f, indent=2, ensure_ascii=False, allow_nan=False)

    print(f"Saved data.json: data={len(snapshots)}, legacy signals={len(leaders)}, GPT POWER candidates={len(gpt_power_stocks)}")
    print(f"Session: {scan_session}; Status: {status}; Advances={advances}, Declines={declines}")

    # Optional concise Telegram headline. This function is intentionally not called per ticker.
    if gpt_power_stocks and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        top = gpt_power_stocks[:5]
        lines = [f"<b>ORION GPT POWER STOCKS</b> — {current_ist_time} IST"]
        for item in top:
            lines.append(f"{item['symbol']} {item['type']} | Score {item['powerScore']}/100 | {item['status']} | RVOL {item['rvol']}x")
        send_telegram_alert("\n".join(lines))


if __name__ == "__main__":
    main()
