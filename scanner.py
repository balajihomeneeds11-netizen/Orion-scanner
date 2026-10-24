"""ORION 7-PILLARS + GPT POWER STOCKS scanner.

Research-inspired, rule-based NSE stock screener. It does not use an LLM or
claim predictive certainty. Yahoo Finance data may be delayed or incomplete.
"""
from __future__ import annotations

import datetime as dt
import html as html_lib
import hashlib
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
# Official NSE cash-market holiday dates for 2026. Future years are loaded from
# NSE's holiday-master endpoint; scheduled runs fail closed if that calendar cannot be verified.
NSE_CM_HOLIDAYS: dict[int, set[str]] = {
    2026: {
        # NSE cash-equity holidays, verified against NSE's 2026 equities calendar.
        "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31",
        "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26",
        "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24",
        "2026-12-25",
    }
}


def _fetch_nse_cm_holidays(year: int) -> Optional[set[str]]:
    """Load NSE's published CM holiday calendar for a year not bundled above."""
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": NSE_HOME_URL,
        })
        session.get(NSE_HOME_URL, timeout=6)
        response = session.get(f"{NSE_HOME_URL}/api/holiday-master?type=trading&year={year}", timeout=8)
        response.raise_for_status()
        payload = response.json()
        records = payload.get("CM") if isinstance(payload, dict) else None
        if not isinstance(records, list) or len(records) < 5:
            return None
        dates: set[str] = set()
        for row in records:
            if not isinstance(row, dict):
                continue
            value = str(row.get("tradingDate", "")).strip()
            if not value:
                continue
            parsed = None
            for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"):
                try:
                    parsed = dt.datetime.strptime(value, fmt).date()
                    break
                except ValueError:
                    pass
            if parsed:
                dates.add(parsed.isoformat())
        return dates if len(dates) >= 5 else None
    except Exception as exc:
        print(f"NSE holiday calendar unavailable for {year}: {type(exc).__name__}: {exc}")
        return None


def skip_scheduled_run_if_market_closed(now: dt.datetime) -> bool:
    """Skip automatic GitHub scheduled runs on weekends/verified NSE holidays.

    Manual workflow_dispatch runs are deliberately allowed for troubleshooting.
    """
    event_name = os.getenv("GITHUB_EVENT_NAME", "").strip().lower()
    if event_name != "schedule":
        return False
    local_date = now.astimezone(IST).date()
    if local_date.weekday() >= 5:
        print(f"SKIP scheduled scan: {local_date.isoformat()} is Saturday/Sunday (NSE market closed).")
        return True
    year = local_date.year
    holidays = NSE_CM_HOLIDAYS.get(year)
    if holidays is None:
        holidays = _fetch_nse_cm_holidays(year)
        if holidays is None:
            print(f"SKIP scheduled scan: could not verify NSE {year} holiday calendar; failing safe to avoid a holiday run.")
            return True
        NSE_CM_HOLIDAYS[year] = holidays
    if local_date.isoformat() in holidays:
        print(f"SKIP scheduled scan: {local_date.isoformat()} is listed in NSE's CM trading-holiday calendar.")
        return True
    return False

# Existing configured symbol universe for general screener tabs. GPT POWER is separately restricted
# to the current NSE F&O stock-underlying whitelist loaded below.
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
STATIC_SYMBOLS = list(SYMBOLS)  # Keep existing/general screener coverage.
NSE_HOME_URL = "https://www.nseindia.com"
NSE_REFERER_URL = "https://www.nseindia.com/products-services/equity-derivatives-list-underlyings-information"
NSE_UNDERLYINGS_API = "https://www.nseindia.com/api/underlying-information"
# Public fallback snapshot maintained in an open-source NSE F&O watchlist repository.
# It contains only the individual-stock UnderlyingList, not option-chain data.
GITHUB_FNO_SNAPSHOT_URL = "https://raw.githubusercontent.com/sv26000/nse-fno-watchlist/main/data.json"
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTYFPI"}


def _validated_fno_symbols(records: Any) -> list[str]:
    """Extract only explicit underlying symbols from an NSE/API snapshot."""
    found: list[str] = []
    if not isinstance(records, list):
        return found
    for item in records:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if symbol and re.fullmatch(r"[A-Z0-9&.\-]{1,30}", symbol) and symbol not in INDEX_UNDERLYINGS:
            found.append(symbol)
    # Avoid accepting a partial or blocked/error response as the active whitelist.
    return list(dict.fromkeys(found)) if len(set(found)) >= 150 else []


def _extract_fno_from_payload(payload: Any) -> list[str]:
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    # The official API has {UnderlyingList: [...], IndexList: [...]}.
    if isinstance(payload, dict):
        return _validated_fno_symbols(payload.get("UnderlyingList", []))
    # GitHub snapshot is a bare list of {symbol, underlying, serialNumber} records.
    if isinstance(payload, list):
        return _validated_fno_symbols(payload)
    return []


def load_fno_symbols() -> tuple[list[str], str]:
    """Load the F&O stock whitelist without requesting any stock's option-chain data.

    Order: official NSE underlying-information API, then public GitHub snapshot.
    If both sources fail, fail closed for GPT POWER eligibility rather than falsely
    labelling every scanned symbol as F&O eligible.
    """
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        })
        # NSE expects browser session cookies before the underlying-information API call.
        session.get(NSE_HOME_URL, timeout=12)
        session.get(NSE_REFERER_URL, timeout=12)
        response = session.get(NSE_UNDERLYINGS_API, headers={"Referer": NSE_REFERER_URL}, timeout=12)
        response.raise_for_status()
        symbols = _extract_fno_from_payload(response.json())
        if symbols:
            print(f"F&O eligibility source: official NSE API ({len(symbols)} underlyings)")
            return symbols, "official NSE underlying-information API"
        print("NSE API returned an empty/partial underlying list; trying GitHub snapshot.")
    except Exception as exc:
        print(f"NSE F&O API unavailable ({type(exc).__name__}: {exc}); trying GitHub snapshot.")

    try:
        import requests
        response = requests.get(
            GITHUB_FNO_SNAPSHOT_URL,
            headers={"User-Agent": "ORION-Stock-Screener"},
            timeout=12,
        )
        response.raise_for_status()
        symbols = _extract_fno_from_payload(response.json())
        if symbols:
            print(f"F&O eligibility source: GitHub NSE snapshot ({len(symbols)} underlyings)")
            return symbols, "GitHub NSE F&O snapshot (fallback)"
        print("GitHub snapshot returned an empty/partial underlying list.")
    except Exception as exc:
        print(f"GitHub F&O snapshot unavailable ({type(exc).__name__}: {exc}).")

    # Intentionally empty: stale static symbols must not be falsely labelled F&O eligible.
    return [], "unavailable — F&O eligibility not verified"


# Do not perform network requests during module import. The live F&O list is loaded
# when main() starts; this also makes the scanner's calculation helpers testable offline.
FNO_SYMBOLS: list[str] = []
FNO_UNIVERSE_SOURCE = "not loaded yet"
FNO_SYMBOL_SET: set[str] = set()
# Preserve all existing symbols for general/legacy tabs. The current F&O universe is
# appended at scan startup; GPT POWER is separately filtered against FNO_SYMBOL_SET.
SYMBOLS = list(STATIC_SYMBOLS)
YF_SYMBOLS = {symbol: f"{symbol}.NS" for symbol in SYMBOLS}

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

# Sector dashboard universe. Labels intentionally match the supplied reference screenshots.
# Returns are representative averages of available constituent stocks (pct change vs prior close),
# not official sector-index quotes. A sector with no usable constituents is shown as unavailable.
def _sector_members(symbols: str) -> set[str]:
    return set(symbols.split())

SECTOR_INDEX_MEMBERS: dict[str, set[str]] = {
    "PSU BANK": _sector_members("SBIN BANKBARODA CANBK PNB UNIONBANK BANKINDIA INDIANB MAHABANK CENTRALBK UCOBANK INDIANB INDBANK"),
    "OIL & GAS": _sector_members("RELIANCE ONGC BPCL IOC HINDPETRO GAIL IGL MGL PETRONET AEGISLOG OIL GUJGASLTD GSPL"),
    "METAL": _sector_members("TATASTEEL JSWSTEEL JINDALSTEL SAIL HINDALCO VEDL NATIONALUM HINDCOPPER NMDC COALINDIA MOIL RATNAMANI"),
    "ENERGY": _sector_members("NTPC POWERGRID TATAPOWER TORNTPOWER ADANIGREEN JSWENERGY NHPC SJVN CESC IEX PFC RECLTD"),
    "BANKNIFTY": _sector_members("HDFCBANK ICICIBANK SBIN AXISBANK KOTAKBANK INDUSINDBK FEDERALBNK BANDHANBNK IDFCFIRSTB RBLBANK AUBANK BANKBARODA CANBK PNB UNIONBANK BANKINDIA CUB INDIANB"),
    "PHARMA": _sector_members("SUNPHARMA DRREDDY CIPLA DIVISLAB LUPIN AUROPHARMA ALKEM TORNTPHARM GLENMARK ZYDUSLIFE BIOCON LAURUSLABS GRANULES IPCALAB NATCOPHARM MANKIND"),
    "COMMODITIES": _sector_members("TATASTEEL JSWSTEEL JINDALSTEL SAIL HINDALCO VEDL NATIONALUM HINDCOPPER NMDC COALINDIA ONGC BPCL IOC HINDPETRO RELIANCE AARTIIND ATUL DEEPAKNTR CHAMBLFERT COROMANDEL GNFC NAVINFLUOR SRF UPL PIIND"),
    "INFRA": _sector_members("LT ADANIPORTS CONCOR DLF GODREJPROP OBEROIRLTY PHOENIXLTD PRESTIGE NBCC RVNL HUDCO IRB KNRCON PNCINFRA KEC HGINFRA"),
    "AUTO": _sector_members("TATAMOTORS TMPV MARUTI M&M BAJAJ-AUTO HEROMOTOCO EICHERMOT TVSMOTOR ASHOKLEY BHARATFORG BALKRISIND APOLLOTYRE MRF MOTHERSON BOSCHLTD EXIDEIND SONACOMS UNOMINDA TIINDIA"),
    "HEALTHCARE": _sector_members("SUNPHARMA DRREDDY CIPLA DIVISLAB LUPIN AUROPHARMA ALKEM TORNTPHARM GLENMARK ZYDUSLIFE BIOCON LAURUSLABS APOLLOHOSP MAXHEALTH FORTIS LALPATHLAB METROPOLIS SYNGENE"),
    "DEFENCE": _sector_members("BEL HAL BDL GRSE MAZDOCK COCHINSHIP DATAPATTNS PARAS IDEA"),
    "CAPITAL MRKT": _sector_members("BSE MCX CDSL KFINTECH CAMS ANGELONE 360ONE IIFL MOTILALOFS HDFCAMC NUVAMA"),
    "CONSUMPTION": _sector_members("ITC HINDUNILVR NESTLEIND BRITANNIA TATACONSUM DABUR MARICO GODREJCP COLPAL UBL MCDOWELL-N VBL TRENT DMART NYKAA ZOMATO ETERNAL JUBLFOOD DEVYANI WESTLIFE PVRINOX TITAN ASIANPAINT"),
    "NIFTY": _sector_members("ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL BPCL BRITANNIA CIPLA COALINDIA DIVISLAB DRREDDY EICHERMOT GRASIM HCLTECH HDFCBANK HDFCLIFE HEROMOTOCO HINDALCO HINDUNILVR ICICIBANK INDUSINDBK INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI NESTLEIND NTPC ONGC POWERGRID RELIANCE SBILIFE SBIN SHRIRAMFIN SUNPHARMA TATACONSUM TATASTEEL TCS TECHM TITAN TRENT ULTRACEMCO WIPRO"),
    "MIDCAP": _sector_members("AARTIIND AUBANK AUROPHARMA BALKRISIND BHARATFORG COFORGE CONCOR CUMMINS DEEPAKNTR DIXON FEDERALBNK HINDPETRO INDHOTEL INDUSTOWER LALPATHLAB LAURUSLABS MPHASIS PERSISTENT PIIND POLYCAB PRESTIGE RVNL SHREECEM SRF SUPREMEIND TATACHEM TVSMOTOR VOLTAS ZEEL"),
    "CONSR DURBL": _sector_members("DIXON POLYCAB HAVELLS CROMPTON VOLTAS WHIRLPOOL AMBER KAYNES TITAN VGUARD BLUESTAR HINDWARE SYMPHONY"),
    "REALTY": _sector_members("DLF GODREJPROP OBEROIRLTY PHOENIXLTD PRESTIGE SOBHA BRIGADE MAHLIFE SUNTECK ANANTRAJ"),
    "SERVICES": _sector_members("INDUSTOWER BHARTIARTL IDEA CONCOR ADANIPORTS INDHOTEL ETERNAL ZOMATO NAUKRI BSE MCX CDSL KFINTECH CAMS ANGELONE 360ONE BAJFINANCE HDFCLIFE ICICIPRULI"),
    "IT": _sector_members("TCS INFY HCLTECH WIPRO TECHM LTIM COFORGE PERSISTENT MPHASIS BSOFT OFSS NAUKRI LTTS INTELLECT KPITTECH TATAELXSI ECLERX FSL"),
    "FMCG": _sector_members("HINDUNILVR ITC NESTLEIND BRITANNIA TATACONSUM DABUR MARICO GODREJCP COLPAL UBL MCDOWELL-N VBL EMAMILTD GILLETTE"),
    "FINNIFTY": _sector_members("HDFCBANK ICICIBANK SBIN AXISBANK KOTAKBANK INDUSINDBK FEDERALBNK BANKBARODA BAJFINANCE BAJAJFINSV CHOLAFIN SHRIRAMFIN MUTHOOTFIN PFC RECLTD HDFCLIFE ICICIPRULI SBILIFE ICICIGI HDFCAMC ANGELONE BSE CDSL KFINTECH CAMS"),
    "CHEMICALS": _sector_members("AARTIIND ATUL DEEPAKNTR CHAMBLFERT COROMANDEL GNFC GUJGASLTD NAVINFLUOR SRF UPL PIIND PIDILITIND AETHER CHEMPLAST FINPIPE FINCABLES TATACHEM BALAMINES CLEAN"),
    "PVT BANK": _sector_members("HDFCBANK ICICIBANK AXISBANK KOTAKBANK INDUSINDBK FEDERALBNK BANDHANBNK IDFCFIRSTB RBLBANK AUBANK YESBANK"),
}
SECTOR_LABEL_ORDER = [
    "PSU BANK", "OIL & GAS", "METAL", "ENERGY", "BANKNIFTY", "PHARMA",
    "COMMODITIES", "INFRA", "AUTO", "HEALTHCARE", "DEFENCE", "CAPITAL MRKT",
    "CONSUMPTION", "NIFTY", "MIDCAP", "CONSR DURBL", "REALTY", "SERVICES",
    "IT", "FMCG", "FINNIFTY", "CHEMICALS", "PVT BANK",
]


# Yahoo Finance index symbols for sectors with a matching published NSE/Nifty index.
# Yahoo is still the data vendor (not a direct official NSE real-time feed); unsupported
# symbols fall back to a clearly labelled, same-session constituent proxy.
SECTOR_INDEX_TICKERS: dict[str, str] = {
    "PSU BANK": "^CNXPSUBANK",
    "OIL & GAS": "^CNXOILGAS",
    "METAL": "^CNXMETAL",
    "ENERGY": "^CNXENERGY",
    "BANKNIFTY": "^NSEBANK",
    "PHARMA": "^CNXPHARMA",
    "COMMODITIES": "^CNXCMDT",
    "INFRA": "^CNXINFRA",
    "AUTO": "^CNXAUTO",
    "HEALTHCARE": "^CNXHEALTHCARE",
    "CONSUMPTION": "^CNXCONSUM",
    "NIFTY": "^NSEI",
    "MIDCAP": "^CNXMIDCAP",
    "CONSR DURBL": "^CNXCONSUMER",
    "REALTY": "^CNXREALTY",
    "SERVICES": "^CNXSERVICE",
    "IT": "^CNXIT",
    "FMCG": "^CNXFMCG",
    # Prefer the Nifty Financial Services index symbol; unsupported aliases fall back to proxy.
    "FINNIFTY": "^CNXFINANCE",
    "CHEMICALS": "^CNXCHEMICALS",
    "PVT BANK": "^CNXPVTBANK",
}


def _market_is_open_window(now: dt.datetime) -> bool:
    local = now.astimezone(IST)
    return local.weekday() < 5 and dt.time(9, 15) <= local.time().replace(tzinfo=None) <= dt.time(15, 30)


