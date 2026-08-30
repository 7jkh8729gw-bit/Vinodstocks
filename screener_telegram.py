import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
import pickle
import requests
from datetime import datetime, timedelta
import telebot
from telebot import types
from datasets import load_dataset
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================
# USE 'ta' LIBRARY - CORRECT IMPORTS
# ============================================
import ta
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator

# ============================================
# BOT DETAILS (PULL FROM ENVIRONMENT VARIABLES)
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
YOUR_CHAT_ID = os.environ.get('CHAT_ID')
# ============================================

if not BOT_TOKEN or not YOUR_CHAT_ID:
    print("❌ BOT_TOKEN or CHAT_ID not set in environment variables.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
CACHE_FILE = "screener_cache.pkl"
WATCHLIST_FILE = "morning_watchlist.pkl"

STORED_RESULTS = {}

print("=" * 70)
print("🌅 MORNING SCREENER - AUTO-RANKED WITH TECHNICALS")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# NSE API HELPERS (KEPT FOR CACHE BUILDING & LIVE DATA)
# ============================================
def get_nse_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    session.get('https://www.nseindia.com', timeout=10)
    time.sleep(1)
    return session

def fetch_nse_live(symbol):
    try:
        session = get_nse_session()
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            price_info = data.get('priceInfo', {})
            return {
                'price': price_info.get('lastPrice', 0),
                'prev_close': price_info.get('previousClose', 0),
                'volume': data.get('totalTradedVolume', 0),
                'high_52w': price_info.get('weekHigh52', 0),
                'market_cap': data.get('marketCap', 0) / 10000000,
            }
    except:
        return None

def fetch_nse_historical(symbol, days=365):
    end = datetime.now()
    start = end - timedelta(days=days)
    from_date = start.strftime('%d-%m-%Y')
    to_date = end.strftime('%d-%m-%Y')
    try:
        session = get_nse_session()
        url = f"https://www.nseindia.com/api/historical/cm/equity?symbol={symbol}&series=EQ&from={from_date}&to={to_date}"
        resp = session.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data:
                df = pd.DataFrame(data['data'])
                df['DATE'] = pd.to_datetime(df['DATE'], format='%d-%m-%Y')
                df = df.sort_values('DATE')
                # Handle different column names
                close_col = 'CH_CLOSING' if 'CH_CLOSING' in df.columns else 'CLOSE'
                high_col = 'CH_TRADE_HIGH_PRICE' if 'CH_TRADE_HIGH_PRICE' in df.columns else 'HIGH'
                low_col = 'CH_TRADE_LOW_PRICE' if 'CH_TRADE_LOW_PRICE' in df.columns else 'LOW'
                open_col = 'CH_OPENING_PRICE' if 'CH_OPENING_PRICE' in df.columns else 'OPEN'
                vol_col = 'CH_VOLUME' if 'CH_VOLUME' in df.columns else 'VOLUME'
                df['Close'] = df[close_col].astype(float)
                df['High'] = df[high_col].astype(float)
                df['Low'] = df[low_col].astype(float)
                df['Open'] = df[open_col].astype(float)
                df['Volume'] = df[vol_col].astype(float)
                return df[['DATE', 'Open', 'High', 'Low', 'Close', 'Volume']]
    except Exception as e:
        print(f"NSE historical error for {symbol}: {e}")
        return None

def get_data(symbol):
    live = fetch_nse_live(symbol)
    if live:
        hist = fetch_nse_historical(symbol)
        if hist is not None and len(hist) >= 200:
            return {'live': live, 'hist': hist}
    # Fallback to yfinance
    for suffix in ['.NS', '.BO']:
        try:
            ticker = yf.Ticker(f"{symbol}{suffix}")
            info = ticker.info
            hist = ticker.history(period="1y")
            if len(hist) >= 200 and info:
                price = info.get('regularMarketPrice', info.get('currentPrice', 0))
                prev_close = info.get('regularMarketPreviousClose', 0)
                volume = info.get('regularMarketVolume', 0)
                high_52w = info.get('fiftyTwoWeekHigh', 0)
                market_cap = info.get('marketCap', 0) / 10000000
                live = {'price': price, 'prev_close': prev_close, 'volume': volume,
                        'high_52w': high_52w, 'market_cap': market_cap}
                return {'live': live, 'hist': hist}
        except:
            continue
    return None

# ============================================
# GET ALL NSE STOCKS
# ============================================
def get_all_nse_stocks():
    print("📊 Fetching NSE stock list...")
    try:
        ds = load_dataset("tickertruth/nse-india-security-master", data_files="data/nse_security_master.csv")
        df = ds["train"].to_pandas()
        stocks = df[df["active_flag"] == True]["nse_symbol"].tolist()
        print(f"✅ Loaded {len(stocks)} stocks")
        return stocks
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK']

# ============================================
# CACHE FUNCTIONS
# ============================================
def load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
            print(f"✅ Cache loaded: {len(cache)} stocks")
            return cache
        else:
            print("ℹ️ No cache found, will build new")
            return {}
    except Exception as e:
        print(f"⚠️ Error loading cache: {e}")
        return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
        print(f"✅ Cache saved: {len(cache)} stocks")
    except Exception as e:
        print(f"⚠️ Error saving cache: {e}")

def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, 'wb') as f:
            pickle.dump(watchlist, f)
        print(f"✅ Watchlist saved to {WATCHLIST_FILE}")
    except Exception as e:
        print(f"⚠️ Error saving watchlist: {e}")

