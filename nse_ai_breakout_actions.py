"""
NSE AI BREAKOUT BOT V2
======================
Complete replacement for the previous Render/Flask-based screener.

What V2 does:
1. Scans the broad NSE equity universe.
2. Applies the user's core trend/liquidity/52-week-high filters.
3. Builds a morning candidate list from daily OHLCV data.
4. Detects bullish daily-chart structures:
   - Golden Cross / bullish EMA alignment
   - Double Bottom
   - Higher High / Higher Low
   - Bullish Engulfing
   - Hammer
   - Morning Star
   - 3 White Soldiers
   - MACD bullish crossover
   - RSI strength
   - OBV accumulation
   - Near-breakout / breakout
5. Searches Google News RSS for recent stock-specific headlines and
   estimates catalyst sentiment using a transparent keyword model.
6. Creates a composite AI-style score (rules + weighted evidence).
7. Before market: sends the ranked morning watchlist to Telegram.
8. During market: continuously checks ONLY the morning candidates for
   intraday volume spikes and breakout conditions and sends BUY alerts.
9. At the same time, the main universe scan continues periodically so
   NEW stocks that meet the criteria can join the live watchlist.
10. Stores state locally to avoid repeated Telegram alerts.
11. NO Flask / Render Web Service is used.

IMPORTANT:
- This is a rule-based quantitative assistant, not a guarantee of profit.
- yfinance is convenient but is not a guaranteed real-time NSE feed.
- For production-grade intraday execution, replace the market-data layer
  with a broker/data-provider API.
- Never blindly execute a signal; verify price, liquidity, spread and SL.
"""

import os
import re
import time
import json
import math
import pickle
import logging
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, time as dt_time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf
import requests
import telebot
from telebot import types
from datasets import load_dataset

from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator


# ============================================================
# CONFIGURATION
# ============================================================

IST_OFFSET_HOURS = 5
IST_OFFSET_MINUTES = 30

# Core universe filters
MIN_MARKET_CAP_CR = float(os.getenv("MIN_MARKET_CAP_CR", "1000"))
MIN_PRICE = float(os.getenv("MIN_PRICE", "100"))
MAX_DAY_CHANGE = float(os.getenv("MAX_DAY_CHANGE", "15"))
MIN_DAY_VOLUME = int(os.getenv("MIN_DAY_VOLUME", "200000"))
MAX_FROM_52W_HIGH = float(os.getenv("MAX_FROM_52W_HIGH", "10"))
MIN_DAILY_VOLUME_RATIO = float(os.getenv("MIN_DAILY_VOLUME_RATIO", "1.5"))
MIN_AVG_VOLUME = int(os.getenv("MIN_AVG_VOLUME", "500000"))

# Trend filters
REQUIRE_50_ABOVE_200 = True
REQUIRE_10_ABOVE_50 = True

# Morning scan
MORNING_SCAN_HOUR = int(os.getenv("MORNING_SCAN_HOUR", "8"))
MORNING_SCAN_MINUTE = int(os.getenv("MORNING_SCAN_MINUTE", "45"))

# Main universe re-scan during market
UNIVERSE_RESCAN_MINUTES = int(os.getenv("UNIVERSE_RESCAN_MINUTES", "15"))

# Intraday breakout scan
INTRADAY_SCAN_SECONDS = int(os.getenv("INTRADAY_SCAN_SECONDS", "60"))
INTRADAY_INTERVAL = os.getenv("INTRADAY_INTERVAL", "5m")

# Intraday signal thresholds
MIN_INTRADAY_VOLUME_RATIO = float(os.getenv("MIN_INTRADAY_VOLUME_RATIO", "1.8"))
MIN_BREAKOUT_SCORE = float(os.getenv("MIN_BREAKOUT_SCORE", "70"))
MIN_BUY_SCORE = float(os.getenv("MIN_BUY_SCORE", "75"))

# V2.1 PRE-BREAKOUT ENGINE
RESISTANCE_LOOKBACK = int(os.getenv("RESISTANCE_LOOKBACK", "60"))
RESISTANCE_PIVOT_WINDOW = int(os.getenv("RESISTANCE_PIVOT_WINDOW", "3"))
MAX_PREBREAKOUT_DISTANCE = float(os.getenv("MAX_PREBREAKOUT_DISTANCE", "4.0"))
MIN_COMPRESSION_SCORE = float(os.getenv("MIN_COMPRESSION_SCORE", "45"))
MIN_SETUP_SCORE = float(os.getenv("MIN_SETUP_SCORE", "60"))
EXTENDED_DAY_CHANGE = float(os.getenv("EXTENDED_DAY_CHANGE", "7"))
VERY_EXTENDED_DAY_CHANGE = float(os.getenv("VERY_EXTENDED_DAY_CHANGE", "10"))
EXTENDED_RSI = float(os.getenv("EXTENDED_RSI", "72"))
VERY_EXTENDED_RSI = float(os.getenv("VERY_EXTENDED_RSI", "78"))
MIN_RR = float(os.getenv("MIN_RR", "1.5"))
VWAP_LOOKBACK_BARS = int(os.getenv("VWAP_LOOKBACK_BARS", "75"))
BREAKOUT_CONFIRM_BARS = int(os.getenv("BREAKOUT_CONFIRM_BARS", "1"))

# News
NEWS_LOOKBACK_HOURS = int(os.getenv("NEWS_LOOKBACK_HOURS", "30"))
MAX_NEWS_ITEMS = int(os.getenv("MAX_NEWS_ITEMS", "5"))

# Universe data workers
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))

# Persistence
STATE_FILE = "ai_bot_v2_state.pkl"
CACHE_FILE = "ai_bot_v2_daily_cache.pkl"
WATCHLIST_FILE = "ai_bot_v2_watchlist.pkl"

# Optional: limit Telegram morning list to this many stocks
MORNING_TOP_N = int(os.getenv("MORNING_TOP_N", "20"))

# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("NSE-AI-V2")


# ============================================================
# GLOBAL STATE
# ============================================================

STATE = {
    "alerted": set(),
    "morning_sent_date": None,
    "last_universe_scan": None,
    "last_status_date": None,
}

WATCHLIST = {}
UNIVERSE = []
UNIVERSE_LOCK = threading.Lock()


# ============================================================
# TIME HELPERS
# ============================================================

def now_ist():
    # Avoid external timezone dependency.
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def today_str():
    return now_ist().strftime("%Y-%m-%d")


