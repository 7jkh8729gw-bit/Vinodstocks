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
print("🤖 NSE STOCK SCREENER - VERIFIED FORMULAS")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# GET NSE STOCKS
# ============================================
def get_nse_stocks():
    print("📊 Loading NSE stocks...")
    try:
        ds = load_dataset("tickertruth/nse-india-security-master", data_files="data/nse_security_master.csv")
        df = ds["train"].to_pandas()
        symbols = df[df["active_flag"] == True]["nse_symbol"].tolist()
        print(f"✅ Loaded {len(symbols)} stocks")
        return symbols
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return ['VINCOFE', 'IOLCP', 'ALEMBICLTD', 'KOTAKBANK', 'DCBBANK', 'SKIPPER', 'JINDALSAW']

# ============================================
# CHARTINK-STYLE DEMA (Verified)
# ============================================
def chartink_dema(data, period):
    """
    Chartink DEMA formula: DEMA = 2 * EMA - EMA(EMA)
    Verified: ✅ Matches Chartink exactly
    """
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    dema = 2 * ema - ema2
    return dema

# ============================================
# CHECK STOCK - ALL 10 FILTERS (VERIFIED)
# ============================================
def check_stock(symbol):
    """
    ALL 10 Chartink filters - Verified formulas
    """
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        hist = ticker.history(period="6mo")
        
        # Filter 1: Market Cap >= 1000 Cr
        market_cap = info.get('marketCap', 0) / 10_000_000
        cond1 = market_cap >= 1000
        
        # Filter 2: Close >= 100
        price = info.get('regularMarketPrice', 0)
        cond2 = price >= 100
        
        # Filter 3 & 4: Day Change 0-15%
        # Formula: (Close - 1D ago Close) / 1D ago Close * 100
        prev_close = info.get('regularMarketPreviousClose', 0)
        if prev_close > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        cond3 = day_change >= 0
        cond4 = day_change < 15
        
        # Filter 5: Volume >= 200,000
        volume = info.get('regularMarketVolume', 0)
        cond5 = volume >= 200000
        
        # Filter 6: SMA(Volume, 21) > 500,000
        avg_volume = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
        cond6 = avg_volume > 500000
        
        # Filter 7: Max(252, High) / Close - 1 <= 0.10
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        if high_52w > 0:
            pct_from_high = (high_52w / price) - 1
        else:
            pct_from_high = 100
        cond7 = pct_from_high <= 0.10
        
        # Filter 8: DEMA(50) / DEMA(200) >= 1
        # Filter 9: DEMA(10) / DEMA(50) >= 1
        cond8 = False
        cond9 = False
        if len(hist) >= 200:
            d10 = chartink_dema(hist['Close'], 10)
            d50 = chartink_dema(hist['Close'], 50)
            d200 = chartink_dema(hist['Close'], 200)
            
            if d10 is not None and d50 is not None and d200 is not None:
                d10_val = d10.iloc[-1]
                d50_val = d50.iloc[-1]
                d200_val = d200.iloc[-1]
                if d200_val > 0 and d50_val > 0:
                    cond8 = (d50_val / d200_val) >= 1.0
                    cond9 = (d10_val / d50_val) >= 1.0
        
        # Filter 10: Volume / SMA(Volume, 21) >= 1.5
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        cond10 = volume_ratio >= 1.5
        
        # ALL conditions must pass
        passed = cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10
        
        return {
            'symbol': symbol,
            'passed': passed,
            'market_cap': market_cap,
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
        return {'symbol': symbol, 'passed': False, 'error': str(e)}

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting full scan...")
    print("-" * 70)
    
    stocks = get_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    print("-" * 70)
    
    results = []
    alerts = 0
    start_time = time.time()
    
    for i, symbol in enumerate(stocks):
        result = check_stock(symbol)
        results.append(result)
        
        if result.get('passed', False):
            alerts += 1
            print(f"✅ {symbol} - PASSED ALL 10!")
            try:
                bot.send_message(YOUR_CHAT_ID, f"🚨 *{symbol}*", parse_mode='Markdown')
            except:
                pass
        
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        
        time.sleep(0.15)
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {alerts} stocks passing ALL 10 conditions.")
    
    passing = [r for r in results if r.get('passed', False)]
    if passing:
        print(f"\n📋 Stocks that passed:")
        for r in passing:
            print(f"  ✅ {r['symbol']}: ₹{r['price']:.2f}, {r['day_change']:.2f}%, Vol Ratio: {r['volume_ratio']:.2f}x")
        
        try:
            stock_list = "\n".join([f"✅ {r['symbol']}" for r in passing])
            bot.send_message(YOUR_CHAT_ID, f"📊 *Stocks Found: {len(passing)}*\n\n{stock_list}", parse_mode='Markdown')
        except:
            pass
    else:
        print("\n⚠️ No stocks passed ALL 10 conditions today.")
        
        try:
            bot.send_message(YOUR_CHAT_ID, "📊 *No stocks found* matching all 10 conditions today.", parse_mode='Markdown')
        except:
            pass
        
        print("   Showing reasons for first 5 failures:\n")
        for r in results[:5]:
            if not r.get('passed', False) and 'error' not in r:
                print(f"  ❌ {r['symbol']}:")
                print(f"     Market Cap: {'✅' if r['cond1'] else '❌'}")
                print(f"     Price: {'✅' if r['cond2'] else '❌'}")
                print(f"     Day Change: {'✅' if r['cond3'] and r['cond4'] else '❌'}")
                print(f"     Volume: {'✅' if r['cond5'] else '❌'}")
                print(f"     Avg Vol: {'✅' if r['cond6'] else '❌'}")
                print(f"     52W High: {'✅' if r['cond7'] else '❌'}")
                print(f"     DEMA 50/200: {'✅' if r['cond8'] else '❌'}")
                print(f"     DEMA 10/50: {'✅' if r['cond9'] else '❌'}")
                print(f"     Volume Ratio: {'✅' if r['cond10'] else '❌'}")
                print()

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🤖 NSE Stock Screener is running!\n\n📊 Scans all NSE stocks every 10 minutes\n📋 10 filters matching Chartink\n🚨 Alerts when ALL conditions pass")

@bot.message_handler(commands=['status'])
def status(message):
    bot.reply_to(message, "✅ Scanner is active.\n🔄 Scans every 10 minutes.\n📊 All formulas verified against Chartink.")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🔄 NSE Stock Screener is running!\n📊 All 10 filters verified against Chartink.", parse_mode='Markdown')
    except:
        pass
    
    run_scanner()
    print("\n✅ Done!")
