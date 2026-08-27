import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import json
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

# Initialize Telegram bot
bot = telebot.TeleBot(BOT_TOKEN)

print("=" * 70)
print("🤖 NSE STOCK SCREENER BOT (DEBUG MODE)")
print("=" * 70)

# Test connection
try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
    print(f"🆔 Chat ID: {YOUR_CHAT_ID}")
    print("=" * 70)
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# CACHE FILE
# ============================================
CACHE_FILE = "stock_cache.pkl"

def load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
            print(f"✅ Cache loaded: {len(cache)} entries")
            return cache
        else:
            print("ℹ️ No cache found")
            return {}
    except Exception as e:
        print(f"⚠️ Error loading cache: {e}")
        return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
        print(f"✅ Cache saved: {len(cache)} entries")
    except Exception as e:
        print(f"⚠️ Error saving cache: {e}")

# ============================================
# NSE STOCK LIST
# ============================================
def get_all_nse_stocks():
    print("📊 Loading NSE stock list...")
    try:
        ds = load_dataset("tickertruth/nse-india-security-master", data_files="data/nse_security_master.csv")
        df = ds["train"].to_pandas()
        active_stocks = df[df["active_flag"] == True]
        symbols = active_stocks["nse_symbol"].tolist()
        print(f"✅ Loaded {len(symbols)} active NSE stocks")
        return symbols
    except Exception as e:
        print(f"⚠️ Error loading: {e}")
        return get_fallback_stocks()

def get_fallback_stocks():
    return ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'WEL', 'ALEMBIC']

# ============================================
# DEMA CALCULATION
# ============================================
def calculate_dema(data, period):
    """Calculate Double Exponential Moving Average"""
    ema1 = data.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    return 2 * ema1 - ema2

# ============================================
# BUILD CACHE
# ============================================
def build_initial_cache(symbols):
    """Build initial cache with historical data"""
    print("🏗️ Building initial cache... This may take a few minutes.")
    cache = {}
    total = len(symbols)
    
    for i, symbol in enumerate(symbols):
        if (i + 1) % 50 == 0:
            print(f"📊 Progress: {i+1}/{total} stocks cached...")
        
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            hist = ticker.history(period="6mo")
            
            if len(hist) >= 200:
                # Calculate DEMAs
                dema_10 = calculate_dema(hist['Close'], 10).iloc[-1]
                dema_50 = calculate_dema(hist['Close'], 50).iloc[-1]
                dema_200 = calculate_dema(hist['Close'], 200).iloc[-1]
                
                # Calculate 21-day SMA for volume
                avg_volume_21 = hist['Volume'].tail(21).mean()
                
                cache[symbol] = {
                    'dema_10': dema_10,
                    'dema_50': dema_50,
                    'dema_200': dema_200,
                    'avg_volume_21': avg_volume_21,
                    'last_checked': datetime.now().strftime('%Y-%m-%d')
                }
            else:
                cache[symbol] = None
                
        except Exception as e:
            cache[symbol] = None
        
        time.sleep(0.3)
    
    print(f"✅ Cache built for {len([k for k, v in cache.items() if v is not None])} stocks")
    return cache