# ============================================
# CHARTINK-STYLE DEMA
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

def build_cache(stocks):
    print("🏗️ Building initial cache (this may take time)...")
    cache = {}
    total = len(stocks)
    built = 0
    for i, symbol in enumerate(stocks):
        try:
            data = get_data(symbol)
            if data is None:
                continue
            hist = data['hist']
            if len(hist) < 200:
                continue
            d10 = chartink_dema(hist['Close'], 10)
            d50 = chartink_dema(hist['Close'], 50)
            d200 = chartink_dema(hist['Close'], 200)
            if d10 is not None and d50 is not None and d200 is not None:
                avg_vol = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
                cache[symbol] = {
                    'dema_10': d10.iloc[-1],
                    'dema_50': d50.iloc[-1],
                    'dema_200': d200.iloc[-1],
                    'avg_volume': avg_vol,
                    'last_update': datetime.now().strftime('%Y-%m-%d')
                }
                built += 1
        except:
            pass
        if (i + 1) % 50 == 0:
            print(f"📊 Cache progress: {i+1}/{total} (built: {built})")
        time.sleep(0.1)
    print(f"✅ Cache built for {built} stocks")
    return cache

# ============================================
# PRE-FILTER USING CACHE
# ============================================
def pre_filter_with_cache(cache):
    shortlisted = []
    for symbol, data in cache.items():
        if symbol == '_last_update':
            continue
        if data.get('avg_volume', 0) <= 500000:
            continue
        if data.get('dema_50', 0) <= data.get('dema_200', 0):
            continue
        if data.get('dema_10', 0) <= data.get('dema_50', 0):
            continue
        shortlisted.append(symbol)
    print(f"📊 Pre-filtered {len(shortlisted)} stocks (from {len(cache)}) using cache only.")
    return shortlisted

# ============================================
# CONCURRENT NSE API FETCHING
# ============================================
def fetch_live_data_concurrent(symbols, max_workers=15):
    results = {}
    total = len(symbols)
    print(f"📊 Fetching live data for {total} stocks using {max_workers} threads...")
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {executor.submit(get_data, symbol): symbol for symbol in symbols}
        completed = 0
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                data = future.result(timeout=15)
                if data and data.get('live'):
                    results[symbol] = data['live']
                completed += 1
                if completed % 20 == 0:
                    print(f"  📊 Fetched {completed}/{total}...")
            except Exception as e:
                pass
            time.sleep(0.05)
    elapsed = time.time() - start_time
    print(f"✅ Live data fetch complete: {len(results)} stocks in {elapsed:.1f}s")
    return results

