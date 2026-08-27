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
print("🧪 TEST MODE: 5 STOCKS, 1 FILTER")
print("=" * 60)

# Test connection
try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
    print(f"✅ Chat ID: {YOUR_CHAT_ID}")
    print("=" * 60)
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# TEST STOCKS (Only 5 stocks)
# ============================================
TEST_STOCKS = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK']

# ============================================
# SIMPLE CHECK - Only 1 condition
# ============================================
def check_simple(symbol):
    """
    Only checks: Price >= 100
    This should return TRUE for all test stocks
    """
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        price = info.get('regularMarketPrice', 0)
        
        # Only 1 condition: Price >= 100
        passed = price >= 100
        
        print(f"  {symbol}: ₹{price:.2f} -> {'✅ PASS' if passed else '❌ FAIL'}")
        
        return passed, price
        
    except Exception as e:
        print(f"  {symbol}: ❌ ERROR - {e}")
        return False, 0

# ============================================
# MAIN TEST
# ============================================
def run_test():
    print("\n🚀 Running simple test...")
    print("-" * 40)
    
    alerts_sent = 0
    
    for symbol in TEST_STOCKS:
        print(f"\n📊 Checking {symbol}...")
        passed, price = check_simple(symbol)
        
        if passed:
            try:
                # Send alert to Telegram
                msg = f"🧪 *TEST ALERT: {symbol}* \nPrice: ₹{price:.2f} ✅"
                bot.send_message(YOUR_CHAT_ID, msg, parse_mode='Markdown')
                alerts_sent += 1
                print(f"  ✅ ALERT SENT to Telegram!")
            except Exception as e:
                print(f"  ❌ Telegram error: {e}")
        
        time.sleep(0.5)  # Small delay
    
    print("\n" + "-" * 40)
    print(f"✅ Test complete! Alerts sent: {alerts_sent}/{len(TEST_STOCKS)}")
    print("=" * 60)

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🧪 Test mode is running! Check GitHub Actions logs.")

@bot.message_handler(commands=['status'])
def status(message):
    bot.reply_to(message, f"🧪 Test mode: {len(TEST_STOCKS)} stocks, 1 filter (Price >= 100)")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🧪 Test mode started! Checking 5 stocks with 1 filter...")
        print("✅ Startup message sent!")
    except Exception as e:
        print(f"⚠️ Could not send: {e}")
    
    run_test()
    print("✅ Test complete!")
