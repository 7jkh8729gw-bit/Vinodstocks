import os
import yfinance as yf
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
print("🧪 TEST: 5 STOCKS, 2 FILTERS")
print("=" * 60)

# Test connection
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
# CHECK WITH 2 FILTERS
# ============================================
def check_stock(symbol):
    """
    Filters:
    1. Price >= 100
    2. Volume > 200,000
    """
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        
        price = info.get('regularMarketPrice', 0)
        volume = info.get('regularMarketVolume', 0)
        
        # Check both conditions
        passed = price >= 100 and volume > 200000
        
        print(f"  {symbol}: ₹{price:.2f}, Vol: {volume:,} -> {'✅ PASS' if passed else '❌ FAIL'}")
        
        return passed, price, volume
        
    except Exception as e:
        print(f"  {symbol}: ❌ ERROR - {e}")
        return False, 0, 0

# ============================================
# MAIN TEST
# ============================================
def run_test():
    print("\n🚀 Running test with 2 filters...")
    print("-" * 40)
    
    alerts_sent = 0
    
    for symbol in TEST_STOCKS:
        print(f"\n📊 Checking {symbol}...")
        passed, price, volume = check_stock(symbol)
        
        if passed:
            try:
                msg = f"🧪 *ALERT: {symbol}*\nPrice: ₹{price:.2f}\nVolume: {volume:,}"
                bot.send_message(YOUR_CHAT_ID, msg, parse_mode='Markdown')
                alerts_sent += 1
                print(f"  ✅ ALERT SENT!")
            except Exception as e:
                print(f"  ❌ Telegram error: {e}")
        
        time.sleep(0.5)
    
    print("\n" + "-" * 40)
    print(f"✅ Test complete! Alerts sent: {alerts_sent}/{len(TEST_STOCKS)}")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🧪 Testing with 2 filters...")
    except:
        pass
    
    run_test()
    print("✅ Done!")