def market_is_open():
    n = now_ist()
    if n.weekday() >= 5:
        return False

    start = dt_time(9, 15)
    end = dt_time(15, 30)
    return start <= n.time() <= end


def before_market():
    n = now_ist()
    return n.weekday() < 5 and n.time() < dt_time(9, 15)


def after_market():
    n = now_ist()
    return n.weekday() < 5 and n.time() > dt_time(15, 30)


# ============================================================
# PERSISTENCE
# ============================================================

def load_pickle(path, default):
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return pickle.load(f)
    except Exception as e:
        log.warning("Could not load %s: %s", path, e)
    return default


def save_pickle(path, obj):
    try:
        with open(path, "wb") as f:
            pickle.dump(obj, f)
    except Exception as e:
        log.warning("Could not save %s: %s", path, e)


def load_state():
    global STATE, WATCHLIST
    old_state = load_pickle(STATE_FILE, {})
    if isinstance(old_state, dict):
        STATE.update(old_state)

    if not isinstance(STATE.get("alerted"), set):
        STATE["alerted"] = set()

    WATCHLIST = load_pickle(WATCHLIST_FILE, {})
    if not isinstance(WATCHLIST, dict):
        WATCHLIST = {}


def save_state():
    save_pickle(STATE_FILE, STATE)
    save_pickle(WATCHLIST_FILE, WATCHLIST)


# ============================================================
# TELEGRAM HELPERS
# ============================================================

def tg_send(text, parse_mode="Markdown"):
    if not bot or not CHAT_ID:
        log.warning("Telegram is not configured.")
        return None

    try:
        return bot.send_message(
            CHAT_ID,
            text,
            parse_mode=parse_mode,
            disable_web_page_preview=True
        )
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return None


def tg_long_send(text):
    # Telegram message limit is ~4096 chars.
    chunks = []
    while text:
        chunks.append(text[:3900])
        text = text[3900:]

    for chunk in chunks:
        tg_send(chunk)


# ============================================================
# NSE UNIVERSE
# ============================================================

def get_all_nse_stocks():
    """
    Uses the same Hugging Face security master approach as V1.
    Removes obvious non-equity / malformed symbols.
    """
    log.info("Loading NSE universe...")

    try:
        ds = load_dataset(
            "tickertruth/nse-india-security-master",
            data_files="data/nse_security_master.csv"
        )
        df = ds["train"].to_pandas()

        df = df[df["active_flag"] == True]

        symbols = (
            df["nse_symbol"]
            .astype(str)
            .str.strip()
            .str.upper()
            .tolist()
        )

        symbols = sorted(set(
            s for s in symbols
            if re.fullmatch(r"[A-Z0-9&._-]+", s)
        ))

        log.info("NSE universe loaded: %s symbols", len(symbols))
        return symbols

    except Exception as e:
        log.exception("Universe loading failed: %s", e)
        return [
            "RELIANCE",
            "TCS",
            "HDFCBANK",
            "INFY",
            "ICICIBANK",
        ]


# ============================================================
# YFINANCE DATA
# ============================================================

def yf_daily(symbol, period="1y"):
    try:
        df = yf.download(
            f"{symbol}.NS",
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in required):
            return None

        df = df[required].copy()
        df = df.dropna()
        return df

    except Exception as e:
        log.debug("Daily data error %s: %s", symbol, e)
        return None


def yf_intraday(symbol):
    try:
        df = yf.download(
            f"{symbol}.NS",
            period="2d",
            interval=INTRADAY_INTERVAL,
            auto_adjust=False,
            progress=False,
            threads=False
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in required):
            return None

        df = df[required].dropna()
        return df

    except Exception as e:
        log.debug("Intraday data error %s: %s", symbol, e)
        return None


def get_info(symbol):
    """
    yfinance info is relatively expensive and can fail.
    It is used only when needed.
    """
    try:
        t = yf.Ticker(f"{symbol}.NS")
        info = t.info or {}

        return {
            "price": float(
                info.get("regularMarketPrice")
                or info.get("currentPrice")
                or 0
            ),
            "prev_close": float(
                info.get("regularMarketPreviousClose")
                or info.get("previousClose")
                or 0
            ),
            "volume": int(info.get("regularMarketVolume") or 0),
            "high_52w": float(info.get("fiftyTwoWeekHigh") or 0),
            "market_cap": float(info.get("marketCap") or 0) / 1e7,
        }

    except Exception:
        return {
            "price": 0,
            "prev_close": 0,
            "volume": 0,
            "high_52w": 0,
            "market_cap": 0,
        }


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def dema(series, period):
    ema1 = series.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    return (2 * ema1) - ema2


