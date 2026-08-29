import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
import pickle
import requests
from datetime import datetime, timedelta
import telebot
from datasets import load_dataset
import pandas_ta as ta

# ============================================
# BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)
CACHE_FILE = "screener_cache.pkl"
WATCHLIST_FILE = "morning_watchlist.pkl"

print("=" * 70)
print("🌅 MORNING SCREENER - NSE API + FALLBACK")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# NSE API HELPERS (ORIGINAL)
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
                df['Close'] = df['CH_CLOSING'].astype(float)
                df['Volume'] = df['CH_VOLUME'].astype(float)
                return df[['DATE', 'Close', 'Volume']]
    except:
        return None

def get_data(symbol):
    live = fetch_nse_live(symbol)
    if live:
        hist = fetch_nse_historical(symbol)
        if hist is not None and len(hist) >= 200:
            return {'live': live, 'hist': hist}
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
# GET ALL NSE STOCKS (ORIGINAL)
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
# CACHE FUNCTIONS (ORIGINAL)
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

# ============================================
# CHARTINK-STYLE DEMA (ORIGINAL)
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

# ============================================
# BUILD CACHE (ORIGINAL)
# ============================================
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
                    'market_cap': data['live']['market_cap'],
                    'last_update': datetime.now().strftime('%Y-%m-%d')
                }
                built += 1
        except:
            pass
        if (i + 1) % 50 == 0:
            print(f"📊 Cache progress: {i+1}/{total} (built: {built})")
        time.sleep(0.05)
    print(f"✅ Cache built for {built} stocks")
    return cache

# ============================================
# SAVE WATCHLIST (ORIGINAL)
# ============================================
def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, 'wb') as f:
            pickle.dump(watchlist, f)
        print(f"✅ Watchlist saved to {WATCHLIST_FILE}")
    except Exception as e:
        print(f"⚠️ Error saving watchlist: {e}")

# ============================================
# CHECK STOCK - 10 FILTERS (UNCHANGED)
# ============================================
def check_stock(symbol, cached):
    try:
        data = get_data(symbol)
        if data is None:
            return None
        live = data['live']
        price = live['price']
        prev_close = live['prev_close']
        volume = live['volume']
        high_52w = live['high_52w']
        market_cap = live['market_cap']
        avg_volume = cached.get('avg_volume', 0)
        dema_10 = cached.get('dema_10', 0)
        dema_50 = cached.get('dema_50', 0)
        dema_200 = cached.get('dema_200', 0)

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
        cond6 = avg_volume > 500000
        cond7 = pct_from_high <= 10
        cond8 = dema_50 > dema_200
        cond9 = dema_10 > dema_50
        cond10 = volume_ratio >= 1.5

        if cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10:
            return {
                'symbol': symbol,
                'price': price,
                'day_change': day_change,
                'volume_ratio': volume_ratio,
                'market_cap': market_cap,
                'pct_from_high': pct_from_high,
                'avg_volume': avg_volume,
                'volume': volume,
                'dema_10': dema_10,
                'dema_50': dema_50,
                'dema_200': dema_200
            }
        return None
    except:
        return None

# ============================================
# 🆕 ENRICHMENT FUNCTIONS (ADD-ON DATA)
# ============================================

def detect_patterns(df):
    """Detects bullish candlestick patterns in the last 5 candles."""
    patterns = []
    try:
        if len(df) < 10:
            return patterns
        
        # Check only the most recent candle (index -1) for clear signals, 
        # but also look if pattern occurred in last 5 days.
        o = df['Open']
        h = df['High']
        l = df['Low']
        c = df['Close']
        
        # Bullish Engulfing
        engulf = ta.cdl_engulfing(o, h, l, c)
        if engulf.iloc[-1] == 100 or engulf.iloc[-2] == 100:
            patterns.append("Bullish Engulfing")
        
        # Hammer
        hammer = ta.cdl_hammer(o, h, l, c)
        if hammer.iloc[-1] != 0:
            patterns.append("Hammer")
        
        # Morning Star
        ms = ta.cdl_morning_star(o, h, l, c)
        if ms.iloc[-1] != 0 or ms.iloc[-2] != 0:
            patterns.append("Morning Star")
        
        # Three White Soldiers
        tws = ta.cdl_three_white_soldiers(o, h, l, c)
        if tws.iloc[-1] != 0:
            patterns.append("3 White Soldiers")
        
        # Bullish Harami
        harami = ta.cdl_harami(o, h, l, c)
        if harami.iloc[-1] != 0:
            patterns.append("Bullish Harami")
        
        # Golden Cross Check (50 DEMA > 200 DEMA) - we already have this as a filter, but confirming
        # Actually, we'll just use the DEMA from cache for the summary.
        
    except Exception as e:
        pass
    return patterns

