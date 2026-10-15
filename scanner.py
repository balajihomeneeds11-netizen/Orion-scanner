
import os
import json
import datetime
import urllib.parse
import urllib.request

import yfinance as yf
import pandas as pd
import numpy as np


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }

        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data)

        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()

    except Exception as err:
        print(f"Telegram dispatch error: {err}")


def format_ist_time(ts):
    try:
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

        ts = pd.Timestamp(ts)

        if ts.tzinfo is not None:
            ist_ts = ts.tz_convert(ist)
        else:
            # Yahoo Finance intraday timestamps are generally timezone-aware.
            # Treat a naive timestamp as IST rather than adding 5:30 blindly.
            ist_ts = ts.tz_localize(ist)

        return ist_ts.strftime("%H:%M")

    except Exception:
        return "09:20"


# ---------------------------------------------------------
# JSON SERIALIZATION FIX
# Converts NumPy and Pandas objects to JSON-safe values.
# ---------------------------------------------------------

def json_safe(obj):
    if isinstance(obj, dict):
        return {
            str(k): json_safe(v)
            for k, v in obj.items()
        }

    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]

    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())

    if isinstance(obj, np.bool_):
        return bool(obj)

    if isinstance(obj, np.integer):
        return int(obj)

    if isinstance(obj, np.floating):
        value = float(obj)
        if not np.isfinite(value):
            return None
        return value

    if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
        return obj.isoformat()

    if obj is pd.NA or obj is pd.NaT:
        return None

    if isinstance(obj, float) and not np.isfinite(obj):
        return None

    return obj


def json_default(obj):
    """Fallback for NumPy/Pandas values encountered by json.dump."""
    if isinstance(obj, (np.bool_,)):
        return bool(obj)

    if isinstance(obj, np.integer):
        return int(obj)

    if isinstance(obj, np.floating):
        value = float(obj)
        if not np.isfinite(value):
            return None
        return value

    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())

    if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
        return obj.isoformat()

    if obj is pd.NA or obj is pd.NaT:
        return None

    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable"
    )


# ---------------------------------------------------------
# SECTOR MAP
# ---------------------------------------------------------

SECTOR_MAP = {
    "HDFCBANK": "Banking", "ICICIBANK": "Banking",
    "SBIN": "Banking", "AXISBANK": "Banking",
    "KOTAKBANK": "Banking", "INDUSINDBK": "Banking",
    "FEDERALBNK": "Banking", "BANDHANBNK": "Banking",
    "IDFCFIRSTB": "Banking", "RBLBANK": "Banking",
    "AUBANK": "Banking", "BANKBARODA": "Banking",
    "CANBK": "Banking", "PNB": "Banking",
    "UNIONBANK": "Banking",

    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT",
    "WIPRO": "IT", "TECHM": "IT", "LTIM": "IT",
    "COFORGE": "IT", "PERSISTENT": "IT",
    "MPHASIS": "IT", "BSOFT": "IT",
    "OFSS": "IT", "NAUKRI": "IT",

    "TATAMOTORS": "Auto", "MARUTI": "Auto",
    "M&M": "Auto", "BAJAJ-AUTO": "Auto",
    "HEROMOTOCO": "Auto", "EICHERMOT": "Auto",
    "TVSMOTOR": "Auto", "ASHOKLEY": "Auto",
    "BHARATFORG": "Auto", "BALKRISIND": "Auto",
    "APOLLOTYRE": "Auto", "MRF": "Auto",
    "MOTHERSON": "Auto", "BOSCHLTD": "Auto",
    "EXIDEIND": "Auto",

    "RELIANCE": "Energy", "ONGC": "Energy",
    "BPCL": "Energy", "IOC": "Energy",
    "HINDPETRO": "Energy", "GAIL": "Energy",
    "IGL": "Energy", "MGL": "Energy",
    "NTPC": "Energy", "POWERGRID": "Energy",
    "TATAPOWER": "Energy",

    "TATASTEEL": "Metals", "JSWSTEEL": "Metals",
    "JINDALSTEL": "Metals", "SAIL": "Metals",
    "HINDALCO": "Metals", "VEDL": "Metals",
    "NATIONALUM": "Metals", "HINDCOPPER": "Metals",
    "NMDC": "Metals", "COALINDIA": "Metals",

    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma",
    "CIPLA": "Pharma", "DIVISLAB": "Pharma",
    "LUPIN": "Pharma", "AUROPHARMA": "Pharma",
    "ALKEM": "Pharma", "TORNTPHARM": "Pharma",
    "GLENMARK": "Pharma", "ZYDUSLIFE": "Pharma",
    "BIOCON": "Pharma",

    "HINDUNILVR": "FMCG", "ITC": "FMCG",
    "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG", "DABUR": "FMCG",
    "MARICO": "FMCG", "GODREJCP": "FMCG",
    "COLPAL": "FMCG",

    "BAJFINANCE": "Finance", "BAJAJFINSV": "Finance",
    "CHOLAFIN": "Finance", "SHRIRAMFIN": "Finance",
    "MUTHOOTFIN": "Finance", "M&MFIN": "Finance",
    "LICHSGFIN": "Finance", "RECLTD": "Finance",
    "PFC": "Finance", "MANAPPURAM": "Finance",
    "PAYTM": "New Age",

    "LT": "Infra", "BEL": "Defense", "HAL": "Defense",
    "COCHINSHIP": "Industrials", "DIXON": "Durables",
    "POLYCAB": "Durables", "ASTRAL": "Industrials",
    "INDUSTOWER": "Telecom", "ANGELONE": "CapitalMkt",
    "INDHOTEL": "Hotels", "ICICIGI": "Finance"
}