def add_indicators(df):
    x = df.copy()

    x["EMA10"] = EMAIndicator(x["Close"], window=10).ema_indicator()
    x["EMA20"] = EMAIndicator(x["Close"], window=20).ema_indicator()
    x["EMA50"] = EMAIndicator(x["Close"], window=50).ema_indicator()
    x["EMA200"] = EMAIndicator(x["Close"], window=200).ema_indicator()

    x["DEMA10"] = dema(x["Close"], 10)
    x["DEMA50"] = dema(x["Close"], 50)
    x["DEMA200"] = dema(x["Close"], 200)

    x["RSI"] = RSIIndicator(x["Close"], window=14).rsi()

    macd = MACD(
        x["Close"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    x["MACD"] = macd.macd()
    x["MACDSignal"] = macd.macd_signal()
    x["MACDHist"] = macd.macd_diff()

    x["ATR"] = AverageTrueRange(
        x["High"],
        x["Low"],
        x["Close"],
        window=14
    ).average_true_range()

    x["OBV"] = OnBalanceVolumeIndicator(
        x["Close"],
        x["Volume"]
    ).on_balance_volume()

    x["ADX"] = ADXIndicator(
        x["High"],
        x["Low"],
        x["Close"],
        window=14
    ).adx()

    x["AvgVol20"] = x["Volume"].rolling(20).mean()
    x["AvgVol50"] = x["Volume"].rolling(50).mean()

    return x


# ============================================================
# CANDLE PATTERNS
# ============================================================

def candle_body(row):
    return abs(row["Close"] - row["Open"])


def detect_candlestick_patterns(df):
    patterns = []

    if df is None or len(df) < 5:
        return patterns

    x = df.iloc[-5:].copy()

    last = x.iloc[-1]
    prev = x.iloc[-2]
    p2 = x.iloc[-3]

    body = candle_body(last)
    prev_body = candle_body(prev)

    # Bullish engulfing
    if (
        prev["Close"] < prev["Open"]
        and last["Close"] > last["Open"]
        and last["Open"] <= prev["Close"]
        and last["Close"] >= prev["Open"]
    ):
        patterns.append("Bullish Engulfing")

    # Hammer
    if body > 0:
        lower = min(last["Open"], last["Close"]) - last["Low"]
        upper = last["High"] - max(last["Open"], last["Close"])

        if lower >= 2 * body and upper <= body * 0.5:
            patterns.append("Hammer")

    # Morning star
    if (
        p2["Close"] < p2["Open"]
        and abs(prev["Close"] - prev["Open"]) <= abs(p2["Close"] - p2["Open"]) * 0.5
        and last["Close"] > last["Open"]
        and last["Close"] > (p2["Open"] + p2["Close"]) / 2
    ):
        patterns.append("Morning Star")

    # 3 white soldiers
    if len(x) >= 3:
        a, b, c = x.iloc[-3], x.iloc[-2], x.iloc[-1]
        if (
            a["Close"] > a["Open"]
            and b["Close"] > b["Open"]
            and c["Close"] > c["Open"]
            and b["Close"] > a["Close"]
            and c["Close"] > b["Close"]
        ):
            patterns.append("3 White Soldiers")

    return patterns


# ============================================================
# STRUCTURAL PATTERNS
# ============================================================

def detect_golden_cross(df):
    if len(df) < 210:
        return False

    ema50 = df["EMA50"]
    ema200 = df["EMA200"]

    recent = ema50.iloc[-10:] > ema200.iloc[-10:]

    # Current bullish alignment
    alignment = ema50.iloc[-1] > ema200.iloc[-1]

    # Actual recent crossover
    crossover = False
    for i in range(1, min(15, len(df))):
        a = ema50.iloc[-i-1] - ema200.iloc[-i-1]
        b = ema50.iloc[-i] - ema200.iloc[-i]
        if a <= 0 and b > 0:
            crossover = True
            break

    return bool(alignment and (crossover or recent.sum() >= 7))


def _pivot_lows(df, window=3):
    lows = df["Low"].astype(float).values
    out = []
    for i in range(window, len(df) - window):
        if lows[i] <= np.min(lows[i-window:i]) and lows[i] <= np.min(lows[i+1:i+window+1]):
            out.append(i)
    return out


def _pivot_highs(df, window=3):
    highs = df["High"].astype(float).values
    out = []
    for i in range(window, len(df) - window):
        if highs[i] >= np.max(highs[i-window:i]) and highs[i] >= np.max(highs[i+1:i+window+1]):
            out.append(i)
    return out


def detect_double_bottom(df, return_details=False):
    """Strict double-bottom: separated equal lows, meaningful rebound, neckline, and retest/approach."""
    if len(df) < 80:
        return ({"valid": False} if return_details else False)
    x = df.tail(min(150, len(df))).reset_index(drop=True)
    lows = x["Low"].astype(float)
    highs = x["High"].astype(float)
    closes = x["Close"].astype(float)
    pivots = _pivot_lows(x, 3)
    best = None
    for ai, a in enumerate(pivots[:-1]):
        for b in pivots[ai+1:]:
            sep = b - a
            if sep < 12 or sep > 70:
                continue
            low1, low2 = lows.iloc[a], lows.iloc[b]
            avg_low = (low1 + low2) / 2
            if avg_low <= 0 or abs(low1-low2)/avg_low > 0.035:
                continue
            valley = float(highs.iloc[a+1:b].max())
            if valley <= avg_low * 1.07:
                continue
            # Second bottom should be a genuine pullback, not just two adjacent lows.
            if closes.iloc[b] > valley * 1.01:
                continue
            recent_high = float(closes.iloc[-1])
            distance = (valley - recent_high) / valley * 100
            if distance < -3.0 or distance > 5.0:
                continue
            score = 100 - abs(low1-low2)/avg_low*1000 + min(20, (valley/avg_low-1)*100)
            candidate = {"valid": True, "first_low": float(low1), "second_low": float(low2),
                         "neckline": valley, "distance_to_neckline": round(distance,2), "score": round(score,1)}
            if best is None or candidate["score"] > best["score"]:
                best = candidate
    if return_details:
        return best or {"valid": False}
    return bool(best)


def find_daily_resistance(df, lookback=60):
    x = df.tail(min(lookback, len(df))).reset_index(drop=True)
    pivots = _pivot_highs(x, 3)
    current = float(x["Close"].iloc[-1])
    candidates = [float(x["High"].iloc[i]) for i in pivots if float(x["High"].iloc[i]) >= current * 0.98]
    if not candidates:
        candidates = [float(x["High"].max())]
    resistance = min(candidates, key=lambda v: abs(v-current))
    return resistance


def calculate_compression_score(df):
    if len(df) < 25:
        return 0.0
    x = df.copy()
    close = x["Close"].astype(float)
    atr = x["ATR"] if "ATR" in x else pd.Series(index=x.index, dtype=float)
    recent = x.tail(20)
    range_pct = (recent["High"].max() - recent["Low"].min()) / max(close.iloc[-1], 0.01) * 100
    atr_pct = float(atr.iloc[-1] / close.iloc[-1] * 100) if pd.notna(atr.iloc[-1]) else 0
    daily_ranges = ((x["High"]-x["Low"]) / x["Close"]).tail(20)
    contraction = 1 - (daily_ranges.tail(10).mean() / max(daily_ranges.head(10).mean(), 1e-9))
    score = 0
    if range_pct <= 12: score += 35
    elif range_pct <= 18: score += 25
    elif range_pct <= 25: score += 15
    if atr_pct <= 3: score += 25
    elif atr_pct <= 4.5: score += 18
    elif atr_pct <= 6: score += 10
    if contraction >= 0.25: score += 25
    elif contraction >= 0.10: score += 15
    elif contraction >= 0: score += 8
    # Higher lows improve base quality.
    lows = recent["Low"].tail(10).values
    if len(lows) >= 6 and lows[-1] >= np.min(lows[:5]) * 1.005:
        score += 15
    return round(min(100, score), 1)


def calculate_relative_strength(df):
    """Internal price-strength proxy when index data is unavailable."""
    if len(df) < 30:
        return 50.0
    ret20 = float(df["Close"].iloc[-1] / df["Close"].iloc[-21] - 1)
    ret5 = float(df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1)
    score = 50 + ret20*180 + ret5*120
    return round(max(0, min(100, score)), 1)


def classify_setup(day_change, rsi, setup_score, distance, compression, breakout=False):
    if breakout:
        if day_change >= VERY_EXTENDED_DAY_CHANGE or rsi >= VERY_EXTENDED_RSI:
            return "EXTENDED BREAKOUT"
        return "BREAKOUT CONFIRMED"
    if day_change >= VERY_EXTENDED_DAY_CHANGE or rsi >= VERY_EXTENDED_RSI:
        return "EXTENDED MOMENTUM"
    if setup_score >= 75 and distance <= 2.0 and compression >= 55:
        return "PRE-BREAKOUT"
    if setup_score >= MIN_SETUP_SCORE and distance <= MAX_PREBREAKOUT_DISTANCE:
        return "BREAKOUT WATCH"
    return "BULLISH WATCH"


def detect_near_breakout(df):
    if len(df) < 40:
        return False
    resistance = find_daily_resistance(df, RESISTANCE_LOOKBACK)
    close = float(df["Close"].iloc[-1])
    return close <= resistance and ((resistance-close)/resistance*100) <= MAX_PREBREAKOUT_DISTANCE

def detect_breakout(df):
    if len(df) < 25:
        return False

    resistance = df["High"].iloc[-21:-1].max()
    close = df["Close"].iloc[-1]
    volume = df["Volume"].iloc[-1]
    avg = df["Volume"].iloc[-21:-1].mean()

    return (
        close > resistance
        and avg > 0
        and volume >= avg * 1.5
    )


# ============================================================
# NEWS / CATALYST ENGINE
# ============================================================

BULLISH_WORDS = {
    "order": 3,
    "contract": 3,
    "wins": 2,
    "win": 2,
    "approval": 3,
    "approved": 3,
    "launch": 2,
    "expansion": 2,
    "acquisition": 2,
    "merger": 2,
    "earnings": 1,
    "profit": 3,
    "profits": 3,
    "revenue": 2,
    "growth": 2,
    "upgrade": 3,
    "buy": 2,
    "target": 1,
    "capacity": 2,
    "investment": 2,
    "partnership": 2,
    "export": 2,
    "record": 2,
    "strong": 1,
    "positive": 2,
    "surge": 2,
    "rises": 1,
}

BEARISH_WORDS = {
    "fraud": 6,
    "default": 5,
    "downgrade": 4,
    "loss": 3,
    "losses": 3,
    "decline": 2,
    "falls": 2,
    "fall": 2,
    "probe": 4,
    "investigation": 4,
    "resign": 3,
    "resignation": 3,
    "warning": 2,
    "debt": 2,
    "lawsuit": 3,
    "penalty": 3,
    "cut": 2,
    "weak": 2,
    "negative": 2,
}


def clean_text(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def news_sentiment(text):
    text = text.lower()

    bull = 0
    bear = 0

    for word, weight in BULLISH_WORDS.items():
        if re.search(r"\b" + re.escape(word) + r"\b", text):
            bull += weight

    for word, weight in BEARISH_WORDS.items():
        if re.search(r"\b" + re.escape(word) + r"\b", text):
            bear += weight

    raw = bull - bear

    if raw >= 5:
        label = "Bullish"
    elif raw <= -4:
        label = "Bearish"
    else:
        label = "Neutral"

    return raw, label


def fetch_google_news(symbol):
    """
    Google News RSS. No API key required.
    """
    try:
        q = urllib.parse.quote(f"{symbol} NSE India stock")
        url = (
            "https://news.google.com/rss/search?"
            f"q={q}&hl=en-IN&gl=IN&ceid=IN:en"
        )

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)

        items = []

        for item in root.findall(".//item")[:MAX_NEWS_ITEMS]:
            title = clean_text(item.findtext("title"))
            link = clean_text(item.findtext("link"))
            pub = clean_text(item.findtext("pubDate"))

            if title:
                score, label = news_sentiment(title)

                items.append({
                    "title": title,
                    "link": link,
                    "published": pub,
                    "score": score,
                    "label": label,
                })

        return items

    except Exception as e:
        log.debug("News error %s: %s", symbol, e)
        return []


def compute_news_score(symbol):
    items = fetch_google_news(symbol)

    if not items:
        return {
            "score": 0,
            "label": "No recent news",
            "headlines": []
        }

    total = 0
    bullish = 0
    bearish = 0

    for item in items:
        total += item["score"]
        if item["label"] == "Bullish":
            bullish += 1
        elif item["label"] == "Bearish":
            bearish += 1

    # Convert roughly to 0-100.
    score = 50 + total * 5
    score += min(15, bullish * 5)
    score -= min(20, bearish * 7)

    score = max(0, min(100, score))

    if score >= 65:
        label = "Bullish"
    elif score <= 35:
        label = "Bearish"
    else:
        label = "Neutral"

    return {
        "score": round(score, 1),
        "label": label,
        "headlines": items,
    }


# ============================================================
# DAILY AI-STYLE ANALYSIS
# ============================================================

def analyze_daily(symbol, df):
    if df is None or len(df) < 210:
        return None
    x = add_indicators(df)
    last, prev = x.iloc[-1], x.iloc[-2]
    close = float(last["Close"])
    atr = float(last["ATR"]) if pd.notna(last["ATR"]) else 0
    if close <= 0:
        return None

    patterns = detect_candlestick_patterns(x)
    golden_cross = detect_golden_cross(x)
    db = detect_double_bottom(x, True)
    double_bottom = db.get("valid", False)
    hh_hl = detect_higher_high_higher_low(x)
    resistance = find_daily_resistance(x, RESISTANCE_LOOKBACK)
    distance = max(0.0, (resistance-close)/resistance*100) if resistance > 0 else 100
    near_breakout = distance <= MAX_PREBREAKOUT_DISTANCE
    breakout = close > resistance * 1.002

    macd_cross = last["MACD"] > last["MACDSignal"] and prev["MACD"] <= prev["MACDSignal"]
    rsi = float(last["RSI"]) if pd.notna(last["RSI"]) else 50
    adx = float(last["ADX"]) if pd.notna(last["ADX"]) else 0
    rsi_prev = float(x["RSI"].iloc[-6]) if pd.notna(x["RSI"].iloc[-6]) else rsi
    macd_hist_slope = float(last["MACDHist"] - x["MACDHist"].iloc[-5]) if pd.notna(x["MACDHist"].iloc[-5]) else 0
    obv_accumulation = len(x) >= 10 and x["OBV"].iloc[-1] > x["OBV"].iloc[-6]
    ema_alignment = last["EMA10"] > last["EMA20"] > last["EMA50"] > last["EMA200"]
    dema_alignment = last["DEMA10"] > last["DEMA50"] > last["DEMA200"]
    volume_ratio = float(last["Volume"] / last["AvgVol20"]) if pd.notna(last["AvgVol20"]) and last["AvgVol20"] > 0 else 0
    compression = calculate_compression_score(x)
    relative_strength = calculate_relative_strength(x)

    # Setup score: Trend 20, Structure 30, Volume/Accumulation 20, Momentum 15, RS 10, Catalyst reserved 5.
    trend = 0
    trend += 7 if dema_alignment else 0
    trend += 5 if ema_alignment else 0
    trend += 4 if golden_cross else 0
    trend += 4 if hh_hl else 0
    structure = 0
    structure += 10 if distance <= 1.5 else 7 if distance <= 3 else 4 if distance <= MAX_PREBREAKOUT_DISTANCE else 0
    structure += min(10, compression/10)
    structure += 10 if double_bottom else 5 if near_breakout else 0
    volume_score = 0
    volume_score += 7 if 0.7 <= volume_ratio <= 2.5 else 4 if volume_ratio > 2.5 else 2
    volume_score += 7 if obv_accumulation else 0
    volume_score += 6 if compression >= 50 else 3
    momentum = 0
    momentum += 6 if 52 <= rsi <= 68 else 3 if 48 <= rsi < 52 else 0
    momentum += 4 if rsi > rsi_prev else 0
    momentum += 3 if macd_hist_slope > 0 else 0
    momentum += 2 if adx >= 20 and adx > float(x["ADX"].iloc[-6]) else 1 if adx >= 20 else 0
    rs_score = 10 if relative_strength >= 65 else 7 if relative_strength >= 55 else 4 if relative_strength >= 45 else 0
    setup_score = round(min(100, trend + structure + volume_score + momentum + rs_score), 1)

    # Structural support: recent pivot/support, with ATR fallback.
    support_candidates = list(x["Low"].tail(40).nsmallest(8).astype(float))
    support = max([v for v in support_candidates if v < close*0.995] or [close - 1.5*atr if atr > 0 else close*0.97])
    sl = support * 0.995
    if sl >= close:
        sl = close - 1.2*atr if atr > 0 else close*0.97
    risk = close - sl
    target1 = max(close + 2*risk, resistance) if resistance > close else close + 2*risk
    target2 = close + 3*risk
    rr = (target1-close)/risk if risk > 0 else 0

    day_change = float((close / float(prev["Close"]) - 1)*100) if float(prev["Close"]) > 0 else 0
    setup = classify_setup(day_change, rsi, setup_score, distance, compression, breakout)
    reasons = []
    if dema_alignment: reasons.append("DEMA trend aligned")
    if near_breakout: reasons.append(f"{distance:.1f}% below resistance")
    if compression >= 50: reasons.append("Price compression")
    if double_bottom: reasons.append("Validated Double Bottom")
    if obv_accumulation: reasons.append("OBV accumulation")
    if rsi > rsi_prev: reasons.append("RSI rising")
    if macd_hist_slope > 0: reasons.append("MACD histogram rising")
    if relative_strength >= 65: reasons.append("Strong relative strength")

    return {
        "symbol": symbol, "close": close, "rsi": round(rsi,2), "adx": round(adx,2), "atr": round(atr,2),
        "volume_ratio": round(volume_ratio,2), "ema_alignment": bool(ema_alignment), "dema_alignment": bool(dema_alignment),
        "golden_cross": bool(golden_cross), "double_bottom": bool(double_bottom), "hh_hl": bool(hh_hl),
        "near_breakout": bool(near_breakout), "breakout": bool(breakout), "macd_bullish": bool(last["MACD"] > last["MACDSignal"]),
        "macd_cross": bool(macd_cross), "obv_accumulation": bool(obv_accumulation), "patterns": patterns,
        "setup": setup, "score": setup_score, "setup_score": setup_score, "trend_score": round(trend,1),
        "structure_score": round(structure,1), "volume_score": round(volume_score,1), "momentum_score": round(momentum,1),
        "relative_strength": relative_strength, "compression_score": compression, "resistance": round(resistance,2),
        "distance_to_resistance": round(distance,2), "support": round(support,2), "risk_reward": round(rr,2),
        "reasons": reasons, "stop_loss": round(sl,2), "target1": round(target1,2), "target2": round(target2,2)
    }


# ============================================================
# CORE FILTER
# ============================================================

def apply_core_filters(symbol, df, info=None):
    if df is None or len(df) < 210:
        return None

    x = add_indicators(df)
    last = x.iloc[-1]

    price = float(last["Close"])
    volume = float(last["Volume"])

    if info is None:
        info = get_info(symbol)

    prev_close = info["prev_close"] or (
        float(x["Close"].iloc[-2]) if len(x) >= 2 else price
    )

    high_52w = info["high_52w"]
    if high_52w <= 0:
        high_52w = float(x["High"].tail(252).max())

    market_cap = info["market_cap"]

    avg_volume = float(
        x["Volume"].tail(21).mean()
    )

    day_change = (
        ((price - prev_close) / prev_close) * 100
        if prev_close > 0 else 0
    )

    volume_ratio = (
        volume / avg_volume
        if avg_volume > 0 else 0
    )

    pct_from_high = (
        ((high_52w - price) / high_52w) * 100
        if high_52w > 0 else 100
    )

    # Required user filters
    if market_cap < MIN_MARKET_CAP_CR:
        return None

    if price < MIN_PRICE:
        return None

    if day_change < 0:
        return None

    if day_change >= MAX_DAY_CHANGE:
        return None

    if volume < MIN_DAY_VOLUME:
        return None

    if avg_volume <= MIN_AVG_VOLUME:
        return None

    if pct_from_high > MAX_FROM_52W_HIGH:
        return None

    if volume_ratio < MIN_DAILY_VOLUME_RATIO:
        return None

    if REQUIRE_50_ABOVE_200:
        if float(last["DEMA50"]) <= float(last["DEMA200"]):
            return None

    if REQUIRE_10_ABOVE_50:
        if float(last["DEMA10"]) <= float(last["DEMA50"]):
            return None

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "day_change": round(day_change, 2),
        "volume": int(volume),
        "avg_volume": int(avg_volume),
        "volume_ratio": round(volume_ratio, 2),
        "high_52w": round(high_52w, 2),
        "pct_from_high": round(pct_from_high, 2),
        "market_cap": round(market_cap, 2),
    }


# ============================================================
# CANDIDATE ANALYSIS
# ============================================================

def analyze_candidate(symbol):
    try:
        df = yf_daily(symbol, "1y")
        if df is None:
            return None

        base = apply_core_filters(symbol, df)

        if base is None:
            return None

        technical = analyze_daily(symbol, df)

        if technical is None:
            return None

        news = compute_news_score(symbol)

        # V2.1: technical setup is primary; news is only a catalyst modifier.
        core_score = 0
        core_score += 10 if base["volume_ratio"] >= 2 else 7 if base["volume_ratio"] >= 1.5 else 4
        core_score += 8 if base["pct_from_high"] <= 3 else 6 if base["pct_from_high"] <= 7 else 3
        core_score += 7 if 0 <= base["day_change"] <= 5 else 4
        extension_penalty = 0
        if base["day_change"] > VERY_EXTENDED_DAY_CHANGE: extension_penalty += 10
        elif base["day_change"] > EXTENDED_DAY_CHANGE: extension_penalty += 5
        if technical["rsi"] >= VERY_EXTENDED_RSI: extension_penalty += 10
        elif technical["rsi"] >= EXTENDED_RSI: extension_penalty += 5
        combined = technical["setup_score"] * 0.70 + core_score * 0.20 + news["score"] * 0.10 - extension_penalty
        combined = max(0, min(100, combined))

        return {
            "symbol": symbol,
            "base": base,
            "technical": technical,
            "news": news,
            "core_score": round(core_score, 1),
            "combined_score": round(combined, 1),
            "extension_penalty": extension_penalty,
            "status": technical["setup"],
            "added_at": now_ist().isoformat(),
        }

    except Exception as e:
        log.debug("Candidate error %s: %s", symbol, e)
        return None


# ============================================================
# PARALLEL UNIVERSE SCAN
# ============================================================

def scan_universe(symbols=None):
    if symbols is None:
        symbols = UNIVERSE

    log.info("Starting main universe scan: %s stocks", len(symbols))

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(analyze_candidate, s): s
            for s in symbols
        }

        completed = 0

        for future in as_completed(futures):
            completed += 1

            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                pass

            if completed % 100 == 0:
                log.info(
                    "Universe progress: %s/%s | candidates=%s",
                    completed,
                    len(symbols),
                    len(results)
                )

    results.sort(
        key=lambda x: x["combined_score"],
        reverse=True
    )

    log.info(
        "Universe scan complete: %s candidates",
        len(results)
    )

    return results


