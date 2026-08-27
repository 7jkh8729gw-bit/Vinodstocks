import os
import yfinance as yf
import pandas as pd
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

print("=" * 60)
print("🧪 TEST: 5 STOCKS, ALL 10 FILTERS")
print("=" * 60)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# TEST STOCKS
# ============================================
TEST_STOCKS = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK']

# ============================================
# DEMA CALCULATION
# ============================================
def calculate_dema(data, period):
    if len(data) < period:
        return None
    ema1 = data.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    return 2 * ema1 - ema2

# ============================================
# CHECK WITH ALL 10 FILTERS
# ============================================
def check_stock(symbol):
    """
    ALL 10 Chartink filters
    """
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        hist = ticker.history(period="6mo")
        
        # 1. Market Cap >= 1000 Cr
        market_cap = info.get('marketCap', 0) / 10_000_000
        cond1 = market_cap >= 1000
        
        # 2. Price >= 100
        price = info.get('regularMarketPrice', 0)
        cond2 = price >= 100
        
        # 3 & 4. Day Change 0-15%
        prev_close = info.get('regularMarketPreviousClose', 0)
        if prev_close > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        cond3 = day_change >= 0
        cond4 = day_change < 15
        
        # 5. Volume >= 200,000
        volume = info.get('regularMarketVolume', 0)
        cond5 = volume >= 200000
        
        # 6. 21-Day Avg Volume > 500,000
        avg_volume = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
        cond6 = avg_volume > 500000
        
        # 7. Within 10% of 52W High
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        if high_52w > 0:
            pct_from_high = (high_52w / price) - 1
        else:
            pct_from_high = 100
        cond7 = pct_from_high <= 0.10
        
        # 8 & 9. DEMA calculations
        if len(hist) >= 200:
            dema_10 = calculate_dema(hist['Close'], 10)
            dema_50 = calculate_dema(hist['Close'], 50)
            dema_200 = calculate_dema(hist['Close'], 200)
            
            if dema_10 is not None and dema_50 is not None and dema_200 is not None:
                d10 = dema_10.iloc[-1]
                d50 = dema_50.iloc[-1]
                d200 = dema_200.iloc[-1]
                cond8 = d50 / d200 >= 1 if d200 > 0 else False
                cond9 = d10 / d50 >= 1 if d50 > 0 else False
            else:
                cond8 = False
                cond9 = False
        else:
            cond8 = False
            cond9 = False
        
        # 10. Volume Ratio >= 1.5x
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        cond10 = volume_ratio >= 1.5
        
        # ALL conditions must pass
        passed = cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10
        
        # Print debug
        print(f"\n📊 {symbol}:")
        print(f"  1️⃣ Market Cap: ₹{market_cap:.1f} Cr {'✅' if cond1 else '❌'}")
        print(f"  2️⃣ Price: ₹{price:.2f} {'✅' if cond2 else '❌'}")
        print(f"  3️⃣ Day Change: {day_change:.2f}% {'✅' if cond3 and cond4 else '❌'}")
        print(f"  4️⃣ Volume: {volume:,} {'✅' if cond5 else '❌'}")
        print(f"  5️⃣ Avg Vol: {avg_volume:,.0f} {'✅' if cond6 else '❌'}")
        print(f"  6️⃣ From 52W High: {pct_from_high*100:.2f}% {'✅' if cond7 else '❌'}")
        if 'd50' in locals() and 'd200' in locals() and d200 > 0:
            print(f"  7️⃣ DEMA(50)/DEMA(200): {(d50/d200):.3f} {'✅' if cond8 else '❌'}")
        else:
            print(f"  7️⃣ DEMA(50)/DEMA(200): N/A {'❌'}")
        if 'd10' in locals() and 'd50' in locals() and d50 > 0:
            print(f"  8️⃣ DEMA(10)/DEMA(50): {(d10/d50):.3f} {'✅' if cond9 else '❌'}")
        else:
            print(f"  8️⃣ DEMA(10)/DEMA(50): N/A {'❌'}")
        print(f"  9️⃣ Volume Ratio: {volume_ratio:.2f}x {'✅' if cond10 else '❌'}")
        print(f"  RESULT: {'✅ PASS' if passed else '❌ FAIL'}")
        
        return passed
        
    except Exception as e:
        print(f"  {symbol}: ❌ ERROR - {e}")
        return False

# ============================================
# MAIN TEST
# ============================================
def run_test():
    print("\n🚀 Testing all 10 filters on 5 stocks...")
    print("-" * 40)
    
    alerts_sent = 0
    
    for symbol in TEST_STOCKS:
        if check_stock(symbol):
            try:
                bot.send_message(YOUR_CHAT_ID, f"🚨 *ALERT: {symbol}* (All 10 filters passed!)", parse_mode='Markdown')
                alerts_sent += 1
                print(f"  ✅ ALERT SENT!")
            except Exception as e:
                print(f"  ❌ Telegram error: {e}")
        
        time.sleep(0.5)
    
    print("\n" + "-" * 40)
    print(f"✅ Test complete! Alerts sent: {alerts_sent}/{len(TEST_STOCKS)}")

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🧪 Testing all 10 filters on 5 stocks!")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🧪 Testing ALL 10 filters on 5 stocks...")
    except:
        pass
    
    run_test()
    print("✅ Done!")
