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
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as err:
        print(f"Telegram dispatch error: {err}")

# Sector Mapping
SECTOR_MAP = {
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking", "AXISBANK": "Banking",
    "KOTAKBANK": "Banking", "INDUSINDBK": "Banking", "FEDERALBNK": "Banking", "BANDHANBNK": "Banking",
    "IDFCFIRSTB": "Banking", "RBLBANK": "Banking", "AUBANK": "Banking", "BANKBARODA": "Banking",
    "CANBK": "Banking", "PNB": "Banking", "UNIONBANK": "Banking",
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT", "TECHM": "IT", "LTIM": "IT",
    "COFORGE": "IT", "PERSISTENT": "IT", "MPHASIS": "IT", "BSOFT": "IT", "OFSS": "IT", "NAUKRI": "IT",
    "TATAMOTORS": "Auto", "MARUTI": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto", "HEROMOTOCO": "Auto",
    "EICHERMOT": "Auto", "TVSMOTOR": "Auto", "ASHOKLEY": "Auto", "BHARATFORG": "Auto", "BALKRISIND": "Auto",
    "APOLLOTYRE": "Auto", "MRF": "Auto", "MOTHERSON": "Auto", "BOSCHLTD": "Auto", "EXIDEIND": "Auto",
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "IOC": "Energy", "HINDPETRO": "Energy",
    "GAIL": "Energy", "IGL": "Energy", "MGL": "Energy", "NTPC": "Energy", "POWERGRID": "Energy", "TATAPOWER": "Energy",
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "JINDALSTEL": "Metals", "SAIL": "Metals", "HINDALCO": "Metals",
    "VEDL": "Metals", "NATIONALUM": "Metals", "HINDCOPPER": "Metals", "NMDC": "Metals", "COALINDIA": "Metals",
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma", "DIVISLAB": "Pharma", "LUPIN": "Pharma",
    "AUROPHARMA": "Pharma", "ALKEM": "Pharma", "TORNTPHARM": "Pharma", "GLENMARK": "Pharma", "ZYDUSLIFE": "Pharma", "BIOCON": "Pharma",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG", "TATACONSUM": "FMCG", "DABUR": "FMCG", "MARICO": "FMCG", "GODREJCP": "FMCG", "COLPAL": "FMCG",
    "BAJFINANCE": "Finance", "BAJAJFINSV": "Finance", "CHOLAFIN": "Finance", "SHRIRAMFIN": "Finance", "MUTHOOTFIN": "Finance",
    "M&MFIN": "Finance", "LICHSGFIN": "Finance", "RECLTD": "Finance", "PFC": "Finance", "MANAPPURAM": "Finance", "PAYTM": "New Age",
    "LT": "Infra", "BEL": "Defense", "HAL": "Defense", "COCHINSHIP": "Industrials", "DIXON": "Durables", "POLYCAB": "Durables",
    "ASTRAL": "Industrials", "INDUSTOWER": "Telecom", "ANGELONE": "CapitalMkt", "INDHOTEL": "Hotels", "ICICIGI": "Finance"
}

LOT_SIZES = {
    "RELIANCE": 250, "HDFCBANK": 550, "ICICIBANK": 700, "SBIN": 750, "AXISBANK": 625, "KOTAKBANK": 400,
    "TCS": 175, "INFY": 400, "HCLTECH": 350, "WIPRO": 1500, "TECHM": 600, "LTIM": 150, "COFORGE": 150,
    "TATAMOTORS": 550, "MARUTI": 50, "M&M": 350, "TATASTEEL": 5500, "VEDL": 1150, "HINDALCO": 1400,
    "MANAPPURAM": 3000, "DIXON": 50, "COCHINSHIP": 350, "PAYTM": 500, "ONGC": 3850, "ASTRAL": 275,
    "INDUSTOWER": 1700, "MPHASIS": 275, "BHARTIARTL": 475, "BEL": 2850, "HAL": 150, "PNB": 8000,
    "ZYDUSLIFE": 900, "ANGELONE": 250, "INDHOTEL": 1000, "ICICIGI": 250
}

