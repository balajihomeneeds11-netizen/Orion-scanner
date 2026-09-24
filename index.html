import json
import datetime
import yfinance as yf
import pandas as pd
import numpy as np

# Expanded liquid NSE F&O universe
SYMBOLS = [
    # Index Heavies & Banks
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS",
    # IT Leaders
    "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
    # Auto & Metals
    "TATAMOTORS.NS", "MARUTI.NS", "M&M.NS", "TATASTEEL.NS", "JINDALSTEL.NS", "HINDALCO.NS",
    # High-Momentum Mid/Large F&O
    "BHARTIARTL.NS", "ASTRAL.NS", "VOLTAS.NS", "MANAPPURAM.NS", "PNBHOUSING.NS",
    "KFINTECH.NS", "NAM-INDIA.NS", "DIXON.NS", "POLYCAB.NS", "COFORGE.NS", "PERSISTENT.NS",
    "CANBK.NS", "FEDERALBNK.NS", "INDUSINDBK.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS",
    "SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "LTIM.NS", "LT.NS", "BEL.NS", "HAL.NS"
]

leaders = []
advances = 0
declines = 0

print("Scanning broad F&O universe across 7 Pillars...")

for sym in SYMBOLS:
    try:
        ticker = yf.Ticker(sym)
        df_daily = ticker.history(period="5d", interval="1d")
        df_intra = ticker.history(period="1d", interval="5m")

        if len(df_intra) < 2 or len(df_daily) < 2:
            continue

        last_bar = df_intra.iloc[-1]
        prev_bar = df_intra.iloc[-2]
        pdh = float(df_daily['High'].iloc[-2])

        clean_symbol = sym.replace(".NS", "")
        close = round(float(last_bar['Close']), 2)
        open_p = round(float(last_bar['Open']), 2)
        low_p = round(float(last_bar['Low']), 2)

        if close >= open_p:
            advances += 1
        else:
            declines += 1

        # Pillar Checks
        p1_liquidity = (close > 50) and (float(last_bar['Volume']) > 5000)
        
        avg_vol = df_intra['Volume'].mean()
        vol_x = round(float(last_bar['Volume'] / avg_vol), 1) if avg_vol > 0 else 1.0
        p2_volume = vol_x >= 2.5

        p3_orb = close >= float(df_intra['High'].iloc[0])

        cum_vol = df_intra['Volume'].cumsum()
        vwap = (df_intra['Volume'] * df_intra['Close']).cumsum() / cum_vol
        p4_vwap = close > float(vwap.iloc[-1])

        p5_pdh = close > pdh

        p6_follow = (close > open_p) and (close > float(prev_bar['High']))

        delta = df_intra['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi_val = round(float(rsi_series.iloc[-1]), 1) if not np.isnan(rsi_series.iloc[-1]) else 60.0
        p7_rsi = rsi_val >= 58.0

        pillars_passed = sum([p1_liquidity, p2_volume, p3_orb, p4_vwap, p5_pdh, p6_follow, p7_rsi])

        if pillars_passed >= 4:
            if pillars_passed >= 6 and vol_x >= 4.0:
                tier = "EXPLOSIVE"
            elif pillars_passed >= 5:
                tier = "STRONG"
            else:
                tier = "SPURT"

            strike_step = 50 if close >= 500 else (20 if close >= 200 else 10)
            atm_strike = int(round(close / strike_step) * strike_step)
            sl = low_p if low_p < close else round(close * 0.99, 2)
            t1 = round(close + ((close - sl) * 1.5), 2)

            leaders.append({
                "symbol": clean_symbol,
                "type": "CE",
                "tier": tier,
                "score": f"{pillars_passed}/7",
                "detectTime": datetime.datetime.now().strftime("%H:%M:%S"),
                "price": close,
                "pctChange": f"+{round(((close - open_p) / open_p) * 100, 2)}%",
                "volumeX": f"{vol_x}x",
                "strike": f"{atm_strike} CE",
                "premium": "₹--",
                "sl": sl,
                "t1": t1,
                "rsi": rsi_val
            })
    except Exception as e:
        print(f"Skipping {sym}: {e}")

leaders = sorted(leaders, key=lambda x: int(x['score'].split('/')[0]), reverse=True)

output = {
    "lastUpdated": datetime.datetime.now().strftime("%I:%M:%S %p"),
    "breadth": {
        "advances": advances,
        "declines": declines,
        "sentiment": "STRONG BULLISH" if advances > (declines * 1.5) else ("BULLISH" if advances >= declines else "BEARISH")
    },
    "leaders": leaders
}

with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Updated data.json with {len(leaders)} setups.")
