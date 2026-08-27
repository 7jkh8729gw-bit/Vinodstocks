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

print("=" * 60)
print("🤖 NSE STOCK SCREENER BOT (CHARTINK MATCH)")
print("=" * 60)

# Test connection
try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
    print(f"🆔 Chat ID: {YOUR_CHAT_ID}")
    print("=" * 60)
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
    return ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR']

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
                
                # Calculate 21-day SMA for volume (last 21 trading days)
                avg_volume_21 = hist['Volume'].tail(21).mean()
                
                # Store all data
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
        
        # ============================================
        # FILTER 1: Market Cap >= 1000 Cr
        # ============================================
        market_cap = info.get('marketCap', 0)
        if market_cap == 0:
            market_cap = info.get('enterpriseValue', 0)
        market_cap_crores = market_cap / 10_000_000
        cond1 = market_cap_crores >= 1000
        
        # ============================================
        # FILTER 2: Close >= 100
        # ============================================
        current_price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        cond2 = current_price >= 100
        
        # ============================================
        # FILTER 3 & 4: Day Change 0% to 15%
        # ============================================
        prev_close = info.get('regularMarketPreviousClose', 0)
        if prev_close > 0:
            day_change = ((current_price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        cond3 = day_change >= 0  # >= 0%
        cond4 = day_change < 15  # < 15%
        
        # ============================================
        # FILTER 5: Volume >= 200,000
        # ============================================
        volume = info.get('regularMarketVolume', 0)
        cond5 = volume >= 200000
        
        # ============================================
        # FILTER 6: SMA(Volume, 21) > 500,000
        # ============================================
        avg_volume_21 = cache_data.get('avg_volume_21', 0)
        cond6 = avg_volume_21 > 500000
        
        # ============================================
        # FILTER 7: Max(252, High) / Close - 1 <= 0.10
        # ============================================
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        if high_52w > 0:
            pct_from_high = (high_52w / current_price) - 1
        else:
            pct_from_high = 100
        cond7 = pct_from_high <= 0.10  # Within 10% of 52W high
        
        # ============================================
        # FILTER 8: DEMA(50) / DEMA(200) >= 1
        # ============================================
        dema_10 = cache_data.get('dema_10', 0)
        dema_50 = cache_data.get('dema_50', 0)
        dema_200 = cache_data.get('dema_200', 0)
        
        if dema_200 > 0:
            cond8 = (dema_50 / dema_200) >= 1.000
        else:
            cond8 = False
        
        # ============================================
        # FILTER 9: DEMA(10) / DEMA(50) >= 1
        # ============================================
        if dema_50 > 0:
            cond9 = (dema_10 / dema_50) >= 1.000
        else:
            cond9 = False
        
        # ============================================
        # FILTER 10: Volume / SMA(Volume, 21) >= 1.5
        # ============================================
        if avg_volume_21 > 0:
            volume_ratio = volume / avg_volume_21
            cond10 = volume_ratio >= 1.5  # ✅ CHANGED FROM 15 TO 1.5
        else:
            cond10 = False
        
        # ============================================
        # CHECK ALL 10 CONDITIONS
        # ============================================
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
                'dema_200': dema_200,
                'cond1': cond1, 'cond2': cond2, 'cond3': cond3,
                'cond4': cond4, 'cond5': cond5, 'cond6': cond6,
                'cond7': cond7, 'cond8': cond8, 'cond9': cond9,
                'cond10': cond10
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
    print("\n" + "=" * 60)
    print("🚀 STARTING MAIN SCANNER")
    print("=" * 60)
    
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
    
    print("-" * 60)
    print("⚡ Scanning all stocks...")
    print("-" * 60)
    
    alerts_sent = 0
    total_stocks = len(stocks)
    
    for i, symbol in enumerate(stocks):
        cache_data = cache.get(symbol) if cache else None
        
        if cache_data is not None and cache_data != 'last_cache_update':
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
            print(f"📊 Progress: {i+1}/{total_stocks} stocks checked...")
        
        time.sleep(0.2)
    
    print("-" * 60)
    print(f"✅ Scan complete! Alerts sent: {alerts_sent}")
    print("=" * 60)

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
    
    cache = load_cache()
    cache_data = cache.get(symbol) if cache else None
    
    if cache_data is None or cache_data == 'last_cache_update':
        bot.reply_to(message, f"❌ No cached data for {symbol}")
        return
    
    passed, details = check_stock(symbol, cache_data)
    
    if passed:
        bot.send_message(message.chat.id, f"✅ {symbol} PASSED all 10 conditions!", parse_mode='Markdown')
    else:
        # Show which conditions failed
        fail_msg = f"❌ {symbol} failed:\n"
        if not details.get('cond1', False): fail_msg += "❌ Market Cap < 1000 Cr\n"
        if not details.get('cond2', False): fail_msg += "❌ Price < 100\n"
        if not details.get('cond3', False): fail_msg += "❌ Day Change < 0%\n"
        if not details.get('cond4', False): fail_msg += "❌ Day Change ≥ 15%\n"
        if not details.get('cond5', False): fail_msg += "❌ Volume < 200,000\n"
        if not details.get('cond6', False): fail_msg += "❌ 21-Day Avg Vol ≤ 500,000\n"
        if not details.get('cond7', False): fail_msg += f"❌ >10% from 52W High\n"
        if not details.get('cond8', False): fail_msg += "❌ DEMA(50)/DEMA(200) < 1\n"
        if not details.get('cond9', False): fail_msg += "❌ DEMA(10)/DEMA(50) < 1\n"
        if not details.get('cond10', False): 
            ratio = details.get('volume_ratio', 0)
            fail_msg += f"❌ Volume ratio: {ratio:.2f}x (need ≥ 1.5x)\n"
        bot.reply_to(message, fail_msg)

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
    print("🚀 Starting NSE Stock Screener...")
    
    try:
        bot.send_message(YOUR_CHAT_ID, "🔄 NSE Stock Screener is running with all 10 Chartink filters!")
        print("✅ Startup notification sent!")
    except Exception as e:
        print(f"⚠️ Could not send notification: {e}")
    
    run_scanner()
    print("✅ Screener completed successfully!")