SYMBOLS = [
    "AARTIIND.NS", "ABB.NS", "ABBOTINDIA.NS", "ABCAPITAL.NS", "ABFRL.NS", "ACC.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "ALKEM.NS", "AMBUJACEM.NS", "ANGELONE.NS", "APOLLOHOSP.NS",
    "APOLLOTYRE.NS", "ASHOKLEY.NS", "ASIANPAINT.NS", "ASTRAL.NS", "ATUL.NS", "AUBANK.NS",
    "AUROPHARMA.NS", "AXISBANK.NS", "BAJAJ-AUTO.NS", "BAJAJFINSV.NS", "BAJFINANCE.NS",
    "BALKRISIND.NS", "BALRAMCHIN.NS", "BANDHANBNK.NS", "BANKBARODA.NS", "BATAINDIA.NS",
    "BEL.NS", "BERGEPAINT.NS", "BHARATFORG.NS", "BHEL.NS", "BPCL.NS", "BHARTIARTL.NS",
    "BIOCON.NS", "BSOFT.NS", "BOSCHLTD.NS", "BRITANNIA.NS", "CANFINHOME.NS", "CANBK.NS",
    "CHAMBLFERT.NS", "CHOLAFIN.NS", "CIPLA.NS", "COALINDIA.NS", "COFORGE.NS", "COLPAL.NS",
    "CONCOR.NS", "COROMANDEL.NS", "CROMPTON.NS", "CUMMINSIND.NS", "DABUR.NS", "DALBHARAT.NS",
    "DEEPAKNTR.NS", "DELTACORP.NS", "DIVISLAB.NS", "DIXON.NS", "DLF.NS", "DRREDDY.NS",
    "EICHERMOT.NS", "ESCORTS.NS", "EXIDEIND.NS", "FEDERALBNK.NS", "GAIL.NS", "GLENMARK.NS",
    "GMRINFRA.NS", "GNFC.NS", "GODREJCP.NS", "GODREJPROP.NS", "GRANULES.NS", "GRASIM.NS",
    "GUJGASLTD.NS", "HAL.NS", "HAVELLS.NS", "HCLTECH.NS", "HDFCAMC.NS", "HDFCBANK.NS",
    "HDFCLIFE.NS", "HEROMOTOCO.NS", "HINDALCO.NS", "HINDCOPPER.NS", "HINDPETRO.NS",
    "HINDUNILVR.NS", "ICICIBANK.NS", "ICICIGI.NS", "ICICIPRULI.NS", "IDFC.NS", "IDFCFIRSTB.NS",
    "IEX.NS", "IGL.NS", "INDHOTEL.NS", "INDIACEM.NS", "INDIAMART.NS", "INDIGO.NS",
    "INDUSINDBK.NS", "INDUSTOWER.NS", "INFY.NS", "IOC.NS", "IPCALAB.NS", "IRCTC.NS",
    "ITC.NS", "JINDALSTEL.NS", "JKCEMENT.NS", "JSWSTEEL.NS", "JUBLFOOD.NS", "KOTAKBANK.NS",
    "LALPATHLAB.NS", "LAURUSLABS.NS", "LICHSGFIN.NS", "LT.NS", "LTIM.NS", "LTF.NS",
    "LUPIN.NS", "M&M.NS", "M&MFIN.NS", "MANAPPURAM.NS", "MARICO.NS", "MARUTI.NS",
    "MCX.NS", "METROPOLIS.NS", "MFSL.NS", "MGL.NS", "MOTHERSON.NS", "MPHASIS.NS",
    "MRF.NS", "MUTHOOTFIN.NS", "NATIONALUM.NS", "NAUKRI.NS", "NAVINFLUOR.NS", "NESTLEIND.NS",
    "NMDC.NS", "NTPC.NS", "OBEROIRLTY.NS", "OFSS.NS", "ONGC.NS", "PAGEIND.NS",
    "PEL.NS", "PERSISTENT.NS", "PETRONET.NS", "PFC.NS", "PIDILITIND.NS", "PIIND.NS",
    "PNB.NS", "POLYCAB.NS", "POONAWALLA.NS", "POWERGRID.NS", "PVRINOX.NS", "RAMCOCEM.NS",
    "RBLBANK.NS", "RECLTD.NS", "RELIANCE.NS", "SAIL.NS", "SBICARD.NS", "SBILIFE.NS",
    "SBIN.NS", "SHREECEM.NS", "SHRIRAMFIN.NS", "SIEMENS.NS", "SRF.NS", "SUNPHARMA.NS",
    "SUNTV.NS", "SYNGENE.NS", "TATACHEM.NS", "TATACOMM.NS", "TATACONSUM.NS", "TATAMOTORS.NS",
    "TATAPOWER.NS", "TATASTEEL.NS", "TCS.NS", "TECHM.NS", "TITAN.NS", "TORNTPHARM.NS",
    "TRENT.NS", "TVSMOTOR.NS", "UBL.NS", "ULTRACEMCO.NS", "UNIONBANK.NS", "UPL.NS",
    "VEDL.NS", "VOLTAS.NS", "WIPRO.NS", "ZEEL.NS", "ZYDUSLIFE.NS"
]

