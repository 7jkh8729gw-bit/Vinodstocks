"""
Momentum/Breakout Screener with Telegram Alerts
-------------------------------------------------
Same breakout logic as before, but sends a Telegram message for every
new candidate found instead of (or in addition to) printing to console.

Reads secrets from environment variables so the token/chat ID are never
hardcoded in the file (safe for GitHub Actions or any cloud runner):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

Requirements:
    pip install yfinance pandas requests --break-system-packages
"""

import os
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime

# ---------------- CONFIG ----------------
TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL",
    "NFLX", "CRM", "AVGO", "COST", "SHOP", "PLTR", "SMCI"
]

BREAKOUT_LOOKBACK = 20
VOLUME_MULTIPLE = 2.0
MA_TREND_PERIOD = 50
LOOKBACK_DAYS = 120

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# -----------------------------------------


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set — skipping alert send.")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code != 200:
            print(f"Telegram send failed: {r.text}")
    except Exception as e:
        print(f"Telegram send error: {e}")


def fetch_data(ticker, period_days=LOOKBACK_DAYS):
    df = yf.download(ticker, period=f"{period_days}d", interval="1d", progress=False)
    if df.empty:
        return None
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def check_breakout(df):
    if df is None or len(df) < BREAKOUT_LOOKBACK + 1:
        return None

    df = df.copy()
    df["avg_vol_20"] = df["Volume"].rolling(20).mean()
    df["ma_trend"] = df["Close"].rolling(MA_TREND_PERIOD).mean()
    df["rolling_high"] = df["Close"].rolling(BREAKOUT_LOOKBACK).max().shift(1)

    latest = df.iloc[-1]
    if pd.isna(latest["ma_trend"]) or pd.isna(latest["rolling_high"]):
        return None

    breakout = latest["Close"] > latest["rolling_high"]
    volume_surge = latest["Volume"] >= VOLUME_MULTIPLE * latest["avg_vol_20"]
    above_trend = latest["Close"] > latest["ma_trend"]

    if breakout and volume_surge and above_trend:
        return {
            "close": round(latest["Close"], 2),
            "prior_high": round(latest["rolling_high"], 2),
            "volume_ratio": round(latest["Volume"] / latest["avg_vol_20"], 2),
            "pct_above_ma50": round((latest["Close"] / latest["ma_trend"] - 1) * 100, 2),
        }
    return None


def run_screener(tickers=TICKERS):
    hits = []
    for ticker in tickers:
        try:
            df = fetch_data(ticker)
            hit = check_breakout(df)
            if hit:
                hit["ticker"] = ticker
                hits.append(hit)
        except Exception as e:
            print(f"Skipping {ticker}: {e}")
    return hits


if __name__ == "__main__":
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    hits = run_screener()

    if not hits:
        print(f"[{now}] No breakout candidates found.")
    else:
        for h in hits:
            msg = (
                f"🚀 *Breakout Alert: {h['ticker']}*\n"
                f"Close: ${h['close']}\n"
                f"Broke above 20d high: ${h['prior_high']}\n"
                f"Volume: {h['volume_ratio']}x average\n"
                f"Above 50d MA by: {h['pct_above_ma50']}%\n"
                f"Time: {now}"
            )
            send_telegram_message(msg)
            print(msg)
