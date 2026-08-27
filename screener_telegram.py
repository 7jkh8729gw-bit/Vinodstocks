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
# YOUR BOT DETAILS - CONFIRMED WORKING
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

# Initialize Telegram bot
bot = telebot.TeleBot(BOT_TOKEN)

print("=" * 60)
print("🤖 NSE STOCK SCREENER BOT (OPTIMIZED)")
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
# CACHE FILE FOR STORING HISTORICAL DATA
# ============================================
CACHE_FILE = "stock_cache.pkl"

def load_cache():
    """Load cached stock data from file"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
            print(f"✅ Cache loaded: {len(cache)} stocks")
            return cache
        else:
            print("ℹ️ No cache found, will build new cache")
            return {}
    except Exception as e:
        print(f"⚠️ Error loading cache: {e}")
        return {}

def save_cache(cache):
    """Save stock data to cache file"""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
        print(f"✅ Cache saved: {len(cache)} stocks")
    except Exception as e:
        print(f"⚠️ Error saving cache: {e}")

# ============================================
# NSE STOCK LIST - FULL LIST
# ============================================
def get_all_nse_stocks():
    """Loads the complete list of active NSE stocks."""
    print("📊 Loading the full NSE security master list...")
    try:
        ds = load_dataset("tickertruth/nse-india-security-master", data_files="data/nse_security_master.csv")
        df = ds["train"].to_pandas()
        active_stocks = df[df["active_flag"] == True]
        symbols = active_stocks["nse_symbol"].tolist()
        print(f"✅ Successfully loaded {len(symbols)} active NSE stocks.")
        return symbols
    except Exception as e:
        print(f"⚠️ Could not load master list: {e}")
        return get_fallback_stocks()

def get_fallback_stocks():
    """Fallback list of major NSE stocks."""
    return [
        'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
        'HINDUNILVR', 'ITC', 'SBIN', 'BHARTIARTL', 'KOTAKBANK',
        'LT', 'HCLTECH', 'AXISBANK', 'MARUTI', 'SUNPHARMA',
        'TITAN', 'WIPRO', 'ULTRACEMCO', 'BAJFINANCE', 'NTPC'
    ]

# ============================================
# DEMA CALCULATION
# ============================================
def calculate_dema(data, period):
    """Calculate Double Exponential Moving Average"""
    ema1 = data.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    return 2 * ema1 - ema2

def build_initial_cache(symbols):
    """Build initial cache with historical data for all stocks"""
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
                # Calculate DEMAs once and store
                dema_10 = calculate_dema(hist['Close'], 10).iloc[-1]
                dema_50 = calculate_dema(hist['Close'], 50).iloc[-1]
                dema_200 = calculate_dema(hist['Close'], 200).iloc[-1]
                
                # Calculate 1 Month Average Volume (21 trading days)
                avg_volume_1m = hist['Volume'].tail(21).mean()
                
                # Store all necessary data
                cache[symbol] = {
                    'dema_10': dema_10,
                    'dema_50': dema_50,
                    'dema_200': dema_200,
                    'avg_volume_1m': avg_volume_1m,
                    'last_checked': datetime.now().strftime('%Y-%m-%d'),
                    'historical_close': hist['Close'].tolist()
                }
            else:
                cache[symbol] = None
                
        except Exception as e:
            cache[symbol] = None
        
        time.sleep(0.3)
    
    print(f"✅ Cache built for {len([k for k, v in cache.items() if v is not None])} stocks")
    return cache

def update_stock_check(symbol, cache_data):
    """
    Check if a stock meets ALL conditions
    Uses cached data for DEMAs and 1M Avg Volume
    """
    try:
        if cache_data is None:
            return False, {}
        
        # Fetch only today's data (much faster)
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        
        # 1. Market Cap > 1000 Crore
        market_cap = info.get('marketCap', 0)
        if market_cap == 0:
            market_cap = info.get('enterpriseValue', 0)
        market_cap_crores = market_cap / 10_000_000
        
        # 2. Price > 100
        current_price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        
        # 3. Day Change: 0 to 15%
        prev_close = info.get('regularMarketPreviousClose', 0)
        if prev_close > 0:
            day_change = ((current_price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        
        # 4. Daily Volume > 200,000
        volume = info.get('regularMarketVolume', 0)
        
        # 5. 1 Month Average Volume > 500,000 (FROM CACHE)
        avg_volume_1m = cache_data.get('avg_volume_1m', 0)
        
        # 6. 0-10% from 52W High
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        if high_52w > 0:
            pct_from_high = ((high_52w - current_price) / high_52w) * 100
        else:
            pct_from_high = 100
        
        # 7. Use cached DEMA values
        cond_10_50 = cache_data['dema_10'] > cache_data['dema_50']
        cond_50_200 = cache_data['dema_50'] > cache_data['dema_200']
        
        # Check ALL conditions
        conditions_met = (
            market_cap_crores > 1000 and
            current_price > 100 and
            0 <= day_change <= 15 and
            volume > 200000 and
            avg_volume_1m > 500000 and
            0 <= pct_from_high <= 10 and
            cond_10_50 and
            cond_50_200
        )
        
        if conditions_met:
            details = {
                'symbol': symbol,
                'price': current_price,
                'market_cap': market_cap_crores,
                'day_change': day_change,
                'volume': volume,
                'avg_volume_1m': avg_volume_1m,
                'pct_from_high': pct_from_high,
                'dema_10': cache_data['dema_10'],
                'dema_50': cache_data['dema_50'],
                'dema_200': cache_data['dema_200']
            }
            return True, details
        return False, {}
            
    except Exception as e:
        return False, {}

def format_alert_message(details):
    """Format alert message - SIMPLIFIED: Only stock name"""
    return f"🚨 *SCREENER ALERT: {details['symbol']}*"

# ============================================
# DAILY CACHE UPDATE
# ============================================
def should_update_cache():
    """Check if cache needs updating (once per day)"""
    if os.path.exists(CACHE_FILE):
        cache = load_cache()
        if cache and 'last_cache_update' in cache:
            last_update = datetime.strptime(cache['last_cache_update'], '%Y-%m-%d')
            if (datetime.now() - last_update).days < 1:
                return False
    return True

def update_full_cache(symbols):
    """Update the entire cache (daily)"""
    print("🔄 Updating daily cache...")
    cache = load_cache()
    
    if cache:
        for symbol in symbols:
            if symbol in cache and cache[symbol] is not None:
                try:
                    ticker = yf.Ticker(f"{symbol}.NS")
                    hist = ticker.history(period="6mo")
                    
                    if len(hist) >= 200:
                        dema_10 = calculate_dema(hist['Close'], 10).iloc[-1]
                        dema_50 = calculate_dema(hist['Close'], 50).iloc[-1]
                        dema_200 = calculate_dema(hist['Close'], 200).iloc[-1]
                        avg_volume_1m = hist['Volume'].tail(21).mean()
                        
                        cache[symbol]['dema_10'] = dema_10
                        cache[symbol]['dema_50'] = dema_50
                        cache[symbol]['dema_200'] = dema_200
                        cache[symbol]['avg_volume_1m'] = avg_volume_1m
                        cache[symbol]['last_checked'] = datetime.now().strftime('%Y-%m-%d')
                
                except Exception as e:
                    pass
                
                time.sleep(0.2)
        
        cache['last_cache_update'] = datetime.now().strftime('%Y-%m-%d')
        save_cache(cache)
        return cache
    else:
        return build_initial_cache(symbols)

# ============================================
# MAIN SCANNER - OPTIMIZED
# ============================================
def run_scanner():
    """Optimized scanner using cached data"""
    print("📊 Fetching NSE stock list...")
    stocks = get_all_nse_stocks()
    
    if not stocks:
        print("❌ No stocks found")
        return
    
    print(f"📊 Monitoring {len(stocks)} stocks...")
    
    if should_update_cache():
        print("📅 Cache needs updating...")
        cache = update_full_cache(stocks)
    else:
        print("📦 Cache is fresh, loading...")
        cache = load_cache()
        if cache and 'last_cache_update' not in cache:
            cache['last_cache_update'] = datetime.now().strftime('%Y-%m-%d')
            save_cache(cache)
    
    if not cache:
        print("⚠️ Building initial cache...")
        cache = build_initial_cache(stocks)
        cache['last_cache_update'] = datetime.now().strftime('%Y-%m-%d')
        save_cache(cache)
    
    print("-" * 60)
    print(f"⚡ Starting fast scan using cached data...")
    print("-" * 60)
    
    alerts_sent = 0
    total_stocks = len(stocks)
    checked = 0
    
    for i, symbol in enumerate(stocks):
        cache_data = cache.get(symbol) if cache else None
        
        if cache_data is not None and cache_data != 'last_cache_update':
            checked += 1
            passed, details = update_stock_check(symbol, cache_data)
            
            if passed:
                msg = format_alert_message(details)
                try:
                    bot.send_message(YOUR_CHAT_ID, msg, parse_mode='Markdown')
                    alerts_sent += 1
                    print(f"✅ ALERT: {symbol}")
                except Exception as e:
                    print(f"❌ Failed to send alert for {symbol}: {e}")
        
        if (i + 1) % 500 == 0:
            print(f"📊 Progress: {i+1}/{total_stocks} stocks checked...")
    
    print("-" * 60)
    print(f"✅ Scan complete! Checked {checked} stocks. Alerts sent: {alerts_sent}")
    print("=" * 60)

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """
🤖 *NSE Stock Screener - Optimized*