# ---------------------------------------------------------
# LOT SIZES
# ---------------------------------------------------------

LOT_SIZES = {
    "RELIANCE": 250, "HDFCBANK": 550,
    "ICICIBANK": 700, "SBIN": 750,
    "AXISBANK": 625, "KOTAKBANK": 400,
    "TCS": 175, "INFY": 400, "HCLTECH": 350,
    "WIPRO": 1500, "TECHM": 600, "LTIM": 150,
    "COFORGE": 150, "TATAMOTORS": 550,
    "MARUTI": 50, "M&M": 350, "TATASTEEL": 5500,
    "VEDL": 1150, "HINDALCO": 1400,
    "MANAPPURAM": 3000, "DIXON": 50,
    "COCHINSHIP": 350, "PAYTM": 500,
    "ONGC": 3850, "ASTRAL": 275,
    "INDUSTOWER": 1700, "MPHASIS": 275,
    "BHARTIARTL": 475, "BEL": 2850, "HAL": 150,
    "PNB": 8000, "ZYDUSLIFE": 900,
    "ANGELONE": 250, "INDHOTEL": 1000,
    "ICICIGI": 250
}


# ---------------------------------------------------------
# NSE SYMBOLS
# ---------------------------------------------------------

SYMBOLS = [
    "AARTIIND.NS", "ABB.NS", "ABBOTINDIA.NS",
    "ABCAPITAL.NS", "ABFRL.NS", "ACC.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "ALKEM.NS",
    "AMBUJACEM.NS", "ANGELONE.NS", "APOLLOHOSP.NS",
    "APOLLOTYRE.NS", "ASHOKLEY.NS", "ASIANPAINT.NS",
    "ASTRAL.NS", "ATUL.NS", "AUBANK.NS",
    "AUROPHARMA.NS", "AXISBANK.NS", "BAJAJ-AUTO.NS",
    "BAJAJFINSV.NS", "BAJFINANCE.NS", "BALKRISIND.NS",
    "BALRAMCHIN.NS", "BANDHANBNK.NS", "BANKBARODA.NS",
    "BATAINDIA.NS", "BEL.NS", "BERGEPAINT.NS",
    "BHARATFORG.NS", "BHEL.NS", "BPCL.NS",
    "BHARTIARTL.NS", "BIOCON.NS", "BSOFT.NS",
    "BOSCHLTD.NS", "BRITANNIA.NS", "CANFINHOME.NS",
    "CANBK.NS", "CHAMBLFERT.NS", "CHOLAFIN.NS",
    "CIPLA.NS", "COALINDIA.NS", "COFORGE.NS",
    "COLPAL.NS", "CONCOR.NS", "COROMANDEL.NS",
    "CROMPTON.NS", "CUMMINSIND.NS", "DABUR.NS",
    "DALBHARAT.NS", "DEEPAKNTR.NS", "DELTACORP.NS",
    "DIVISLAB.NS", "DIXON.NS", "DLF.NS",
    "DRREDDY.NS", "EICHERMOT.NS", "ESCORTS.NS",
    "EXIDEIND.NS", "FEDERALBNK.NS", "GAIL.NS",
    "GLENMARK.NS", "GMRINFRA.NS", "GNFC.NS",
    "GODREJCP.NS", "GODREJPROP.NS", "GRANULES.NS",
    "GRASIM.NS", "GUJGASLTD.NS", "HAL.NS",
    "HAVELLS.NS", "HCLTECH.NS", "HDFCAMC.NS",
    "HDFCBANK.NS", "HDFCLIFE.NS", "HEROMOTOCO.NS",
    "HINDALCO.NS", "HINDCOPPER.NS", "HINDPETRO.NS",
    "HINDUNILVR.NS", "ICICIBANK.NS", "ICICIGI.NS",
    "ICICIPRULI.NS", "IDFC.NS", "IDFCFIRSTB.NS",
    "IEX.NS", "IGL.NS", "INDHOTEL.NS",
    "INDIACEM.NS", "INDIAMART.NS", "INDIGO.NS",
    "INDUSINDBK.NS", "INDUSTOWER.NS", "INFY.NS",
    "IOC.NS", "IPCALAB.NS", "IRCTC.NS",
    "ITC.NS", "JINDALSTEL.NS", "JKCEMENT.NS",
    "JSWSTEEL.NS", "JUBLFOOD.NS", "KOTAKBANK.NS",
    "LALPATHLAB.NS", "LAURUSLABS.NS", "LICHSGFIN.NS",
    "LT.NS", "LTIM.NS", "LTF.NS", "LUPIN.NS",
    "M&M.NS", "M&MFIN.NS", "MANAPPURAM.NS",
    "MARICO.NS", "MARUTI.NS", "MCX.NS",
    "METROPOLIS.NS", "MFSL.NS", "MGL.NS",
    "MOTHERSON.NS", "MPHASIS.NS", "MRF.NS",
    "MUTHOOTFIN.NS", "NATIONALUM.NS", "NAUKRI.NS",
    "NAVINFLUOR.NS", "NESTLEIND.NS", "NMDC.NS",
    "NTPC.NS", "OBEROIRLTY.NS", "OFSS.NS",
    "ONGC.NS", "PAGEIND.NS", "PEL.NS",
    "PERSISTENT.NS", "PETRONET.NS", "PFC.NS",
    "PIDILITIND.NS", "PIIND.NS", "PNB.NS",
    "POLYCAB.NS", "POONAWALLA.NS", "POWERGRID.NS",
    "PVRINOX.NS", "RAMCOCEM.NS", "RBLBANK.NS",
    "RECLTD.NS", "RELIANCE.NS", "SAIL.NS",
    "SBICARD.NS", "SBILIFE.NS", "SBIN.NS",
    "SHREECEM.NS", "SHRIRAMFIN.NS", "SIEMENS.NS",
    "SRF.NS", "SUNPHARMA.NS", "SUNTV.NS",
    "SYNGENE.NS", "TATACHEM.NS", "TATACOMM.NS",
    "TATACONSUM.NS", "TATAMOTORS.NS", "TATAPOWER.NS",
    "TATASTEEL.NS", "TCS.NS", "TECHM.NS",
    "TITAN.NS", "TORNTPHARM.NS", "TRENT.NS",
    "TVSMOTOR.NS", "UBL.NS", "ULTRACEMCO.NS",
    "UNIONBANK.NS", "UPL.NS", "VEDL.NS",
    "VOLTAS.NS", "WIPRO.NS", "ZEEL.NS",
    "ZYDUSLIFE.NS"
]