# ============================================
# CHECK STOCK - APPLIES REMAINING 7 FILTERS
# ============================================
def check_stock(symbol, cached, live_data):
    if symbol not in live_data:
        return None
    live = live_data[symbol]
    price = live['price']
    prev_close = live['prev_close']
    volume = live['volume']
    high_52w = live['high_52w']
    market_cap = live['market_cap']
    avg_volume = cached.get('avg_volume', 0)

    if prev_close > 0 and price > 0:
        day_change = ((price - prev_close) / prev_close) * 100
    else:
        day_change = 0

    volume_ratio = volume / avg_volume if avg_volume > 0 else 0
    pct_from_high = ((high_52w - price) / high_52w) * 100 if high_52w > 0 else 100

    cond1 = market_cap >= 1000
    cond2 = price >= 100
    cond3 = day_change >= 0
    cond4 = day_change < 15
    cond5 = volume >= 200000
    cond7 = pct_from_high <= 10
    cond10 = volume_ratio >= 1.5

    if cond1 and cond2 and cond3 and cond4 and cond5 and cond7 and cond10:
        return {
            'symbol': symbol,
            'price': price,
            'day_change': day_change,
            'volume_ratio': volume_ratio,
            'market_cap': market_cap,
            'pct_from_high': pct_from_high,
            'avg_volume': avg_volume,
            'volume': volume
        }
    return None

# ============================================
# NEWS AND CHART SCORE FUNCTIONS
# ============================================

def fetch_news_mock(symbol):
    mock_db = {
        'CGCL': {
            'headlines': ['Q3 Earnings Beat Estimates', 'Analyst Upgrade to Buy', 'Strong Order Book'],
            'sentiment': 0.85,
            'count': 3
        },
        'ATHERENERG': {
            'headlines': ['EV Sales Surge', 'New Model Launch'],
            'sentiment': 0.7,
            'count': 2
        },
        'FMGOETZE': {
            'headlines': ['M&A Rumors', 'Contract Win with Govt', 'Earnings Surprise'],
            'sentiment': 0.95,
            'count': 3
        },
        'GENUSPOWER': {
            'headlines': ['General Market Update'],
            'sentiment': 0.1,
            'count': 1
        },
    }
    return mock_db.get(symbol, {'headlines': [], 'sentiment': 0, 'count': 0})

def compute_news_score(symbol):
    data = fetch_news_mock(symbol)
    count = data['count']
    sentiment = data['sentiment']
    headlines = data['headlines']
    if count == 0:
        return 0
    count_score = min(count, 10) * 5
    sentiment_score = sentiment * 40
    catalyst_keywords = ['Earnings', 'Beat', 'Upgrade', 'M&A', 'Contract', 'FDA', 'Approval', 'Surprise', 'Launch']
    bonus = 0
    for head in headlines:
        if any(kw in head for kw in catalyst_keywords):
            bonus += 10
    bonus = min(bonus, 30)
    raw = count_score + sentiment_score + bonus
    return round(max(0, min(100, raw)), 2)