# ============================================
# TEST SPECIFIC STOCKS (DEBUG FUNCTION)
# ============================================
def test_specific_stocks():
    """Test specific stocks and print detailed debug output"""
    print("\n" + "=" * 70)
    print("🧪 TESTING SPECIFIC STOCKS FROM CHARTINK")
    print("=" * 70)
    
    test_symbols = ['WEL', 'ALEMBIC', 'RELIANCE', 'TCS', 'HDFCBANK']
    
    for symbol in test_symbols:
        print(f"\n📊 Testing: {symbol}")
        print("-" * 50)
        
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            info = ticker.info
            hist = ticker.history(period="6mo")
            
            # Calculate all values
            market_cap = info.get('marketCap', 0)
            if market_cap == 0:
                market_cap = info.get('enterpriseValue', 0)
            market_cap_crores = market_cap / 10_000_000
            
            current_price = info.get('regularMarketPrice', info.get('currentPrice', 0))
            
            prev_close = info.get('regularMarketPreviousClose', 0)
            if prev_close > 0:
                day_change = ((current_price - prev_close) / prev_close) * 100
            else:
                day_change = 0
            
            volume = info.get('regularMarketVolume', 0)
            
            if len(hist) >= 21:
                avg_volume_21 = hist['Volume'].tail(21).mean()
            else:
                avg_volume_21 = 0
            
            high_52w = info.get('fiftyTwoWeekHigh', 0)
            if high_52w > 0:
                pct_from_high = (high_52w / current_price) - 1
            else:
                pct_from_high = 100
            
            if len(hist) >= 200:
                dema_10 = calculate_dema(hist['Close'], 10).iloc[-1]
                dema_50 = calculate_dema(hist['Close'], 50).iloc[-1]
                dema_200 = calculate_dema(hist['Close'], 200).iloc[-1]
            else:
                dema_10 = dema_50 = dema_200 = 0
            
            volume_ratio = volume / avg_volume_21 if avg_volume_21 > 0 else 0
            
            # Check conditions
            cond1 = market_cap_crores >= 1000
            cond2 = current_price >= 100
            cond3 = day_change >= 0
            cond4 = day_change < 15
            cond5 = volume >= 200000
            cond6 = avg_volume_21 > 500000
            cond7 = pct_from_high <= 0.10
            cond8 = (dema_50 / dema_200) >= 1 if dema_200 > 0 else False
            cond9 = (dema_10 / dema_50) >= 1 if dema_50 > 0 else False
            cond10 = volume_ratio >= 1.5
            
            # Print debug
            print(f"  1️⃣ Market Cap: ₹{market_cap_crores:.1f} Cr {'✅' if cond1 else '❌'} (need ≥ 1000)")
            print(f"  2️⃣ Price: ₹{current_price:.2f} {'✅' if cond2 else '❌'} (need ≥ 100)")
            print(f"  3️⃣ Day Change: {day_change:.2f}% {'✅' if cond3 and cond4 else '❌'} (need 0-15%)")
            print(f"  4️⃣ Volume: {volume:,} {'✅' if cond5 else '❌'} (need ≥ 200,000)")
            print(f"  5️⃣ 21-Day Avg Vol: {avg_volume_21:,.0f} {'✅' if cond6 else '❌'} (need > 500,000)")
            print(f"  6️⃣ From 52W High: {pct_from_high*100:.2f}% {'✅' if cond7 else '❌'} (need ≤ 10%)")
            print(f"  7️⃣ DEMA(50)/DEMA(200): {(dema_50/dema_200):.3f} {'✅' if cond8 else '❌'} (need ≥ 1)")
            print(f"  8️⃣ DEMA(10)/DEMA(50): {(dema_10/dema_50):.3f} {'✅' if cond9 else '❌'} (need ≥ 1)")
            print(f"  9️⃣ Volume Ratio: {volume_ratio:.2f}x {'✅' if cond10 else '❌'} (need ≥ 1.5x)")
            
            all_pass = cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10
            print(f"  RESULT: {'✅ ALL PASSED!' if all_pass else '❌ FAILED'}")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")