def download_sector_index_readings(now: dt.datetime) -> dict[str, dict]:
    """Fetch best-effort 5-minute index readings from Yahoo Finance.

    These are index-symbol quotes where supported, not a claim of a direct NSE feed.
    Any unavailable or stale symbol is omitted and the sector builder may use a proxy.
    """
    ticker_to_labels: dict[str, list[str]] = defaultdict(list)
    for label, ticker in SECTOR_INDEX_TICKERS.items():
        ticker_to_labels[ticker].append(label)
    tickers = list(ticker_to_labels)
    if not tickers:
        return {}

    daily_frames: dict[str, pd.DataFrame] = {}
    intra_frames: dict[str, pd.DataFrame] = {}
    for start in range(0, len(tickers), BATCH_SIZE):
        batch_tickers = tickers[start:start + BATCH_SIZE]
        print(f"Downloading sector index batch {start + 1}-{start + len(batch_tickers)} of {len(tickers)} tickers...")
        try:
            daily_batch = yf_download_batch(batch_tickers, "1y", "1d")
        except Exception as exc:
            print(f"Sector index daily batch error: {type(exc).__name__}: {exc}")
            daily_batch = pd.DataFrame()
        try:
            intra_batch = yf_download_batch(batch_tickers, "5d", "5m")
        except Exception as exc:
            print(f"Sector index intraday batch error: {type(exc).__name__}: {exc}")
            intra_batch = pd.DataFrame()
        for ticker in batch_tickers:
            daily_frames[ticker] = extract_ticker_frame(daily_batch, ticker)
            intra_frames[ticker] = extract_ticker_frame(intra_batch, ticker)

    readings: dict[str, dict] = {}
    local_now = now.astimezone(IST)
    for label, ticker in SECTOR_INDEX_TICKERS.items():
        daily = clean_ohlcv(daily_frames.get(ticker, pd.DataFrame()))
        intra = remove_incomplete_5m_bars(clean_ohlcv(intra_frames.get(ticker, pd.DataFrame())), now)
        if daily.empty or intra.empty:
            print(f"SECTOR INDEX unavailable: {label} ({ticker}) — no usable Yahoo candles")
            continue
        session_date = max(intra.index.date)
        today = intra.loc[[d == session_date for d in intra.index.date]].copy()
        if today.empty:
            continue
        hist = get_daily_history_before(daily, session_date)
        if hist.empty:
            print(f"SECTOR INDEX unavailable: {label} ({ticker}) — no previous daily close")
            continue
        prev_close = safe_float(hist["Close"].iloc[-1])
        close = safe_float(today["Close"].iloc[-1])
        if prev_close <= 0 or close <= 0:
            continue
        bar_start = today.index[-1]
        if bar_start.tzinfo is None:
            bar_start = bar_start.tz_localize(IST)
        else:
            bar_start = bar_start.tz_convert(IST)
        bar_close = bar_start + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES)
        age_minutes = max(0.0, (pd.Timestamp(local_now) - bar_close).total_seconds() / 60.0)
        fresh = bool(session_date == local_now.date() and age_minutes <= 15.0)
        # During regular hours, reject stale direct-index readings. Outside that window,
        # the latest candle can be used as the previous/current session snapshot, with its date shown.
        if _market_is_open_window(local_now) and not fresh:
            print(f"SECTOR INDEX stale: {label} ({ticker}) — age {age_minutes:.1f} min")
            continue
        readings[label] = {
            "changePct": float(pct_change(close, prev_close)),
            "sessionDate": session_date.isoformat(),
            "asOf": bar_close.isoformat(),
            "sourceAgeMinutes": round(age_minutes, 1),
            "sourceBarFresh": fresh,
            "sourceTicker": ticker,
            "method": "index_quote",
            "sourceLabel": "Yahoo Finance index symbol; may be delayed",
        }
        print(f"SECTOR INDEX {label}: {readings[label]['changePct']:+.2f}% ({ticker}) as of {bar_close.isoformat()}")
    return readings


def build_sector_rankings(snapshots: list[dict], gpt_power_stocks: list[dict],
                          leaders: list[dict], breaker_stocks: list[dict],
                          sector_index_readings: Optional[dict[str, dict]] = None,
                          target_session: Optional[str] = None,
                          now: Optional[dt.datetime] = None) -> tuple[list[dict], dict]:
    """Build sector rankings using matching index quotes where possible.

    Fallback proxies are restricted to the same market session and use unrounded
    constituent returns. The function is additive: scanner scoring/candidate logic is untouched.
    """
    sector_index_readings = sector_index_readings or {}
    if target_session is None:
        candidates = [str(row.get("sessionDate")) for row in snapshots if row.get("sessionDate")]
        target_session = max(candidates) if candidates else None
    local_now = (now or dt.datetime.now(IST)).astimezone(IST)
    market_open = _market_is_open_window(local_now)

    session_snapshots = [row for row in snapshots
                         if target_session and str(row.get("sessionDate", "")) == target_session]
    # Use a shared recent candle window to avoid mixing yesterday's data with today's prices.
    timestamps = []
    for row in session_snapshots:
        raw_time = row.get("lastSourceBarCloseAt")
        if not raw_time:
            continue
        try:
            timestamp = pd.Timestamp(raw_time)
            timestamp = timestamp.tz_localize(IST) if timestamp.tzinfo is None else timestamp.tz_convert(IST)
            if not market_open or bool(row.get("sourceBarFresh", False)):
                timestamps.append(timestamp)
        except Exception:
            continue
    reference_time = max(timestamps) if timestamps else None
    allowed_lag_minutes = 10.0 if market_open else 20.0

    def aligned_for_sector(row: dict) -> bool:
        if not target_session or str(row.get("sessionDate", "")) != target_session:
            return False
        if market_open and not bool(row.get("sourceBarFresh", False)):
            return False
        if reference_time is None:
            return True
        raw_time = row.get("lastSourceBarCloseAt")
        if not raw_time:
            return False
        try:
            timestamp = pd.Timestamp(raw_time)
            timestamp = timestamp.tz_localize(IST) if timestamp.tzinfo is None else timestamp.tz_convert(IST)
            return abs((reference_time - timestamp).total_seconds()) <= allowed_lag_minutes * 60
        except Exception:
            return False

    by_symbol = {str(row.get("symbol", "")).upper(): row for row in session_snapshots if aligned_for_sector(row)}
    eligible: dict[str, dict] = {}

    def add_eligible(record: dict, source: str) -> None:
        symbol = str(record.get("symbol", "")).upper().strip()
        if not symbol:
            return
        snapshot = by_symbol.get(symbol, {})
        snapshot_atr = safe_float(snapshot.get("atr"), 0.0)
        snapshot_fuel = snapshot.get("fuelLeftPct")
        item = eligible.setdefault(symbol, {
            "symbol": symbol, "sources": [], "price": record.get("price"),
            "pctChange": record.get("pctChange"), "sector": snapshot.get("sector", "General"),
            "fuelLeftPct": snapshot_fuel if snapshot_atr > 0 else None,
            "atrUsedPct": snapshot.get("atrUsedPct"),
            "fuelLeft": (f"{safe_float(snapshot_fuel):.0f}%" if snapshot_atr > 0 and snapshot_fuel is not None else None),
            "fuelAsOf": snapshot.get("lastSourceBarCloseAt"),
            "sourceBarFresh": bool(snapshot.get("sourceBarFresh", False)),
            "fnoEligible": bool(record.get("fnoEligible", False)),
        })
        if source not in item["sources"]:
            item["sources"].append(source)
        if item.get("price") is None:
            item["price"] = record.get("price")
        if not item.get("pctChange"):
            item["pctChange"] = record.get("pctChange")
        item["fnoEligible"] = bool(item.get("fnoEligible") or record.get("fnoEligible", False))
        if source == "GPT POWER":
            item["score"] = record.get("powerScore")
            item["signal"] = record.get("status", record.get("type", "WATCH"))
        elif source == "BRAHMASTRA":
            item["score"] = record.get("score", record.get("numScore"))
            item["signal"] = record.get("type", "BRAHMASTRA")
        elif source == "BREAKER":
            item["score"] = max(safe_float(record.get("bullScore")), safe_float(record.get("bearScore")))
            item["signal"] = "BUY" if record.get("hasBuySignal") else "SELL" if record.get("hasSellSignal") else "BREAKER WATCH"

    for row in gpt_power_stocks:
        add_eligible(row, "GPT POWER")
    for row in leaders:
        if row.get("tier") == "BRAHMASTRA":
            add_eligible(row, "BRAHMASTRA")
    for row in breaker_stocks:
        add_eligible(row, "BREAKER")

    rankings: list[dict] = []
    for label in SECTOR_LABEL_ORDER:
        universe = SECTOR_INDEX_MEMBERS[label]
        members = [by_symbol[symbol] for symbol in universe if symbol in by_symbol]
        valid_changes = []
        for row in members:
            raw_change = row.get("pctChangePrecise", row.get("pctChangeNum"))
            if raw_change is None:
                continue
            try:
                numeric_change = float(raw_change)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric_change):
                valid_changes.append(numeric_change)

        index_quote = sector_index_readings.get(label)
        use_index = bool(index_quote and target_session and
                         str(index_quote.get("sessionDate", "")) == target_session)
        if use_index and market_open:
            use_index = bool(index_quote.get("sourceBarFresh", False))
            if reference_time is not None and index_quote.get("asOf"):
                try:
                    idx_time = pd.Timestamp(index_quote["asOf"])
                    idx_time = idx_time.tz_localize(IST) if idx_time.tzinfo is None else idx_time.tz_convert(IST)
                    use_index = use_index and abs((reference_time - idx_time).total_seconds()) <= allowed_lag_minutes * 60
                except Exception:
                    use_index = False
        elif use_index and reference_time is not None and index_quote.get("asOf"):
            try:
                idx_time = pd.Timestamp(index_quote["asOf"])
                idx_time = idx_time.tz_localize(IST) if idx_time.tzinfo is None else idx_time.tz_convert(IST)
                use_index = abs((reference_time - idx_time).total_seconds()) <= allowed_lag_minutes * 60
            except Exception:
                use_index = False

        if use_index:
            change = round(float(index_quote["changePct"]), 2)
            method = "index_quote"
            source_ticker = index_quote.get("sourceTicker")
            as_of = index_quote.get("asOf")
            source_age = index_quote.get("sourceAgeMinutes")
            source_label = index_quote.get("sourceLabel", "Yahoo Finance index symbol; may be delayed")
        else:
            change = round(sum(valid_changes) / len(valid_changes), 2) if valid_changes else None
            method = "stock_proxy" if valid_changes else "unavailable"
            source_ticker = None
            as_of = (max([str(row.get("lastSourceBarCloseAt")) for row in members if row.get("lastSourceBarCloseAt")], default=None))
            source_age = None
            source_label = "Average of same-session representative stocks; not an official index quote" if valid_changes else "No aligned data available"

        sector_eligible = []
        for symbol in universe:
            item = eligible.get(symbol)
            if item:
                sector_eligible.append(dict(item))
        sector_eligible.sort(key=lambda row: (
            -len(row.get("sources", [])),
            -safe_float(row.get("score")),
            str(row.get("symbol", "")),
        ))
        rankings.append({
            "name": label,
            "changePct": change,
            "coverage": len(valid_changes),
            "universeSize": len(universe),
            "advances": sum(1 for value in valid_changes if value > 0),
            "declines": sum(1 for value in valid_changes if value < 0),
            "eligibleStocks": sector_eligible,
            "available": change is not None,
            "method": method,
            "sourceTicker": source_ticker,
            "sourceLabel": source_label,
            "asOf": as_of,
            "sourceAgeMinutes": source_age,
            "sessionDate": target_session,
        })

    # Keep the exact 23 screenshot labels; unavailable readings sort last and are never fabricated.
    rankings.sort(key=lambda row: (row["changePct"] is None,
                                   -(row["changePct"] if row["changePct"] is not None else -999.0),
                                   SECTOR_LABEL_ORDER.index(row["name"])))
    available_rankings = [row for row in rankings if row["available"]]
    strong_names = {row["name"] for row in available_rankings[:5]}
    weak_names = {row["name"] for row in available_rankings[-5:]}
    for rank, row in enumerate(rankings, start=1):
        row["rank"] = rank
        row["strength"] = "STRONG" if row["name"] in strong_names else "WEAK" if row["name"] in weak_names else "MIDDLE"
        row["eligibleCount"] = len(row["eligibleStocks"])

    available = [row for row in rankings if row["available"]]
    positive = sum(1 for row in available if row["changePct"] > 0)
    negative = sum(1 for row in available if row["changePct"] < 0)
    unchanged = sum(1 for row in available if row["changePct"] == 0)
    directional = positive + negative
    methods = {method: sum(1 for row in available if row["method"] == method)
               for method in ("index_quote", "stock_proxy")}
    sentiment = {
        "positiveCount": positive,
        "negativeCount": negative,
        "unchangedCount": unchanged,
        "availableSectors": len(available),
        "totalSectors": len(SECTOR_LABEL_ORDER),
        "positivePct": round(positive / directional * 100, 1) if directional else 0,
        "negativePct": round(negative / directional * 100, 1) if directional else 0,
        "indexQuoteSectors": methods["index_quote"],
        "proxySectors": methods["stock_proxy"],
        "sessionDate": target_session,
        "referenceAsOf": reference_time.isoformat() if reference_time is not None else None,
        "basis": "Index quote from Yahoo Finance where available; otherwise a same-session average of representative constituents. Yahoo data may be delayed.",
    }
    return rankings, sentiment


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


