import os
import yfinance as yf
import pickle
import time
from datetime import datetime
import telebot

# ============================================
# BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)
WATCHLIST_FILE = "morning_watchlist.pkl"

print("=" * 70)
print("📊 VOLUME SCREENER - MARKET HOURS")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# LOAD WATCHLIST
# ============================================
def load_watchlist():
    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE, 'rb') as f:
                return pickle.load(f)
        return None
    except:
        return None

# ============================================
# GET INTRADAY DATA
# ============================================
def get_intraday_data(symbol):
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        current_volume = info.get('regularMarketVolume', 0)
        current_price = info.get('regularMarketPrice', 0)
        return current_volume, current_price
    except:
        return 0, 0

# ============================================
# MONITOR VOLUME
# ============================================
def monitor_volume(watchlist, spike_multiplier=3):
    print(f"\n📊 Monitoring {len(watchlist)} stocks from morning watchlist...")
    print(f"⚡ Volume spike threshold: {spike_multiplier}x")
    print("=" * 70)

    alerted = {}

    while True:
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"\n🕐 {current_time} - Checking volume...")

        for stock in watchlist:
            symbol = stock['symbol']
            avg_volume = stock['avg_volume']

            try:
                current_volume, current_price = get_intraday_data(symbol)

                if avg_volume > 0 and current_volume > 0:
                    spike_ratio = current_volume / avg_volume

                    if spike_ratio >= spike_multiplier:
                        if symbol not in alerted:
                            alerted[symbol] = True
                            print(f"⚡ VOLUME SPIKE: {symbol} ({spike_ratio:.1f}x)")

                            msg = (
                                f"🚨 *VOLUME SPIKE DETECTED*\n"
                                f"📊 *{symbol}*\n\n"
                                f"💰 Price: ₹{current_price:.2f}\n"
                                f"📈 Day Change: {stock['day_change']:.2f}%\n"
                                f"📊 Volume Spike: {spike_ratio:.1f}x\n"
                                f"📊 Avg Volume: {avg_volume:,.0f}\n"
                                f"📊 Current Volume: {current_volume:,}\n"
                                f"💼 Market Cap: ₹{stock['market_cap']:.2f} Cr\n\n"
                                f"✅ Stock passed Morning Screener!\n"
                                f"🚀 *Consider buying!*"
                            )
                            bot.send_message(YOUR_CHAT_ID, msg, parse_mode='Markdown')

                    elif spike_ratio < spike_multiplier:
                        if symbol in alerted:
                            alerted.pop(symbol, None)

            except Exception as e:
                print(f"⚠️ Error checking {symbol}: {e}")

            time.sleep(0.2)

        time.sleep(60)  # Check every minute

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    # Send start message
    bot.send_message(YOUR_CHAT_ID, "📊 *Volume Screener is running!*", parse_mode='Markdown')

    watchlist = load_watchlist()

    if not watchlist:
        print("❌ No watchlist found.")
        bot.send_message(YOUR_CHAT_ID, "📊 *No stocks cleared in Volume Screener today.*", parse_mode='Markdown')
        exit(0)

    print(f"✅ Loaded {len(watchlist)} stocks from watchlist")

    # Send watchlist summary
    summary = f"📊 *Volume Screener - Monitoring {len(watchlist)} stocks*\n\n"
    for s in watchlist[:10]:
        summary += f"✅ {s['symbol']} - ₹{s['price']:.2f} ({s['day_change']:.2f}%)\n"
    bot.send_message(YOUR_CHAT_ID, summary, parse_mode='Markdown')

    monitor_volume(watchlist)