def compute_chart_score(df):
    # Now returns 0 if no data (instead of 50)
    if df is None or len(df) < 20:
        return 0
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    volume = df['Volume'].values
    open_prices = df['Open'].values

    # Trend Score (30%)
    if len(close) >= 20:
        sma20 = pd.Series(close).rolling(20).mean()
        if len(sma20) > 5:
            slope = (sma20.iloc[-1] - sma20.iloc[-5]) / sma20.iloc[-5] * 100
            trend_score = max(0, min(30, 30 * (slope / 5)))
        else:
            trend_score = 15
    else:
        trend_score = 15

    # Pattern Score (40%)
    pattern_score = 0
    if len(close) >= 20:
        if close[-1] > max(close[-20:-1]):
            pattern_score += 15
    if len(close) >= 3:
        if (close[-1] > open_prices[-1] and close[-2] < open_prices[-2] and 
            close[-1] > open_prices[-2] and open_prices[-1] < close[-2]):
            pattern_score += 10
        body = abs(close[-1] - open_prices[-1])
        if body > 0:
            lower_wick = min(open_prices[-1], close[-1]) - low[-1]
            upper_wick = high[-1] - max(open_prices[-1], close[-1])
            if lower_wick > 2 * body and upper_wick < 0.1 * body:
                pattern_score += 10
    pattern_score = min(40, pattern_score)

    # Volume & Momentum Score (30%)
    vol_score = 0
    avg_vol = pd.Series(volume).rolling(20).mean()
    if len(avg_vol) > 0 and volume[-1] > avg_vol.iloc[-1] * 1.5:
        vol_score = 15
    else:
        vol_score = 5

    rsi = RSIIndicator(pd.Series(close), window=14).rsi()
    if len(rsi) > 0:
        if rsi.iloc[-1] > 60:
            vol_score += 15
        elif rsi.iloc[-1] > 50:
            vol_score += 7
    vol_score = min(30, vol_score)

    total_chart_score = trend_score + pattern_score + vol_score
    return round(max(0, min(100, total_chart_score)), 2)

# ============================================
# TECHNICAL ANALYSIS FOR FINAL SHORTLIST (USES YFINANCE)
# ============================================

def detect_patterns(df):
    patterns = []
    try:
        if len(df) < 10:
            return patterns
        o = df['Open'].iloc[-5:].values
        h = df['High'].iloc[-5:].values
        l = df['Low'].iloc[-5:].values
        c = df['Close'].iloc[-5:].values
        i = -1

        if len(o) >= 2:
            if c[i] > o[i-1] and c[i-1] < o[i]:
                patterns.append("Bullish Engulfing")
        body = abs(c[i] - o[i])
        if body > 0:
            lower_wick = min(o[i], c[i]) - l[i]
            upper_wick = h[i] - max(o[i], c[i])
            if lower_wick > 2 * body and upper_wick < 0.1 * body:
                patterns.append("Hammer")
        if len(c) >= 3:
            if c[i-2] < o[i-2] and abs(c[i-1] - o[i-1]) < abs(c[i-2] - o[i-2]) and c[i] > o[i]:
                patterns.append("Morning Star")
        if len(c) >= 3:
            if (c[i-2] > o[i-2] and c[i-1] > o[i-1] and c[i] > o[i] and
                c[i-1] > c[i-2] and c[i] > c[i-1]):
                patterns.append("3 White Soldiers")
        if len(o) >= 2:
            if c[i-1] < o[i-1] and o[i] > c[i-1] and c[i] < o[i-1]:
                patterns.append("Bullish Harami")
        if len(c) >= 2:
            prev_body = o[i-1] - c[i-1]
            if prev_body > 0 and c[i] > o[i] and c[i] > o[i-1] - prev_body/2:
                patterns.append("Piercing Pattern")
    except:
        pass
    return patterns

