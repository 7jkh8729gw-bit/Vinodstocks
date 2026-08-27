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
print("🧪 TEST MODE: ONLY CHARTINK STOCKS")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# CHARTINK STOCKS FROM YOUR EXCEL
# ============================================
TEST_STOCKS = [
    'MANINDS',
    'VINCOFE',
    'WELCORP',
    'ALEMBICLTD',
    'IOLCP',
    'OMAXE',
    'JINDALSAW',
    'LAURUSLABS',
    'KOTAKBANK',
    'DCBBANK'
]

# ============================================
# CHARTINK DATA (from your Excel)
# ============================================
CHARTINK_DATA = {
    'MANINDS': {'price': 767.45, 'day_change': 9.15, 'volume': 2684284, 'avg_volume': 1236460.52, 'high_52w': 783.4, 'market_cap': 5273.92, 'dema_10': 739.50, 'dema_50': 643.52, 'dema_200': 575.98},
    'VINCOFE': {'price': 174.65, 'day_change': 6.44, 'volume': 13730329, 'avg_volume': 2919582.71, 'high_52w': 179.85, 'market_cap': 2390.6, 'dema_10': 165.48, 'dema_50': 157.73, 'dema_200': 154.68},
    'WELCORP': {'price': 2405.8, 'day_change': 4.30, 'volume': 4310413, 'avg_volume': 2371344.43, 'high_52w': 2437.3, 'market_cap': 60848.59, 'dema_10': 2375.86, 'dema_50': 2081.81, 'dema_200': 1631.18},
    'ALEMBICLTD': {'price': 102.77, 'day_change': 4.12, 'volume': 3080956, 'avg_volume': 621174.19, 'high_52w': 109.91, 'market_cap': 2534.44, 'dema_10': 97.82, 'dema_50': 90.99, 'dema_200': 86.59},
    'IOLCP': {'price': 193.07, 'day_change': 3.80, 'volume': 11917299, 'avg_volume': 4395158.05, 'high_52w': 195.64, 'market_cap': 5459.91, 'dema_10': 182.03, 'dema_50': 174.01, 'dema_200': 142.89},
    'OMAXE': {'price': 113.0, 'day_change': 3.32, 'volume': 5405181, 'avg_volume': 3435716.1, 'high_52w': 115.0, 'market_cap': 2000.38, 'dema_10': 108.63, 'dema_50': 98.48, 'dema_200': 84.46},
    'JINDALSAW': {'price': 310.25, 'day_change': 2.58, 'volume': 9221997, 'avg_volume': 2757155.43, 'high_52w': 316.95, 'market_cap': 19341.93, 'dema_10': 297.97, 'dema_50': 283.22, 'dema_200': 248.37},
    'LAURUSLABS': {'price': 1929.4, 'day_change': 2.25, 'volume': 4204238, 'avg_volume': 1994197.86, 'high_52w': 1930.0, 'market_cap': 101945.1, 'dema_10': 1883.04, 'dema_50': 1880.43, 'dema_200': 1625.53},
    'KOTAKBANK': {'price': 424.2, 'day_change': 1.80, 'volume': 33584640, 'avg_volume': 11231559.24, 'high_52w': 453.2, 'market_cap': 414479.37, 'dema_10': 412.83, 'dema_50': 397.56, 'dema_200': 391.6},
    'DCBBANK': {'price': 217.51, 'day_change': 1.72, 'volume': 9932276, 'avg_volume': 2790306.33, 'high_52w': 220.5, 'market_cap': 6886.98, 'dema_10': 209.74, 'dema_50': 195.76, 'dema_200': 194.98}
}

# ============================================
# DEMA CALCULATION
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

# ============================================
# CHECK STOCK - COMPARE WITH CHARTINK
# ============================================
def check_stock(symbol):
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        hist = ticker.history(period="1y")  # 1 year for DEMA
        
        if not info or len(hist) == 0:
            return {'symbol': symbol, 'passed': False, 'error': 'No data'}
        
        # Get bot data
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
        
        # Check conditions
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
            'bot_price': price,
            'bot_day_change': day_change,
            'bot_volume': volume,
            'bot_avg_volume': avg_volume,
            'bot_market_cap': market_cap_raw,
            'bot_high_52w': high_52w,
            'bot_dema_10': dema_10,
            'bot_dema_50': dema_50,
            'bot_dema_200': dema_200,
            'bot_volume_ratio': volume_ratio,
            'data_days': len(hist),
            'cond1': cond1, 'cond2': cond2, 'cond3': cond3,
            'cond4': cond4, 'cond5': cond5, 'cond6': cond6,
            'cond7': cond7, 'cond8': cond8, 'cond9': cond9, 'cond10': cond10
        }
        
    except Exception as e:
        return {'symbol': symbol, 'passed': False, 'error': str(e)[:50]}