I scan ALL NSE listed stocks for:
✅ Market Cap > ₹1000 Cr
✅ Price > ₹100
✅ Day Change: 0-15%
✅ Volume > 200,000
✅ 1M Avg Vol > 500,000  ← Updated!
✅ 0-10% from 52W High
✅ 10 DEMA > 50 DEMA
✅ 50 DEMA > 200 DEMA

⚡ Optimized for speed using cached data!
🔄 Scans every 10 minutes
📦 Cache updates daily

I'll alert you when ANY stock meets ALL conditions!
"""
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['status'])
def check_status(message):
    """Show current scanner status"""
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
🕐 Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚡ Optimized for speed using cached data!
📊 Using 1 Month Average Volume
"""
    bot.reply_to(message, status_text, parse_mode='Markdown')

@bot.message_handler(commands=['test'])
def test_stock(message):
    """Test a specific stock"""
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /test SYMBOL (e.g., /test RELIANCE)")
            return
        
        symbol = args[1].upper()
        bot.reply_to(message, f"🔍 Testing {symbol}...")
        
        # Load cache
        cache = load_cache()
        cache_data = cache.get(symbol) if cache else None
        
        if cache_data is None or cache_data == 'last_cache_update':
            bot.reply_to(message, f"❌ No cached data for {symbol}")
            return
        
        passed, details = update_stock_check(symbol, cache_data)
        
        if passed:
            msg = format_alert_message(details)
            bot.send_message(message.chat.id, msg, parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ {symbol} did NOT meet all conditions")
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['chatid'])
def send_chatid(message):
    chat_id = message.chat.id
    bot.reply_to(message, f"Your Chat ID is: `{chat_id}`", parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
📚 *Help & Commands*

/start - Show welcome message
/status - Check scanner status
/test SYMBOL - Test a specific stock
/chatid - Show your Chat ID
/help - Show this help message

⚡ The bot uses cached data for speed!
🔄 First run builds cache (takes ~5-10 mins)
📦 Subsequent runs are super fast (< 1 minute)
📊 Uses 1 Month Average Volume
"""
    bot.reply_to(message, help_text, parse_mode='Markdown')

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    print("🚀 Starting NSE Stock Screener (Optimized)...")
    
    try:
        bot.send_message(YOUR_CHAT_ID, "🔄 NSE Stock Screener is running (Optimized)...")
        print("✅ Startup notification sent!")
    except Exception as e:
        print(f"⚠️ Could not send notification: {e}")
    
    run_scanner()
    print("✅ Screener completed successfully!")