def send_telegram_alert(message: str) -> bool:
    """Send one HTML Telegram message. Returns True only when Telegram accepts it."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram dispatch skipped: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID is not configured.")
        return False
    try:
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
        with urlopen(Request(url, data=payload), timeout=10) as response:
            body = response.read()
            status_code = response.status
        result = json.loads(body.decode("utf-8")) if body else {}
        if status_code == 200 and result.get("ok") is True:
            return True
        print(f"Telegram rejected message: {result.get('description', 'unknown response')}")
    except Exception as exc:
        print(f"Telegram dispatch error: {type(exc).__name__}: {exc}")
    return False


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
    # Keep the scanner's legacy fuel value unchanged for its existing heuristic/ranking logic.
    atr = context["atr"] or max(today_range, close * 0.01)
    atr_used_pct = (today_range / atr * 100.0) if atr > 0 else 0.0
    fuel_left_pct = max(0.0, 100.0 - atr_used_pct)
    # A separate, more complete DISPLAY metric includes overnight gaps, matching the
    # market's daily true-range/ATR concept. It is used only for the added UI meter.
    today_true_range = max(0.0, max(high_day, prev_close) - min(low_day, prev_close))
    daily_atr_baseline = safe_float(context.get("atr"), 0.0)
    fuel_display_used_pct = (today_true_range / daily_atr_baseline * 100.0) if daily_atr_baseline > 0 else None
    fuel_display_left_pct = max(0.0, 100.0 - fuel_display_used_pct) if fuel_display_used_pct is not None else None

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

    # Source timestamps are explicit: yfinance timestamps commonly identify candle starts,
    # so the completed 5-minute candle closes five minutes later.
    last_bar_start = today.index[-1]
    if last_bar_start.tzinfo is None:
        last_bar_start = last_bar_start.tz_localize(IST)
    else:
        last_bar_start = last_bar_start.tz_convert(IST)
    last_bar_close = last_bar_start + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES)
    age_minutes = max(0.0, (pd.Timestamp(now.astimezone(IST)) - last_bar_close).total_seconds() / 60.0)

    # First daily row prior to the scan session provides the correct previous close/high/low.
    metrics = {
        "symbol": symbol, "sector": sector, "sessionDate": session_date.isoformat(),
        "lastSourceBarCloseAt": last_bar_close.isoformat(),
        "sourceBarAgeMinutes": round(age_minutes, 1),
        "sourceBarFresh": bool(session_date == now.astimezone(IST).date() and age_minutes <= 15),
        "today": today, "allIntraday": all_intraday, "context": context,
        "price": round(close, 2), "openDay": round(open_day, 2),
        "highDay": round(high_day, 2), "lowDay": round(low_day, 2),
        "pctChangeNum": round(change_pct, 2), "pctChangePrecise": float(change_pct),
        "sessionReturnPct": round(session_return_pct, 2),
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
        "fuelLeftPct": round(fuel_left_pct, 1), "fuelDailyAtr14": round(daily_atr_baseline, 4) if daily_atr_baseline > 0 else None,
        "fuelTrueRange": round(today_true_range, 4),
        "fuelDisplayUsedPct": round(fuel_display_used_pct, 1) if fuel_display_used_pct is not None else None,
        "fuelDisplayLeftPct": round(fuel_display_left_pct, 1) if fuel_display_left_pct is not None else None,
        "avgTurnoverCr": round(context["avgTurnoverCr"], 2),
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
        "sector": m.get("sector", "General"),
        "fuelLeftPct": m.get("fuelLeftPct"), "numFuel": m.get("fuelLeftPct"),
        "fuelLeft": (f"{safe_float(m.get('fuelLeftPct')):.0f}%" if m.get("fuelLeftPct") is not None else None),
        "displayFuelLeftPct": m.get("fuelDisplayLeftPct"), "displayAtrUsedPct": m.get("fuelDisplayUsedPct"),
        "fuelAsOf": m.get("lastSourceBarCloseAt"), "sourceBarFresh": bool(m.get("sourceBarFresh", False)),
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
    """Return the CLOSE time of the first completed 5-minute bar satisfying GPT POWER rules.

    yfinance 5-minute timestamps normally identify candle start, so five minutes are
    added for the displayed confirmation time. Unfinished candles are excluded.
    """
    today = to_ist_index(m.get("today", pd.DataFrame()))
    if today.empty:
        return None

    # Keep the timestamp rule correct even if an upstream caller supplies raw bars.
    now_ist = pd.Timestamp.now(tz=IST)
    today = today.loc[today.index + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES) <= now_ist]
    if len(today) < 4:
        return None

    # First three full candles form the 15-minute opening range.
    opening_range = today.iloc[:3]
    or_high = safe_float(opening_range["High"].max())
    or_low = safe_float(opening_range["Low"].min())
    previous_day_high = safe_float(m["context"].get("pdh"))
    previous_day_low = safe_float(m["context"].get("pdl"))

    typical = (today["High"] + today["Low"] + today["Close"]) / 3.0
    cumulative_volume = today["Volume"].cumsum()
    vwap_series = (typical * today["Volume"]).cumsum() / cumulative_volume.replace(0, np.nan)
    vwap_series = vwap_series.ffill().fillna(today["Close"])
    closes = today["Close"]
    ema9 = closes.ewm(span=9, adjust=False).mean()
    ema20 = closes.ewm(span=20, adjust=False).mean()

    # Evaluate in chronological order, using only each candle and its past.
    for i in range(3, len(today)):
        close = safe_float(closes.iloc[i])
        prefix = today.iloc[:i + 1]
        rvol = current_rvol(prefix, i, historical_baselines)
        momentum_3bar = pct_change(close, safe_float(closes.iloc[i - 3]))
        vwap = safe_float(vwap_series.iloc[i], close)
        fast = safe_float(ema9.iloc[i], close)
        slow = safe_float(ema20.iloc[i], close)

        if side == "CE":
            breakout = close > or_high or close > previous_day_high
            confirmed = breakout and close > vwap and rvol >= 1.15 and momentum_3bar > 0 and fast >= slow
        else:
            breakout = close < or_low or close < previous_day_low
            confirmed = breakout and close < vwap and rvol >= 1.15 and momentum_3bar < 0 and fast <= slow

        if confirmed:
            close_time = today.index[i] + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES)
            return close_time.strftime("%H:%M")
    return None



def apply_confirmation_audit(power: dict, confirmation_time: Optional[str]) -> dict:
    """Keep the displayed status consistent with completed-candle confirmation audit.

    The scoring and candidate selection remain unchanged. This only prevents a
    confirmed label when the chronological candle audit cannot reproduce it.
    """
    if power.get("breakoutConfirmed") and confirmation_time:
        power["detectTime"] = confirmation_time
    else:
        power["detectTime"] = "Not confirmed"
        if power.get("breakoutConfirmed"):
            power["status"] = "CONFIRMATION NOT VERIFIED"
            power["breakoutConfirmed"] = False
    return power


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
        "sector": m.get("sector", "General"),
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
        "fuelLeftPct": m.get("fuelLeftPct"), "atrUsedPct": m.get("atrUsedPct"),
        "fuelAsOf": m.get("lastSourceBarCloseAt"), "sourceBarFresh": bool(m.get("sourceBarFresh", False)),
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



def _breaker_wilder_rma(values: pd.Series, length: int) -> pd.Series:
    """Wilder-style RMA used to approximate Pine Script ta.atr()."""
    x = pd.to_numeric(values, errors="coerce").astype(float)
    out = pd.Series(np.nan, index=x.index, dtype=float)
    if len(x) < length:
        return out
    arr = x.to_numpy(dtype=float)
    first = None
    for i in range(length - 1, len(arr)):
        window = arr[i - length + 1:i + 1]
        if np.isfinite(window).all():
            first = i
            out.iloc[i] = float(window.mean())
            break
    if first is None:
        return out
    previous = float(out.iloc[first])
    for i in range(first + 1, len(arr)):
        value = arr[i]
        if not np.isfinite(value):
            continue
        previous = ((previous * (length - 1)) + float(value)) / length
        out.iloc[i] = previous
    return out


def _breaker_resistance_crosses(bars: pd.DataFrame, atr14: pd.Series,
                                left_bars: int = 10, right_bars: int = 10,
                                max_lines: int = 5) -> pd.Series:
    """Approximate the provided Pine S/R engine: confirmed pivots, merged levels, single-fire breaks."""
    result = pd.Series(False, index=bars.index, dtype=bool)
    if len(bars) < left_bars + right_bars + 2:
        return result
    highs = pd.to_numeric(bars["High"], errors="coerce").to_numpy(dtype=float)
    closes = pd.to_numeric(bars["Close"], errors="coerce").to_numpy(dtype=float)
    active: list[dict[str, Any]] = []

    for i in range(len(bars)):
        pivot_idx = i - right_bars
        if pivot_idx >= left_bars:
            window = highs[pivot_idx - left_bars:pivot_idx + right_bars + 1]
            pivot_high = highs[pivot_idx]
            if len(window) and np.isfinite(pivot_high) and pivot_high >= np.nanmax(window):
                current_atr = safe_float(atr14.iloc[i], 0.0)
                tolerance = current_atr * 0.20
                found = False
                for item in active:
                    if abs(item["level"] - pivot_high) <= tolerance:
                        item["level"] = (item["level"] + pivot_high) / 2.0
                        found = True
                        break
                if not found:
                    active.append({"level": float(pivot_high), "broken": False})
                    if len(active) > max_lines:
                        active.pop(0)

        if i == 0 or not np.isfinite(closes[i]) or not np.isfinite(closes[i - 1]):
            continue
        for item in active:
            level = item["level"]
            crossed = closes[i] > level and closes[i - 1] <= level
            if crossed and not item["broken"]:
                result.iloc[i] = True
                item["broken"] = True
    return result



def _breaker_support_crosses(bars: pd.DataFrame, atr14: pd.Series,
                             left_bars: int = 10, right_bars: int = 10,
                             max_lines: int = 5) -> pd.Series:
    """Mirror the existing confirmed-pivot breakout helper for support breakdowns."""
    result = pd.Series(False, index=bars.index, dtype=bool)
    if len(bars) < left_bars + right_bars + 2:
        return result
    lows = pd.to_numeric(bars["Low"], errors="coerce").to_numpy(dtype=float)
    closes = pd.to_numeric(bars["Close"], errors="coerce").to_numpy(dtype=float)
    active: list[dict[str, Any]] = []
    for i in range(len(bars)):
        pivot_idx = i - right_bars
        if pivot_idx >= left_bars:
            window = lows[pivot_idx - left_bars:pivot_idx + right_bars + 1]
            pivot_low = lows[pivot_idx]
            if len(window) and np.isfinite(pivot_low) and pivot_low <= np.nanmin(window):
                tolerance = safe_float(atr14.iloc[i], 0.0) * 0.20
                found = False
                for item in active:
                    if abs(item["level"] - pivot_low) <= tolerance:
                        item["level"] = (item["level"] + pivot_low) / 2.0
                        found = True
                        break
                if not found:
                    active.append({"level": float(pivot_low), "broken": False})
                    if len(active) > max_lines:
                        active.pop(0)
        if i == 0 or not np.isfinite(closes[i]) or not np.isfinite(closes[i - 1]):
            continue
        for item in active:
            level = item["level"]
            if closes[i] < level and closes[i - 1] >= level and not item["broken"]:
                result.iloc[i] = True
                item["broken"] = True
    return result


def _breaker_order_block_state(bars: pd.DataFrame, atr14: pd.Series, direction: str,
                               lookback: int = 48) -> tuple[int, bool, Optional[float], Optional[float]]:
    """Heuristic 5-minute OB detector: opposite-colour candle before displacement/break.

    Counts currently active zones in the last `lookback` bars. These are transparent
    scanner approximations, not a claim of exact TradingView order-block parity.
    """
    if bars.empty or len(bars) < 8:
        return 0, False, None, None
    work = bars.tail(lookback + 8)
    op = work["Open"].astype(float).to_numpy()
    hi = work["High"].astype(float).to_numpy()
    lo = work["Low"].astype(float).to_numpy()
    cl = work["Close"].astype(float).to_numpy()
    atr = atr14.reindex(work.index).astype(float).to_numpy()
    start = max(1, len(work) - lookback - 1)
    zones: list[tuple[float, float, int]] = []
    for j in range(start, len(work) - 1):
        a = safe_float(atr[j + 1], 0.0)
        if a <= 0 or not np.isfinite(a):
            continue
        prior_start = max(0, j - 5)
        if direction == "BUY":
            opposite = cl[j] < op[j]
            displacement = cl[j + 1] > op[j + 1] and cl[j + 1] > np.nanmax(hi[prior_start:j + 1]) and (hi[j + 1] - lo[j + 1]) >= 0.5 * a
        else:
            opposite = cl[j] > op[j]
            displacement = cl[j + 1] < op[j + 1] and cl[j + 1] < np.nanmin(lo[prior_start:j + 1]) and (hi[j + 1] - lo[j + 1]) >= 0.5 * a
        if opposite and displacement:
            zones.append((float(lo[j]), float(hi[j]), j))
    active = []
    latest_close = float(cl[-1])
    for zlo, zhi, idx in zones:
        later = cl[idx + 2:]
        if direction == "BUY":
            valid = latest_close > zhi and not (len(later) and np.any(later < zlo))
        else:
            valid = latest_close < zlo and not (len(later) and np.any(later > zhi))
        if valid:
            active.append((zlo, zhi, idx))
    last_zone = active[-1] if active else None
    return len(active), bool(last_zone), (last_zone[0] if last_zone else None), (last_zone[1] if last_zone else None)


def _breaker_rf_15m_alignment(bars: pd.DataFrame) -> tuple[bool, bool, dict[str, Any]]:
    """Calculate R-Factor-style directional alignment on fully formed 15-minute candles."""
    empty = {"close": None, "ema21": None, "vwap": None, "vwma20": None,
             "supertrend": None, "volumeMultiple": None, "candleTime": None}
    if bars.empty:
        return False, False, empty
    cols = ["Open", "High", "Low", "Close", "Volume"]
    source = bars[cols].copy()
    rule = "15min"
    grouped = source.resample(rule, label="right", closed="left", origin="start_day")
    count = grouped["Close"].count()
    fifteen = grouped.agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    # Require three completed 5-minute bars per 15-minute candle.
    fifteen = fifteen.loc[count >= 3].dropna(subset=["Open", "High", "Low", "Close"])
    if fifteen.empty:
        return False, False, empty
    close = fifteen["Close"].astype(float)
    high = fifteen["High"].astype(float)
    low = fifteen["Low"].astype(float)
    volume = fifteen["Volume"].astype(float)
    previous_close = close.shift(1)
    tr = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1, skipna=True)
    atr10 = _breaker_wilder_rma(tr, 10)
    midpoint = (high + low) / 2.0
    upper = midpoint + 3.0 * atr10
    lower = midpoint - 3.0 * atr10
    st_values = np.full(len(fifteen), np.nan, dtype=float)
    c_arr, u_arr, l_arr = close.to_numpy(), upper.to_numpy(), lower.to_numpy()
    for i in range(len(fifteen)):
        if not np.isfinite(u_arr[i]) or not np.isfinite(l_arr[i]):
            continue
        if i == 0 or not np.isfinite(st_values[i - 1]):
            st_values[i] = l_arr[i] if c_arr[i] > u_arr[i] else u_arr[i]
        elif c_arr[i] > st_values[i - 1]:
            st_values[i] = max(l_arr[i], st_values[i - 1])
        else:
            st_values[i] = min(u_arr[i], st_values[i - 1])
    supertrend = pd.Series(st_values, index=fifteen.index)
    ema21 = close.ewm(span=21, adjust=False).mean()
    vwma20 = (close.mul(volume).rolling(20, min_periods=20).sum() /
              volume.rolling(20, min_periods=20).sum().replace(0, np.nan))
    typical = (high + low + close) / 3.0
    keys = pd.Series(fifteen.index.date, index=fifteen.index)
    cv = volume.groupby(keys).cumsum().replace(0, np.nan)
    vwap = (typical * volume).groupby(keys).cumsum() / cv
    vol_ma = volume.rolling(20, min_periods=20).mean()
    i = len(fifteen) - 1
    vals = [ema21.iloc[i], vwma20.iloc[i], vwap.iloc[i], supertrend.iloc[i], vol_ma.iloc[i]]
    ready = all(pd.notna(x) and np.isfinite(float(x)) for x in vals)
    c = safe_float(close.iloc[i])
    v = safe_float(volume.iloc[i])
    avg = safe_float(vol_ma.iloc[i], 0.0)
    green = safe_float(fifteen["Close"].iloc[i]) > safe_float(fifteen["Open"].iloc[i])
    red = safe_float(fifteen["Close"].iloc[i]) < safe_float(fifteen["Open"].iloc[i])
    bull = bool(ready and c > safe_float(ema21.iloc[i]) and c > safe_float(vwap.iloc[i]) and
                c > safe_float(vwma20.iloc[i]) and c > safe_float(supertrend.iloc[i]) and v > avg)
    bear = bool(ready and c < safe_float(ema21.iloc[i]) and c < safe_float(vwap.iloc[i]) and
                c < safe_float(vwma20.iloc[i]) and c < safe_float(supertrend.iloc[i]) and v > avg and red)
    details = {"close": round(c, 2), "ema21": round(safe_float(ema21.iloc[i]), 2) if pd.notna(ema21.iloc[i]) else None,
               "vwap": round(safe_float(vwap.iloc[i]), 2) if pd.notna(vwap.iloc[i]) else None,
               "vwma20": round(safe_float(vwma20.iloc[i]), 2) if pd.notna(vwma20.iloc[i]) else None,
               "supertrend": round(safe_float(supertrend.iloc[i]), 2) if pd.notna(supertrend.iloc[i]) else None,
               "volumeMultiple": round(v / avg, 2) if avg > 0 else None,
               "candleTime": fifteen.index[i].isoformat()}
    return bull, bear, details

def calculate_breaker_setup(m: dict) -> Optional[dict]:
    """Build the bidirectional 6-condition BREAKER matrix plus today's Pine signal flags.

    A 4/6 score is a WATCH, 5/6 is a qualified setup and 6/6 is a full confluence score.
    BUY/SELL entry labels require at least 5/6, the matching breakout condition and a fresh
    completed source candle. The original Pine-style signal markers are also surfaced.
    """
    try:
        bars = to_ist_index(m.get("allIntraday", pd.DataFrame()))
        if bars.empty or len(bars) < 30:
            return None
        session_date = dt.date.fromisoformat(str(m.get("sessionDate")))
        today = bars.loc[[stamp.date() == session_date for stamp in bars.index]].copy()
        if today.empty:
            return None

        close = bars["Close"].astype(float)
        open_ = bars["Open"].astype(float)
        high = bars["High"].astype(float)
        low = bars["Low"].astype(float)
        volume = bars["Volume"].astype(float)
        previous_close = close.shift(1)
        true_range = pd.concat([(high - low), (high - previous_close).abs(),
                                (low - previous_close).abs()], axis=1).max(axis=1, skipna=True)
        atr10 = _breaker_wilder_rma(true_range, 10)
        atr14 = _breaker_wilder_rma(true_range, 14)
        vol_ma = volume.rolling(20, min_periods=20).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        vwma20 = (close.mul(volume).rolling(20, min_periods=20).sum() /
                  volume.rolling(20, min_periods=20).sum().replace(0, np.nan))

        # Pine close-based VWAP for R-Factor and typical-price VWAP for bearish matrix check.
        session_keys = pd.Series(bars.index.date, index=bars.index)
        cum_vol = volume.groupby(session_keys).cumsum().replace(0, np.nan)
        rf_vwap = close.mul(volume).groupby(session_keys).cumsum() / cum_vol
        typical = (high + low + close) / 3.0
        matrix_vwap = typical.mul(volume).groupby(session_keys).cumsum() / cum_vol

        midpoint = (high + low) / 2.0
        upper = midpoint + 3.0 * atr10
        lower = midpoint - 3.0 * atr10
        st_values = np.full(len(bars), np.nan, dtype=float)
        c_arr, u_arr, l_arr = close.to_numpy(dtype=float), upper.to_numpy(dtype=float), lower.to_numpy(dtype=float)
        for i in range(len(bars)):
            if not np.isfinite(u_arr[i]) or not np.isfinite(l_arr[i]):
                continue
            if i == 0 or not np.isfinite(st_values[i - 1]):
                st_values[i] = l_arr[i] if c_arr[i] > u_arr[i] else u_arr[i]
            elif c_arr[i] > st_values[i - 1]:
                st_values[i] = max(l_arr[i], st_values[i - 1])
            else:
                st_values[i] = min(u_arr[i], st_values[i - 1])
        supertrend = pd.Series(st_values, index=bars.index)

        highest_previous_15 = high.shift(1).rolling(15, min_periods=15).max()
        lowest_previous_15 = low.shift(1).rolling(15, min_periods=15).min()
        res_cross = _breaker_resistance_crosses(bars, atr14)
        sup_cross = _breaker_support_crosses(bars, atr14)
        bull_breakout_series = res_cross | (close > highest_previous_15)
        bear_breakdown_series = sup_cross | (close < lowest_previous_15)
        high_volume = volume >= (vol_ma * 1.5)
        pdh = safe_float(m.get("context", {}).get("pdh"), 0.0)
        pdl = safe_float(m.get("context", {}).get("pdl"), 0.0)
        above_pdh = (close > pdh) if pdh > 0 else pd.Series(False, index=bars.index)
        below_pdl = (close < pdl) if pdl > 0 else pd.Series(False, index=bars.index)
        # A confirmed intraday level break requires a completed candle to cross the prior-day
        # level, volume at/above 1.5x MA20 on that breakout candle, and price to remain beyond
        # the level on the latest completed candle. This is stricter than merely trading above/below it.
        pdh_cross_up = ((close > pdh) & (close.shift(1) <= pdh)) if pdh > 0 else pd.Series(False, index=bars.index)
        pdl_cross_down = ((close < pdl) & (close.shift(1) >= pdl)) if pdl > 0 else pd.Series(False, index=bars.index)
        pdh_breakout_volume_event = bool((pdh_cross_up & high_volume).loc[today.index].any())
        pdl_breakdown_volume_event = bool((pdl_cross_down & high_volume).loc[today.index].any())
        range_gt_atr = (high - low) > atr14
        day_low_series = low.groupby(session_keys).cummin()
        at_day_low = close <= day_low_series
        below_vwap = close < matrix_vwap

        bull_ob_count, bull_ob_active, bull_ob_low, bull_ob_high = _breaker_order_block_state(bars, atr14, "BUY")
        bear_ob_count, bear_ob_active, bear_ob_low, bear_ob_high = _breaker_order_block_state(bars, atr14, "SELL")
        rf15_bull, rf15_bear, rf15_details = _breaker_rf_15m_alignment(bars)

        # Pine volume decomposition: buyer/seller dominance is based on close location in candle.
        candle_range = (high - low).replace(0, np.nan)
        buy_ratio = ((close - low) / candle_range).fillna(0.5)
        bought_vol = np.floor(volume * buy_ratio + 0.5)
        sold_vol = np.floor(volume * (1.0 - buy_ratio) + 0.5)
        buyer_dominant = bought_vol > (sold_vol * 1.3)
        seller_dominant = sold_vol > (bought_vol * 1.3)
        volume_breakout_buy_series = res_cross & high_volume & buyer_dominant
        volume_breakout_sell_series = sup_cross & high_volume & seller_dominant

        # Reproduce the provided R-Factor one-signal-per-day and 9:30–14:45 filters.
        r_factor_buy_time = None
        r_factor_sell_time = None
        signal_taken_today = False
        today_positions = bars.index.get_indexer(today.index)
        for i in today_positions:
            stamp = bars.index[i]
            cur_minutes = stamp.hour * 60 + stamp.minute
            time_ok = (9 * 60 + 30) <= cur_minutes <= (14 * 60 + 45)
            avg = safe_float(vol_ma.iloc[i], 0.0)
            rv_ok = avg > 0 and safe_float(volume.iloc[i]) / avg >= 0.80
            st_value = safe_float(supertrend.iloc[i], float("nan"))
            ready = (pd.notna(ema21.iloc[i]) and pd.notna(rf_vwap.iloc[i]) and
                     pd.notna(vwma20.iloc[i]) and math.isfinite(st_value) and pd.notna(vol_ma.iloc[i]))
            raw_buy = bool(ready and close.iloc[i] > ema21.iloc[i] and close.iloc[i] > rf_vwap.iloc[i] and
                           close.iloc[i] > vwma20.iloc[i] and close.iloc[i] > st_value and volume.iloc[i] > avg)
            raw_sell = bool(ready and close.iloc[i] < ema21.iloc[i] and close.iloc[i] < rf_vwap.iloc[i] and
                            close.iloc[i] < vwma20.iloc[i] and close.iloc[i] < st_value and
                            volume.iloc[i] > avg and close.iloc[i] < open_.iloc[i])
            if not signal_taken_today and time_ok and rv_ok and (raw_buy or raw_sell):
                close_time = (stamp + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES)).strftime("%H:%M")
                if raw_buy:
                    r_factor_buy_time = close_time
                else:
                    r_factor_sell_time = close_time
                signal_taken_today = True

        volume_buy_times = []
        volume_sell_times = []
        for i in today_positions:
            if bool(volume_breakout_buy_series.iloc[i]):
                volume_buy_times.append((bars.index[i] + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES)).strftime("%H:%M"))
            if bool(volume_breakout_sell_series.iloc[i]):
                volume_sell_times.append((bars.index[i] + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES)).strftime("%H:%M"))
        volume_buy_time = volume_buy_times[-1] if volume_buy_times else None
        volume_sell_time = volume_sell_times[-1] if volume_sell_times else None

        last_idx = len(bars) - 1
        latest_close = safe_float(close.iloc[last_idx])
        recent_vol_x = safe_float(volume.iloc[last_idx]) / safe_float(vol_ma.iloc[last_idx], 1.0) if safe_float(vol_ma.iloc[last_idx], 0.0) > 0 else 0.0
        bull_breakout = bool(bull_breakout_series.iloc[last_idx])
        bear_breakdown = bool(bear_breakdown_series.iloc[last_idx])
        bull_conditions = [
            {"name": "Breakout", "ok": bull_breakout, "detail": "Swing-resistance cross or close above previous 15-bar high"},
            {"name": "Volume", "ok": bool(high_volume.iloc[last_idx]), "detail": "Volume ≥ 1.5 × 20-bar average"},
            {"name": "PDH", "ok": bool(above_pdh.iloc[last_idx]), "detail": "Close above previous-day high"},
            {"name": "Range", "ok": bool(range_gt_atr.iloc[last_idx]), "detail": "Candle range > ATR(14)"},
            {"name": "Bull OB", "ok": bool(bull_ob_active), "detail": f"{bull_ob_count} active bullish demand zone(s); heuristic OB detector"},
            {"name": "RF + 15m", "ok": bool(rf15_bull), "detail": "15m close above EMA21/VWAP/VWMA20/Supertrend with volume confirmation"},
        ]
        bear_conditions = [
            {"name": "Breakdown", "ok": bear_breakdown, "detail": "Support cross or close below previous 15-bar low"},
            {"name": "VWAP", "ok": bool(below_vwap.iloc[last_idx]), "detail": "Close below intraday VWAP"},
            {"name": "DL", "ok": bool(at_day_low.iloc[last_idx]), "detail": "Close at current session low"},
            {"name": "PDL", "ok": bool(below_pdl.iloc[last_idx]), "detail": "Close below previous-day low"},
            {"name": "Bear OB", "ok": bool(bear_ob_active), "detail": f"{bear_ob_count} active bearish supply zone(s); heuristic OB detector"},
            {"name": "RF + 15m", "ok": bool(rf15_bear), "detail": "15m close below EMA21/VWAP/VWMA20/Supertrend with volume confirmation"},
        ]
        bull_score = sum(1 for x in bull_conditions if x["ok"])
        bear_score = sum(1 for x in bear_conditions if x["ok"])
        pdh_breakout_confirmed = bool(pdh > 0 and latest_close > pdh and pdh_breakout_volume_event)
        pdl_breakdown_confirmed = bool(pdl > 0 and latest_close < pdl and pdl_breakdown_volume_event)
        r_factor_buy = r_factor_buy_time is not None
        r_factor_sell = r_factor_sell_time is not None
        volume_buy = volume_buy_time is not None
        volume_sell = volume_sell_time is not None
        fresh = bool(m.get("sourceBarFresh", False))
        bull_setup_signal = bool(fresh and bull_score >= 5 and bull_breakout)
        bear_setup_signal = bool(fresh and bear_score >= 5 and bear_breakdown)
        buy_signal = bool(bull_setup_signal or r_factor_buy or volume_buy)
        sell_signal = bool(bear_setup_signal or r_factor_sell or volume_sell)
        if buy_signal and bull_score >= bear_score:
            signal_type = "BUY"
        elif sell_signal and bear_score >= bull_score:
            signal_type = "SELL"
        elif bull_score >= 4 and bull_score > bear_score:
            signal_type = "BUY WATCH"
        elif bear_score >= 4 and bear_score > bull_score:
            signal_type = "SELL WATCH"
        else:
            signal_type = "WATCH"
        if bull_score >= 4 or bear_score >= 4 or buy_signal or sell_signal:
            latest_stamp = bars.index[last_idx]
            pct_change_num = safe_float(m.get("pctChangeNum"), 0.0)
            strongest = max(bull_score, bear_score)
            score_label = f"{strongest}/6"
            return {
                "symbol": str(m.get("symbol", "")), "tier": "BREAKER", "type": signal_type,
                "sector": m.get("sector", "General"),
                "price": round(latest_close, 2), "pctChange": f"{pct_change_num:+.2f}%",
                "fuelLeftPct": m.get("fuelLeftPct"), "numFuel": m.get("fuelLeftPct"),
                "fuelLeft": (f"{safe_float(m.get('fuelLeftPct')):.0f}%" if m.get("fuelLeftPct") is not None else None),
                "atrUsedPct": m.get("atrUsedPct"), "fuelAsOf": m.get("lastSourceBarCloseAt"),
                "sourceBarFresh": bool(m.get("sourceBarFresh", False)),
                "score": strongest, "scoreLabel": score_label,
                "bullScore": bull_score, "bullScoreLabel": f"{bull_score}/6",
                "bearScore": bear_score, "bearScoreLabel": f"{bear_score}/6",
                "conditions": bull_conditions, "bullConditions": bull_conditions, "bearConditions": bear_conditions,
                "hasBuySignal": bool(buy_signal), "hasSellSignal": bool(sell_signal),
                "pdhBreakoutConfirmed": pdh_breakout_confirmed,
                "pdhBreakoutVolumeConfirmed": pdh_breakout_volume_event,
                "pdlBreakdownConfirmed": pdl_breakdown_confirmed,
                "pdlBreakdownVolumeConfirmed": pdl_breakdown_volume_event,
                "buySetupSignal": bull_setup_signal, "sellSetupSignal": bear_setup_signal,
                "rFactorBuySignal": r_factor_buy, "rFactorBuyTime": r_factor_buy_time,
                "rFactorSellSignal": r_factor_sell, "rFactorSellTime": r_factor_sell_time,
                "volumeBreakoutBuySignal": volume_buy, "volumeBreakoutBuyTime": volume_buy_time,
                "volumeBreakoutSellSignal": volume_sell, "volumeBreakoutSellTime": volume_sell_time,
                "hasPineSignal": bool(r_factor_buy or r_factor_sell or volume_buy or volume_sell),
                "signalType": signal_type,
                "volumeMultiple": round(recent_vol_x, 2), "pdh": round(pdh, 2), "pdl": round(pdl, 2),
                "dayLow": round(safe_float(today["Low"].min()), 2),
                "vwap": round(safe_float(matrix_vwap.iloc[last_idx]), 2),
                "candleRange": round(safe_float((high - low).iloc[last_idx]), 2),
                "atr14": round(safe_float(atr14.iloc[last_idx]), 2),
                "bullOBCount": int(bull_ob_count), "bullOBActive": bool(bull_ob_active),
                "bullOBLow": round(bull_ob_low, 2) if bull_ob_low is not None else None,
                "bullOBHigh": round(bull_ob_high, 2) if bull_ob_high is not None else None,
                "bearOBCount": int(bear_ob_count), "bearOBActive": bool(bear_ob_active),
                "bearOBLow": round(bear_ob_low, 2) if bear_ob_low is not None else None,
                "bearOBHigh": round(bear_ob_high, 2) if bear_ob_high is not None else None,
                "rf15mBullAligned": bool(rf15_bull), "rf15mBearAligned": bool(rf15_bear), "rf15m": rf15_details,
                "sourceBarFresh": fresh, "sourceBarCloseAt": m.get("lastSourceBarCloseAt"),
                "sourceBarAgeMinutes": m.get("sourceBarAgeMinutes"), "sessionDate": m.get("sessionDate"),
                "lastPriceTimestamp": latest_stamp.isoformat(),
                "dataWarning": ("SOURCE CANDLE STALE — verify price before acting" if not fresh
                                else "Yahoo Finance source; not guaranteed real-time"),
            }
        return None
    except Exception as exc:
        print(f"BREAKER calculation skipped for {m.get('symbol', 'UNKNOWN')}: {type(exc).__name__}: {exc}")
        return None

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



PAPER_STOP_LOSS_PCT = 0.50
PAPER_TARGET1_PCT = 1.00  # 1:2 reward/risk when stop is 0.5%
PAPER_TARGET2_PCT = 1.50  # 1:3 reward/risk when stop is 0.5%
PAPER_HISTORY_LIMIT = 1000
PAPER_CLOSED_LIMIT = 2000


def load_previous_paper_tracker(path: str = "data.json") -> dict:
    """Load persisted paper-tracker state from data.json."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            old = json.load(f)
        tracker = old.get("paperTradeTracker", {}) if isinstance(old, dict) else {}
        if not isinstance(tracker, dict):
            tracker = {}
    except (OSError, json.JSONDecodeError, TypeError):
        tracker = {}
    tracker.setdefault("version", 2)
    tracker.setdefault("stopLossPct", PAPER_STOP_LOSS_PCT)
    tracker.setdefault("target1Pct", PAPER_TARGET1_PCT)
    tracker.setdefault("target2Pct", PAPER_TARGET2_PCT)
    tracker.setdefault("openTrades", [])
    tracker.setdefault("closedTrades", [])
    tracker.setdefault("signalHistory", [])
    tracker.setdefault("processedScanIds", [])
    return tracker


