import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime
import telebot
from datasets import load_dataset

# ============================================
# YOUR BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)

print("=" * 70)
print("🤖 NSE STOCK SCREENER - PRODUCTION VERSION")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
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
        return get_fallback_stocks()

def get_fallback_stocks():
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
# CHECK STOCK
# ============================================
def check_stock(symbol):
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        hist = ticker.history(period="1y")  # 1 year for DEMA
        
        if not info or len(hist) == 0:
            return {'symbol': symbol, 'passed': False}
        
        # Get data
        price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        market_cap_raw = info.get('marketCap', 0) / 10000000
        prev_close = info.get('regularMarketPreviousClose', 0)
        volume = info.get('regularMarketVolume', 0)
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        
        if prev_close > 0 and price > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        
        if len(hist) >= 21:
            avg_volume = hist['Volume'].tail(21).mean()
        else:
            avg_volume = 0
        
        # DEMA
        dema_10 = dema_50 = dema_200 = 0
        if len(hist) >= 200:
            d10 = chartink_dema(hist['Close'], 10)
            d50 = chartink_dema(hist['Close'], 50)
            d200 = chartink_dema(hist['Close'], 200)
            if d10 is not None and d50 is not None and d200 is not None:
                dema_10 = d10.iloc[-1]
                dema_50 = d50.iloc[-1]
                dema_200 = d200.iloc[-1]
        
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
            'avg_volume': avg_volume,
            'volume_ratio': volume_ratio
        }
        
    except Exception as e:
        return {'symbol': symbol, 'passed': False}

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting full scan...")
    print("-" * 70)
    
    stocks = get_all_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    print("-" * 70)
    
    alerts = 0
    start_time = time.time()
    
    for i, symbol in enumerate(stocks):
        result = check_stock(symbol)
        
        if result.get('passed', False):
            alerts += 1
            print(f"✅ {symbol} - PASSED!")
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
    bot.reply_to(message, "🤖 NSE Stock Screener is running!\n📊 Scans ALL NSE stocks\n📋 10 filters matching Chartink\n🚨 Alerts when ALL conditions pass")

@bot.message_handler(commands=['status'])
def status(message):
    bot.reply_to(message, "✅ Scanner active.\n🔄 Scans every 10 minutes.")

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
