import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
import pickle
from datetime import datetime, timedelta
import telebot
from datasets import load_dataset

# ============================================
# YOUR DOUBLE BOTTOM BOT DETAILS
# ============================================
BOT_TOKEN = "8845742478:AAFQ_WRTUeMa5brPkiJHYevnWjLyg-fo6aQ"
YOUR_CHAT_ID = "5261154533"
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)
CACHE_FILE = "double_bottom_cache.pkl"

print("=" * 70)
print("🔍 DOUBLE BOTTOM PATTERN SCANNER")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
    print(f"✅ Chat ID: {YOUR_CHAT_ID}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

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
# DEMA CALCULATION
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

# ============================================
# DOUBLE BOTTOM DETECTION
# ============================================
def detect_double_bottom(close_prices, lookback=30):
    if len(close_prices) < lookback:
        return False, {}
    
    recent = close_prices[-lookback:]
    
    lows = []
    for i in range(5, len(recent) - 5):
        window = recent[i-5:i+6]
        if recent[i] == min(window):
            lows.append((i, recent[i]))
    
    if len(lows) < 2:
        return False, {}
    
    low1 = lows[-2]
    low2 = lows[-1]
    
    if low1[1] <= 0 or low2[1] <= 0:
        return False, {}
    
    diff_pct = abs((low2[1] - low1[1]) / low1[1])
    if diff_pct > 0.05:
        return False, {}
    
    peak_price = max(recent[low1[0]:low2[0]+1])
    
    if peak_price < low1[1] * 1.03:
        return False, {}
    
    current_price = recent[-1]
    if current_price < peak_price * 0.99:
        return False, {}
    
    return True, {
        'low1': low1[1],
        'low2': low2[1],
        'peak': peak_price,
        'current': current_price,
        'breakout_pct': ((current_price - peak_price) / peak_price) * 100,
        'days_between': low2[0] - low1[0]
    }

# ============================================
# BUILD CACHE
# ============================================
def build_cache(stocks):
    print("🏗️ Building initial cache (this will take ~15-20 minutes)...")
    cache = {}
    total = len(stocks)
    
    for i, symbol in enumerate(stocks):
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            hist = ticker.history(period="1y")
            
            if len(hist) >= 200:
                d50 = chartink_dema(hist['Close'], 50)
                d200 = chartink_dema(hist['Close'], 200)
                
                if d50 is not None and d200 is not None:
                    avg_volume = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
                    
                    cache[symbol] = {
                        'dema_50': d50.iloc[-1],
                        'dema_200': d200.iloc[-1],
                        'avg_volume': avg_volume,
                        'last_update': datetime.now().strftime('%Y-%m-%d'),
                        'close_prices': hist['Close'].tolist()[-200:]
                    }
        except:
            pass
        
        if (i + 1) % 100 == 0:
            print(f"📊 Cache progress: {i+1}/{total}")
        
        time.sleep(0.1)
    
    print(f"✅ Cache built for {len(cache)} stocks")
    return cache

# ============================================
# CHECK STOCK FOR DOUBLE BOTTOM
# ============================================
def check_double_bottom(symbol, cache):
    try:
        cached = cache.get(symbol)
        if cached is None:
            return {'symbol': symbol, 'passed': False}
        
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        
        if not info:
            return {'symbol': symbol, 'passed': False}
        
        price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        market_cap_raw = info.get('marketCap', 0) / 10000000
        volume = info.get('regularMarketVolume', 0)
        
        close_prices = cached.get('close_prices', [])
        avg_volume = cached.get('avg_volume', 0)
        dema_50 = cached.get('dema_50', 0)
        dema_200 = cached.get('dema_200', 0)
        
        has_pattern, pattern_details = detect_double_bottom(close_prices)
        
        if not has_pattern:
            return {'symbol': symbol, 'passed': False}
        
        cond1 = market_cap_raw >= 1000
        cond2 = price >= 100
        cond3 = volume >= 1.5 * avg_volume if avg_volume > 0 else False
        cond4 = dema_50 > dema_200
        
        passed = cond1 and cond2 and cond3 and cond4
        
        return {
            'symbol': symbol,
            'passed': passed,
            'price': price,
            'volume': volume,
            'avg_volume': avg_volume,
            'volume_ratio': volume / avg_volume if avg_volume > 0 else 0,
            'market_cap': market_cap_raw,
            'golden_cross': cond4,
            'low1': pattern_details.get('low1', 0),
            'low2': pattern_details.get('low2', 0),
            'peak': pattern_details.get('peak', 0),
            'breakout_pct': pattern_details.get('breakout_pct', 0),
            'days_between': pattern_details.get('days_between', 0)
        }
        
    except Exception as e:
        return {'symbol': symbol, 'passed': False}

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting Double Bottom scan...")
    print("-" * 70)
    
    stocks = get_all_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
            print(f"✅ Cache loaded: {len(cache)} stocks")
        except:
            pass
    
    if not cache:
        cache = build_cache(stocks)
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
        print("✅ Cache saved")
    
    print("-" * 70)
    print("⚡ Scanning using cached data...")
    print("-" * 70)
    
    alerts = 0
    start_time = time.time()
    
    for i, symbol in enumerate(stocks):
        result = check_double_bottom(symbol, cache)
        
        if result.get('passed', False):
            alerts += 1
            print(f"✅ {symbol} - DOUBLE BOTTOM FOUND!")
            try:
                # SIMPLIFIED ALERT: Only stock name
                bot.send_message(YOUR_CHAT_ID, f"🔔 *{symbol}*", parse_mode='Markdown')
            except:
                pass
        
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        
        time.sleep(0.05)
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {alerts} double bottom patterns.")
    print(f"⏱️ Time taken: {time.time() - start_time:.1f} seconds")
    
    if alerts == 0:
        try:
            bot.send_message(YOUR_CHAT_ID, "📊 *No double bottom patterns found* today.", parse_mode='Markdown')
        except:
            pass

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, 
        "🔍 *Double Bottom Pattern Scanner*\n\n"
        "I scan ALL NSE stocks for Double Bottom patterns.\n\n"
        "📊 *Conditions:*\n"
        "• Double Bottom pattern (two lows within 5%)\n"
        "• Volume spike (≥ 1.5x avg)\n"
        "• Golden Cross (50 DEMA > 200 DEMA)\n"
        "• Price ≥ ₹100\n"
        "• Market Cap ≥ ₹1000 Cr\n\n"
        "I'll alert you with just the stock name when conditions are met!",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['status'])
def status(message):
    cache_size = 0
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
                cache_size = len(cache)
        except:
            pass
    
    bot.reply_to(message, 
        f"✅ *Scanner Status*\n"
        f"📦 Cache: {cache_size} stocks\n"
        f"🔄 Scans every 10 minutes",
        parse_mode='Markdown'
    )

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🔍 Double Bottom Scanner is running!", parse_mode='Markdown')
    except:
        pass
    
    run_scanner()
    print("\n✅ Done!")
