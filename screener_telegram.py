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
# YOUR BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)
CACHE_FILE = "stock_cache.pkl"

print("=" * 70)
print("🤖 NSE STOCK SCREENER - CACHED VERSION")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

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
            print("ℹ️ No cache found")
            return {}
    except Exception as e:
        print(f"⚠️ Cache load error: {e}")
        return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
        print(f"✅ Cache saved: {len(cache)} stocks")
    except Exception as e:
        print(f"⚠️ Cache save error: {e}")

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
# CHARTINK-STYLE DEMA
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

# ============================================
# BUILD CACHE (First Run Only)
# ============================================
def build_cache(stocks):
    """Build cache with historical data for all stocks"""
    print("🏗️ Building initial cache (this will take ~15-20 minutes)...")
    cache = {}
    total = len(stocks)
    
    for i, symbol in enumerate(stocks):
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            hist = ticker.history(period="1y")
            
            if len(hist) >= 200:
                # Calculate DEMAs and store them
                d10 = chartink_dema(hist['Close'], 10)
                d50 = chartink_dema(hist['Close'], 50)
                d200 = chartink_dema(hist['Close'], 200)
                
                if d10 is not None and d50 is not None and d200 is not None:
                    # Calculate 21-day average volume
                    avg_volume = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
                    
                    cache[symbol] = {
                        'dema_10': d10.iloc[-1],
                        'dema_50': d50.iloc[-1],
                        'dema_200': d200.iloc[-1],
                        'avg_volume': avg_volume,
                        'last_update': datetime.now().strftime('%Y-%m-%d'),
                        'historical_close': hist['Close'].tolist()[-200:]  # Store last 200 days
                    }
        
        except Exception as e:
            pass
        
        if (i + 1) % 100 == 0:
            print(f"📊 Cache progress: {i+1}/{total}")
        
        time.sleep(0.1)
    
    print(f"✅ Cache built for {len(cache)} stocks")
    return cache

# ============================================
# CHECK STOCK - USING CACHE
# ============================================
def check_stock(symbol, cache):
    try:
        # Get cached data
        cached = cache.get(symbol)
        if cached is None:
            return {'symbol': symbol, 'passed': False}
        
        # Get ONLY today's data (fast!)
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        today = ticker.history(period="1d")
        
        if not info:
            return {'symbol': symbol, 'passed': False}
        
        # Use cached DEMA values
        dema_10 = cached['dema_10']
        dema_50 = cached['dema_50']
        dema_200 = cached['dema_200']
        avg_volume = cached['avg_volume']
        
        # Get live data
        price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        market_cap_raw = info.get('marketCap', 0) / 10000000
        prev_close = info.get('regularMarketPreviousClose', 0)
        volume = info.get('regularMarketVolume', 0)
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        
        if prev_close > 0 and price > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        
        # Check 10 conditions
        cond1 = market_cap_raw >= 1000
        cond2 = price >= 100
        cond3 = day_change >= 0
        cond4 = day_change < 15
        cond5 = volume >= 200000
        cond6 = avg_volume > 500000
        cond7 = high_52w > 0 and (high_52w / price) - 1 <= 0.10
        cond8 = dema_200 > 0 and (dema_50 / dema_200) >= 1.0
        cond9 = dema_50 > 0 and (dema_10 / dema_50) >= 1.0
        cond10 = volume_ratio >= 1.5
        
        passed = cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10
        
        return {
            'symbol': symbol,
            'passed': passed,
            'price': price,
            'day_change': day_change,
            'volume': volume,
            'volume_ratio': volume_ratio
        }
        
    except Exception as e:
        return {'symbol': symbol, 'passed': False}

# ============================================
# UPDATE CACHE (Daily)
# ============================================
def update_cache(cache, stocks):
    """Update cache daily to refresh DEMA values"""
    print("🔄 Updating cache (daily refresh)...")
    updated = 0
    
    for symbol in stocks:
        if symbol in cache:
            try:
                ticker = yf.Ticker(f"{symbol}.NS")
                hist = ticker.history(period="1y")
                
                if len(hist) >= 200:
                    d10 = chartink_dema(hist['Close'], 10)
                    d50 = chartink_dema(hist['Close'], 50)
                    d200 = chartink_dema(hist['Close'], 200)
                    
                    if d10 is not None and d50 is not None and d200 is not None:
                        cache[symbol]['dema_10'] = d10.iloc[-1]
                        cache[symbol]['dema_50'] = d50.iloc[-1]
                        cache[symbol]['dema_200'] = d200.iloc[-1]
                        cache[symbol]['avg_volume'] = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
                        cache[symbol]['last_update'] = datetime.now().strftime('%Y-%m-%d')
                        updated += 1
            except:
                pass
            time.sleep(0.05)
    
    print(f"✅ Updated {updated} stocks")
    return cache

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting fast scan...")
    print("-" * 70)
    
    stocks = get_all_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    
    # Load or build cache
    cache = load_cache()
    
    # Check if cache needs update (once per day)
    need_update = False
    if cache:
        last_update = cache.get('_last_update')
        if last_update:
            try:
                last_date = datetime.strptime(last_update, '%Y-%m-%d')
                if (datetime.now() - last_date).days >= 1:
                    need_update = True
            except:
                need_update = True
        else:
            need_update = True
    else:
        need_update = True
    
    if need_update:
        if cache:
            cache = update_cache(cache, stocks)
        else:
            cache = build_cache(stocks)
        cache['_last_update'] = datetime.now().strftime('%Y-%m-%d')
        save_cache(cache)
    
    print("-" * 70)
    print("⚡ Scanning using cached data (fast!)...")
    print("-" * 70)
    
    alerts = 0
    start_time = time.time()
    
    for i, symbol in enumerate(stocks):
        result = check_stock(symbol, cache)
        
        if result.get('passed', False):
            alerts += 1
            print(f"✅ {symbol} - PASSED!")
            try:
                bot.send_message(YOUR_CHAT_ID, f"🚨 *{symbol}*", parse_mode='Markdown')
            except:
                pass
        
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        
        time.sleep(0.05)  # Faster rate limit
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {alerts} stocks passing.")
    print(f"⏱️ Time taken: {time.time() - start_time:.1f} seconds")
    
    if alerts == 0:
        try:
            bot.send_message(YOUR_CHAT_ID, "📊 *No stocks found* matching all 10 conditions today.", parse_mode='Markdown')
        except:
            pass

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🤖 NSE Stock Screener is running!\n📊 Scans ALL NSE stocks\n📋 10 filters matching Chartink\n⚡ Cached version - fast scans!")

@bot.message_handler(commands=['status'])
def status(message):
    cache = load_cache()
    cache_size = len(cache) - 1 if cache else 0
    bot.reply_to(message, f"✅ Scanner active.\n📦 Cache: {cache_size} stocks\n🔄 Scans every 10 minutes")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🔄 NSE Stock Screener is running (CACHED VERSION)!", parse_mode='Markdown')
    except:
        pass
    
    run_scanner()
    print("\n✅ Done!")
