import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime
import telebot

# ============================================
# YOUR BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)

print("=" * 70)
print("🔍 DEBUG MODE - TESTING MANINDS")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# DEMA CALCULATION (Same as your bot)
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

# ============================================
# COMPARE FUNCTION
# ============================================
def compare_stock(symbol):
    print("\n" + "=" * 70)
    print(f"🔍 COMPARING: {symbol}")
    print("=" * 70)
    
    # CHARTINK DATA (from your Excel)
    chartink_data = {
        'symbol': 'MANINDS',
        'price': 767.45,
        'day_change': 9.15,
        'volume': 2684284,
        'avg_volume': 1236460.52,
        'high_52w': 783.4,
        'market_cap': 5273.92,
        'dema_10': 739.50,
        'dema_50': 643.52,
        'dema_200': 575.98
    }
    
    print("\n📊 CHARTINK DATA (from your Excel):")
    print(f"  Price: ₹{chartink_data['price']:.2f}")
    print(f"  Day Change: {chartink_data['day_change']:.2f}%")
    print(f"  Volume: {chartink_data['volume']:,}")
    print(f"  1M Avg Volume: {chartink_data['avg_volume']:.2f}")
    print(f"  52W High: {chartink_data['high_52w']:.2f}")
    print(f"  Market Cap: ₹{chartink_data['market_cap']:.2f} Cr")
    print(f"  10 DEMA: {chartink_data['dema_10']:.2f}")
    print(f"  50 DEMA: {chartink_data['dema_50']:.2f}")
    print(f"  200 DEMA: {chartink_data['dema_200']:.2f}")
    
    # YFINANCE DATA
    print("\n📊 YFINANCE DATA:")
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        hist = ticker.history(period="6mo")
        
        yf_price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        yf_market_cap = info.get('marketCap', 0) / 10000000 if info.get('marketCap', 0) > 0 else 0
        yf_prev_close = info.get('regularMarketPreviousClose', 0)
        yf_volume = info.get('regularMarketVolume', 0)
        yf_high_52w = info.get('fiftyTwoWeekHigh', 0)
        
        print(f"  Price: ₹{yf_price:.2f}")
        print(f"  Market Cap: ₹{yf_market_cap:.2f} Cr")
        print(f"  Previous Close: ₹{yf_prev_close:.2f}")
        print(f"  Volume: {yf_volume:,}")
        print(f"  52W High: ₹{yf_high_52w:.2f}")
        print(f"  Data length: {len(hist)} days")
        
        # Calculate DEMA
        if len(hist) >= 200:
            d10 = chartink_dema(hist['Close'], 10)
            d50 = chartink_dema(hist['Close'], 50)
            d200 = chartink_dema(hist['Close'], 200)
            
            if d10 is not None and d50 is not None and d200 is not None:
                yf_d10 = d10.iloc[-1]
                yf_d50 = d50.iloc[-1]
                yf_d200 = d200.iloc[-1]
                print(f"  10 DEMA: {yf_d10:.2f}")
                print(f"  50 DEMA: {yf_d50:.2f}")
                print(f"  200 DEMA: {yf_d200:.2f}")
            else:
                print("  ❌ DEMA calculation failed")
        else:
            print(f"  ⚠️ Insufficient data for DEMA (need 200 days, have {len(hist)})")
            
    except Exception as e:
        print(f"  ❌ yfinance error: {e}")
    
    # NSETOOLS DATA
    print("\n📊 NSETOOLS DATA:")
    try:
        import nsetools
        nse = nsetools.Nse()
        quote = nse.get_quote(symbol)
        
        nse_price = quote.get('lastPrice', 0)
        nse_market_cap = quote.get('marketCap', 0) / 10000000 if quote.get('marketCap', 0) > 0 else 0
        nse_prev_close = quote.get('previousClose', 0)
        nse_volume = quote.get('totalTradedVolume', 0)
        nse_high_52w = quote.get('weekHigh52', 0)
        nse_day_change = quote.get('change', 0)
        
        print(f"  Price: ₹{nse_price:.2f}")
        print(f"  Market Cap: ₹{nse_market_cap:.2f} Cr")
        print(f"  Previous Close: ₹{nse_prev_close:.2f}")
        print(f"  Volume: {nse_volume:,}")
        print(f"  52W High: ₹{nse_high_52w:.2f}")
        print(f"  Day Change: {nse_day_change:.2f}%")
        
    except Exception as e:
        print(f"  ❌ nsetools error: {e}")
    
    print("\n" + "=" * 70)
    print("📝 COMPARISON SUMMARY")
    print("=" * 70)
    print("Check if the values match Chartink data above!")
    print("If they don't match, that's why your bot shows 0 stocks.")
    
    # Send to Telegram
    try:
        msg = f"🔍 *Debug Results for {symbol}*\n\n"
        msg += f"Chartink Close: ₹767.45\n"
        msg += f"yfinance Close: ₹{yf_price:.2f}\n" if 'yf_price' in locals() else ""
        msg += f"nsetools Close: ₹{nse_price:.2f}\n" if 'nse_price' in locals() else ""
        bot.send_message(YOUR_CHAT_ID, msg, parse_mode='Markdown')
    except:
        pass

# ============================================
# MAIN RUN
# ============================================
if __name__ == "__main__":
    print("\n🚀 Starting Debug Mode...")
    compare_stock("MANINDS")
    print("\n✅ Debug complete!")
