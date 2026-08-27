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
print("🧪 TEST: RELAXED DEMA CONDITIONS")
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
        return symbols[:100]  # Only first 100 for testing
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'KOTAKBANK']

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
# CHECK WITH RELAXED CONDITIONS
# ============================================
def check_stock(symbol):
    """Check conditions with RELAXED DEMA (just need > 0)"""
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
        
        # 8 & 9. RELAXED DEMA (just need them to exist, not crossing)
        cond8 = True
        cond9 = True
        if len(hist) >= 200:
            dema_10 = calculate_dema(hist['Close'], 10)
            dema_50 = calculate_dema(hist['Close'], 50)
            dema_200 = calculate_dema(hist['Close'], 200)
            
            if dema_10 is not None and dema_50 is not None and dema_200 is not None:
                d10 = dema_10.iloc[-1]
                d50 = dema_50.iloc[-1]
                d200 = dema_200.iloc[-1]
                # Just need them to be valid values
                cond8 = d50 > 0 and d200 > 0
                cond9 = d10 > 0 and d50 > 0
            else:
                cond8 = False
                cond9 = False
        else:
            cond8 = False
            cond9 = False
        
        # 10. Volume Ratio >= 1.5x
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        cond10 = volume_ratio >= 1.5
        
        # ALL conditions
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
# MAIN TEST
# ============================================
def run_test():
    print("\n🚀 Scanning with RELAXED DEMA conditions (just need valid values)...")
    print("-" * 70)
    
    stocks = get_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    print("-" * 70)
    
    results = []
    alerts = 0
    
    for i, symbol in enumerate(stocks):
        result = check_stock(symbol)
        results.append(result)
        
        if result.get('passed', False):
            alerts += 1
            print(f"✅ {symbol} - PASSED ALL 10 (with relaxed DEMA)!")
            try:
                bot.send_message(YOUR_CHAT_ID, f"🚨 *{symbol}* (Relaxed DEMA)", parse_mode='Markdown')
            except:
                pass
        
        # Show progress
        if (i + 1) % 20 == 0:
            print(f"📊 Progress: {i+1}/{len(stocks)}")
        
        time.sleep(0.1)
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {alerts} stocks with relaxed DEMA conditions.")
    
    # Summary of passing stocks
    passing = [r for r in results if r.get('passed', False)]
    if passing:
        print(f"\n📋 Stocks that passed (relaxed DEMA):")
        for r in passing:
            print(f"  ✅ {r['symbol']}: ₹{r['price']:.2f}, {r['day_change']:.2f}%, Vol Ratio: {r['volume_ratio']:.2f}x")
    else:
        print("\n⚠️ Still no stocks passed with relaxed DEMA.")
        print("   The main bottleneck is likely the Volume Ratio (>= 1.5x)")
        print("   or the 52W High condition.")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🧪 Testing with relaxed DEMA conditions...")
    except:
        pass
    
    start_time = time.time()
    run_test()
    print(f"\n⏱️ Total time: {time.time() - start_time:.1f} seconds")
    print("✅ Done!")