# Track historical breakout detection times
TRIGGER_LOG_FILE = "trigger_timestamps.json"
trigger_cache = {}
if os.path.exists(TRIGGER_LOG_FILE):
    try:
        with open(TRIGGER_LOG_FILE, "r") as tf:
            trigger_cache = json.load(tf)
    except Exception:
        trigger_cache = {}

ist_now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
current_ist_time = ist_now.strftime("%I:%M %p")
today_date_str = ist_now.strftime("%Y-%m-%d")

if trigger_cache.get("date") != today_date_str:
    trigger_cache = {"date": today_date_str, "timestamps": {}}

leaders = []
advances = 0
declines = 0
sector_trends = {}

print(f"Scanning F&O universe at {current_ist_time} IST...")

try:
    data_daily = yf.download(SYMBOLS, period="1y", interval="1d", group_by="ticker", threads=True, progress=False)
    data_intra = yf.download(SYMBOLS, period="1d", interval="5m", group_by="ticker", threads=True, progress=False)
except Exception as e:
    print(f"Batch fetch error: {e}")
    data_daily = None
    data_intra = None

if data_intra is not None:
    for sym in SYMBOLS:
        try:
            df_i = data_intra[sym].dropna()
            if len(df_i) < 2:
                continue
            clean = sym.replace(".NS", "")
            sec = SECTOR_MAP.get(clean, "General")
            c = float(df_i['Close'].iloc[-1])
            o = float(df_i['Open'].iloc[0])
            chg = (c - o) / o
            if sec not in sector_trends:
                sector_trends[sec] = []
            sector_trends[sec].append(chg)
        except Exception:
            continue