# ============================================================
# WATCHLIST MANAGEMENT
# ============================================================

def merge_watchlist(results):
    added = []

    with UNIVERSE_LOCK:
        for item in results:
            symbol = item["symbol"]

            if symbol not in WATCHLIST:
                WATCHLIST[symbol] = item
                added.append(item)
            else:
                # Update latest analysis while preserving signal state.
                old = WATCHLIST[symbol]

                signal_state = old.get(
                    "signal_state",
                    "WATCHING"
                )

                item["signal_state"] = signal_state
                WATCHLIST[symbol] = item

    save_state()
    return added


# ============================================================
# MORNING REPORT
# ============================================================

def format_morning_report(results):
    date = today_str()

    top = results[:MORNING_TOP_N]

    msg = (
        f"ð *NSE AI BREAKOUT V2*\n"
        f"ð {date}\n"
        f"ð Candidates passing core filters: *{len(results)}*\n\n"
    )

    for i, item in enumerate(top, 1):
        t = item["technical"]
        n = item["news"]
        b = item["base"]

        patterns = ", ".join(t["patterns"]) if t["patterns"] else "None"

        msg += (
            f"*{i}. {item['symbol']}* â "
            f"AI Score *{item['combined_score']}/100*\n"
            f"ð° â¹{b['price']:.2f} | "
            f"ð {b['day_change']:.2f}% | "
            f"ð Vol {b['volume_ratio']:.2f}x\n"
            f"ð· Status: *{t['setup']}* | Setup *{t['setup_score']}/100*\n"
            f"ð Resistance â¹{t['resistance']:.2f} | Distance *{t['distance_to_resistance']:.2f}%*\n"
            f"ð Compression {t['compression_score']}/100 | RS {t['relative_strength']}/100\n"
            f"ð§  Patterns: {patterns}\n"
            f"ð RSI {t['rsi']} | ADX {t['adx']} | MACD {'ð¢' if t['macd_bullish'] else 'ð´'}\n"
            f"ð° Catalyst: {n['label']} ({n['score']}/100) [10% weight]\n"
            f"ð¡ Support â¹{t['support']:.2f} | R:R {t['risk_reward']:.2f}\n"
            f"ð¯ SL â¹{t['stop_loss']:.2f} | T1 â¹{t['target1']:.2f} | T2 â¹{t['target2']:.2f}\n"
            f"ââââââââââââââââ\n"
        )

    msg += (
        "\nâ¡ *Live mode:* I will now watch these candidates for "
        "intraday volume expansion + breakout confirmation.\n"
        "ð The main universe scanner will also continue searching "
        "for NEW qualifying stocks."
    )

    return msg