def make_paper_tracker(
    previous: dict,
    scan_id: str,
    scan_time: str,
    session_date: Optional[str],
    candidates: list[dict],
    price_snapshots: list[dict],
    fresh_session: bool,
) -> dict:
    """Track BUY/SELL paper trades on underlying stock prices, never option premiums.

    Stop loss is 0.5%; Target 1 is 1.0% (1:2); Target 2 is 1.5% (1:3).
    A candle touching stop and a target together is scored stop-first.
    """
    tracker = dict(previous or {})
    stop_pct = safe_float(tracker.get("stopLossPct"), PAPER_STOP_LOSS_PCT) or PAPER_STOP_LOSS_PCT
    if stop_pct <= 0:
        stop_pct = PAPER_STOP_LOSS_PCT
    target1_pct = safe_float(tracker.get("target1Pct"), PAPER_TARGET1_PCT)
    target2_pct = safe_float(tracker.get("target2Pct"), PAPER_TARGET2_PCT)
    if target1_pct <= 0: target1_pct = PAPER_TARGET1_PCT
    if target2_pct <= target1_pct: target2_pct = PAPER_TARGET2_PCT
    tracker.update({"version": 3, "stopLossPct": stop_pct, "target1Pct": target1_pct, "target2Pct": target2_pct,
                    "paperStartTime": "09:15", "paperCutoffTime": "11:00", "timezone": "Asia/Kolkata"})
    try:
        scan_dt = dt.datetime.fromisoformat(str(scan_time).replace("Z", "+00:00"))
        scan_dt = scan_dt.astimezone(IST) if scan_dt.tzinfo else scan_dt.replace(tzinfo=IST)
    except Exception:
        scan_dt = dt.datetime.now(IST)
    scan_clock = scan_dt.time()
    paper_entry_window_open = (dt.time(9, 15) <= scan_clock < dt.time(11, 0))
    paper_cutoff_reached = scan_clock >= dt.time(11, 0)
    open_trades = list(tracker.get("openTrades", []))
    closed_trades = list(tracker.get("closedTrades", []))
    signal_history = list(tracker.get("signalHistory", []))
    processed = list(tracker.get("processedScanIds", []))
    snapshots_by_symbol = {str(x.get("symbol")): x for x in price_snapshots if isinstance(x, dict) and x.get("symbol")}

    remaining_open = []
    for trade in open_trades:
        if not isinstance(trade, dict):
            continue
        # Migrate prior CE/PE paper records to directional BUY/SELL labels.
        if trade.get("side") in ("CE", "PE"):
            trade["direction"] = trade["side"]
            trade["side"] = "BUY" if trade["direction"] == "CE" else "SELL"
        direction = trade.get("side", "BUY")
        snap = snapshots_by_symbol.get(str(trade.get("symbol")))
        if not snap or not snap.get("sourceBarFresh"):
            remaining_open.append(trade); continue
        candle_time = str(snap.get("candleTime") or "")
        entry_candle_time = str(trade.get("entryCandleTime") or "")
        last_processed = str(trade.get("lastProcessedCandleTime") or entry_candle_time)
        if not candle_time:
            remaining_open.append(trade); continue
        low = safe_float(snap.get("low"), safe_float(snap.get("price")))
        high = safe_float(snap.get("high"), safe_float(snap.get("price")))
        close = safe_float(snap.get("price"), safe_float(trade.get("entryPrice")))
        entry = safe_float(trade.get("entryPrice"))
        sl = safe_float(trade.get("stopLoss"))
        t1 = safe_float(trade.get("target1"), safe_float(trade.get("target")))
        t2 = safe_float(trade.get("target2"), safe_float(trade.get("target", t1)))
        is_buy = direction == "BUY" or direction == "CE"
        is_new_candle = candle_time > entry_candle_time and candle_time > last_processed
        stop_hit = (low <= sl if is_buy else high >= sl) if is_new_candle else False
        t1_hit = (high >= t1 if is_buy else low <= t1) if is_new_candle else False
        t2_hit = (high >= t2 if is_buy else low <= t2) if is_new_candle else False
        if is_new_candle:
            trade["lastProcessedCandleTime"] = candle_time
            trade["lastPrice"] = close
            trade["lastMarkAt"] = candle_time
        direction_points = close - entry if is_buy else entry - close
        trade["unrealizedPoints"] = round(direction_points, 4)
        trade["unrealizedPct"] = round((direction_points / entry * 100.0) if entry else 0.0, 4)
        # Conservative ordering: stop beats targets within a candle; otherwise close at 11:00 mark.
        exit_reason = "STOP_LOSS" if stop_hit else ("TARGET_2" if t2_hit else None)
        exit_price = sl if stop_hit else (t2 if t2_hit else None)
        if t1_hit and not stop_hit:
            trade["target1Hit"] = True
            trade.setdefault("target1HitAt", candle_time)
        if exit_reason is None and paper_cutoff_reached:
            exit_reason = "SESSION_CUTOFF_11AM"
            exit_price = close
        if exit_reason:
            points = (safe_float(exit_price) - entry) if is_buy else (entry - safe_float(exit_price))
            trade.update({"status":"CLOSED", "exitReason":exit_reason, "exitPrice":round(safe_float(exit_price),4),
                          "exitCandleTime":candle_time, "closedAt":scan_time, "pnlPoints":round(points,4),
                          "pnlPct":round((points / entry * 100.0) if entry else 0.0,4),
                          "sessionCutoffTime":"11:00 IST" if exit_reason == "SESSION_CUTOFF_11AM" else None})
            closed_trades.append(trade)
        else:
            remaining_open.append(trade)
    open_trades = remaining_open

    if scan_id not in processed:
        sample = {"scanId":scan_id,"scanTime":scan_time,"sessionDate":session_date,"freshSession":bool(fresh_session),
                  "stopLossPct":stop_pct,"target1Pct":target1_pct,"target2Pct":target2_pct,"candidates":[]}
        for candidate in candidates:
            direction = "BUY" if candidate.get("type") == "CE" else "SELL"
            candle_time = str(candidate.get("lastSourceBarCloseAt") or "")
            item = {"symbol":candidate.get("symbol"),"side":direction,"score":candidate.get("powerScore"),
                    "status":candidate.get("status"),"price":candidate.get("price"),"candleTime":candle_time,
                    "sourceBarFresh":candidate.get("sourceBarFresh",False),"tradeCreated":False,"tradeId":None}
            # Only create a paper trade from a confirmed breakout/breakdown on a fresh completed candle.
            if fresh_session and paper_entry_window_open and candidate.get("sourceBarFresh") and candidate.get("breakoutConfirmed") and candle_time:
                trade_id = f"{candidate.get('symbol')}:{direction}:{candle_time}"
                already_exists = any(str(t.get("tradeId")) == trade_id for t in open_trades + closed_trades)
                entry = safe_float(candidate.get("price"))
                if entry > 0 and not already_exists:
                    is_buy = direction == "BUY"
                    sl = entry * (1 - stop_pct/100) if is_buy else entry * (1 + stop_pct/100)
                    t1 = entry * (1 + target1_pct/100) if is_buy else entry * (1 - target1_pct/100)
                    t2 = entry * (1 + target2_pct/100) if is_buy else entry * (1 - target2_pct/100)
                    trade = {"tradeId":trade_id,"symbol":candidate.get("symbol"),"side":direction,
                             "direction":"CE" if is_buy else "PE","scoreAtEntry":candidate.get("powerScore"),
                             "signalStatusAtEntry":candidate.get("status"),"entryPrice":round(entry,4),
                             "entryTime":scan_time,"entryCandleTime":candle_time,"lastProcessedCandleTime":candle_time,
                             "lastPrice":round(entry,4),"lastMarkAt":candle_time,"stopLoss":round(sl,4),
                             "target1":round(t1,4),"target2":round(t2,4),"target":round(t2,4),
                             "stopLossPct":stop_pct,"target1Pct":target1_pct,"target2Pct":target2_pct,
                             "target1Hit":False,"status":"OPEN","unrealizedPoints":0.0,"unrealizedPct":0.0,
                             "source":"paper underlying-price simulation"}
                    open_trades.append(trade); item["tradeCreated"] = True; item["tradeId"] = trade_id
            sample["candidates"].append(item)
        signal_history.append(sample); processed.append(scan_id)

    tracker.update({"updatedAt":scan_time,"sessionDate":session_date,"stopLossPct":stop_pct,
                    "target1Pct":target1_pct,"target2Pct":target2_pct,"openTrades":open_trades,
                    "closedTrades":closed_trades[-PAPER_CLOSED_LIMIT:],"signalHistory":signal_history[-PAPER_HISTORY_LIMIT:],
                    "processedScanIds":processed[-PAPER_HISTORY_LIMIT:]})
    wins = sum(1 for t in tracker["closedTrades"] if safe_float(t.get("pnlPoints")) > 0)
    losses = sum(1 for t in tracker["closedTrades"] if safe_float(t.get("pnlPoints")) <= 0)
    closed_count = len(tracker["closedTrades"])
    realized_points = sum(safe_float(t.get("pnlPoints")) for t in tracker["closedTrades"])
    unrealized_points = sum(safe_float(t.get("unrealizedPoints")) for t in tracker["openTrades"])
    tracker["stats"] = {"signalsRecorded":sum(len(x.get("candidates",[])) for x in tracker["signalHistory"]),
                         "scansRecorded":len(tracker["signalHistory"]),"openTrades":len(tracker["openTrades"]),
                         "closedTrades":closed_count,"wins":wins,"losses":losses,
                         "winRatePct":round((wins/closed_count*100) if closed_count else 0,2),
                         "realizedPointsPerShare":round(realized_points,4),"unrealizedPointsPerShare":round(unrealized_points,4),
                         "totalPointsPerShare":round(realized_points+unrealized_points,4)}
    tracker["methodology"] = (f"Underlying stock price only; BUY bullish breakout / SELL bearish breakdown; stop {stop_pct:.2f}%, "
                               f"Target 1 {target1_pct:.2f}% (1:2), Target 2 {target2_pct:.2f}% (1:3). "
                               "Paper entries allowed 09:15–10:59 IST; remaining open trades close at the latest completed candle at or before 11:00 IST. "
                               "If one candle touches stop and target, stop-loss is recorded first. No option premium, brokerage or slippage simulated.")
    return tracker