def fetch_enriched_data(symbol, cached):
    """Fetches RSI, MACD, ATR, Patterns, OBV for a single stock."""
    try:
        ticker = yf.Ticker(symbol + ".NS")
        df = ticker.history(period="3mo", interval="1d")
        if df.empty or len(df) < 20:
            ticker = yf.Ticker(symbol + ".BO")
            df = ticker.history(period="3mo", interval="1d")
        if df.empty or len(df) < 20:
            return None
        
        # Indicators
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        macd_data = ta.macd(df['Close'], fast=12, slow=26, signal=9)
        macd_line = macd_data['MACD_12_26_9'].iloc[-1]
        signal_line = macd_data['MACDs_12_26_9'].iloc[-1]
        histogram = macd_data['MACDh_12_26_9'].iloc[-1]
        
        # ATR
        atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]
        
        # Trade Plan
        current_price = df['Close'].iloc[-1]
        buy_price = round(current_price, 2)
        stop_loss = round(current_price - (1.5 * atr), 2)
        target_1 = round(current_price + (2 * atr), 2)
        target_2 = round(current_price + (3.5 * atr), 2)
        
        # MACD Trend
        macd_trend = "🟢 Bullish" if macd_line > signal_line else "🔴 Bearish"
        
        # RSI Status
        if rsi > 70: rsi_status = "Overbought"
        elif rsi < 30: rsi_status = "Oversold"
        else: rsi_status = "Neutral"
        
        # Patterns
        patterns = detect_patterns(df)
        
        # Order Flow (OBV - On Balance Volume)
        obv = ta.obv(df['Close'], df['Volume'])
        obv_rising = False
        if len(obv) > 5:
            if obv.iloc[-1] > obv.iloc[-5]:
                obv_rising = True
        
        return {
            'rsi': round(rsi, 2),
            'macd_line': round(macd_line, 2),
            'signal_line': round(signal_line, 2),
            'histogram': round(histogram, 2),
            'macd_trend': macd_trend,
            'rsi_status': rsi_status,
            'buy_price': buy_price,
            'stop_loss': stop_loss,
            'target_1': target_1,
            'target_2': target_2,
            'patterns': patterns,
            'obv_rising': obv_rising,
            'atr': round(atr, 2)
        }
    except Exception as e:
        return None

def calculate_bullish_score(base_result, enriched):
    """Ranks stocks so the most promising appears at the top."""
    if not enriched:
        return 0
    score = 0
    
    # 1. Day Change (weight: 3)
    if base_result['day_change'] >= 5: score += 3
    elif base_result['day_change'] >= 3: score += 2
    elif base_result['day_change'] >= 1: score += 1
    
    # 2. Volume Ratio (weight: 3)
    if base_result['volume_ratio'] >= 3: score += 3
    elif base_result['volume_ratio'] >= 2: score += 2
    else: score += 1
    
    # 3. RSI (weight: 2) - Healthy bullish is 50-70
    if 50 <= enriched['rsi'] <= 70: score += 2
    elif 40 <= enriched['rsi'] < 50: score += 1
    elif enriched['rsi'] > 70: score -= 1  # Overbought penalty
    
    # 4. MACD Trend (weight: 2)
    if enriched['macd_trend'] == "🟢 Bullish": score += 2
    
    # 5. Patterns (weight: 5) - Major bonus
    if enriched['patterns']:
        score += 5
    
    # 6. OBV Rising (weight: 3)
    if enriched['obv_rising']:
        score += 3
    
    return score