# ============================================================
# INTRADAY BREAKOUT ENGINE
# ============================================================

def analyze_intraday(symbol, morning_item):
    df = yf_intraday(symbol)
    if df is None or len(df) < 10:
        return None
    today = now_ist().date()
    try:
        dates = pd.to_datetime(df.index)
        day = df.loc[dates.date == today].copy()
    except Exception:
        day = df.tail(30).copy()
    if len(day) < 3:
        return None
    last = day.iloc[-1]
    price = float(last["Close"]); volume = float(last["Volume"])
    prior = day.iloc[:-1]
    avg_bar_volume = float(prior["Volume"].tail(12).mean()) if len(prior) else 0
    volume_ratio = volume / avg_bar_volume if avg_bar_volume > 0 else 0
    lookback = min(12, len(day)-1)
    local_resistance = float(day["High"].iloc[-lookback-1:-1].max()) if lookback >= 2 else float(day["High"].iloc[:-1].max())
    daily_resistance = float(morning_item["technical"].get("resistance", local_resistance))
    resistance = max(local_resistance, daily_resistance)
    bullish = float(last["Close"]) > float(last["Open"])
    rng = max(float(last["High"]-last["Low"]), 0.01)
    body = abs(float(last["Close"]-last["Open"]))
    strong_body = body/rng >= 0.55
    typical = (day["High"]+day["Low"]+day["Close"])/3
    vwap = float((typical*day["Volume"]).cumsum().iloc[-1] / max(day["Volume"].cumsum().iloc[-1],1))
    breakout = price > resistance * 1.001
    volume_score = 30 if volume_ratio >= 3 else 25 if volume_ratio >= 2.5 else 18 if volume_ratio >= MIN_INTRADAY_VOLUME_RATIO else 0
    score = (35 if breakout else 0) + volume_score + (10 if bullish else 0) + (10 if strong_body else 0) + (5 if price > vwap else 0)
    score += min(10, morning_item["technical"]["setup_score"]/10)
    score = round(min(100, score),1)
    buy_signal = breakout and volume_ratio >= MIN_INTRADAY_VOLUME_RATIO and bullish and price > vwap and score >= MIN_BUY_SCORE
    atr = morning_item["technical"]["atr"]
    support = morning_item["technical"].get("support", price-1.2*atr)
    sl = min(support*0.995, price-0.8*atr) if atr > 0 else price*0.985
    if sl <= 0 or sl >= price: sl = price-1.2*atr if atr > 0 else price*0.985
    risk = price-sl
    target1 = max(price+2*risk, daily_resistance if daily_resistance > price else 0)
    target2 = price+3*risk
    rr = (target1-price)/risk if risk > 0 else 0
    if rr < MIN_RR:
        buy_signal = False
    return {"symbol":symbol,"price":round(price,2),"resistance":round(resistance,2),"daily_resistance":round(daily_resistance,2),
            "volume_ratio":round(volume_ratio,2),"vwap":round(vwap,2),"score":score,"breakout":breakout,
            "bullish_candle":bullish,"strong_body":strong_body,"buy_signal":buy_signal,"sl":round(sl,2),
            "target1":round(target1,2),"target2":round(target2,2),"risk_reward":round(rr,2),"time":now_ist().strftime("%H:%M:%S")}