# Sniper Scanner universe membership is additive and does not feed into ORION scoring.
# Broad-market constituents are refreshed from official Nifty Indices CSVs when available.
SNIPER_BROAD_INDEX_CSVS: dict[str, str] = {
    "NIFTY_50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "NIFTY_MIDCAP_100": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap100list.csv",
    "NIFTY_MIDCAP_150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "NIFTY_SMALLCAP_250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "NIFTY_500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
}

SNIPER_SECTOR_MEMBERSHIP_KEYS: dict[str, str] = {
    "NIFTY_BANK": "BANKNIFTY",
    "NIFTY_FINANCIAL": "FINNIFTY",
    "NIFTY_HEALTHCARE": "HEALTHCARE",
    "NIFTY_SERVICES": "SERVICES",
    "NIFTY_PRIVATE_BANK": "PVT BANK",
    "NIFTY_PSU_BANK": "PSU BANK",
    "NIFTY_IT": "IT",
    "NIFTY_PHARMA": "PHARMA",
    "NIFTY_AUTO": "AUTO",
    "NIFTY_FMCG": "FMCG",
    "NIFTY_METAL": "METAL",
    "NIFTY_ENERGY": "ENERGY",
    "NIFTY_OIL_GAS": "OIL & GAS",
    "NIFTY_REALTY": "REALTY",
    "NIFTY_CONSUMER_DURABLES": "CONSR DURBL",
    "NIFTY_INFRASTRUCTURE": "INFRA",
    "NIFTY_CONSUMPTION": "CONSUMPTION",
    "NIFTY_COMMODITIES": "COMMODITIES",
    "NIFTY_DEFENCE": "DEFENCE",
}

SNIPER_MEDIA_MEMBERS = set("ZEEL SUNTV PVRINOX NETWORK18 TV18BRDCST NAZARA SAREGAMA HATHWAY DEN DISHTV TVTODAY".split())


def build_sniper_universe_memberships() -> tuple[dict[str, list[str]], dict[str, str]]:
    """Build separate selection universes for Sniper Scanner only.

    Broad-market constituents are loaded from Nifty Indices CSVs with bounded timeouts.
    Sectoral sets use ORION's bundled representative baskets and are labelled as such.
    Missing official list data is left unavailable instead of falsely approximating an index.
    """
    memberships: dict[str, set[str]] = {}
    sources: dict[str, str] = {}

    # Live/refreshable broad-market constituents. A failed download stays unavailable,
    # except NIFTY 50 which can use the pre-existing ORION reference set as a labelled fallback.
    for key, url in SNIPER_BROAD_INDEX_CSVS.items():
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
                "Referer": "https://www.niftyindices.com/",
                "Accept": "text/csv,text/plain,*/*",
            })
            with urllib.request.urlopen(req, timeout=3.0) as response:
                raw = response.read().decode("utf-8-sig", errors="replace")
            frame = pd.read_csv(StringIO(raw))
            symbol_column = next((col for col in frame.columns if str(col).strip().lower() in {"symbol", "symbols", "ticker"}), None)
            found = set()
            if symbol_column is not None:
                found = {str(v).strip().upper() for v in frame[symbol_column].dropna().tolist()
                         if re.fullmatch(r"[A-Z0-9&.\-]{1,30}", str(v).strip().upper())}
            minimums = {"NIFTY_50": 40, "NIFTY_MIDCAP_100": 80, "NIFTY_MIDCAP_150": 120,
                        "NIFTY_SMALLCAP_250": 200, "NIFTY_500": 400}
            if len(found) >= minimums[key]:
                memberships[key] = found
                sources[key] = f"Nifty Indices constituent CSV ({len(found)} symbols)"
            else:
                raise ValueError(f"CSV had only {len(found)} symbols")
        except Exception as exc:
            print(f"SNIPER universe list unavailable: {key} ({type(exc).__name__})")
            if key == "NIFTY_50":
                fallback = set(SECTOR_INDEX_MEMBERS.get("NIFTY", set()))
                if len(fallback) >= 40:
                    memberships[key] = fallback
                    sources[key] = "ORION bundled NIFTY reference list fallback; may be outdated"
                else:
                    memberships[key] = set()
                    sources[key] = "Unavailable; official membership CSV could not be verified"
            else:
                memberships[key] = set()
                sources[key] = "Unavailable; official membership CSV could not be verified"

    memberships["FNO_STOCKS"] = set(FNO_SYMBOL_SET)
    sources["FNO_STOCKS"] = f"Current NSE F&O underlying list: {FNO_UNIVERSE_SOURCE}" if FNO_SYMBOL_SET else "F&O membership unavailable; NSE list not verified"

    # Sectoral membership uses the project's current reference baskets (matching the
    # Sector dashboard definitions). These are stock filters, not a claim of full official index composition.
    for filter_key, sector_key in SNIPER_SECTOR_MEMBERSHIP_KEYS.items():
        members = set(SECTOR_INDEX_MEMBERS.get(sector_key, set()))
        memberships[filter_key] = members
        sources[filter_key] = f"ORION {sector_key} reference basket ({len(members)} symbols; not a live official constituent feed)" if members else "Sector reference basket unavailable"
    memberships["NIFTY_MEDIA"] = set(SNIPER_MEDIA_MEMBERS)
    sources["NIFTY_MEDIA"] = "ORION media-sector reference basket; not a live official constituent feed"

    normalized = {key: sorted(symbol for symbol in values if symbol) for key, values in memberships.items()}
    return normalized, sources


def build_sniper_scanner_data(snapshots: list[dict], now: dt.datetime,
                              universe_memberships: Optional[dict[str, list[str]]] = None,
                              universe_sources: Optional[dict[str, str]] = None) -> dict:
    """Build additive Sniper Scanner research results from already-downloaded data.

    These results never feed back into GPT POWER, legacy tiers, BRAHMASTRA or BREAKER.
    Pattern labels are heuristic candidate flags, not confirmed chart patterns.
    Market-cap filters stay unavailable unless a trusted market-cap field is supplied.
    """
    rows: list[dict] = []
    for m in snapshots:
        context = m.get("context") or {}
        hist = context.get("hist")
        if not isinstance(hist, pd.DataFrame) or hist.empty or not {"Open", "High", "Low", "Close", "Volume"}.issubset(hist.columns):
            continue
        h = hist.dropna(subset=["High", "Low", "Close"]).copy()
        if h.empty:
            continue
        close_s = pd.to_numeric(h["Close"], errors="coerce").dropna()
        high_s = pd.to_numeric(h["High"], errors="coerce").dropna()
        low_s = pd.to_numeric(h["Low"], errors="coerce").dropna()
        vol_s = pd.to_numeric(h["Volume"], errors="coerce").fillna(0)
        price_now = safe_float(m.get("price"), 0.0)
        if price_now <= 0 or close_s.empty or high_s.empty or low_s.empty:
            continue

        high52 = safe_float(context.get("high52w"), safe_float(high_s.tail(252).max()))
        low52 = safe_float(low_s.tail(252).min())
        high20 = safe_float(high_s.tail(20).max()) if len(high_s) >= 20 else None
        avg_vol20 = safe_float(vol_s.tail(20).median()) if len(vol_s) >= 20 else None
        # A pivot calculated from the prior completed session.
        pdh, pdl, prev_close = (safe_float(context.get(k), 0.0) for k in ("pdh", "pdl", "prevClose"))
        pivot = (pdh + pdl + prev_close) / 3.0 if min(pdh, pdl, prev_close) > 0 else None
        orb_high = safe_float(m.get("orbHigh15"), 0.0)
        orb_low = safe_float(m.get("orbLow15"), 0.0)
        rvol = safe_float(m.get("rvol"), 0.0)
        rvol_available = bool(m.get("rvolAvailable", False))
        pct_change = safe_float(m.get("pctChangeNum"), 0.0)
        fresh = bool(m.get("sourceBarFresh", False))
        source_asof = m.get("lastSourceBarCloseAt")

        cleared_20d_high = bool(high20 and price_now > high20)
        cleared_pivot = bool(pivot and price_now > pivot and orb_high > 0 and price_now > orb_high)
        breakout_structure = bool(cleared_20d_high or cleared_pivot)
        distance_to_52w_high = ((high52 - price_now) / high52 * 100.0) if high52 > 0 else None
        within_52w_high_1pct = bool(high52 > 0 and price_now >= high52 * 0.99)

        # Standard 8-point trend-template approximation, evaluated only when the moving
        # averages needed for it exist. The user can see the score and available points.
        closes = close_s.astype(float)
        sma50 = safe_float(closes.tail(50).mean()) if len(closes) >= 50 else None
        sma150 = safe_float(closes.tail(150).mean()) if len(closes) >= 150 else None
        sma200 = safe_float(closes.tail(200).mean()) if len(closes) >= 200 else None
        sma200_series = closes.rolling(200).mean().dropna() if len(closes) >= 200 else pd.Series(dtype=float)
        sma200_rising = (bool(sma200_series.iloc[-1] > sma200_series.iloc[-21])
                         if len(sma200_series) >= 21 else None)
        template_checks = [
            (price_now > sma50) if sma50 is not None else None,
            (price_now > sma150) if sma150 is not None else None,
            (price_now > sma200) if sma200 is not None else None,
            (sma50 > sma150) if sma50 is not None and sma150 is not None else None,
            (sma150 > sma200) if sma150 is not None and sma200 is not None else None,
            sma200_rising,
            (low52 > 0 and price_now >= low52 * 1.30) if len(closes) >= 200 else None,
            (high52 > 0 and price_now >= high52 * 0.75) if len(closes) >= 200 else None,
        ]
        template_available = sum(v is not None for v in template_checks)
        template_score = sum(v is True for v in template_checks)
        template_detail = [
            "Price > SMA50", "Price > SMA150", "Price > SMA200", "SMA50 > SMA150",
            "SMA150 > SMA200", "SMA200 rising", "30% above 52W low", "Within 25% of 52W high"
        ]
        template_points = [{"label": name, "pass": check} for name, check in zip(template_detail, template_checks)]

        # Daily + weekly confluence uses prior completed daily history for its averages.
        daily_bull = bool(sma50 is not None and sma150 is not None and price_now > sma50 and sma50 > sma150)
        daily_bear = bool(sma50 is not None and sma150 is not None and price_now < sma50 and sma50 < sma150)
        weekly_close = closes.resample("W-FRI").last().dropna() if len(closes) >= 30 else pd.Series(dtype=float)
        weekly_sma10 = weekly_close.rolling(10).mean().dropna() if len(weekly_close) >= 10 else pd.Series(dtype=float)
        weekly_bull = (bool(price_now > weekly_sma10.iloc[-1] and weekly_sma10.iloc[-1] > weekly_sma10.iloc[-5])
                       if len(weekly_sma10) >= 5 else None)
        weekly_bear = (bool(price_now < weekly_sma10.iloc[-1] and weekly_sma10.iloc[-1] < weekly_sma10.iloc[-5])
                       if len(weekly_sma10) >= 5 else None)
        mtf_bull = bool(daily_bull and weekly_bull is True)
        mtf_bear = bool(daily_bear and weekly_bear is True)

        # Conservative, explicitly heuristic chart-pattern flags based on daily OHLC.
        ranges = (pd.to_numeric(h["High"], errors="coerce") - pd.to_numeric(h["Low"], errors="coerce")).dropna()
        patterns: list[str] = []
        pattern_evidence: dict[str, bool] = {"VCP": False, "CUP_HANDLE": False, "BULL_FLAG": False, "FLAT_BASE": False}
        if len(ranges) >= 15 and len(high_s) >= 20:
            r_old = safe_float(ranges.tail(15).iloc[:5].mean())
            r_mid = safe_float(ranges.tail(10).iloc[:5].mean())
            r_new = safe_float(ranges.tail(5).mean())
            pattern_evidence["VCP"] = bool(r_old > 0 and r_mid > 0 and r_new > 0 and r_new < r_mid * 0.92 and r_mid < r_old * 0.92 and price_now >= high_s.tail(20).max() * 0.94)
        if len(closes) >= 25:
            base_close = safe_float(closes.iloc[-16])
            recent_close = safe_float(closes.iloc[-6])
            lead_gain = (recent_close / base_close - 1.0) * 100.0 if base_close > 0 else 0.0
            flag_pullback = (price_now / recent_close - 1.0) * 100.0 if recent_close > 0 else 0.0
            pattern_evidence["BULL_FLAG"] = bool(lead_gain >= 8.0 and -6.0 <= flag_pullback <= 3.0 and price_now >= (sma20 := safe_float(closes.tail(20).mean())))
        if len(high_s) >= 20 and len(low_s) >= 20:
            range_pct = (safe_float(high_s.tail(20).max()) - safe_float(low_s.tail(20).min())) / max(price_now, 0.01) * 100.0
            pattern_evidence["FLAT_BASE"] = bool(range_pct <= 10.0 and price_now >= safe_float(high_s.tail(20).max()) * 0.90)
        if len(h) >= 60:
            hh = pd.to_numeric(h["High"], errors="coerce")
            rim = safe_float(hh.iloc[-60:-20].max())
            cup_low = safe_float(pd.to_numeric(h["Low"], errors="coerce").iloc[-40:-10].min())
            handle_low = safe_float(pd.to_numeric(h["Low"], errors="coerce").tail(5).min())
            pullback_from_rim = (rim - handle_low) / rim * 100.0 if rim > 0 else 0.0
            pattern_evidence["CUP_HANDLE"] = bool(rim > 0 and cup_low < rim * 0.92 and price_now >= rim * 0.95 and 1.0 <= pullback_from_rim <= 12.0)
        patterns = [name.replace("_", " ") for name, detected in pattern_evidence.items() if detected]

        # A first-observed-daily-bar reference can be a proxy for recent IPOs, but is not
        # guaranteed to be the official listing day. Keep the caveat in the emitted record.
        history_sessions = int(len(closes))
        first_seen_high = safe_float(high_s.iloc[0]) if len(high_s) else None
        recent_closes = closes.tail(5)
        ipo_proxy_available = bool(history_sessions < 230 and first_seen_high and first_seen_high > 0)
        ipo_recent_cross = bool(ipo_proxy_available and price_now > first_seen_high and any(float(c) <= first_seen_high for c in recent_closes))

        atr = safe_float(m.get("atr"), 0.0)
        long_trigger = max([v for v in (pivot, orb_high if orb_high > 0 else None, high20) if v is not None], default=None)
        short_trigger = min([v for v in (pdl if pdl > 0 else None, orb_low if orb_low > 0 else None) if v is not None], default=None)
        entry_plan = None
        # Make the displayed reference side agree with the trend/momentum context where possible.
        prefer_short = bool(mtf_bear or (daily_bear and pct_change < 0))
        if atr > 0 and prefer_short and short_trigger is not None:
            risk = max(atr * 0.5, short_trigger * 0.0025)
            entry_plan = {"side":"SHORT reference", "trigger":round(short_trigger,2), "stop":round(short_trigger+risk,2), "target1":round(short_trigger-risk,2), "target2":round(short_trigger-2*risk,2), "riskPerShare":round(risk,2), "method":"Trigger level with 0.5 ATR stop; T1=1R, T2=2R"}
        elif atr > 0 and long_trigger is not None:
            risk = max(atr * 0.5, long_trigger * 0.0025)
            entry_plan = {"side":"LONG reference", "trigger":round(long_trigger,2), "stop":round(long_trigger-risk,2), "target1":round(long_trigger+risk,2), "target2":round(long_trigger+2*risk,2), "riskPerShare":round(risk,2), "method":"Trigger level with 0.5 ATR stop; T1=1R, T2=2R"}
        elif atr > 0 and short_trigger is not None:
            risk = max(atr * 0.5, short_trigger * 0.0025)
            entry_plan = {"side":"SHORT reference", "trigger":round(short_trigger,2), "stop":round(short_trigger+risk,2), "target1":round(short_trigger-risk,2), "target2":round(short_trigger-2*risk,2), "riskPerShare":round(risk,2), "method":"Trigger level with 0.5 ATR stop; T1=1R, T2=2R"}

        cap_cr = m.get("marketCapCr")
        try:
            cap_cr = float(cap_cr) if cap_cr is not None and math.isfinite(float(cap_cr)) and float(cap_cr) > 0 else None
        except (TypeError, ValueError):
            cap_cr = None
        cap_bucket = None
        if cap_cr is not None:
            cap_bucket = "Large-Cap" if cap_cr >= 20000 else "Mid-Cap" if cap_cr >= 5000 else "Small-Cap" if cap_cr >= 500 else "Micro-Cap"

        rows.append({
            "symbol": str(m.get("symbol", "")).upper(), "sector": m.get("sector", "General"),
            "price": round(price_now, 2), "pctChange": round(pct_change, 2),
            "sessionReturnPct": round(safe_float(m.get("sessionReturnPct")), 2),
            "rvol": round(rvol, 2), "rvolAvailable": rvol_available,
            "sourceBarFresh": fresh, "sourceBarAgeMinutes": m.get("sourceBarAgeMinutes"),
            "asOf": source_asof, "sessionDate": m.get("sessionDate"),
            "high52w": round(high52, 2) if high52 > 0 else None,
            "low52w": round(low52, 2) if low52 > 0 else None,
            "distanceTo52wHighPct": round(distance_to_52w_high, 2) if distance_to_52w_high is not None else None,
            "within52wHigh1Pct": within_52w_high_1pct,
            "prior20dHigh": round(high20, 2) if high20 is not None else None,
            "cleared20dHigh": cleared_20d_high, "pivot": round(pivot, 2) if pivot is not None else None,
            "clearedPivotAndORB": cleared_pivot, "breakoutStructure": breakout_structure,
            "trendTemplateScore": template_score, "trendTemplateAvailable": template_available,
            "trendTemplatePasses": template_points, "dailyTrendBull": daily_bull, "dailyTrendBear": daily_bear,
            "weeklyTrendBull": weekly_bull, "weeklyTrendBear": weekly_bear,
            "mtfBullish": mtf_bull, "mtfBearish": mtf_bear,
            "patterns": patterns, "patternEvidence": pattern_evidence,
            "historySessions": history_sessions, "ipoReferenceAvailable": ipo_proxy_available,
            "ipoReferenceHigh": round(first_seen_high,2) if ipo_proxy_available else None,
            "ipoRecentCrossProxy": ipo_recent_cross,
            "ipoReferenceNote": "First observed daily candle is only a proxy; not verified as official listing-day high." if ipo_proxy_available else None,
            "marketCapCr": cap_cr, "marketCapBucket": cap_bucket,
            "entryPlan": entry_plan,
        })

    # Stable ordering by power/momentum but preserve every supported symbol for filter scans.
    rows.sort(key=lambda r: (bool(r.get("sourceBarFresh")), int(r.get("trendTemplateScore", 0)), float(r.get("pctChange", 0))), reverse=True)
    cap_available = any(r.get("marketCapCr") is not None for r in rows)
    return {
        "asOf": now.astimezone(IST).isoformat(),
        "sessionDate": max((r.get("sessionDate") or "" for r in rows), default="") or None,
        "source": "Existing ORION scanner snapshots + 1-year daily OHLC history; 5-minute RVOL is versus median cumulative volume at the same time across available recent sessions.",
        "freshRecordCount": sum(1 for r in rows if r.get("sourceBarFresh")),
        "stockCount": len(rows), "marketCapDataAvailable": cap_available,
        "marketCapNote": "Reliable market-cap metadata is not present in the current OHLC feed. Cap filters are shown but cannot be applied until a trusted metadata source is configured." if not cap_available else "Market cap available for at least some symbols; unavailable symbols remain unclassified.",
        "volumeRatioNote": "RVOL is time-of-day matched against available recent intraday sessions, not a claimed 20-day cumulative-volume baseline. Results are indicative if the provider has fewer sessions.",
        "patternNote": "Chart-pattern flags are heuristic screens from daily OHLC history, not a confirmed visual chart-pattern detector.",
        "ipoNote": "IPO screen uses first-observed daily bar as a listing-high proxy when history is short. It is not proof of official IPO/listing date or listing-day high.",
        "universeMemberships": universe_memberships if universe_memberships is not None else {},
        "universeMembershipSources": universe_sources if universe_sources is not None else {},
        "universeMembershipNote": "Universe selection filters Sniper Scanner only. Broad-market membership is loaded from Nifty Indices constituent CSVs when available; sectoral filters use ORION reference baskets, which may not include every current official constituent. Missing broad-market lists are not approximated.",
        "strategies": {
            "volumeBreakout": {"label":"Volume Breakout", "defaultMinRvol":2.0, "defaultMinChangePct":1.0},
            "fresh52wHigh": {"label":"Fresh 52W High", "defaultNearHighPct":1.0, "defaultMinRvol":1.2, "defaultMinChangePct":1.0},
            "ipoListingHigh": {"label":"IPO · Listing-Day High Breakout", "requiresReferenceValidation":True},
            "trendTemplate": {"label":"8-Point Trend Template", "defaultMinScore":6},
            "mtfConfluence": {"label":"Daily + Weekly Confluence"},
            "chartPatterns": {"label":"VCP / Cup & Handle / Bull Flag / Flat Base"},
        },
        "stocks": rows,
    }