# ============================================
# COMPARE WITH CHARTINK
# ============================================
def compare_with_chartink(symbol, bot_data):
    chartink = CHARTINK_DATA.get(symbol)
    if not chartink:
        return
    
    print(f"\n📊 {symbol}:")
    print("-" * 40)
    
    # Price
    price_diff = abs(bot_data['bot_price'] - chartink['price']) / chartink['price'] * 100
    print(f"  Price: Chartink {chartink['price']:.2f} | Bot {bot_data['bot_price']:.2f} | Diff {price_diff:.2f}%")
    
    # Day Change
    day_diff = abs(bot_data['bot_day_change'] - chartink['day_change']) / abs(chartink['day_change']) * 100 if chartink['day_change'] != 0 else 0
    print(f"  Day Change: Chartink {chartink['day_change']:.2f}% | Bot {bot_data['bot_day_change']:.2f}% | Diff {day_diff:.2f}%")
    
    # Volume
    vol_diff = abs(bot_data['bot_volume'] - chartink['volume']) / chartink['volume'] * 100 if chartink['volume'] != 0 else 0
    print(f"  Volume: Chartink {chartink['volume']:,} | Bot {bot_data['bot_volume']:,} | Diff {vol_diff:.2f}%")
    
    # Avg Volume
    avg_diff = abs(bot_data['bot_avg_volume'] - chartink['avg_volume']) / chartink['avg_volume'] * 100 if chartink['avg_volume'] != 0 else 0
    print(f"  Avg Vol: Chartink {chartink['avg_volume']:.2f} | Bot {bot_data['bot_avg_volume']:.2f} | Diff {avg_diff:.2f}%")
    
    # 52W High
    high_diff = abs(bot_data['bot_high_52w'] - chartink['high_52w']) / chartink['high_52w'] * 100 if chartink['high_52w'] != 0 else 0
    print(f"  52W High: Chartink {chartink['high_52w']:.2f} | Bot {bot_data['bot_high_52w']:.2f} | Diff {high_diff:.2f}%")
    
    # Market Cap
    cap_diff = abs(bot_data['bot_market_cap'] - chartink['market_cap']) / chartink['market_cap'] * 100 if chartink['market_cap'] != 0 else 0
    print(f"  Market Cap: Chartink {chartink['market_cap']:.2f} Cr | Bot {bot_data['bot_market_cap']:.2f} Cr | Diff {cap_diff:.2f}%")
    
    # DEMA 10
    d10_diff = abs(bot_data['bot_dema_10'] - chartink['dema_10']) / chartink['dema_10'] * 100 if chartink['dema_10'] != 0 else 0
    print(f"  10 DEMA: Chartink {chartink['dema_10']:.2f} | Bot {bot_data['bot_dema_10']:.2f} | Diff {d10_diff:.2f}%")
    
    # DEMA 50
    d50_diff = abs(bot_data['bot_dema_50'] - chartink['dema_50']) / chartink['dema_50'] * 100 if chartink['dema_50'] != 0 else 0
    print(f"  50 DEMA: Chartink {chartink['dema_50']:.2f} | Bot {bot_data['bot_dema_50']:.2f} | Diff {d50_diff:.2f}%")
    
    # DEMA 200
    d200_diff = abs(bot_data['bot_dema_200'] - chartink['dema_200']) / chartink['dema_200'] * 100 if chartink['dema_200'] != 0 else 0
    print(f"  200 DEMA: Chartink {chartink['dema_200']:.2f} | Bot {bot_data['bot_dema_200']:.2f} | Diff {d200_diff:.2f}%")
    
    # Conditions
    print(f"\n  Conditions passed: {sum([bot_data['cond1'], bot_data['cond2'], bot_data['cond3'], bot_data['cond4'], bot_data['cond5'], bot_data['cond6'], bot_data['cond7'], bot_data['cond8'], bot_data['cond9'], bot_data['cond10']])}/10")
    
    if bot_data['passed']:
        print(f"  ✅ {symbol} PASSED ALL 10!")
        try:
            bot.send_message(YOUR_CHAT_ID, f"🚨 *{symbol}* PASSED ALL 10!", parse_mode='Markdown')
        except:
            pass
    else:
        # Show which conditions failed
        failed = []
        if not bot_data['cond1']: failed.append("Market Cap")
        if not bot_data['cond2']: failed.append("Price")
        if not bot_data['cond3'] or not bot_data['cond4']: failed.append("Day Change")
        if not bot_data['cond5']: failed.append("Volume")
        if not bot_data['cond6']: failed.append("Avg Volume")
        if not bot_data['cond7']: failed.append("52W High")
        if not bot_data['cond8']: failed.append("DEMA 50/200")
        if not bot_data['cond9']: failed.append("DEMA 10/50")
        if not bot_data['cond10']: failed.append("Volume Ratio")
        print(f"  ❌ Failed on: {', '.join(failed)}")

# ============================================
# MAIN RUN
# ============================================
def run_test():
    print("\n🚀 Testing Chartink stocks against yfinance...")
    print("=" * 70)
    
    passed_count = 0
    
    for symbol in TEST_STOCKS:
        result = check_stock(symbol)
        compare_with_chartink(symbol, result)
        if result.get('passed', False):
            passed_count += 1
        time.sleep(0.5)
    
    print("\n" + "=" * 70)
    print(f"✅ Test complete! {passed_count}/{len(TEST_STOCKS)} passed ALL 10 conditions.")
    print("=" * 70)
    
    if passed_count == 0:
        try:
            bot.send_message(YOUR_CHAT_ID, f"📊 Test complete: 0/{len(TEST_STOCKS)} passed all 10 conditions.", parse_mode='Markdown')
        except:
            pass

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🧪 Testing Chartink stocks with yfinance data...", parse_mode='Markdown')
    except:
        pass
    
    run_test()
    print("\n✅ Done!")