# ============================================================
# LIVE BUY ALERT
# ============================================================

def alert_key(symbol):
    return f"{today_str()}::{symbol}::BUY"


def send_buy_alert(signal, morning_item):
    symbol = signal["symbol"]
    key = alert_key(symbol)

    if key in STATE["alerted"]:
        return

    STATE["alerted"].add(key)

    t = morning_item["technical"]
    n = morning_item["news"]

    msg = (
        f"ð¨ *AI BUY SIGNAL â V2*\n"
        f"ââââââââââââââââââââ\n"
        f"ð *{symbol}*\n"
        f"ð° Price: *â¹{signal['price']:.2f}*\n"
        f"ð Breakout: *â¹{signal['resistance']:.2f}*\n"
        f"ð Intraday Volume: *{signal['volume_ratio']:.2f}x*\n"
        f"ð§  Breakout Score: *{signal['score']}/100*\n"
        f"ð VWAP: â¹{signal['vwap']:.2f} | Vol: *{signal['volume_ratio']:.2f}x*\n"
        f"ð Daily Setup: *{t['setup']}* | Setup *{t['setup_score']}/100*\n"
        f"ð Daily Resistance: â¹{signal['daily_resistance']:.2f}\n"
        f"ð RSI: {t['rsi']} | ADX: {t['adx']} | R:R {signal['risk_reward']:.2f}\n"
        f"ð° Catalyst: *{n['label']}*\n\n"
        f"ð¯ *Entry:* â¹{signal['price']:.2f}\n"
        f"ð *SL:* â¹{signal['sl']:.2f}\n"
        f"ð *T1:* â¹{signal['target1']:.2f}\n"
        f"ð *T2:* â¹{signal['target2']:.2f}\n\n"
        f"â ï¸ Confirm spread/liquidity before entering.\n"
        f"â° {signal['time']}"
    )

    tg_send(msg)
    save_state()