def load_previous_scan_output(path: str = "data.json") -> dict:
    """Load prior output for Telegram de-duplication and persistent tracker state."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def build_special10_candidates(gpt_power_stocks: list[dict], leaders: list[dict], breaker_stocks: list[dict]) -> list[dict]:
    """Mirror the browser SPECIAL 10 merge/rank logic for shared UI and Telegram output."""
    by_symbol: dict[str, dict] = {}

    def add(record: dict, source: str) -> None:
        symbol = str(record.get("symbol", "")).strip().upper()
        if not symbol:
            return
        item = by_symbol.setdefault(symbol, {
            "symbol": symbol, "sources": [], "power": None, "brahmastra": None, "breaker": None,
            "price": record.get("price"), "pctChange": record.get("pctChange"),
            "sector": record.get("sector") or record.get("sectorStatus") or "General",
            "sourceBarFresh": bool(record.get("sourceBarFresh", False)),
        })
        if source not in item["sources"]:
            item["sources"].append(source)
        if source == "GPT POWER": item["power"] = record
        elif source == "BRAHMASTRA": item["brahmastra"] = record
        elif source == "BREAKER": item["breaker"] = record
        if record.get("price") is not None: item["price"] = record.get("price")
        if record.get("pctChange") is not None: item["pctChange"] = record.get("pctChange")
        if record.get("sector") or record.get("sectorStatus"):
            item["sector"] = record.get("sector") or record.get("sectorStatus")
        item["sourceBarFresh"] = bool(item["sourceBarFresh"] or record.get("sourceBarFresh", False))

    for record in gpt_power_stocks: add(record, "GPT POWER")
    for record in leaders:
        if record.get("tier") == "BRAHMĀSTRA" or record.get("tier") == "BRAHMASTRA":
            add(record, "BRAHMĀSTRA")
    for record in breaker_stocks: add(record, "BREAKER")

    rows = list(by_symbol.values())
    for item in rows:
        power, brahmastra, breaker = item.get("power") or {}, item.get("brahmastra") or {}, item.get("breaker") or {}
        item["commonCount"] = len(item["sources"])
        item["rankScore"] = (
            item["commonCount"] * 1000 + safe_float(power.get("powerScore"))
            + safe_float(brahmastra.get("numScore")) * 10
            + max(safe_float(breaker.get("bullScore")), safe_float(breaker.get("bearScore"))) * 15
            + (30 if power.get("status") == "BREAKOUT CONFIRMED" else 0)
            + (25 if breaker.get("hasBuySignal") or breaker.get("hasSellSignal") else 0)
        )
        item["signal"] = (
            "BREAKER BUY" if breaker.get("hasBuySignal") else
            "BREAKER SELL" if breaker.get("hasSellSignal") else
            "GPT CONFIRMED" if power.get("status") == "BREAKOUT CONFIRMED" else
            "BRAHMĀSTRA" if brahmastra else "WATCH"
        )
    rows.sort(key=lambda row: (-safe_float(row.get("rankScore")), row["symbol"]))
    selected: list[dict] = []

    def push_unique(row: Optional[dict]) -> None:
        if row and not any(existing["symbol"] == row["symbol"] for existing in selected) and len(selected) < 10:
            selected.append(row)

    push_unique(next((row for row in rows if row.get("power")), None))
    push_unique(next((row for row in rows if row.get("brahmastra")), None))
    for row in rows: push_unique(row)
    for idx, row in enumerate(selected, 1): row["specialRank"] = idx
    return selected


def sniper_strategy_matches(stock: dict) -> list[str]:
    """Use the Sniper UI's default thresholds for an additive shortlist/alert."""
    matches = []
    change = safe_float(stock.get("pctChange")); rvol = safe_float(stock.get("rvol"))
    rvol_available = bool(stock.get("rvolAvailable")); price = safe_float(stock.get("price"))
    if stock.get("breakoutStructure") and rvol_available and rvol >= 2.0 and change >= 1.0:
        matches.append("Volume Breakout")
    high52 = stock.get("high52w")
    if high52 is not None and safe_float(high52) > 0 and price >= safe_float(high52) * 0.99 and rvol_available and rvol >= 1.2 and change >= 1.0:
        matches.append("Fresh 52W High")
    if int(safe_float(stock.get("trendTemplateAvailable"))) == 8 and int(safe_float(stock.get("trendTemplateScore"))) >= 6:
        matches.append("8-Point Trend Template")
    patterns = stock.get("patterns") if isinstance(stock.get("patterns"), list) else []
    if patterns: matches.append("Chart Patterns: " + ", ".join(str(x) for x in patterns[:3]))
    if stock.get("mtfBullish") or stock.get("mtfBearish"): matches.append("Daily + Weekly Confluence")
    if stock.get("ipoRecentCrossProxy"): matches.append("IPO High (provisional)")
    return matches


def build_quick_picks(gpt_power_stocks: list[dict], leaders: list[dict], breaker_stocks: list[dict],
                      sniper_scanner: dict, sector_rankings: list[dict], stock_fuel_metrics: dict,
                      now: dt.datetime) -> dict:
    """Rank a top-10 shortlist from existing signals; does not modify source scores."""
    by_symbol: dict[str, dict] = {}

    def add(record: dict, source: str) -> None:
        symbol = str(record.get("symbol", "")).upper().strip()
        if not symbol: return
        item = by_symbol.setdefault(symbol, {
            "symbol": symbol, "sources": [], "price": None, "pctChange": None, "sector": "General",
            "sourceBarFresh": False, "power": None, "brahmastra": None, "breaker": None,
            "sniper": None, "sniperStrategies": [], "sessionDate": record.get("sessionDate"),
        })
        if source not in item["sources"]: item["sources"].append(source)
        item["sourceBarFresh"] = bool(item["sourceBarFresh"] or record.get("sourceBarFresh", False))
        if record.get("sessionDate"): item["sessionDate"] = record.get("sessionDate")
        for key in ("price", "pctChange", "sector", "type", "status"):
            if record.get(key) is not None: item[key] = record.get(key)
        if source == "GPT POWER": item["power"] = record
        elif source == "BRAHMĀSTRA": item["brahmastra"] = record
        elif source == "BREAKER": item["breaker"] = record
        elif source == "SNIPER SCANNER":
            item["sniper"] = record
            item["sniperStrategies"] = sniper_strategy_matches(record)

    for row in gpt_power_stocks: add(row, "GPT POWER")
    for row in leaders:
        if row.get("tier") == "BRAHMĀSTRA" or row.get("tier") == "BRAHMASTRA": add(row, "BRAHMĀSTRA")
    for row in breaker_stocks: add(row, "BREAKER")
    sniper_rows = sniper_scanner.get("stocks", []) if isinstance(sniper_scanner, dict) else []
    if isinstance(sniper_rows, list):
        for row in sniper_rows:
            if sniper_strategy_matches(row): add(row, "SNIPER SCANNER")

    sector_by_symbol: dict[str, dict] = {}
    for sector in sector_rankings:
        members = sector.get("eligibleStocks", [])
        if isinstance(members, list):
            for member in members:
                symbol = str(member.get("symbol", "")).upper().strip()
                if symbol: sector_by_symbol[symbol] = sector
    fuel_metrics = stock_fuel_metrics if isinstance(stock_fuel_metrics, dict) else {}
    results = []
    for symbol, item in by_symbol.items():
        power = item.get("power") or {}; brahmastra = item.get("brahmastra") or {}
        breaker = item.get("breaker") or {}; sniper = item.get("sniper") or {}
        metric = fuel_metrics.get(symbol, {})
        if not item.get("sector") or item.get("sector") == "General": item["sector"] = metric.get("sector") or "General"
        item["fuelLeftPct"] = metric.get("fuelLeftPct"); item["atrUsedPct"] = metric.get("atrUsedPct")
        item["fuelAsOf"] = metric.get("asOf"); item["entryPlan"] = sniper.get("entryPlan")
        item["rvol"] = sniper.get("rvol", power.get("rvol")); item["trendTemplateScore"] = sniper.get("trendTemplateScore")
        item["pctChangeNum"] = safe_float(str(item.get("pctChange", "0")).replace("%", ""))
        item["commonCount"] = len(item["sources"])
        sector = sector_by_symbol.get(symbol, {})
        item["sectorRank"] = sector.get("rank"); item["sectorChangePct"] = sector.get("changePct")
        evidence = []
        if len(item["sources"]) > 1: evidence.append(f"Appears in {len(item['sources'])} scanner sections")
        if power: evidence.append(f"GPT POWER {safe_float(power.get('powerScore')):.0f}/100 · {power.get('status', 'candidate')}")
        if brahmastra: evidence.append(f"BRAHMĀSTRA {brahmastra.get('numScore', brahmastra.get('score', 'active'))}/7")
        if breaker: evidence.append(f"BREAKER bull/bear {safe_float(breaker.get('bullScore')):.0f}/6 / {safe_float(breaker.get('bearScore')):.0f}/6")
        if sniper.get("trendTemplateAvailable") is not None: evidence.append(f"Trend template {safe_float(sniper.get('trendTemplateScore')):.0f}/8")
        if sniper.get("rvolAvailable"): evidence.append(f"RVOL {safe_float(sniper.get('rvol')):.2f}×")
        evidence.extend(item.get("sniperStrategies", [])[:3])
        if item.get("sectorRank") and item.get("sectorChangePct") is not None:
            evidence.append(f"Sector rank #{item['sectorRank']} ({safe_float(item['sectorChangePct']):+.2f}%)")
        item["evidence"] = evidence[:8]
        score = max(0, item["commonCount"] - 1) * 100 + (25 if item["sourceBarFresh"] else 0)
        score += safe_float(power.get("powerScore")) * 0.25 + safe_float(brahmastra.get("numScore")) * 4
        score += max(safe_float(breaker.get("bullScore")), safe_float(breaker.get("bearScore"))) * 4
        score += min(8, safe_float(sniper.get("trendTemplateScore"))) * 3 + min(4, safe_float(item.get("rvol"))) * 3
        if sniper.get("breakoutStructure"): score += 12
        if sniper.get("mtfBullish"): score += 8
        if power.get("breakoutConfirmed"): score += 10
        if item.get("sectorRank") and int(safe_float(item["sectorRank"])) <= 5: score += 10
        elif item.get("sectorRank") and int(safe_float(item["sectorRank"])) >= 19: score -= 5
        item["rankScore"] = round(score, 1)
        item["rankLabel"] = "Research ranking only—not a probability or guarantee"
        item["signalSummary"] = (
            "BREAKOUT CONFIRMED" if power.get("status") == "BREAKOUT CONFIRMED" else
            "BREAKER BUY" if breaker.get("hasBuySignal") else
            "BREAKER SELL" if breaker.get("hasSellSignal") else
            "BRAHMĀSTRA" if brahmastra else "SNIPER SETUP" if item.get("sniperStrategies") else "WATCH"
        )
        results.append(item)
    results.sort(key=lambda row: (bool(row.get("sourceBarFresh")), safe_float(row.get("rankScore")), safe_float(row.get("rvol"))), reverse=True)
    return {
        "asOf": now.astimezone(IST).isoformat(),
        "sessionDate": max((str(row.get("sessionDate")) for row in results if row.get("sessionDate")), default=None),
        "candidateCount": len(results), "stockCount": min(10, len(results)),
        "source": "Additive shortlist from existing GPT POWER, BRAHMĀSTRA, BREAKER and Sniper signals; source scoring and selection are unchanged.",
        "rankNote": "Rank score prioritizes cross-scanner overlap, freshness, existing scores and trend/volume/sector evidence. It is not a probability or trading recommendation.",
        "stocks": [{k: v for k, v in row.items() if k not in ("power", "brahmastra", "breaker", "sniper")} for row in results[:10]],
    }