# ---------------------------------------------------------
# INITIALIZATION
# ---------------------------------------------------------

ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
ist_now = datetime.datetime.now(datetime.timezone.utc).astimezone(ist)
current_ist_time = ist_now.strftime("%I:%M %p")

advances = 0
declines = 0
sector_trends = {}

buckets = {
    "BRAHMASTRA": [],
    "EXPLOSIVE": [],
    "STRONG": [],
    "SPURT": [],
    "SHORT ZONE": []
}

print(
    f"Downloading market data for {len(SYMBOLS)} "
    f"tickers at {current_ist_time} IST..."
)


# ---------------------------------------------------------
# NIFTY DAILY CHANGE
# ---------------------------------------------------------

nifty_chg = 0.0

try:
    nifty_d = yf.download(
        "^NSEI",
        period="5d",
        interval="1d",
        progress=False,
        multi_level_index=False
    )

    if nifty_d is not None and not nifty_d.empty and len(nifty_d) >= 2:
        previous_nifty_close = float(nifty_d["Close"].iloc[-2])
        current_nifty_close = float(nifty_d["Close"].iloc[-1])

        if previous_nifty_close != 0:
            nifty_chg = (
                (current_nifty_close - previous_nifty_close)
                / previous_nifty_close
            ) * 100

except Exception as err:
    print(f"Nifty download error: {err}")


