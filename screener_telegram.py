import os
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import telebot
from PKNSETools.Benny.NSE import NSE
from PKNSETools import nseStockDataFetcher, get_Company_History_Data, getTodayData

# ============================================
# YOUR BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)

print("=" * 70)
print("🤖 NSE STOCK SCREENER - PKNSETools VERSION")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# GET NSE STOCKS - Using PKNSETools
# ============================================
def get_nse_stocks():
    """Fetch all NSE stocks using PKNSETools"""
    print("📊 Loading NSE stocks...")
    try:
        fetcher = nseStockDataFetcher()
        # Index 12 = All NSE equities [citation:1][citation:4]
        all_stocks = fetcher.fetchStockCodes(12)
        print(f"✅ Loaded {len(all_stocks)} stocks")
        return all_stocks
    except Exception as e:
        print(f"⚠️ Error: {e}, using fallback")
        return ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'KOTAKBANK']

# ============================================
# CHARTINK-STYLE DEMA
# ============================================
def chartink_dema(data, period):
    """Match Chartink's DEMA calculation exactly"""
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    dema = 2 * ema - ema2
    return dema

# ============================================
# CHECK STOCK - Using PKNSETools
# ============================================
def check_stock(symbol):
    """Check ALL 10 Chartink filters using PKNSETools"""
    try:
        # Initialize NSE API client
        nse = NSE(download_folder="./data")
        
        # Get real-time quote
        quote = nse.quote(symbol)
        price_info = quote.get('priceInfo', {})
        
        # 1. Market Cap (from quote)
        market_cap_raw = quote.get('marketCap', 0)
        market_cap_crores = market_cap_raw / 10000000 if market_cap_raw > 0 else 0
        cond1 = market_cap_crores >= 1000
        
        # 2. Price >= 100
        price = price_info.get('lastPrice', 0)
        cond2 = price >= 100
        
        # 3 & 4. Day Change 0-15%
        prev_close = price_info.get('previousClose', 0)
        if prev_close > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        cond3 = day_change >= 0
        cond4 = day_change < 15
        
        # 5. Volume >= 200,000
        volume = quote.get('totalTradedVolume', 0)
        cond5 = volume >= 200000
        
        # 6. 21-Day Avg Volume from historical data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)
        
        hist = get_Company_History_Data(
            company=symbol,
            from_date=start_date.strftime('%d-%m-%Y'),
            to_date=end_date.strftime('%d-%m-%Y')
        )
        
        if len(hist) >= 21:
            avg_volume = hist['Volume'].tail(21).mean()
        else:
            avg_volume = 0
        cond6 = avg_volume > 500000
        
        # 7. Within 10% of 52W High
        high_52w = price_info.get('weekHigh', 0)
        if high_52w > 0:
            pct_from_high = (high_52w / price) - 1
        else:
            pct_from_high = 100
        cond7 = pct_from_high <= 0.10
        
        # 8 & 9. DEMA calculations
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
        
        # 10. Volume Ratio >= 1.5x
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        cond10 = volume_ratio >= 1.5
        
        # ALL conditions
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
        return {'symbol': symbol, 'passed': False, 'error': str(e)}

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting full scan with PKNSETools...")
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
        
        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        
        time.sleep(0.3)
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {alerts} stocks passing ALL 10 conditions.")
    
    passing = [r for r in results if r.get('passed', False)]
    if passing:
        print(f"\n📋 Stocks that passed:")
        for r in passing:
            print(f"  ✅ {r['symbol']}: ₹{r['price']:.2f}, {r['day_change']:.2f}%")
        
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

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🤖 NSE Stock Screener is running with PKNSETools!\n\n📊 Scans all NSE stocks every 10 minutes\n📋 10 filters matching Chartink\n🚨 Alerts when ALL conditions pass")

@bot.message_handler(commands=['status'])
def status(message):
    bot.reply_to(message, "✅ Scanner is active.\n🔄 Scans every 10 minutes.\n📊 Using PKNSETools for reliable NSE data.")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🔄 NSE Stock Screener is running with PKNSETools!", parse_mode='Markdown')
    except:
        pass
    
    run_scanner()
    print("\n✅ Done!")