def build_top_two_trade_candidates(
    gpt_power_stocks: list[dict],
    leaders: list[dict],
    breaker_stocks: list[dict],
    sniper_scanner: dict,
    sector_rankings: list[dict],
    breadth_sentiment: str,
    now: dt.datetime,
    minimum_score: float = 24.0,
) -> dict:
    """Additive, direction-neutral final ranking for at most two trade candidates.

    This is a research ranking, not a calibrated probability or a guarantee of movement.
    It consumes existing scanner outputs and never alters any source scanner's selection.
    """
    by_symbol: dict[str, dict] = {}

    def add(row: dict, source: str) -> None:
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol:
            return
        item = by_symbol.setdefault(symbol, {
            "symbol": symbol, "records": {"GPT POWER": [], "ORION TIERS": [], "BREAKER": [], "SNIPER SCANNER": []},
            "sources": [], "sourceBarFresh": False, "price": None, "pctChange": None,
            "sector": row.get("sector") or "General", "sessionDate": row.get("sessionDate"),
        })
        item["records"][source].append(row)
        if source not in item["sources"]:
            item["sources"].append(source)
        item["sourceBarFresh"] = bool(item["sourceBarFresh"] or row.get("sourceBarFresh", False))
        for key in ("price", "pctChange", "sector", "sessionDate"):
            if row.get(key) is not None:
                item[key] = row.get(key)

    for row in gpt_power_stocks:
        if isinstance(row, dict): add(row, "GPT POWER")
    for row in leaders:
        if isinstance(row, dict): add(row, "ORION TIERS")
    for row in breaker_stocks:
        if isinstance(row, dict): add(row, "BREAKER")
    sniper_rows = sniper_scanner.get("stocks", []) if isinstance(sniper_scanner, dict) else []
    for row in sniper_rows if isinstance(sniper_rows, list) else []:
        if isinstance(row, dict): add(row, "SNIPER SCANNER")

    sector_by_symbol: dict[str, dict] = {}
    for sector in sector_rankings if isinstance(sector_rankings, list) else []:
        if not isinstance(sector, dict):
            continue
        members = sector.get("eligibleStocks", [])
        if isinstance(members, list):
            for member in members:
                if isinstance(member, dict):
                    symbol = str(member.get("symbol", "")).upper().strip()
                    if symbol:
                        sector_by_symbol[symbol] = sector

    def pct_value(row: dict) -> float:
        value = row.get("pctChangeNum", row.get("pctChange", 0.0))
        return safe_float(str(value if value is not None else 0).replace("%", ""), 0.0)

    def side_of(row: dict) -> str | None:
        value = str(row.get("type", row.get("signalType", ""))).upper().strip()
        if value in {"CE", "BUY", "BULLISH", "LONG", "BUY WATCH"}:
            return "CE"
        if value in {"PE", "SELL", "BEARISH", "SHORT", "SELL WATCH"}:
            return "PE"
        return None

    candidates: list[dict] = []
    sentiment = str(breadth_sentiment or "").upper()
    for symbol, item in by_symbol.items():
        records = item["records"]
        all_records = [row for rows in records.values() for row in rows]
        pct = next((pct_value(row) for row in all_records if row.get("pctChange") is not None or row.get("pctChangeNum") is not None), 0.0)
        price_now = safe_float(item.get("price"), 0.0)
        sector = sector_by_symbol.get(symbol, {})
        sector_change = safe_float(sector.get("changePct"), 0.0)
        sector_rank = sector.get("rank")
        rvols = [safe_float(row.get("rvol"), 0.0) for row in all_records if row.get("rvol") is not None]
        rvol = max(rvols, default=0.0)

        direction_results = {}
        for side in ("CE", "PE"):
            points = 0.0
            aligned_sources: set[str] = set()
            reasons: list[str] = []
            supporting_rows: list[dict] = []

            for row in records["GPT POWER"]:
                if side_of(row) == side:
                    aligned_sources.add("GPT POWER")
                    supporting_rows.append(row)
                    power_score = safe_float(row.get("powerScore"), 0.0)
                    points += 4.0 + min(22.0, power_score * 0.22)
                    if row.get("breakoutConfirmed") or row.get("status") == "BREAKOUT CONFIRMED":
                        points += 5.0
                        reasons.append("GPT POWER breakout/breakdown confirmation")
                    else:
                        reasons.append(f"GPT POWER score {power_score:.0f}/100")

            for row in records["ORION TIERS"]:
                if side_of(row) == side:
                    aligned_sources.add("ORION TIERS")
                    supporting_rows.append(row)
                    legacy_score = safe_float(row.get("numScore", row.get("score", 0.0)), 0.0)
                    if isinstance(row.get("score"), str) and "/" in row.get("score", ""):
                        try: legacy_score = float(row["score"].split("/", 1)[0])
                        except (ValueError, TypeError): pass
                    points += 4.0 + min(14.0, legacy_score * 1.8)
                    reasons.append(f"{row.get('tier', 'ORION tier')} direction matches")

            for row in records["BREAKER"]:
                directional_score = safe_float(row.get("bullScore" if side == "CE" else "bearScore"), 0.0)
                direct_flags = (
                    ("hasBuySignal", "buySetupSignal", "rFactorBuySignal", "volumeBreakoutBuySignal")
                    if side == "CE" else
                    ("hasSellSignal", "sellSetupSignal", "rFactorSellSignal", "volumeBreakoutSellSignal")
                )
                direct_signal = any(bool(row.get(flag)) for flag in direct_flags)
                if directional_score >= 4 or direct_signal:
                    aligned_sources.add("BREAKER")
                    supporting_rows.append(row)
                    points += min(13.0, directional_score * 2.0)
                    if direct_signal:
                        points += 5.0
                        reasons.append(f"BREAKER {('bullish' if side == 'CE' else 'bearish')} signal")
                    else:
                        reasons.append(f"BREAKER score {directional_score:.0f}/6")

            for row in records["SNIPER SCANNER"]:
                mtf_match = bool(row.get("mtfBullish" if side == "CE" else "mtfBearish"))
                strategy_match = bool(side == "CE" and (
                    row.get("breakoutStructure") or row.get("within52wHigh1Pct") or row.get("ipoRecentCrossProxy")
                    or safe_float(row.get("trendTemplateScore")) >= 6
                ))
                if mtf_match or strategy_match:
                    aligned_sources.add("SNIPER SCANNER")
                    supporting_rows.append(row)
                    if mtf_match:
                        points += 8.0
                        reasons.append("Sniper daily/weekly trend confluence")
                    if strategy_match:
                        points += 3.0 if mtf_match else 6.0
                        reasons.append("Sniper trend/breakout structure")

            if not aligned_sources:
                direction_results[side] = {"score": 0.0, "sources": [], "reasons": [], "supportingRows": []}
                continue

            # Additive common evidence; directional multipliers remain symmetric.
            points += min(12.0, max(0, len(aligned_sources) - 1) * 4.0)
            if item["sourceBarFresh"]:
                points += 6.0
                reasons.append("source data marked fresh")
            else:
                reasons.append("source data may be delayed/stale")
            if rvol >= 2.0:
                points += 5.0
                reasons.append(f"relative volume {rvol:.2f}×")
            elif rvol >= 1.3:
                points += 3.0
                reasons.append(f"relative volume {rvol:.2f}×")
            directional_move = pct if side == "CE" else -pct
            if directional_move > 0:
                move_points = min(7.0, directional_move * 2.5)
                points += move_points
                if abs(pct) >= 0.3:
                    reasons.append(f"price move {pct:+.2f}% aligned")
            elif directional_move < 0:
                points -= min(5.0, abs(directional_move) * 1.5)
                reasons.append(f"price move {pct:+.2f}% opposes this direction")

            if side == "CE" and "BULLISH" in sentiment:
                points += 3.0; reasons.append("market breadth bullish")
            elif side == "PE" and "BEARISH" in sentiment:
                points += 3.0; reasons.append("market breadth bearish")
            elif (side == "CE" and "BEARISH" in sentiment) or (side == "PE" and "BULLISH" in sentiment):
                points -= 2.0

            sector_matches = (side == "CE" and sector_change > 0) or (side == "PE" and sector_change < 0)
            sector_opposes = (side == "CE" and sector_change < 0) or (side == "PE" and sector_change > 0)
            if sector_matches:
                points += 4.0
                reasons.append(f"sector move aligned ({sector_change:+.2f}%)")
            elif sector_opposes:
                points -= 2.0
                reasons.append(f"sector move opposes ({sector_change:+.2f}%)")
            if sector_rank is not None and int(safe_float(sector_rank, 0)) <= 5 and sector_matches:
                points += 1.0

            # Attach an existing plan only when its directional side agrees. No fabricated levels.
            plan = None
            for row in supporting_rows:
                raw_plan = row.get("entryPlan")
                if isinstance(raw_plan, dict):
                    plan_side = str(raw_plan.get("side", "")).upper()
                    is_long_plan = "LONG" in plan_side or "BUY" in plan_side
                    is_short_plan = "SHORT" in plan_side or "SELL" in plan_side
                    if (side == "CE" and is_long_plan) or (side == "PE" and is_short_plan):
                        plan = {k: raw_plan.get(k) for k in ("trigger", "stop", "target1", "target2", "method") if raw_plan.get(k) is not None}
                        if plan: break
                if side_of(row) == side and row.get("triggerLevel") is not None:
                    plan = {"trigger": row.get("triggerLevel"), "stop": row.get("invalidationLevel"),
                            "method": "Existing GPT POWER trigger/invalidation levels"}
                    break
                if side_of(row) == side and row.get("sl") is not None and row.get("t1") is not None:
                    plan = {"stop": row.get("sl"), "target1": row.get("t1"),
                            "method": "Existing ORION tier risk/target references; trigger still requires confirmation"}
                    break

            direction_results[side] = {
                "score": round(min(100.0, max(0.0, points)), 1),
                "sources": sorted(aligned_sources),
                "reasons": list(dict.fromkeys(reasons))[:5],
                "supportingRows": supporting_rows,
                "entryPlan": plan,
            }

        bull = direction_results["CE"]
        bear = direction_results["PE"]
        best_side = "CE" if bull["score"] >= bear["score"] else "PE"
        best = direction_results[best_side]
        other = bear if best_side == "CE" else bull
        # Avoid publishing a direction when the same symbol has nearly tied, opposing evidence.
        if bull["score"] >= minimum_score and bear["score"] >= minimum_score and abs(bull["score"] - bear["score"]) < 5.0:
            continue
        if best["score"] < minimum_score or not best["sources"]:
            continue

        display_sources = []
        for source in best["sources"]:
            if source == "ORION TIERS":
                tiers = sorted({str(row.get("tier")) for row in records[source] if side_of(row) == best_side and row.get("tier")})
                display_sources.append(" / ".join(tiers) if tiers else source)
            else:
                display_sources.append(source)
        reasons = list(best["reasons"])
        if other["score"] >= minimum_score and best["score"] - other["score"] >= 5.0:
            reasons.append(f"directional edge over opposite side: {best['score'] - other['score']:.1f} points")
        candidates.append({
            "symbol": symbol,
            "direction": "BULLISH" if best_side == "CE" else "BEARISH",
            "type": best_side,
            "score": best["score"],
            "scoreLabel": f"{best['score']:.1f}/100 ranking points",
            "oppositeScore": other["score"],
            "sources": display_sources,
            "sourceCount": len(best["sources"]),
            "sourceBarFresh": bool(item["sourceBarFresh"]),
            "dataStatus": "FRESH SOURCE DATA" if item["sourceBarFresh"] else "DELAYED / LAST AVAILABLE DATA",
            "price": price_now or None,
            "pctChange": f"{pct:+.2f}%",
            "sector": item.get("sector") or "General",
            "sectorChangePct": sector_change,
            "rvol": rvol or None,
            "reasons": reasons[:5],
            "entryPlan": best.get("entryPlan"),
            "sessionDate": item.get("sessionDate"),
            "selectionNote": "Research ranking only—not a probability or a trade guarantee. Verify live price and trigger before entry.",
        })

    candidates.sort(key=lambda row: (safe_float(row.get("score")), bool(row.get("sourceBarFresh")), safe_float(row.get("sourceCount")), safe_float(row.get("rvol"))), reverse=True)
    selected = candidates[:2]
    for index, row in enumerate(selected, 1):
        row["rank"] = index
    return {
        "asOf": now.astimezone(IST).isoformat(),
        "candidateCount": len(candidates),
        "stockCount": len(selected),
        "minimumScore": minimum_score,
        "scoreNote": "Symmetric, additive ranking from existing scanner signals, cross-scanner agreement, directional momentum, relative volume, market/sector context and data freshness. Points are not calibrated win probabilities.",
        "sourceDataNote": "When source candles are stale or delayed, the ranking is for research only. Verify live data and entry conditions.",
        "stocks": selected,
    }

def _parse_pct(value: Any) -> float:
    return safe_float(str(value if value is not None else "0").replace("%", ""))


def _telegram_signature(rows: list[dict], category: str) -> str:
    normalized = []
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        if category == "GPT POWER": state = (row.get("type"), row.get("status"), bool(row.get("breakoutConfirmed")))
        elif category == "BRAHMĀSTRA": state = (row.get("type"), row.get("tier", "BRAHMASTRA"))
        elif category == "SPECIAL 10": state = (tuple(sorted(row.get("sources", []))), row.get("signal"))
        else: state = (tuple(row.get("sniperStrategies", [])), bool(row.get("mtfBullish")), bool(row.get("mtfBearish")))
        normalized.append((symbol, state))
    normalized.sort(key=lambda item: item[0])
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if normalized else "EMPTY"


def _telegram_price(value: Any) -> str:
    number = safe_float(value, 0.0)
    return f"₹{number:,.2f}" if number > 0 else "price N/A"


def _telegram_change(value: Any) -> str:
    return f"{_parse_pct(value):+.2f}%"


def build_telegram_messages(output: dict, now: dt.datetime) -> dict[str, tuple[str, list[dict]]]:
    """Build one consolidated Telegram message with all scanner categories."""
    gpt_all = [r for r in output.get("gptPowerStocks", []) if isinstance(r, dict)]
    leaders_all = [r for r in output.get("leaders", []) if isinstance(r, dict)]
    brahmastra_all = [r for r in leaders_all if r.get("tier") in ("BRAHMASTRA", "BRAHMĀSTRA")]
    breaker_all = [r for r in output.get("breakerStocks", []) if isinstance(r, dict)]
    quick_data = output.get("quickPicks", {}) if isinstance(output.get("quickPicks"), dict) else {}
    quick_all = [r for r in quick_data.get("stocks", []) if isinstance(r, dict)]
    sniper_data = output.get("sniperScanner", {}) if isinstance(output.get("sniperScanner"), dict) else {}
    sniper_all = [r for r in sniper_data.get("stocks", []) if isinstance(r, dict)]
    sniper = []
    for row in sniper_all:
        strategies = sniper_strategy_matches(row)
        if strategies:
            copy_row = dict(row)
            copy_row["sniperStrategies"] = strategies
            sniper.append(copy_row)
    sniper.sort(key=lambda row: (len(row.get("sniperStrategies", [])), safe_float(row.get("trendTemplateScore")), safe_float(row.get("rvol")), _parse_pct(row.get("pctChange"))), reverse=True)

    # Use the existing additive merge/rank function; do not alter stock scoring or selection.
    special_all = build_special10_candidates(gpt_all, brahmastra_all, breaker_all)
    stamp = now.astimezone(IST).strftime("%d %b %Y · %I:%M %p IST")
    freshness_values = [bool(r.get("sourceBarFresh", False)) for r in (quick_all + gpt_all + brahmastra_all + breaker_all)]
    fresh_count = sum(freshness_values)
    total_count = len(freshness_values)
    freshness_note = ("Source bars marked fresh" if total_count and fresh_count == total_count else
                      f"MIXED/DELAYED DATA: {fresh_count}/{total_count} checked candidates have fresh source bars" if fresh_count else
                      "LAST AVAILABLE DATA may be stale/delayed; verify live quotes before acting")
    lines = [f"<b>ORION · COMPLETE SCANNER REPORT</b> — {html_lib.escape(stamp)}",
             f"<i>{html_lib.escape(freshness_note)}. Scores are rankings, not win probabilities.</i>"]
    all_rows = []
    top_two_data = output.get("topTwoPicks", {}) if isinstance(output.get("topTwoPicks"), dict) else {}
    top_two = [r for r in top_two_data.get("stocks", []) if isinstance(r, dict)]
    lines.append(f"<b>TOP 2 TRADE CANDIDATES</b> ({len(top_two)} selected; threshold {safe_float(top_two_data.get('minimumScore'), 24.0):.0f} ranking points)")
    if top_two:
        for row in top_two[:2]:
            symbol = html_lib.escape(str(row.get("symbol", "—")))
            direction = html_lib.escape(str(row.get("direction", "WATCH")))
            sources = html_lib.escape(", ".join(row.get("sources", [])))
            reasons = html_lib.escape("; ".join(row.get("reasons", [])[:2]))
            price = _telegram_price(row.get("price"))
            change = _telegram_change(row.get("pctChange"))
            plan = row.get("entryPlan") if isinstance(row.get("entryPlan"), dict) else {}
            levels = ""
            if plan:
                items = []
                if plan.get("trigger") is not None: items.append(f"Trigger {_telegram_price(plan.get('trigger'))}")
                if plan.get("stop") is not None: items.append(f"Stop {_telegram_price(plan.get('stop'))}")
                if plan.get("target1") is not None: items.append(f"T1 {_telegram_price(plan.get('target1'))}")
                if items: levels = " | " + " · ".join(items)
            status = "FRESH" if row.get("sourceBarFresh") else "STALE / VERIFY LIVE"
            lines.append(f"• <b>#{row.get('rank', '—')} {symbol}</b> — {direction} | Rank {safe_float(row.get('score')):.1f}/100 | {price} ({change}) | {status} | Sources: {sources}{levels}")
            if reasons:
                lines.append(f"  <i>{reasons}</i>")
            all_rows.append(row)
    else:
        lines.append("• No candidate reached the minimum evidence threshold; no trade is forced.")

    def add_section(title, rows, limit, formatter):
        lines.append(f"<b>{html_lib.escape(title)}</b> ({len(rows)} candidate(s))")
        if not rows:
            lines.append("• No qualifying candidates in this scan")
            return
        for row in rows[:limit]:
            lines.append("• " + formatter(row))
            all_rows.append(row)

    def common(row):
        sym = html_lib.escape(str(row.get("symbol", "—")))
        price = _telegram_price(row.get("price"))
        change = _telegram_change(row.get("pctChange"))
        return f"<b>{sym}</b> {price} ({change})"

    add_section("QUICK PICKS", quick_all, 5, lambda r: common(r) + f" | {html_lib.escape(str(r.get('signal', r.get('status', 'WATCH'))))} | Score {safe_float(r.get('rankScore', r.get('powerScore'))):.0f}")
    add_section("GPT POWER", gpt_all, 5, lambda r: common(r) + f" | {html_lib.escape(str(r.get('type','')))} | Score {safe_float(r.get('powerScore')):.0f}/100 | {html_lib.escape(str(r.get('status','WATCH')))} | RVOL {safe_float(r.get('rvol')):.2f}×")
    add_section("BRAHMĀSTRA", brahmastra_all, 4, lambda r: common(r) + f" | {html_lib.escape(str(r.get('type','')))} | Score {safe_float(r.get('numScore', r.get('score'))):.0f}/7")
    add_section("SPECIAL 10", special_all, 5, lambda r: common(r) + f" | #{r.get('specialRank','—')} | overlap {r.get('commonCount',0)}/3 | {html_lib.escape(str(r.get('signal','WATCH')))}")
    add_section("SNIPER SCANNER", sniper, 4, lambda r: common(r) + f" | {html_lib.escape(', '.join(r.get('sniperStrategies', [])))} | Trend {safe_float(r.get('trendTemplateScore')):.0f}/8 | RVOL {safe_float(r.get('rvol')):.2f}×")
    add_section("BREAKER", breaker_all, 3, lambda r: common(r) + f" | {html_lib.escape(str(r.get('type', r.get('signal','WATCH'))))}")

    message = "\n".join(lines)
    # Telegram has a 4096-character limit. If needed, shrink category rows from the
    # least-priority sections, while retaining TOP 2 and every section heading.
    if len(message) > 3900:
        # Keep the report structure and top-two section intact; progressively remove
        # trailing candidates from the later sections until the message fits.
        removable = ["BREAKER", "SNIPER SCANNER", "SPECIAL 10", "BRAHMĀSTRA", "GPT POWER", "QUICK PICKS"]
        current = list(lines)
        for title in removable:
            if len("\n".join(current)) <= 3900:
                break
            heading_idx = next((i for i, line in enumerate(current) if line.startswith(f"<b>{title}</b> (")), None)
            if heading_idx is None:
                continue
            end_idx = next((i for i in range(heading_idx + 1, len(current)) if current[i].startswith("<b>") and "</b> (" in current[i]), len(current))
            block = current[heading_idx:end_idx]
            row_indices = [i for i in range(heading_idx + 1, end_idx) if current[i].startswith("• <b>")]
            while len("\n".join(current)) > 3900 and len(row_indices) > 1:
                remove_idx = row_indices.pop()
                current.pop(remove_idx)
                row_indices = [i - 1 if i > remove_idx else i for i in row_indices]
            if len("\n".join(current)) > 3900 and len(row_indices) == 1:
                remove_idx = row_indices[0]
                current[remove_idx] = "• Candidate list abbreviated to fit Telegram's single-message limit."
        message = "\n".join(current)
    if len(message) > 4096:
        # Very long symbol/source strings are uncommon; always preserve valid HTML and headings.
        message = message[:3900].rsplit("\n", 1)[0] + "\n<i>Details shortened to fit Telegram's single-message limit.</i>"
    return {"COMPLETE REPORT": (message, all_rows)}