# ============================================================
# CONTINUOUS INTRADAY WATCHER
# ============================================================

def intraday_watcher():
    log.info("Intraday watcher started.")

    while True:
        try:
            if market_is_open():
                with UNIVERSE_LOCK:
                    items = list(WATCHLIST.values())

                if items:
                    log.info(
                        "Intraday scan: watching %s stocks",
                        len(items)
                    )

                for item in items:
                    try:
                        signal = analyze_intraday(
                            item["symbol"],
                            item
                        )

                        if signal and signal["buy_signal"]:
                            send_buy_alert(signal, item)

                    except Exception as e:
                        log.debug(
                            "Intraday error %s: %s",
                            item.get("symbol"),
                            e
                        )

                    time.sleep(0.15)

            time.sleep(INTRADAY_SCAN_SECONDS)

        except Exception as e:
            log.exception("Intraday watcher failure: %s", e)
            time.sleep(10)


# ============================================================
# MAIN UNIVERSE CONTINUOUS SCANNER
# ============================================================

def universe_monitor():
    log.info("Continuous universe monitor started.")

    while True:
        try:
            if market_is_open():
                n = now_ist()

                last = STATE.get("last_universe_scan")

                due = False

                if last is None:
                    due = True
                else:
                    try:
                        previous = datetime.fromisoformat(last)
                        due = (
                            n - previous
                            >= timedelta(
                                minutes=UNIVERSE_RESCAN_MINUTES
                            )
                        )
                    except Exception:
                        due = True

                if due:
                    log.info("Running new-stock universe scan...")

                    results = scan_universe()

                    new_items = merge_watchlist(results)

                    STATE["last_universe_scan"] = n.isoformat()
                    save_state()

                    if new_items:
                        # Only alert Telegram when genuinely NEW candidates
                        # appear after the morning scan.
                        top_new = sorted(
                            new_items,
                            key=lambda x: x["combined_score"],
                            reverse=True
                        )[:10]

                        msg = (
                            f"ð *NEW AI CANDIDATES â V2*\n"
                            f"â° {n.strftime('%H:%M:%S')}\n"
                            f"ð {len(new_items)} new stocks passed filters.\n\n"
                        )

                        for i, item in enumerate(top_new, 1):
                            t = item["technical"]
                            msg += (
                                f"{i}. *{item['symbol']}* "
                                f"Score {item['combined_score']}\n"
                                f"   Setup: {t['setup']} | "
                                f"Vol {item['base']['volume_ratio']}x\n"
                            )

                        tg_send(msg)

            time.sleep(30)

        except Exception as e:
            log.exception("Universe monitor failure: %s", e)
            time.sleep(30)


# ============================================================
# MORNING SCAN
# ============================================================