for sym in SYMBOLS:
    try:
        if data_daily is None or data_intra is None:
            break
            
        df_d = data_daily[sym].dropna()
        df_i = data_intra[sym].dropna()

        if len(df_i) < 2 or len(df_d) < 2:
            continue

        last_bar = df_i.iloc[-1]
        prev_bar = df_i.iloc[-2]
        pdh = float(df_d['High'].iloc[-2])
        pdl = float(df_d['Low'].iloc[-2])
        high_52w = float(df_d['High'].max())

        clean_symbol = sym.replace(".NS", "")
        close = round(float(last_bar['Close']), 2)
        open_p = round(float(last_bar['Open']), 2)
        low_p = round(float(last_bar['Low']), 2)
        high_p = round(float(last_bar['High']), 2)
        open_day = round(float(df_i['Open'].iloc[0]), 2)
        low_day = round(float(df_i['Low'].min()), 2)
        high_day = round(float(df_i['High'].max()), 2)
        first_bar_close = round(float(df_i['Close'].iloc[0]), 2)

        pct_change = round(((close - open_day) / open_day) * 100, 2)
        if close >= open_day:
            advances += 1
        else:
            declines += 1

        avg_vol = df_i['Volume'].mean()
        vol_x = round(float(last_bar['Volume'] / avg_vol), 1) if avg_vol > 0 else 1.0

        cum_vol = df_i['Volume'].cumsum()
        vwap = (df_i['Volume'] * df_i['Close']).cumsum() / cum_vol
        vwap_val = float(vwap.iloc[-1])
        orb_high = float(df_i['High'].iloc[0])
        orb_low = float(df_i['Low'].iloc[0])

        delta = df_i['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi_val = round(float(rsi_series.iloc[-1]), 1) if not np.isnan(rsi_series.iloc[-1]) else 50.0

        body_pct = round(abs((first_bar_close - open_day) / open_day) * 100, 2)
        candle_quality = "Strong" if body_pct >= 0.8 else "Moderate"

        from_low = round(((close - low_day) / low_day) * 100, 2)
        from_high = round(((high_day - close) / high_day) * 100, 2)

        is_52w = close >= (high_52w * 0.985)

        sec_name = SECTOR_MAP.get(clean_symbol, "F&O")
        sec_changes = sector_trends.get(sec_name, [])
        sec_avg = (sum(sec_changes) / len(sec_changes)) if sec_changes else 0.0

        if pct_change >= 0:
            sector_status = f"{sec_name} • WEAK" if sec_avg < 0.001 else f"{sec_name} 🔥 STRONG"
        else:
            sector_status = f"{sec_name} • WEAK" if sec_avg > -0.001 else f"{sec_name} 🔥 STRONG"

        # 7-Pillars Core Alignment
        p1 = close > 50 and float(last_bar['Volume']) > 2000
        p2 = vol_x >= 1.5
        p3 = close > orb_high               # STRICT ORB BREAKOUT MANDATORY
        p4 = close > vwap_val               # STRICT ABOVE VWAP MANDATORY
        p5 = close > pdh                    # PDH BREAKOUT
        p6 = (close > open_p) and (close >= float(prev_bar['High']))
        p7 = rsi_val >= 58.0                # SOLID INTRADAY MOMENTUM
        bull_score = sum([p1, p2, p3, p4, p5, p6, p7])

        bear_score = sum([
            close < pdl,
            close < vwap_val,
            close < orb_low,
            vol_x >= 1.5,
            rsi_val <= 42.0,
            close < open_p
        ])

        tier = None
        card_type = "CE"

        # WEBINAR BRAHMASTRA CRITERIA:
        # 1. Volume Blast (vol_x >= 3.0x) OR Open=Low Drive (within 0.15% of low)
        # 2. MUST trade strictly above VWAP (p4)
        # 3. MUST be above Opening Range High (p3)
        # 4. Movement >= +0.60% (eliminates stationary stocks)
        is_bull_breakout = (close > orb_high) and (close > vwap_val) and (pct_change >= 0.60)
        opened_at_day_low = (abs(open_day - low_day) / open_day) <= 0.0015

        if is_bull_breakout and ((vol_x >= 3.0) or (opened_at_day_low and vol_x >= 1.5)) and bull_score >= 4:
            tier = "BRAHMASTRA"
        elif is_bull_breakout and (bull_score >= 5 or vol_x >= 2.5):
            tier = "EXPLOSIVE"
        elif is_bull_breakout and bull_score >= 4:
            tier = "STRONG"
        elif is_bull_breakout and bull_score >= 3:
            tier = "SPURT"
        elif (close < orb_low) and (close < vwap_val) and (bear_score >= 4 or pct_change <= -1.5):
            tier = "SHORT ZONE"
            card_type = "PE"

        if tier:
            strike_step = 50 if close >= 500 else (20 if close >= 200 else 10)
            target_strike = int(round(close / strike_step) * strike_step)
            strike_label = f"{target_strike} {card_type}"
            lot_qty = LOT_SIZES.get(clean_symbol, 250)

            # Record exact breakout detection time (Dynamic timestamp)
            if clean_symbol not in trigger_cache["timestamps"]:
                trigger_cache["timestamps"][clean_symbol] = current_ist_time
            actual_detect_time = trigger_cache["timestamps"][clean_symbol]

            sl = float(df_i['Low'].iloc[0]) if card_type == "CE" else float(df_i['High'].iloc[0])
            sl = round(sl, 2)
            t1 = round(close + ((close - sl) * 1.5), 2) if card_type == "CE" else round(close - ((sl - close) * 1.5), 2)
            watch_badge = "★★★ STRONG BUY WATCH" if card_type == "CE" else "★★★ STRONG SELL WATCH"

            card_data = {
                "symbol": clean_symbol,
                "type": card_type,
                "tier": tier,
                "optionTag": "⚡ OPTION",
                "score": f"{bull_score}/7" if card_type == "CE" else f"{bear_score}/6",
                "numScore": bull_score if card_type == "CE" else bear_score,
                "detectTime": actual_detect_time,
                "price": close,
                "pctChange": f"+{pct_change}%" if pct_change > 0 else f"{pct_change}%",
                "volumeX": f"{vol_x}x",
                "strike": strike_label,
                "lotSize": lot_qty,
                "sectorStatus": sector_status,
                "watchBadge": watch_badge,
                "candleInfo": f"gap +{pct_change}% • body {body_pct}% • {candle_quality} candle",
                "is52W": is_52w,
                "openedAtLow": opened_at_day_low,
                "sl": sl,
                "t1": t1,
                "rsi": rsi_val
            }

            leaders.append(card_data)

    except Exception:
        continue

# Save trigger timestamps
with open(TRIGGER_LOG_FILE, "w") as tf:
    json.dump(trigger_cache, tf, indent=2)

# Sort strictly: High Momentum and High Volume Surge first
tier_rank = {"BRAHMASTRA": 5, "EXPLOSIVE": 4, "STRONG": 3, "SPURT": 2, "SHORT ZONE": 1}
leaders = sorted(
    leaders,
    key=lambda x: (
        tier_rank.get(x['tier'], 0),
        float(x['volumeX'].replace('x', '')),
        abs(float(x['pctChange'].replace('%', '').replace('+', '')))
    ),
    reverse=True
)

# Cap the output to the top 15 highest-conviction leaders across the market
leaders = leaders[:15]

if leaders:
    top = leaders[0]
    if top['tier'] in ["BRAHMASTRA", "EXPLOSIVE"]:
        badge = "⚡ BRAHMASTRA HIGH MOMENTUM" if top['tier'] == "BRAHMASTRA" else "💥 EXPLOSIVE BREAKOUT"
        msg = (
            f"<b>{badge}</b>\n\n"
            f"🎯 <b>Stock:</b> #{top['symbol']} ({top['type']})\n"
            f"⚡ <b>Volume Surge:</b> {top['volumeX']}\n"
            f"💰 <b>LTP:</b> ₹{top['price']} ({top['pctChange']})\n"
            f"🕒 <b>Breakout Time:</b> {top['detectTime']}\n"
            f"🏢 <b>Sector:</b> {top['sectorStatus']}\n"
            f"🎯 <b>Strike:</b> {top['strike']} (Lot: {top['lotSize']})\n"
            f"🛑 <b>9:15 SL Law:</b> ₹{top['sl']} | <b>T1:</b> ₹{top['t1']}\n\n"
            f"🌐 <a href='https://balajihomeneeds11-netizen.github.io/Orion-scanner/'>Open Live Terminal</a>"
        )
        send_telegram_alert(msg)

output = {
    "lastUpdated": current_ist_time,
    "breadth": {
        "advances": advances,
        "declines": declines,
        "sentiment": "STRONG BULLISH" if advances > (declines * 1.5) else ("BULLISH" if advances >= declines else "BEARISH")
    },
    "leaders": leaders
}

with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Filter applied. Outputting {len(leaders)} high-conviction breakout setups.")