def get_technical_data(symbol):
    """Fetches RSI, MACD, ATR, Patterns, OBV using yfinance (most reliable)."""
    try:
        df = None
        # Try .NS first, then .BO
        for suffix in ['.NS', '.BO']:
            try:
                ticker = yf.Ticker(f"{symbol}{suffix}")
                df = ticker.history(period="6mo")
                if not df.empty and len(df) >= 20:
                    break
            except:
                continue
        # If yfinance fails, fallback to NSE API (via get_data)
        if df is None or df.empty or len(df) < 20:
            full_data = get_data(symbol)
            if full_data and full_data.get('hist') is not None:
                df = full_data['hist']
        if df is None or len(df) < 20:
            return None

        current_price = df['Close'].iloc[-1]
        rsi_indicator = RSIIndicator(df['Close'], window=14)
        rsi = rsi_indicator.rsi().iloc[-1]
        macd_indicator = MACD(df['Close'], window_slow=26, window_fast=12, window_sign=9)
        macd_line = macd_indicator.macd().iloc[-1]
        signal_line = macd_indicator.macd_signal().iloc[-1]
        histogram = macd_indicator.macd_diff().iloc[-1]
        atr_indicator = AverageTrueRange(df['High'], df['Low'], df['Close'], window=14)
        atr = atr_indicator.average_true_range().iloc[-1]

        buy_price = round(current_price, 2)
        stop_loss = round(current_price - (1.5 * atr), 2)
        target_1 = round(current_price + (2 * atr), 2)
        target_2 = round(current_price + (3.5 * atr), 2)

        macd_trend = "🟢 Bullish" if macd_line > signal_line else "🔴 Bearish"
        if rsi > 70:
            rsi_status = "Overbought"
        elif rsi < 30:
            rsi_status = "Oversold"
        else:
            rsi_status = "Neutral"

        patterns = detect_patterns(df)

        obv_indicator = OnBalanceVolumeIndicator(df['Close'], df['Volume'])
        obv = obv_indicator.on_balance_volume()
        obv_rising = False
        obv_trend = "Flat"
        if len(obv) > 5:
            if obv.iloc[-1] > obv.iloc[-5]:
                obv_rising = True
                obv_trend = "📈 Accumulation"
            elif obv.iloc[-1] < obv.iloc[-5]:
                obv_trend = "📉 Distribution"
            else:
                obv_trend = "➡️ Neutral"

        chart_score = compute_chart_score(df)

        return {
            'rsi': round(rsi, 2),
            'rsi_status': rsi_status,
            'macd_line': round(macd_line, 2),
            'signal_line': round(signal_line, 2),
            'histogram': round(histogram, 2),
            'macd_trend': macd_trend,
            'buy_price': buy_price,
            'stop_loss': stop_loss,
            'target_1': target_1,
            'target_2': target_2,
            'patterns': patterns,
            'obv_trend': obv_trend,
            'obv_rising': obv_rising,
            'atr': round(atr, 2),
            'chart_score': chart_score,
            'chart_desc': 'Breakout' if chart_score > 70 else 'Consolidating' if chart_score > 50 else 'Weak'
        }
    except Exception as e:
        print(f"Error getting technical data for {symbol}: {e}")
        return None

def calculate_bullish_score(base_result, tech_data):
    if not tech_data:
        return 0
    score = 0
    if base_result['day_change'] >= 5:
        score += 3
    elif base_result['day_change'] >= 3:
        score += 2
    elif base_result['day_change'] >= 1:
        score += 1

    if base_result['volume_ratio'] >= 3:
        score += 3
    elif base_result['volume_ratio'] >= 2:
        score += 2
    else:
        score += 1

    rsi = tech_data['rsi']
    if 50 <= rsi <= 70:
        score += 2
    elif 40 <= rsi < 50:
        score += 1
    elif rsi > 70:
        score -= 1

    if tech_data['macd_trend'] == "🟢 Bullish":
        score += 2
    if tech_data['patterns']:
        score += 5
    if tech_data['obv_rising']:
        score += 3
    return score

# ============================================
# FORMAT FUNCTIONS
# ============================================