# ---------------------------------------------------------
# MAIN SCANNER
# ---------------------------------------------------------

for sym in SYMBOLS:
    try:
        clean = sym.replace(".NS", "")

        df_d = yf.download(
            sym,
            period="1y",
            interval="1d",
            progress=False,
            multi_level_index=False
        )

        df_i = yf.download(
            sym,
            period="1d",
            interval="5m",
            progress=False,
            multi_level_index=False
        )

        if (
            df_d is None
            or df_i is None
            or df_i.empty
            or df_d.empty
            or len(df_i) < 2
            or len(df_d) < 14
        ):
            continue

        required_columns = {"Open", "High", "Low", "Close", "Volume"}

        if not required_columns.issubset(df_d.columns):
            print(f"{clean}: Missing daily columns")
            continue

        if not required_columns.issubset(df_i.columns):
            print(f"{clean}: Missing intraday columns")
            continue

        sec = SECTOR_MAP.get(clean, "General")

        c = float(df_i["Close"].iloc[-1])
        o = float(df_i["Open"].iloc[0])

        if o == 0:
            continue

        chg = (c - o) / o

        if sec not in sector_trends:
            sector_trends[sec] = []

        sector_trends[sec].append(chg)

        last_bar = df_i.iloc[-1]

        prev_close = float(df_d["Close"].iloc[-2])
        prev_open = float(df_d["Open"].iloc[-2])
        pdh = float(df_d["High"].iloc[-2])
        pdl = float(df_d["Low"].iloc[-2])
        high_52w = float(df_d["High"].max())

        # CPR
        cpr_h = float(df_d["High"].iloc[-2])
        cpr_l = float(df_d["Low"].iloc[-2])
        cpr_c = float(df_d["Close"].iloc[-2])

        pivot = (cpr_h + cpr_l + cpr_c) / 3.0
        bc = (cpr_h + cpr_l) / 2.0
        tc = (pivot - bc) + pivot

        cpr_width_pct = (
            round((abs(tc - bc) / pivot) * 100, 3)
            if pivot > 0 else 0.1
        )

        is_narrow_cpr = bool(cpr_width_pct <= 0.18)

        # NR7
        recent_ranges = (
            df_d["High"] - df_d["Low"]
        ).iloc[-8:-1]

        yesterday_range = (
            float(recent_ranges.iloc[-1])
            if len(recent_ranges) > 0 else 0.0
        )

        is_nr7 = bool(
            yesterday_range <= float(recent_ranges.min())
            if len(recent_ranges) > 0 else False
        )

        # ATR
        tr = pd.concat(
            [
                df_d["High"] - df_d["Low"],
                (df_d["High"] - df_d["Close"].shift()).abs(),
                (df_d["Low"] - df_d["Close"].shift()).abs()
            ],
            axis=1
        ).max(axis=1)

        atr14 = (
            float(tr.rolling(14).mean().iloc[-1])
            if len(tr) >= 14 else 1.0
        )

        if not np.isfinite(atr14) or atr14 <= 0:
            atr14 = 1.0

        # Intraday prices
        close = round(float(last_bar["Close"]), 2)
        open_day = round(float(df_i["Open"].iloc[0]), 2)
        low_day = round(float(df_i["Low"].min()), 2)
        high_day = round(float(df_i["High"].max()), 2)

        first_bar_close = round(float(df_i["Close"].iloc[0]), 2)

        if open_day == 0 or low_day <= 0 or high_day <= 0:
            continue

        today_range = high_day - low_day

        atr_used_pct = round((today_range / atr14) * 100, 1)
        fuel_left_pct = max(0, round(100.0 - atr_used_pct, 1))

        pct_change = round(
            ((close - prev_close) / prev_close) * 100, 2
        ) if prev_close != 0 else 0.0

        prev_day_bullish = bool(
            ((prev_close - prev_open) / prev_open) >= 0.008
            if prev_open != 0 else False
        )

        if pct_change >= 0:
            advances += 1
        else:
            declines += 1

        # Volume
        avg_vol = float(df_i["Volume"].mean())

        cur_vol_x = (
            round(float(last_bar["Volume"]) / avg_vol, 2)
            if avg_vol > 0 else 1.0
        )

        morning_bars = df_i.iloc[:min(12, len(df_i))]

        peak_vol_x = (
            round(float(morning_bars["Volume"].max()) / avg_vol, 2)
            if avg_vol > 0 else 1.0
        )

        vol_x = max(cur_vol_x, peak_vol_x)

        # VWAP
        cum_vol = df_i["Volume"].cumsum()

        vwap = (
            (df_i["Volume"] * df_i["Close"]).cumsum()
            / cum_vol.replace(0, np.nan)
        )

        vwap_val = float(vwap.iloc[-1])

        if not np.isfinite(vwap_val):
            vwap_val = close

        # Opening range
        orb_high = float(df_i["High"].iloc[0])
        orb_low = float(df_i["Low"].iloc[0])

        detect_time_str = format_ist_time(df_i.index[0])

        if close >= open_day:
            bo_bars = df_i[df_i["High"] > orb_high]

            if len(bo_bars) > 0:
                detect_time_str = format_ist_time(bo_bars.index[0])
            else:
                max_v_idx = morning_bars["Volume"].idxmax()
                detect_time_str = format_ist_time(max_v_idx)

        else:
            bd_bars = df_i[df_i["Low"] < orb_low]

            if len(bd_bars) > 0:
                detect_time_str = format_ist_time(bd_bars.index[0])

        # RSI
        delta = df_i["Close"].diff()

        gain = (
            delta.where(delta > 0, 0)
            .rolling(14)
            .mean()
        )

        loss = (
            (-delta.where(delta < 0, 0))
            .rolling(14)
            .mean()
        )

        rs = gain / loss.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))

        rsi_last = rsi_series.iloc[-1]

        rsi_val = (
            round(float(rsi_last), 1)
            if pd.notna(rsi_last) and np.isfinite(float(rsi_last))
            else 50.0
        )

        # Candle quality
        body_pct = round(
            abs((first_bar_close - open_day) / open_day) * 100, 2
        )

        candle_quality = (
            "Strong" if body_pct >= 0.6 else "Moderate"
        )

        from_low = round(
            ((close - low_day) / low_day) * 100, 2
        )

        from_high = round(
            ((high_day - close) / high_day) * 100, 2
        )

        is_52w = bool(close >= (high_52w * 0.985))

        intraday_alpha = round(pct_change - nifty_chg, 2)

        # Sector strength
        sec_name = SECTOR_MAP.get(clean, "F&O")
        sec_changes = sector_trends.get(sec_name, [])

        sec_avg = (
            sum(sec_changes) / len(sec_changes)
            if sec_changes else 0.0
        )

        sector_strong = bool(
            (pct_change >= 0 and sec_avg > 0.0015)
            or (pct_change < 0 and sec_avg < -0.0015)
        )

        sector_status = (
            f"{sec_name} 🔥 STRONG"
            if sector_strong
            else f"{sec_name} • WATCH"
        )

        # Bullish pillars
        p1 = bool(close > open_day and pct_change > 0)
        p2 = bool(close > vwap_val)
        p3 = bool(close > pdh)
        p4 = bool(close > orb_high)
        p5 = bool(from_high <= 0.65)
        p6 = bool(vol_x >= 1.5)
        p7 = bool(rsi_val >= 56.0)

        bull_score = sum([p1, p2, p3, p4, p5, p6, p7])

        # Bearish pillars
        b1 = bool(close < open_day and pct_change < 0)
        b2 = bool(close < vwap_val)
        b3 = bool(close < pdl)
        b4 = bool(close < orb_low)
        b5 = bool(from_low <= 0.65)
        b6 = bool(vol_x >= 1.5)
        b7 = bool(rsi_val <= 44.0)

        bear_score = sum([b1, b2, b3, b4, b5, b6, b7])

        opened_at_day_low = bool(
            (abs(open_day - low_day) / open_day) <= 0.0020
            and close > open_day
        )

        is_ideal = False
        tier = None
        card_type = "CE"

        # -------------------------------------------------
        # SIGNAL CLASSIFICATION
        # -------------------------------------------------

        if (
            (
                opened_at_day_low
                and close > vwap_val
                and pct_change >= 0.8
            )
            or (
                close > orb_high
                and close > vwap_val
                and vol_x >= 3.2
                and bull_score >= 5
            )
        ):
            tier = "BRAHMASTRA"
            card_type = "CE"

        elif (
            (
                close > orb_high
                and close > vwap_val
                and bull_score >= 5
                and pct_change >= 1.0
            )
            or (
                is_52w
                and close > orb_high
                and pct_change >= 0.8
            )
        ):
            tier = "EXPLOSIVE"
            card_type = "CE"

            if bull_score >= 6 and sector_strong:
                is_ideal = True

        elif (
            close > vwap_val
            and bull_score >= 4
            and pct_change >= 0.5
        ):
            tier = "STRONG"
            card_type = "CE"

        elif (
            close < vwap_val
            and close < orb_low
            and (bear_score >= 5 or pct_change <= -1.8)
        ):
            tier = "SHORT ZONE"
            card_type = "PE"

        elif (
            close < vwap_val
            and bear_score >= 4
            and pct_change <= -0.8
        ):
            tier = "STRONG"
            card_type = "PE"

        elif (
            bull_score >= 3
            and pct_change >= 0.35
            and vol_x >= 1.3
        ):
            tier = "SPURT"
            card_type = "CE"

        elif (
            bear_score >= 3
            and pct_change <= -0.50
            and vol_x >= 1.3
        ):
            tier = "SPURT"
            card_type = "PE"

        # -------------------------------------------------
        # BUILD SIGNAL CARD
        # -------------------------------------------------

        if tier:
            strike_step = (
                50 if close >= 500
                else (20 if close >= 200 else 10)
            )

            target_strike = int(
                round(close / strike_step) * strike_step
            )

            strike_label = f"{target_strike} {card_type}"

            lot_qty = LOT_SIZES.get(clean, 250)

            sl = (
                round(float(df_i["Low"].iloc[0]), 2)
                if card_type == "CE"
                else round(float(df_i["High"].iloc[0]), 2)
            )

            risk = (
                abs(close - sl)
                if abs(close - sl) > 0
                else close * 0.008
            )

            t1 = (
                round(close + (risk * 1.5), 2)
                if card_type == "CE"
                else round(close - (risk * 1.5), 2)
            )

            if tier == "SPURT":
                watch_badge = "★★ MODERATE WATCH"
            else:
                watch_badge = (
                    "★★★ STRONG BUY WATCH"
                    if card_type == "CE"
                    else "★★★ STRONG SELL WATCH"
                )

            score_val = (
                bull_score if card_type == "CE" else bear_score
            )

            is_rally = bool(
                card_type == "CE"
                and (
                    pct_change >= 1.5
                    or (
                        p3
                        and p2
                        and from_high <= 0.45
                        and (prev_day_bullish or sector_strong)
                    )
                )
            )

            is_drop = bool(
                card_type == "PE"
                and (
                    pct_change <= -1.2
                    or (
                        b3
                        and b2
                        and from_low <= 0.45
                    )
                )
            )

            fade_risk = bool(
                card_type == "CE" and from_high >= 0.85
            )

            prob_score = min(
                96,
                52
                + (score_val * 4)
                + (5 if is_narrow_cpr else 0)
                + (5 if is_nr7 else 0)
                + (4 if fuel_left_pct >= 65 else 0)
                + (4 if sector_strong else 0)
                + (3 if (is_rally or is_drop) else 0)
            )

            if card_type == "CE":
                pillars_list = [
                    {"name": "Trend", "ok": bool(p1)},
                    {"name": "VWAP", "ok": bool(p2)},
                    {"name": "PDH", "ok": bool(p3)},
                    {"name": "ORB", "ok": bool(p4)},
                    {"name": "Follow", "ok": bool(p5)},
                    {"name": "Vol", "ok": bool(p6)},
                    {"name": "RSI", "ok": bool(p7)}
                ]

            else:
                pillars_list = [
                    {"name": "Trend", "ok": bool(b1)},
                    {"name": "VWAP", "ok": bool(b2)},
                    {"name": "PDL", "ok": bool(b3)},
                    {"name": "ORB", "ok": bool(b4)},
                    {"name": "Follow", "ok": bool(b5)},
                    {"name": "Vol", "ok": bool(b6)},
                    {"name": "RSI", "ok": bool(b7)}
                ]

            card_data = {
                "symbol": clean,
                "type": card_type,
                "tier": tier,
                "optionTag": "⚡ OPTION",
                "score": f"{score_val}/7",
                "numScore": int(score_val),
                "prob": f"{prob_score}%",
                "detectTime": detect_time_str,
                "price": float(close),
                "pctChange": (
                    f"+{pct_change}%"
                    if pct_change > 0
                    else f"{pct_change}%"
                ),
                "absChange": float(abs(pct_change)),
                "volumeX": f"{vol_x}x",
                "numVol": float(vol_x),
                "strike": strike_label,
                "lotSize": int(lot_qty),
                "sectorStatus": sector_status,
                "watchBadge": watch_badge,
                "candleInfo": (
                    f"body {body_pct}% • "
                    f"low ▲{from_low}% • high ▼{from_high}%"
                ),
                "is52W": bool(is_52w),
                "isIdeal": bool(is_ideal),
                "isRally": bool(is_rally),
                "isDrop": bool(is_drop),
                "fadeRisk": bool(fade_risk),
                "openedAtLow": bool(opened_at_day_low),
                "isNarrowCPR": bool(is_narrow_cpr),
                "isNR7": bool(is_nr7),
                "fuelLeft": f"{fuel_left_pct}%",
                "numFuel": float(fuel_left_pct),
                "alpha": (
                    f"+{intraday_alpha}%"
                    if intraday_alpha > 0
                    else f"{intraday_alpha}%"
                ),
                "pillars": pillars_list,
                "sl": float(sl),
                "t1": float(t1),
                "rsi": float(rsi_val)
            }

            buckets[tier].append(card_data)

    except Exception as err:
        # Log the ticker and exception instead of silently hiding failures.
        print(f"ERROR scanning {sym}: {type(err).__name__}: {err}")
        continue


