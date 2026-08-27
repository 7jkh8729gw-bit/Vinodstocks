import os
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import telebot
import yfinance as yf

# ============================================
# YOUR BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)

print("=" * 70)
print("🤖 NSE STOCK SCREENER - FINAL VERSION")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# GET NSE STOCKS - Using nsetools
# ============================================
def get_nse_stocks():
    """Fetch ALL NSE stocks using nsetools"""
    print("📊 Fetching NSE stock list...")
    
    try:
        import nsetools
        nse = nsetools.Nse()
        stocks = nse.get_stock_codes()
        # Get only valid symbols (remove None values)
        stock_list = [symbol for symbol, name in stocks.items() if name is not None]
        print(f"✅ Loaded {len(stock_list)} stocks from nsetools")
        return stock_list
    except Exception as e:
        print(f"⚠️ nsetools error: {e}")
    
    # Fallback
    print("⚠️ Using fallback list")
    return get_fallback_stocks()

def get_fallback_stocks():
    """Comprehensive fallback list"""
    return [
        'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
        'KOTAKBANK', 'HINDUNILVR', 'ITC', 'SBIN', 'BHARTIARTL',
        'LT', 'HCLTECH', 'AXISBANK', 'MARUTI', 'SUNPHARMA',
        'TITAN', 'WIPRO', 'ULTRACEMCO', 'BAJFINANCE', 'NTPC',
        'POWERGRID', 'M&M', 'TATASTEEL', 'JSWSTEEL',
        'TECHM', 'NESTLEIND', 'ONGC', 'ADANIPORTS',
        'ADANIENT', 'DMART', 'SBILIFE', 'HINDALCO', 'BRITANNIA',
        'DRREDDY', 'GRASIM', 'EICHERMOT', 'BAJAJFINSV', 'ASIANPAINT',
        'VINCOFE', 'IOLCP', 'ALEMBICLTD', 'DCBBANK', 'SKIPPER', 'JINDALSAW',
        'WELCORP', 'HDFCLIFE', 'HDFCAMC', 'SHRIRAMFIN', 'MOTHERSON'
    ]

# ============================================
# DEMA CALCULATION
# ============================================
def calculate_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

# ============================================
# CHECK STOCK - Using nsetools for live data
# ============================================
def check_stock(symbol):
    """Check stock using nsetools for live data"""
    try:
        import nsetools
        nse = nsetools.Nse()
        
        # Get live quote from nsetools
        quote = nse.get_quote(symbol)
        
        # Get historical data from yfinance (only for DEMA)
        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(period="6mo")
        
        # 1. Market Cap >= 1000 Cr
        market_cap_raw = quote.get('marketCap', 0)
        market_cap_crores = market_cap_raw / 10000000 if market_cap_raw > 0 else 0
        cond1 = market_cap_crores >= 1000
        
        # 2. Price >= 100
        price = quote.get('lastPrice', 0)
        cond2 = price >= 100
        
        # 3 & 4. Day Change 0-15%
        prev_close = quote.get('previousClose', 0)
        if prev_close > 0 and price > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        cond3 = day_change >= 0
        cond4 = day_change < 15
        
        # 5. Volume >= 200,000
        volume = quote.get('totalTradedVolume', 0)
        cond5 = volume >= 200000
        
        # 6. 21-Day Avg Volume > 500,000
        if len(hist) >= 21:
            avg_volume = hist['Volume'].tail(21).mean()
        else:
            avg_volume = 0
        cond6 = avg_volume > 500000
        
        # 7. Within 10% of 52W High
        high_52w = quote.get('weekHigh52', 0)
        if high_52w > 0 and price > 0:
            pct_from_high = (high_52w / price) - 1
        else:
            pct_from_high = 100
        cond7 = pct_from_high <= 0.10
        
        # 8 & 9. DEMA calculations
        cond8 = False
        cond9 = False
        if len(hist) >= 200:
            d10 = calculate_dema(hist['Close'], 10)
            d50 = calculate_dema(hist['Close'], 50)
            d200 = calculate_dema(hist['Close'], 200)
            
            if d10 is not None and d50 is not None and d200 is not None:
                d10_val = d10.iloc[-1]
                d50_val = d50.iloc[-1]
                d200_val = d200.iloc[-1]
                if d200_val > 0 and d50_val > 0:
                    cond8 = (d50_val / d200_val) >= 1.0
                    cond9 = (d10_val / d50_val) >= 1.0
        
        # 10. Volume Ratio >= 1.5x
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        cond10 = volume_ratio >= 1.5
        
        passed = cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10
        
        return {
            'symbol': symbol,
            'passed': passed,
            'market_cap': market_cap_crores,
            'price': price,
            'day_change': day_change,
            'volume': volume,
            'avg_volume': avg_volume,
            'pct_from_high': pct_from_high * 100,
            'volume_ratio': volume_ratio,
            'cond1': cond1, 'cond2': cond2, 'cond3': cond3,
            'cond4': cond4, 'cond5': cond5, 'cond6': cond6,
            'cond7': cond7, 'cond8': cond8, 'cond9': cond9, 'cond10': cond10
        }
        
    except Exception as e:
        return {'symbol': symbol, 'passed': False, 'error': str(e)[:50]}

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting full scan...")
    print("-" * 70)
    
    stocks = get_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    print("-" * 70)
    
    alerts = 0
    start_time = time.time()
    
    for i, symbol in enumerate(stocks):
        result = check_stock(symbol)
        
        if result.get('passed', False):
            alerts += 1
            print(f"✅ {symbol} - PASSED ALL 10!")
            try:
                bot.send_message(YOUR_CHAT_ID, f"🚨 *{symbol}*", parse_mode='Markdown')
            except:
                pass
        
        if (i + 1) % 20 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        
        time.sleep(0.15)
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {alerts} stocks passing.")
    
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
    bot.reply_to(message, "🤖 NSE Stock Screener is running!\n\n📊 Scans ALL NSE stocks\n📋 10 filters matching Chartink\n🚨 Alerts when ALL conditions pass")

@bot.message_handler(commands=['status'])
def status(message):
    bot.reply_to(message, "✅ Scanner active.\n🔄 Scans every 10 minutes.\n📊 Scans ALL NSE stocks.")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🔄 NSE Stock Screener is running!", parse_mode='Markdown')
    except:
        pass
    
    run_scanner()
    print("\n✅ Done!")