def format_detail_card(index, item):
    base = item['base']
    tech = item['tech']
    symbol = base['symbol']
    price = base['price']
    change = base['day_change']
    vol_ratio = base['volume_ratio']
    pct_high = base['pct_from_high']
    mcap = base['market_cap']

    medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else f"#{index}"

    msg = f"{medal} *{symbol}*\n"
    msg += f"💰 ₹{price:.2f} | 📈 {change:.2f}% | 📊 Vol: {vol_ratio:.2f}x\n"
    msg += f"📏 52W High: {pct_high:.1f}% | 💼 Mkt Cap: ₹{mcap:.2f} Cr\n"

    news_data = fetch_news_mock(symbol)
    news_summary = ", ".join(news_data['headlines'][:2]) if news_data['headlines'] else "No specific catalyst"
    news_sentiment = "Bullish" if news_data['sentiment'] > 0.3 else "Neutral" if news_data['sentiment'] > -0.3 else "Bearish"
    chart_desc = tech.get('chart_desc', 'N/A') if tech else 'N/A'

    msg += f"\n🧠 *News:* {news_sentiment} ({news_summary}) | {news_data['count']} headlines | *Chart:* {chart_desc}\n"
    msg += f"📊 *Scores:* Tech: {item['tech_score']}/100 | News: {item['news_score']}/100 | Chart: {item['chart_score']}/100 | Combined: {item['combined_score']}/100\n"

    if tech:
        msg += f"\n📊 *RSI:* {tech['rsi']} ({tech['rsi_status']}) | *MACD:* {tech['macd_trend']}\n"
        msg += (f"\n🎯 *Buy:* ₹{tech['buy_price']} | 🛑 *SL:* ₹{tech['stop_loss']} | "
                f"🚀 *T1:* ₹{tech['target_1']} | 🌟 *T2:* ₹{tech['target_2']}\n")
        if tech['patterns']:
            msg += f"\n📐 *Patterns:* {', '.join(tech['patterns'])} ✅\n"
        else:
            msg += f"\n📐 *Patterns:* None detected\n"
        msg += f"📦 *Order Flow:* {tech['obv_trend']}\n"
    else:
        msg += f"\n❌ *Technical data not available*\n"

    msg += "━" * 30
    return msg

def format_summary_list(enriched_results):
    total = len(enriched_results)
    msg = f"📊 *🏆 RANKED RESULTS ({total} stocks)*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, item in enumerate(enriched_results[:20], 1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        msg += f"{medal} {item['base']['symbol']} (Combined: {item['combined_score']})\n"
    if total > 20:
        msg += f"\n... and {total - 20} more stocks."
    msg += "\n\n👇 *Tap a button below to view full details.*"
    return msg