# ---------------------------------------------------------
# RANK LEADERS
# ---------------------------------------------------------

leaders = []

for tier_name in [
    "BRAHMASTRA",
    "EXPLOSIVE",
    "STRONG",
    "SPURT",
    "SHORT ZONE"
]:
    sorted_tier = sorted(
        buckets[tier_name],
        key=lambda x: (
            x["numScore"],
            x["numVol"],
            x["numFuel"],
            x["absChange"]
        ),
        reverse=True
    )[:10]

    leaders.extend(sorted_tier)


# ---------------------------------------------------------
# MARKET BREADTH
# ---------------------------------------------------------

if advances > (declines * 1.5):
    sentiment = "STRONG BULLISH"
elif advances >= declines:
    sentiment = "BULLISH"
else:
    sentiment = "BEARISH"


output = {
    "lastUpdated": current_ist_time,
    "breadth": {
        "advances": int(advances),
        "declines": int(declines),
        "sentiment": sentiment
    },
    "leaders": leaders
}


# ---------------------------------------------------------
# SAVE JSON - FIXED
# ---------------------------------------------------------

try:
    safe_output = json_safe(output)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(
            safe_output,
            f,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
            default=json_default
        )

    print("JSON file saved successfully: data.json")
    print(f"Stocks scanned into leaders: {len(leaders)}")
    print(f"Advances: {advances} | Declines: {declines}")
    print("Scan completed successfully.")

except Exception as err:
    print(
        f"FATAL JSON OUTPUT ERROR: "
        f"{type(err).__name__}: {err}"
    )
    raise