def dispatch_telegram_updates(output: dict, previous_output: dict, now: dt.datetime) -> dict:
    """Send exactly one consolidated Telegram report per successful scan; no category spam."""
    previous_state = previous_output.get("telegramAlertState", {})
    previous_state = previous_state if isinstance(previous_state, dict) else {}
    new_state = dict(previous_state)
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram disabled: configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID repository secrets.")
        output["telegramAlertState"] = new_state
        return new_state
    sections = build_telegram_messages(output, now)
    section = sections.get("COMPLETE REPORT")
    if not section:
        print("Telegram COMPLETE REPORT: could not build message.")
        output["telegramAlertState"] = new_state
        return new_state
    message, rows = section
    signature = hashlib.sha256(message.encode("utf-8")).hexdigest()
    # Deliberately send once per scan, even when unchanged. This provides one full
    # consolidated notification on each workflow run and avoids silent duplicate suppression.
    if send_telegram_alert(message):
        new_state["COMPLETE REPORT"] = signature
        print(f"Telegram COMPLETE REPORT: one consolidated message sent; rows={len(rows)}; chars={len(message)}.")
    else:
        new_state["COMPLETE REPORT"] = previous_state.get("COMPLETE REPORT", "")
        print("Telegram COMPLETE REPORT: send failed; will retry next scan.")
    output["telegramAlertState"] = new_state
    return new_state

def main() -> None:
    now = dt.datetime.now(IST)
    if skip_scheduled_run_if_market_closed(now):
        return
    previous_scan_output = load_previous_scan_output("data.json")
    current_ist_time = now.strftime("%I:%M %p")
    global FNO_SYMBOLS, FNO_UNIVERSE_SOURCE, FNO_SYMBOL_SET, SYMBOLS, YF_SYMBOLS
    FNO_SYMBOLS, FNO_UNIVERSE_SOURCE = load_fno_symbols()
    FNO_SYMBOL_SET = set(FNO_SYMBOLS)
    SYMBOLS = list(dict.fromkeys(STATIC_SYMBOLS + FNO_SYMBOLS))
    YF_SYMBOLS = {symbol: f"{symbol}.NS" for symbol in SYMBOLS}

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
        # This membership check uses the stock-underlying eligibility list only. It does
        # NOT download or inspect option-chain prices, OI, strikes, premiums or Greeks.
        if power and m["symbol"] in FNO_SYMBOL_SET:
            power["fnoEligible"] = True
            power["scoreBreakdown"] = bull_parts if power["type"] == "CE" else bear_parts
            baselines = historical_rvol_curve(m["allIntraday"], dt.date.fromisoformat(m["sessionDate"]))
            confirmation_time = first_power_confirmation_time(m, power["type"], baselines)
            # Scoring/candidate selection are unchanged; only reconcile the displayed
            # confirmation state with the completed-candle audit.
            power = apply_confirmation_audit(power, confirmation_time)
            power["sectorStatus"] = f"{m['sector']} {'🔥 STRONG' if sector_strong else '• WATCH'}"
            power["relativeStrength"] = round(m["alphaNum"], 2)
            power["marketSessionDate"] = m["sessionDate"]
            power["lastSourceBarCloseAt"] = m["lastSourceBarCloseAt"]
            power["sourceBarAgeMinutes"] = m["sourceBarAgeMinutes"]
            power["sourceBarFresh"] = m["sourceBarFresh"]
            # A signal can be mathematically confirmed but still based on stale source data.
            # Preserve the signal for transparency and label it clearly in the UI.
            if not m["sourceBarFresh"]:
                power["dataWarning"] = "SOURCE CANDLE STALE — verify price before acting"
            else:
                power["dataWarning"] = "Yahoo Finance source; not guaranteed real-time"
            gpt_power_stocks.append(power)

    leaders: list[dict] = []
    for tier_name in ["BRAHMASTRA", "EXPLOSIVE", "STRONG", "SPURT", "SHORT ZONE"]:
        sorted_tier = sorted(buckets[tier_name], key=lambda x: (x["numScore"], x["numVol"], x["numFuel"], x["absChange"]), reverse=True)[:10]
        leaders.extend(sorted_tier)

    # Limit each symbol to its strongest directional record (identify_power_setup already returns one side).
    gpt_power_stocks.sort(key=lambda x: (x["powerScore"], x["rvol"], abs(float(x["pctChange"].replace("%", "")))), reverse=True)
    gpt_power_stocks = gpt_power_stocks[:POWER_MAX_CARDS]

    # BREAKER high-potential shortlist (maximum 10): exclude stale data and low-confluence rows.
    # Primary focus is confirmed PDH breakouts with 1.5x volume on the breakout candle and at
    # least 4/6 bullish rules. Include at most two bearish candidates, and only for confirmed
    # PDL breakdown + breakout-candle volume + at least 4/6 bearish rules. GPT/BRAHMASTRA logic
    # is not modified; BREAKER is a filtered, additive view over its own calculation.
    breaker_bull_candidates = []
    breaker_bear_candidates = []
    for m in snapshots:
        breaker = calculate_breaker_setup(m)
        if not breaker or not breaker.get("sourceBarFresh", False):
            continue
        breaker["fnoEligible"] = m["symbol"] in FNO_SYMBOL_SET
        if (breaker.get("pdhBreakoutConfirmed") and breaker.get("pdhBreakoutVolumeConfirmed")
                and int(breaker.get("bullScore", 0)) >= 4):
            breaker_bull_candidates.append(breaker)
        elif (breaker.get("pdlBreakdownConfirmed") and breaker.get("pdlBreakdownVolumeConfirmed")
              and int(breaker.get("bearScore", 0)) >= 4):
            breaker_bear_candidates.append(breaker)

    breaker_bull_candidates.sort(
        key=lambda x: (int(x.get("bullScore", 0)), bool(x.get("hasBuySignal", False)),
                       bool(x.get("rf15mBullAligned", False)), float(x.get("volumeMultiple", 0)),
                       abs(safe_float(x.get("pctChange", "0").replace("%", "")))), reverse=True)
    breaker_bear_candidates.sort(
        key=lambda x: (int(x.get("bearScore", 0)), bool(x.get("hasSellSignal", False)),
                       bool(x.get("rf15mBearAligned", False)), float(x.get("volumeMultiple", 0)),
                       abs(safe_float(x.get("pctChange", "0").replace("%", "")))), reverse=True)

    # Strong bullish setups dominate; bearish setups are capped at two of the ten slots.
    breaker_stocks = breaker_bull_candidates[:8] + breaker_bear_candidates[:2]
    if len(breaker_stocks) < 10:
        chosen = {str(x.get("symbol", "")).upper() for x in breaker_stocks}
        remaining_bulls = [x for x in breaker_bull_candidates[8:] if str(x.get("symbol", "")).upper() not in chosen]
        breaker_stocks.extend(remaining_bulls[:10 - len(breaker_stocks)])
    breaker_stocks = breaker_stocks[:10]

    # Additive sector dashboard output: prefer matching index-symbol data; if unavailable,
    # use same-session constituent proxies. This does not alter the existing signal lists.
    scan_session = max(session_dates) if session_dates else None
    sector_index_readings = download_sector_index_readings(now)
    sector_rankings, sector_sentiment = build_sector_rankings(
        snapshots, gpt_power_stocks, leaders, breaker_stocks,
        sector_index_readings=sector_index_readings,
        target_session=scan_session,
        now=now,
    )
    print("Sector data source counts: " + ", ".join(
        f"{method}={sum(1 for item in sector_rankings if item.get('method') == method)}"
        for method in ("index_quote", "stock_proxy", "unavailable")
    ))

    status = "SESSION DATA AVAILABLE" if scan_session == now.date().isoformat() else "LAST AVAILABLE SESSION DATA"
    source_bar_times = [m["lastSourceBarCloseAt"] for m in snapshots if m.get("lastSourceBarCloseAt")]
    latest_source_bar = max(source_bar_times) if source_bar_times else None
    stale_source_symbols = sum(1 for m in snapshots if not m.get("sourceBarFresh", False))

    # Publish completed-candle OHLC for the tracker, including symbols no longer in the top list.
    price_snapshots = []
    paper_cutoff = now.astimezone(IST).replace(hour=11, minute=0, second=0, microsecond=0)
    cutoff_passed = now.astimezone(IST) >= paper_cutoff
    for m in snapshots:
        today_frame = m.get("today", pd.DataFrame())
        if today_frame is None or today_frame.empty:
            continue
        # Paper-trade outcomes are evaluated only through the 11:00 IST cutoff candle.
        frame = today_frame
        if cutoff_passed:
            bar_close_times = frame.index + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES)
            frame = frame.loc[bar_close_times <= paper_cutoff]
        if frame.empty:
            continue
        last_row = frame.iloc[-1]
        candle_close_time = frame.index[-1] + pd.Timedelta(minutes=INTRADAY_INTERVAL_MINUTES)
        price_snapshots.append({
            "symbol": m["symbol"],
            "price": round(safe_float(last_row.get("Close")), 4),
            "open": round(safe_float(last_row.get("Open")), 4),
            "high": round(safe_float(last_row.get("High")), 4),
            "low": round(safe_float(last_row.get("Low")), 4),
            "candleTime": candle_close_time.isoformat(),
            # Source was refreshed for this scan even when the market-cutoff mark is 11:00.
            "sourceBarFresh": bool(m.get("sourceBarFresh", False)),
            "paperCutoffMark": bool(cutoff_passed),
            "fnoEligible": m["symbol"] in FNO_SYMBOL_SET,
        })

    # Keep existing GPT POWER list/scoring untouched; paper-test confirmed fresh breakouts/breakdowns only.
    fresh_session = bool(scan_session == now.date().isoformat())
    fresh_power = [x for x in gpt_power_stocks if x.get("fnoEligible") and x.get("sourceBarFresh")]
    paper_candidates = []
    paper_candidates.extend([x for x in fresh_power if x.get("type") == "CE" and x.get("breakoutConfirmed")][:3])
    paper_candidates.extend([x for x in fresh_power if x.get("type") == "PE" and x.get("breakoutConfirmed")][:2])
    previous_tracker = load_previous_paper_tracker("data.json")
    paper_tracker = make_paper_tracker(
        previous=previous_tracker,
        scan_id=now.isoformat(),
        scan_time=now.isoformat(),
        session_date=scan_session,
        candidates=paper_candidates,
        price_snapshots=price_snapshots,
        fresh_session=fresh_session,
    )

    # Canonical per-stock ATR-room metrics let every frontend tab use the same value.
    # Fuel is a remaining-range proxy, not a forecast or probability of reaching a target.
    stock_fuel_metrics = {}
    for m in snapshots:
        symbol = str(m.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        daily_atr = safe_float(m.get("context", {}).get("atr"), 0.0)
        range_used_pct = m.get("fuelDisplayUsedPct")
        fuel_value = m.get("fuelDisplayLeftPct") if daily_atr > 0 else None
        stock_fuel_metrics[symbol] = {
            "fuelLeftPct": round(safe_float(fuel_value), 1) if fuel_value is not None else None,
            "atrUsedPct": round(safe_float(range_used_pct), 1) if daily_atr > 0 and range_used_pct is not None else None,
            "dailyATR14": round(safe_float(m.get("fuelDailyAtr14")), 4) if safe_float(m.get("fuelDailyAtr14")) > 0 else None,
            "sessionRange": round(max(0.0, safe_float(m.get("highDay")) - safe_float(m.get("lowDay"))), 4),
            "trueRangeIncludingGap": round(safe_float(m.get("fuelTrueRange")), 4),
            "sector": m.get("sector", "General"),
            "asOf": m.get("lastSourceBarCloseAt"),
            "sourceBarFresh": bool(m.get("sourceBarFresh", False)),
            "sessionDate": m.get("sessionDate"),
            "available": bool(daily_atr > 0 and fuel_value is not None),
            "method": "100 - min(100, session true range including previous-close gap / prior 14-session daily ATR x 100)"
        }

    sniper_universe_memberships, sniper_universe_sources = build_sniper_universe_memberships()
    sniper_scanner = build_sniper_scanner_data(snapshots, now, sniper_universe_memberships, sniper_universe_sources)
    special10_stocks = build_special10_candidates(gpt_power_stocks, leaders, breaker_stocks)
    quick_picks = build_quick_picks(gpt_power_stocks, leaders, breaker_stocks, sniper_scanner, sector_rankings, stock_fuel_metrics, now)
    top_two_picks = build_top_two_trade_candidates(
        gpt_power_stocks, leaders, breaker_stocks, sniper_scanner, sector_rankings,
        sentiment, now,
    )
    print(f"Sniper Scanner: {sniper_scanner['stockCount']} symbols; fresh={sniper_scanner['freshRecordCount']}; market-cap metadata available={sniper_scanner['marketCapDataAvailable']}")
    print(f"ORION QUICK PICKS: {quick_picks['stockCount']} shown from {quick_picks['candidateCount']} unique candidates")
    print(f"ORION TOP 2: {top_two_picks['stockCount']} selected from {top_two_picks['candidateCount']} directional candidates")
    print("Sniper universes: " + ", ".join(f"{k}={len(v)}" for k, v in sniper_universe_memberships.items()))

    output = {
        "lastUpdated": current_ist_time,
        "scanGeneratedAt": now.isoformat(),
        "sessionDate": scan_session,
        "marketDataStatus": status,
        "dataSource": "Yahoo Finance via yfinance (no API key); NSE public F&O underlying list with public GitHub snapshot fallback",
        "latestCompleted5mBarCloseAt": latest_source_bar,
        "staleSourceSymbols": int(stale_source_symbols),
        "marketDataNote": "Free, no-key source configuration. Yahoo Finance may be delayed, incomplete or rate-limited; stale candles are flagged, not treated as live quotes. Verify quotes and order levels before trading.",
        "breadth": {"advances": int(advances), "declines": int(declines), "sentiment": sentiment},
        "sectorRankings": sector_rankings,
        "sectorSentiment": sector_sentiment,
        "stockFuelMetrics": stock_fuel_metrics,
        "sniperScanner": sniper_scanner,
        "special10Stocks": special10_stocks,
        "quickPicks": quick_picks,
        "topTwoPicks": top_two_picks,
        "fuelMetricNote": "Displayed fuel is an estimated remaining daily ATR-range allowance, calculated as 100 minus today's true range (including the previous-close gap) relative to the prior 14-session daily ATR; it is not a probability or directional forecast. Legacy internal fuel used by existing signal heuristic/ranking logic is preserved. Marked stale when source candles are stale.",
        "leaders": leaders,
        "gptPowerStocks": gpt_power_stocks,
        "breakerStocks": breaker_stocks,
        "paperTradeCandidates": paper_candidates,
        "priceSnapshots": price_snapshots,
        "paperTradeTracker": paper_tracker,
        "scanSummary": {
            "configuredSymbols": len(SYMBOLS), "symbolsWithData": len(snapshots),
            "staleSourceSymbols": int(stale_source_symbols),
            "universeSource": "existing symbol universe + current F&O underlyings",
            "fnoUniverseSource": FNO_UNIVERSE_SOURCE,
            "fnoEligibleSymbols": len(FNO_SYMBOL_SET),
            "fnoEligibleScanned": sum(1 for m in snapshots if m["symbol"] in FNO_SYMBOL_SET),
            "gptPowerFnoOnly": True,
            "legacySignals": len(leaders), "gptPowerCandidates": len(gpt_power_stocks),
            "breakerCandidates": len(breaker_stocks),
            "powerScoreMeaning": "Relative ranking score out of 100; not a probability or guaranteed prediction."
        }
    }

    # Send one consolidated Telegram report containing all scanner sections.
    dispatch_telegram_updates(output, previous_scan_output, now)

    # Write to a temporary sibling file and atomically replace data.json only after
    # serialization completes, preserving the last valid dashboard data on write errors.
    temp_output = "data.json.tmp"
    with open(temp_output, "w", encoding="utf-8") as f:
        json.dump(to_json_safe(output), f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    os.replace(temp_output, "data.json")

    print(f"F&O eligibility: {len(FNO_SYMBOL_SET)} symbols from {FNO_UNIVERSE_SOURCE}")
    print(f"Saved data.json: data={len(snapshots)}, legacy signals={len(leaders)}, GPT POWER F&O candidates={len(gpt_power_stocks)}")
    print(f"Session: {scan_session}; Status: {status}; Advances={advances}, Declines={declines}")


if __name__ == "__main__":
    main()