# ============================================
# STOCK CHECK - ALL 10 CHARTINK FILTERS
# ============================================
def check_stock(symbol, cache_data):
    """
    Check if a stock meets ALL 10 Chartink conditions
    """
    try:
        if cache_data is None:
            return False, {}
        
        # Fetch today's data
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        hist = ticker.history(period="6mo")
        
        # Calculate all values
        market_cap = info.get('marketCap', 0)
        if market_cap == 0:
            market_cap = info.get('enterpriseValue', 0)
        market_cap_crores = market_cap / 10_000_000
        
        current_price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        
        prev_close = info.get('regularMarketPreviousClose', 0)
        if prev_close > 0:
            day_change = ((current_price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        
        volume = info.get('regularMarketVolume', 0)
        avg_volume_21 = cache_data.get('avg_volume_21', 0)
        
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        if high_52w > 0:
            pct_from_high = (high_52w / current_price) - 1
        else:
            pct_from_high = 100
        
        dema_10 = cache_data.get('dema_10', 0)
        dema_50 = cache_data.get('dema_50', 0)
        dema_200 = cache_data.get('dema_200', 0)
        
        volume_ratio = volume / avg_volume_21 if avg_volume_21 > 0 else 0
        
        # Check conditions
        cond1 = market_cap_crores >= 1000
        cond2 = current_price >= 100
        cond3 = day_change >= 0
        cond4 = day_change < 15
        cond5 = volume >= 200000
        cond6 = avg_volume_21 > 500000
        cond7 = pct_from_high <= 0.10
        cond8 = (dema_50 / dema_200) >= 1 if dema_200 > 0 else False
        cond9 = (dema_10 / dema_50) >= 1 if dema_50 > 0 else False
        cond10 = volume_ratio >= 1.5
        
        # Check ALL conditions
        conditions_met = (
            cond1 and cond2 and cond3 and cond4 and cond5 and
            cond6 and cond7 and cond8 and cond9 and cond10
        )
        
        if conditions_met:
            details = {
                'symbol': symbol,
                'price': current_price,
                'market_cap': market_cap_crores,
                'day_change': day_change,
                'volume': volume,
                'avg_volume_21': avg_volume_21,
                'volume_ratio': volume_ratio,
                'pct_from_high': pct_from_high * 100,
                'dema_10': dema_10,
                'dema_50': dema_50,
                'dema_200': dema_200
            }
            return True, details
        return False, {}
            
    except Exception as e:
        return False, {}

def format_alert_message(details):
    """Format alert message with stock name only"""
    return f"🚨 *SCREENER ALERT: {details['symbol']}*"

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n" + "=" * 70)
    print("🚀 STARTING MAIN SCANNER")
    print("=" * 70)
    
    # FIRST: Test specific stocks from Chartink
    test_specific_stocks()
    
    print("\n" + "=" * 70)
    print("📊 NOW SCANNING ALL STOCKS")
    print("=" * 70)
    
    stocks = get_all_nse_stocks()
    
    if not stocks:
        print("❌ No stocks found")
        return
    
    print(f"📊 Checking {len(stocks)} stocks...")
    
    # Load or build cache
    cache = load_cache()
    
    if not cache or 'last_cache_update' not in cache:
        print("🏗️ Building initial cache...")
        cache = build_initial_cache(stocks)
        cache['last_cache_update'] = datetime.now().strftime('%Y-%m-%d')
        save_cache(cache)
    
    print("-" * 70)
    print("⚡ Scanning all stocks...")
    print("-" * 70)
    
    alerts_sent = 0
    total_stocks = len(stocks)
    stocks_with_cache = 0
    
    for i, symbol in enumerate(stocks):
        cache_data = cache.get(symbol) if cache else None
        
        if cache_data is not None and cache_data != 'last_cache_update':
            stocks_with_cache += 1
            passed, details = check_stock(symbol, cache_data)
            
            if passed:
                msg = format_alert_message(details)
                try:
                    bot.send_message(YOUR_CHAT_ID, msg, parse_mode='Markdown')
                    alerts_sent += 1
                    print(f"✅ ALERT: {symbol}")
                except Exception as e:
                    print(f"❌ Failed to send alert for {symbol}: {e}")
        
        # Progress every 100 stocks
        if (i + 1) % 100 == 0:
            print(f"📊 Progress: {i+1}/{total_stocks} stocks checked... ({stocks_with_cache} with cache)")
        
        time.sleep(0.2)
    
    print("-" * 70)
    print(f"✅ Scan complete!")
    print(f"   Total stocks checked: {total_stocks}")
    print(f"   Stocks with cache: {stocks_with_cache}")
    print(f"   Alerts sent: {alerts_sent}")
    print("=" * 70)

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """
🤖 *NSE Stock Screener - Chartink Match*

I scan ALL NSE stocks with the EXACT Chartink filters:

📊 *10 FILTERS*
1️⃣ Market Cap ≥ ₹1000 Cr
2️⃣ Close ≥ ₹100
3️⃣ Day Change ≥ 0%
4️⃣ Day Change < 15%
5️⃣ Volume ≥ 200,000
6️⃣ 21-Day Avg Vol > 500,000
7️⃣ Within 10% of 52W High
8️⃣ DEMA(50) / DEMA(200) ≥ 1
9️⃣ DEMA(10) / DEMA(50) ≥ 1
🔟 Volume / 21-Day Avg Vol ≥ 1.5x

⚡ Scans every 10 minutes
📦 Cache updates daily

I'll alert you when ANY stock meets ALL 10 conditions!
"""
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['status'])
def check_status(message):
    cache = load_cache()
    cache_size = len([k for k, v in cache.items() if v is not None and k != 'last_cache_update']) if cache else 0
    
    status_text = f"""
📊 *Scanner Status*
━━━━━━━━━━━━━━━━━

✅ Status: Running
🔄 Scan interval: Every 10 minutes
📈 Target: All NSE stocks
📦 Cache size: {cache_size} stocks
🕐 Last cache update: {cache.get('last_cache_update', 'Never') if cache else 'Never'}

🔟 Using all 10 Chartink filters
📊 Volume spike: 1.5x
"""
    bot.reply_to(message, status_text, parse_mode='Markdown')

@bot.message_handler(commands=['test'])
def test_stock(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /test SYMBOL (e.g., /test RELIANCE)")
        return
    
    symbol = args[1].upper()
    bot.reply_to(message, f"🔍 Testing {symbol}...")
    
    try:
        # Fetch live data directly
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        hist = ticker.history(period="6mo")
        
        market_cap = info.get('marketCap', 0) / 10_000_000
        current_price = info.get('regularMarketPrice', 0)
        prev_close = info.get('regularMarketPreviousClose', 0)
        day_change = ((current_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
        volume = info.get('regularMarketVolume', 0)
        avg_volume = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        pct_from_high = (high_52w / current_price) - 1 if high_52w > 0 else 100
        
        if len(hist) >= 200:
            dema_10 = calculate_dema(hist['Close'], 10).iloc[-1]
            dema_50 = calculate_dema(hist['Close'], 50).iloc[-1]
            dema_200 = calculate_dema(hist['Close'], 200).iloc[-1]
        else:
            dema_10 = dema_50 = dema_200 = 0
        
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        
        msg = f"📊 *DEBUG: {symbol}*\n\n"
        msg += f"1️⃣ Market Cap: ₹{market_cap:.1f} Cr {'✅' if market_cap >= 1000 else '❌'} (need ≥ 1000)\n"
        msg += f"2️⃣ Price: ₹{current_price:.2f} {'✅' if current_price >= 100 else '❌'} (need ≥ 100)\n"
        msg += f"3️⃣ Day Change: {day_change:.2f}% {'✅' if 0 <= day_change < 15 else '❌'} (need 0-15%)\n"
        msg += f"4️⃣ Volume: {volume:,} {'✅' if volume >= 200000 else '❌'} (need ≥ 200,000)\n"
        msg += f"5️⃣ 21-Day Avg Vol: {avg_volume:,.0f} {'✅' if avg_volume > 500000 else '❌'} (need > 500,000)\n"
        msg += f"6️⃣ From 52W High: {pct_from_high*100:.2f}% {'✅' if pct_from_high <= 0.10 else '❌'} (need ≤ 10%)\n"
        msg += f"7️⃣ DEMA(50)/DEMA(200): {(dema_50/dema_200):.3f} {'✅' if dema_50/dema_200 >= 1 else '❌'} (need ≥ 1)\n"
        msg += f"8️⃣ DEMA(10)/DEMA(50): {(dema_10/dema_50):.3f} {'✅' if dema_10/dema_50 >= 1 else '❌'} (need ≥ 1)\n"
        msg += f"9️⃣ Volume Ratio: {volume_ratio:.2f}x {'✅' if volume_ratio >= 1.5 else '❌'} (need ≥ 1.5x)\n"
        
        all_pass = (
            market_cap >= 1000 and current_price >= 100 and 
            0 <= day_change < 15 and volume >= 200000 and
            avg_volume > 500000 and pct_from_high <= 0.10 and
            dema_50/dema_200 >= 1 and dema_10/dema_50 >= 1 and
            volume_ratio >= 1.5
        )
        
        msg += f"\n{'✅ ALL CONDITIONS MET!' if all_pass else '❌ Some conditions failed'}"
        
        bot.reply_to(message, msg, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error testing {symbol}: {e}")

@bot.message_handler(commands=['chatid'])
def send_chatid(message):
    bot.reply_to(message, f"Your Chat ID: `{message.chat.id}`", parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
📚 *Commands*

/start - Show welcome
/status - Check scanner status
/test SYMBOL - Test a stock
/chatid - Show your Chat ID
/help - Show this help

🔟 Uses all 10 Chartink filters!
📊 Volume spike: 1.5x
"""
    bot.reply_to(message, help_text, parse_mode='Markdown')

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    print("🚀 Starting NSE Stock Screener (Debug Mode)...")
    
    try:
        bot.send_message(YOUR_CHAT_ID, "🔄 NSE Stock Screener is running with all 10 Chartink filters!")
        print("✅ Startup notification sent!")
    except Exception as e:
        print(f"⚠️ Could not send notification: {e}")
    
    run_scanner()
    print("✅ Screener completed successfully!")