def run_morning_scan():
    if now_ist().weekday() >= 5:
        return

    log.info("Starting V2 morning scan.")

    tg_send(
        "ð *NSE AI V2 Morning Scan Started*\n"
        "Scanning the NSE universe for trend + chart patterns + catalysts..."
    )

    results = scan_universe()

    with UNIVERSE_LOCK:
        WATCHLIST.clear()
        for item in results:
            WATCHLIST[item["symbol"]] = item

    STATE["morning_sent_date"] = today_str()
    STATE["last_universe_scan"] = now_ist().isoformat()

    save_state()

    if results:
        tg_long_send(format_morning_report(results))
    else:
        tg_send(
            "ð *NSE AI V2*\n"
            "No stock passed all core filters today."
        )


# ============================================================
# DAILY SCHEDULER
# ============================================================

def scheduler_loop():
    log.info(
        "Scheduler active. Morning scan %02d:%02d IST.",
        MORNING_SCAN_HOUR,
        MORNING_SCAN_MINUTE
    )

    morning_done = False
    current_date = None

    while True:
        try:
            n = now_ist()

            if n.date() != current_date:
                current_date = n.date()
                morning_done = False

                # Do not reuse yesterday's alerted symbols.
                STATE["alerted"] = {
                    x for x in STATE.get("alerted", set())
                    if x.startswith(today_str() + "::")
                }

            scheduled_time = dt_time(
                MORNING_SCAN_HOUR,
                MORNING_SCAN_MINUTE
            )

            if (
                n.weekday() < 5
                and n.time() >= scheduled_time
                and not morning_done
            ):
                # Morning scan can run before market, or if the process
                # starts late it runs immediately after startup.
                run_morning_scan()
                morning_done = True

            time.sleep(20)

        except Exception as e:
            log.exception("Scheduler failure: %s", e)
            time.sleep(30)


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

def register_commands():
    if not bot:
        return

    @bot.message_handler(commands=["start"])
    def start_cmd(message):
        bot.reply_to(
            message,
            "ð¤ NSE AI Breakout Bot V2 is running.\n\n"
            "/scan - run a fresh universe scan\n"
            "/watchlist - show current watchlist\n"
            "/status - show bot status"
        )

    @bot.message_handler(commands=["scan"])
    def scan_cmd(message):
        bot.reply_to(
            message,
            "ð Manual V2 scan started..."
        )

        def worker():
            results = scan_universe()
            merge_watchlist(results)

            if results:
                tg_long_send(format_morning_report(results))
            else:
                tg_send("ð No qualifying stocks found.")

        threading.Thread(target=worker, daemon=True).start()

    @bot.message_handler(commands=["watchlist"])
    def watchlist_cmd(message):
        with UNIVERSE_LOCK:
            items = list(WATCHLIST.values())

        items.sort(
            key=lambda x: x.get("combined_score", 0),
            reverse=True
        )

        if not items:
            bot.reply_to(message, "Watchlist is empty.")
            return

        msg = "ð *CURRENT V2 WATCHLIST*\n\n"

        for i, item in enumerate(items[:30], 1):
            t = item["technical"]
            msg += (
                f"{i}. *{item['symbol']}* "
                f"{item['combined_score']}/100 â "
                f"{t['setup']}\n"
            )

        bot.reply_to(
            message,
            msg,
            parse_mode="Markdown"
        )

    @bot.message_handler(commands=["status"])
    def status_cmd(message):
        with UNIVERSE_LOCK:
            count = len(WATCHLIST)

        bot.reply_to(
            message,
            f"ð¤ *NSE AI V2 STATUS*\n\n"
            f"Universe: {len(UNIVERSE)}\n"
            f"Watchlist: {count}\n"
            f"Market open: {market_is_open()}\n"
            f"Last universe scan: "
            f"{STATE.get('last_universe_scan', 'Never')}\n"
            f"Morning scan: "
            f"{STATE.get('morning_sent_date', 'Not sent')}",
            parse_mode="Markdown"
        )


# ============================================================
# STARTUP
# ============================================================

def validate_environment():
    if not BOT_TOKEN:
        log.warning(
            "BOT_TOKEN is not set. Telegram alerts are disabled."
        )

    if not CHAT_ID:
        log.warning(
            "CHAT_ID is not set. Telegram alerts are disabled."
        )


def build_universe():
    global UNIVERSE

    UNIVERSE = get_all_nse_stocks()

    if not UNIVERSE:
        raise RuntimeError("NSE universe is empty.")


def main():
    print("=" * 72)
    print("ð¤ NSE AI BREAKOUT BOT V2")
    print("=" * 72)
    print("Render/Flask removed.")
    print("Morning chart + catalyst analysis enabled.")
    print("Continuous intraday breakout monitoring enabled.")
    print("Continuous new-stock universe scan enabled.")
    print("=" * 72)

    validate_environment()
    load_state()
    build_universe()
    register_commands()

    if bot:
        try:
            me = bot.get_me()
            log.info("Telegram connected: @%s", me.username)
        except Exception as e:
            log.warning("Telegram connection test failed: %s", e)

    # --------------------------------------------------------
    # Startup behaviour
    # --------------------------------------------------------
    n = now_ist()

    # If the process starts after morning-scan time but before
    # market close, run today's scan immediately.
    if (
        n.weekday() < 5
        and n.time() >= dt_time(
            MORNING_SCAN_HOUR,
            MORNING_SCAN_MINUTE
        )
        and STATE.get("morning_sent_date") != today_str()
    ):
        threading.Thread(
            target=run_morning_scan,
            daemon=True
        ).start()

    # Continuous universe scanner.
    threading.Thread(
        target=universe_monitor,
        daemon=True
    ).start()

    # Continuous intraday scanner.
    threading.Thread(
        target=intraday_watcher,
        daemon=True
    ).start()

    # Daily scheduler.
    threading.Thread(
        target=scheduler_loop,
        daemon=True
    ).start()

    tg_send(
        "â *NSE AI Breakout Bot V2 is ONLINE*\n"
        "â¢ Broad NSE scan\n"
        "â¢ Daily bullish pattern detection\n"
        "â¢ Golden Cross / Double Bottom\n"
        "â¢ News catalyst scoring\n"
        "â¢ Morning watchlist\n"
        "â¢ Intraday volume-spike breakout alerts\n"
        "â¢ Continuous new-stock discovery\n"
        "â¢ No Render/Flask dependency"
    )

    # Telegram polling must remain in the main thread.
    if bot:
        log.info("Telegram polling started.")
        bot.infinity_polling(
            timeout=30,
            long_polling_timeout=30
        )
    else:
        # Keep process alive even without Telegram.
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