def format_enriched_result(index, base_result, enriched):
    """Formats the final output message for a single stock."""
    symbol = base_result['symbol']
    price = base_result['price']
    change = base_result['day_change']
    vol_ratio = base_result['volume_ratio']
    pct_high = base_result['pct_from_high']
    mcap = base_result['market_cap']
    
    medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else f"#{index}"
    
    # Base details
    msg = f"{medal} *{symbol}* (Score: {calculate_bullish_score(base_result, enriched)})\n"
    msg += f"💰 ₹{price:.2f} | 📈 {change:.2f}% | 📊 Vol: {vol_ratio:.2f}x\n"
    msg += f"📏 52W High: {pct_high:.1f}% | 💼 Mkt Cap: ₹{mcap:.2f} Cr\n"
    
    if enriched:
        # Technicals
        msg += f"📊 RSI: {enriched['rsi']} ({enriched['rsi_status']}) | MACD: {enriched['macd_line']} ({enriched['macd_trend']})\n"
        # Trade Plan
        msg += (f"🎯 *Buy:* ₹{enriched['buy_price']} | "
                f"🛑 *SL:* ₹{enriched['stop_loss']} | "
                f"🚀 *T1:* ₹{enriched['target_1']} | "
                f"🌟 *T2:* ₹{enriched['target_2']}\n")
        # Patterns
        if enriched['patterns']:
            msg += f"📐 *Patterns:* {', '.join(enriched['patterns'])} ✅\n"
        else:
            msg += f"📐 *Patterns:* None detected\n"
        # Order Flow
        if enriched['obv_rising']:
            msg += f"📦 *Order Flow:* OBV Rising 📈 (Accumulation)\n"
        else:
            msg += f"📦 *Order Flow:* OBV Flat/Down\n"
    else:
        msg += f"❌ Could not fetch technical data.\n"
    
    msg += "━" * 30
    return msg

# ============================================
# MAIN SCANNER (MODIFIED TO ENRICH AND SORT)
# ============================================
def run_scanner(chat_id=None):
    send_to = chat_id if chat_id else YOUR_CHAT_ID
    
    print("\n🚀 Starting scan...")
    print("-" * 70)
    bot.send_message(send_to, "🌅 *Morning Screener is running!*", parse_mode='Markdown')

    stocks = get_all_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")

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

    print("-" * 70)
    print("⚡ Scoring stocks...")
    print("-" * 70)

    results = []
    start_time = time.time()
    for i, symbol in enumerate(stocks):
        cached = cache.get(symbol)
        if cached is None:
            continue
        result = check_stock(symbol, cached)
        if result:
            results.append(result)
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        time.sleep(0.05)

    print("-" * 70)
    print(f"✅ Scan complete! Found {len(results)} stocks passing filters.")
    print(f"⏱️ Time taken: {time.time() - start_time:.1f} seconds")

    if results:
        save_watchlist(results)
        
        # ============================================
        # 🆕 ENRICH, SCORE, SORT, and DISPLAY
        # ============================================
        print("📊 Enriching results with technical data and ranking...")
        enriched_results = []
        
        for res in results:
            enriched = fetch_enriched_data(res['symbol'], cache.get(res['symbol']))
            if enriched:
                score = calculate_bullish_score(res, enriched)
                enriched_results.append({
                    'base': res,
                    'enriched': enriched,
                    'score': score
                })
            else:
                # Still include but with lower priority if tech data fails
                enriched_results.append({
                    'base': res,
                    'enriched': None,
                    'score': 0
                })
        
        # Sort by score descending (highest = most promising)
        enriched_results.sort(key=lambda x: x['score'], reverse=True)
        
        # Send summary
        summary = f"📊 *Top {len(enriched_results)} Ranked Stocks*\n"
        for idx, item in enumerate(enriched_results[:15], 1):
            summary += f"{idx}. {item['base']['symbol']} (Score: {item['score']})\n"
        bot.send_message(send_to, summary, parse_mode='Markdown')
        
        # Send detailed cards for Top 10
        for idx, item in enumerate(enriched_results[:10], 1):
            msg = format_enriched_result(idx, item['base'], item['enriched'])
            bot.send_message(send_to, msg, parse_mode='Markdown')
            time.sleep(0.2)  # Avoid rate limiting
        
        if len(enriched_results) > 10:
            bot.send_message(send_to, f"✅ And {len(enriched_results)-10} more stocks... use /scan to refresh.")
            
    else:
        bot.send_message(send_to, "📊 *No stocks found matching all 10 filters today.*", parse_mode='Markdown')
    
    return results