# ============================================
# TELEGRAM CALLBACK HANDLER
# ============================================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    bot.answer_callback_query(call.id)
    data = call.data
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if data == "back_to_list":
        if 'summary_msg' in STORED_RESULTS and 'keyboard' in STORED_RESULTS:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=STORED_RESULTS['summary_msg'],
                reply_markup=STORED_RESULTS['keyboard'],
                parse_mode='Markdown'
            )
        else:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⚠️ Data expired. Please run the screener again.",
                parse_mode='Markdown'
            )
        return

    if data.startswith("show_detail:"):
        symbol = data.split(":")[1]
        target_item = None
        target_index = None
        for idx, item in enumerate(STORED_RESULTS.get('items', []), 1):
            if item['base']['symbol'] == symbol:
                target_item = item
                target_index = idx
                break

        if not target_item:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⚠️ Stock data not found.",
                parse_mode='Markdown'
            )
            return

        detail_msg = format_detail_card(target_index, target_item)
        back_keyboard = types.InlineKeyboardMarkup(row_width=1)
        back_keyboard.add(types.InlineKeyboardButton("⬅️ Back to List", callback_data="back_to_list"))

        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=detail_msg,
            reply_markup=back_keyboard,
            parse_mode='Markdown'
        )

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    global STORED_RESULTS

    print("\n🚀 Starting scan...")
    print("-" * 70)

    bot.send_message(YOUR_CHAT_ID, "🌅 *Morning Screener is running!*", parse_mode='Markdown')

    stocks = get_all_nse_stocks()
    print(f"📊 Total NSE stocks: {len(stocks)}")

    cache = load_cache()
    if not cache:
        cache = build_cache(stocks)
        save_cache(cache)
    else:
        last_update = cache.get('_last_update', '')
        if last_update:
            try:
                last_date = datetime.strptime(last_update, '%Y-%m-%d')
                if (datetime.now() - last_date).days >= 1:
                    print("📅 Cache is old, rebuilding...")
                    cache = build_cache(stocks)
                    save_cache(cache)
            except:
                pass

    cache['_last_update'] = datetime.now().strftime('%Y-%m-%d')
    save_cache(cache)

    pre_filtered_symbols = pre_filter_with_cache(cache)
    if not pre_filtered_symbols:
        bot.send_message(YOUR_CHAT_ID, "📊 *No stocks passed the DEMA/Volume pre-filters.*", parse_mode='Markdown')
        return

    live_data = fetch_live_data_concurrent(pre_filtered_symbols, max_workers=15)

    print("-" * 70)
    print("⚡ Running remaining 7 filters...")
    print("-" * 70)

    results = []
    start_time = time.time()
    for symbol in pre_filtered_symbols:
        if symbol not in live_data:
            continue
        cached = cache.get(symbol)
        if cached is None:
            continue
        result = check_stock(symbol, cached, live_data)
        if result:
            results.append(result)
        time.sleep(0.02)

    print("-" * 70)
    print(f"✅ Scan complete! Found {len(results)} stocks passing all 10 filters.")
    print(f"⏱️ Total time taken: {time.time() - start_time:.1f} seconds")

    if results:
        save_watchlist(results)

        print("📊 Enriching results with technical data and ranking...")
        bot.send_message(YOUR_CHAT_ID, "⏳ *Calculating technicals & ranking...*", parse_mode='Markdown')

        enriched_results = []

        for res in results:
            tech_data = get_technical_data(res['symbol'])
            if tech_data:
                score = calculate_bullish_score(res, tech_data)
                enriched_results.append({
                    'base': res,
                    'tech': tech_data,
                    'score': score
                })
            else:
                enriched_results.append({
                    'base': res,
                    'tech': None,
                    'score': 0
                })
            time.sleep(0.1)

        # Compute final scores
        for item in enriched_results:
            tech_raw = item['score']
            tech_score = min(100, (tech_raw / 18) * 100) if tech_raw > 0 else 0
            news_score = compute_news_score(item['base']['symbol']) if item['tech'] else 0
            chart_score = item['tech'].get('chart_score', 0) if item['tech'] else 0
            combined = (tech_score * 0.50) + (news_score * 0.30) + (chart_score * 0.20)

            item['tech_score'] = round(tech_score, 2)
            item['news_score'] = news_score
            item['chart_score'] = chart_score
            item['combined_score'] = round(combined, 2)

        # Sort by combined score descending
        enriched_results.sort(key=lambda x: x['combined_score'], reverse=True)

        STORED_RESULTS['items'] = enriched_results

        summary_msg = format_summary_list(enriched_results)
        STORED_RESULTS['summary_msg'] = summary_msg

        keyboard = types.InlineKeyboardMarkup(row_width=3)
        buttons = []
        for idx, item in enumerate(enriched_results[:20], 1):
            symbol = item['base']['symbol']
            label = f"{idx}.{symbol}" if idx <= 9 else symbol
            buttons.append(types.InlineKeyboardButton(label, callback_data=f"show_detail:{symbol}"))

        for i in range(0, len(buttons), 3):
            keyboard.add(*buttons[i:i+3])

        STORED_RESULTS['keyboard'] = keyboard

        bot.send_message(
            YOUR_CHAT_ID,
            summary_msg,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

    else:
        bot.send_message(YOUR_CHAT_ID, "📊 *No stocks found matching all 10 filters today.*", parse_mode='Markdown')

    print("✅ Done!")

# ============================================
# MAIN EXECUTION
# ============================================
if __name__ == "__main__":
    print("=" * 70)
    print("🌅 MORNING SCREENER - GITHUB ACTIONS OPTIMIZED")
    print("=" * 70)

    run_scanner()

    print("\n✅ Bot finished sending results! Exiting cleanly.")
