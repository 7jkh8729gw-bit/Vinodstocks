import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
from datetime import datetime
import telebot

# ============================================
# ✅ USE YOUR CORRECT BOT TOKEN
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "YOUR_CORRECT_TOKEN_HERE")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

# Initialize Telegram bot
bot = telebot.TeleBot(BOT_TOKEN)

print("=" * 50)
print("🤖 NSE STOCK SCREENER BOT")
print("=" * 50)

# Test connection
try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
    print(f"🆔 Chat ID: {YOUR_CHAT_ID}")
    print("=" * 50)
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    print("Please check your BOT_TOKEN")
    exit(1)

# ============================================
# NSE STOCK LIST
# ============================================
def get_all_nse_stocks():
    """Get all NSE stock symbols"""
    print("📊 Fetching NSE stock list...")
    try:
        url = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            symbols = []
            for item in data.get('data', []):
                symbol = item.get('symbol')
                if symbol:
                    symbols.append(symbol)
            print(f"✅ Found {len(symbols)} NSE stocks")
            return symbols
        else:
            print(f"⚠️ Using fallback list")
            return get_fallback_stocks()
    except:
        print("⚠️ Using fallback list")
        return get_fallback_stocks()

def get_fallback_stocks():
    """Fallback list of major NSE stocks"""
    return [
        'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
        'HINDUNILVR', 'ITC', 'SBIN', 'BHARTIARTL', 'KOTAKBANK',
        'LT', 'HCLTECH', 'AXISBANK', 'MARUTI', 'SUNPHARMA',
        'TITAN', 'WIPRO', 'ULTRACEMCO', 'BAJFINANCE', 'NTPC'
    ]

# ============================================
# SCREENING FUNCTIONS
# ============================================
def calculate_dema(data, period):
    """Calculate Double Exponential Moving Average"""
    ema1 = data.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    return 2 * ema1 - ema2

def check_stock(symbol):
    """Check if a stock meets ALL conditions"""
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        hist = ticker.history(period="6mo")
        
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
        
        # 4. Volume > 200,000
        volume = info.get('regularMarketVolume', 0)
        
        # 5. 3M Avg Volume > 500,000
        avg_volume = info.get('averageDailyVolume3Month', 0)
        
        # 6. 0-10% from 52W High
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        if high_52w > 0:
            pct_from_high = ((high_52w - current_price) / high_52w) * 100
        else:
            pct_from_high = 100
        
        # 7. Calculate DEMAs
        if len(hist) >= 200:
            dema_10 = calculate_dema(hist['Close'], 10).iloc[-1]
            dema_50 = calculate_dema(hist['Close'], 50).iloc[-1]
            dema_200 = calculate_dema(hist['Close'], 200).iloc[-1]
            cond_10_50 = dema_10 > dema_50
            cond_50_200 = dema_50 > dema_200
        else:
            dema_10 = 0
            dema_50 = 0
            dema_200 = 0
            cond_10_50 = False
            cond_50_200 = False
        
        # Check ALL conditions
        conditions_met = (
            market_cap_crores > 1000 and
            current_price > 100 and
            0 <= day_change <= 15 and
            volume > 200000 and
            avg_volume > 500000 and
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
                'avg_volume': avg_volume,
                'pct_from_high': pct_from_high,
                'dema_10': dema_10,
                'dema_50': dema_50,
                'dema_200': dema_200
            }
            return True, details
        return False, {}
            
    except:
        return False, {}

def format_alert_message(details):
    """Format alert message for Telegram"""
    msg = f"🚨 *SCREENER ALERT: {details['symbol']}* 🚨\n\n"
    msg += f"💰 *Price:* ₹{details['price']:.2f}\n"
    msg += f"📊 *Market Cap:* ₹{details['market_cap']:.1f} Cr\n"
    msg += f"📈 *Day Change:* {details['day_change']:.2f}%\n"
    msg += f"📊 *Volume:* {details['volume']:,}\n"
    msg += f"📊 *3M Avg Volume:* {details['avg_volume']:,}\n"
    msg += f"📉 *From 52W High:* {details['pct_from_high']:.2f}%\n"
    msg += f"📈 *10 DEMA:* {details['dema_10']:.2f}\n"
    msg += f"📈 *50 DEMA:* {details['dema_50']:.2f}\n"
    msg += f"📈 *200 DEMA:* {details['dema_200']:.2f}\n"
    msg += "\n✅ *All conditions met!*"
    return msg

# ============================================
# MAIN SCANNER - SIMPLIFIED FOR GITHUB ACTIONS
# ============================================
def run_scanner():
    """Single scan - runs once and exits (for GitHub Actions)"""
    print("📊 Fetching NSE stock list...")
    stocks = get_all_nse_stocks()
    
    if not stocks:
        print("❌ No stocks found")
        return
    
    print(f"📊 Monitoring {len(stocks)} stocks...")
    print("-" * 50)
    
    alerts_sent = 0
    
    for i, symbol in enumerate(stocks):
        # Show progress
        if (i + 1) % 50 == 0:
            print(f"📊 Progress: {i+1}/{len(stocks)} stocks checked...")
        
        passed, details = check_stock(symbol)
        
        if passed:
            msg = format_alert_message(details)
            try:
                bot.send_message(YOUR_CHAT_ID, msg, parse_mode='Markdown')
                alerts_sent += 1
                print(f"✅ ALERT: {symbol}")
            except Exception as e:
                print(f"❌ Failed to send alert: {e}")
        
        # Rate limiting
        time.sleep(0.3)
    
    print("-" * 50)
    print(f"✅ Scan complete. Alerts sent: {alerts_sent}")
    print("=" * 50)

# ============================================
# RUN - SIMPLIFIED FOR GITHUB ACTIONS
# ============================================
if __name__ == "__main__":
    print("🚀 Starting NSE Stock Screener...")
    
    # Send startup notification
    try:
        bot.send_message(YOUR_CHAT_ID, "🔄 NSE Stock Screener is running...")
        print("✅ Startup notification sent!")
    except Exception as e:
        print(f"⚠️ Could not send notification: {e}")
    
    # Run the scanner
    run_scanner()
    
    print("✅ Screener completed successfully!")