# ============================================
# TELEGRAM COMMAND HANDLERS
# ============================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message,
                 "👋 *Hello! I am your Ranked NSE Screener!*\n\n"
                 "Commands:\n"
                 "• /scan - Run screener & see ranked results\n"
                 "• /trade SYMBOL - Get full RSI/MACD setup\n"
                 "• /help - Show this menu\n\n"
                 "_Top rank = Highest Bullish Score (Patterns + OBV + Momentum)_",
                 parse_mode='Markdown')

@bot.message_handler(commands=['scan'])
def handle_scan(message):
    bot.reply_to(message, "⏳ Scanning NSE stocks... Please wait (2-3 min).")
    try:
        run_scanner(chat_id=message.chat.id)
    except Exception as e:
        print(f"Scan error: {e}")
        bot.reply_to(message, "❌ Scanner failed. Check logs.")

@bot.message_handler(commands=['trade'])
def handle_trade(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Please provide a symbol.\nExample: `/trade COFORGE`", parse_mode='Markdown')
            return
        symbol = parts[1].upper().strip()
        bot.reply_to(message, f"⏳ Fetching data for *{symbol}*...", parse_mode='Markdown')
        
        # Use the existing /trade logic (keep it simple for single stocks)
        try:
            ticker = yf.Ticker(symbol + ".NS")
            df = ticker.history(period="3mo", interval="1d")
            if df.empty or len(df) < 20:
                ticker = yf.Ticker(symbol + ".BO")
                df = ticker.history(period="3mo", interval="1d")
            if df.empty or len(df) < 20:
                bot.reply_to(message, f"❌ No data for {symbol}.")
                return
            current_price = df['Close'].iloc[-1]
            rsi = ta.rsi(df['Close'], length=14).iloc[-1]
            macd_data = ta.macd(df['Close'], fast=12, slow=26, signal=9)
            macd_line = macd_data['MACD_12_26_9'].iloc[-1]
            signal_line = macd_data['MACDs_12_26_9'].iloc[-1]
            histogram = macd_data['MACDh_12_26_9'].iloc[-1]
            atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]
            buy_price = round(current_price, 2)
            stop_loss = round(current_price - (1.5 * atr), 2)
            target_1 = round(current_price + (2 * atr), 2)
            target_2 = round(current_price + (3.5 * atr), 2)
            trend = "🟢 BULLISH" if macd_line > signal_line else "🔴 BEARISH"
            rsi_status = "Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"
            
            msg = (f"📊 *Trade Setup for {symbol}*\n"
                   f"━━━━━━━━━━━━━━━━━\n"
                   f"💰 *Price:* ₹{buy_price}\n"
                   f"📈 *Trend:* {trend}\n\n"
                   f"🔄 *Indicators:*\n"
                   f"   • RSI: {round(rsi, 2)} ({rsi_status})\n"
                   f"   • MACD: {round(macd_line, 2)}\n"
                   f"   • Signal: {round(signal_line, 2)}\n"
                   f"   • Hist: {round(histogram, 2)}\n\n"
                   f"🎯 *Trade Plan:*\n"
                   f"   ✅ Buy: ₹{buy_price}\n"
                   f"   🛑 SL: ₹{stop_loss} (Risk: ₹{round(current_price - stop_loss, 2)})\n"
                   f"   🚀 T1: ₹{target_1} (1:2 R/R)\n"
                   f"   🌟 T2: ₹{target_2} (1:3 R/R)\n\n"
                   f"⚠️ *Not financial advice.*")
            bot.send_message(message.chat.id, msg, parse_mode='Markdown')
        except Exception as e:
            bot.reply_to(message, f"❌ Error fetching {symbol}: {e}")
            
    except Exception as e:
        print(f"Trade command error: {e}")
        bot.reply_to(message, "❌ Error processing your request.")

# ============================================
# MAIN EXECUTION
# ============================================
if __name__ == "__main__":
    print("=" * 70)
    print("🌅 MORNING SCREENER BOT - STARTING (RANKED OUTPUT)")
    print("=" * 70)

    print("🔄 Running initial scan on startup...")
    run_scanner(chat_id=YOUR_CHAT_ID)

    print("=" * 70)
    print("✅ Bot is ONLINE and listening for commands!")
    print("Commands: /scan, /trade SYMBOL, /start, /help")
    print("Press Ctrl+C to stop.")
    print("=" * 70)
    bot.infinity_polling()
