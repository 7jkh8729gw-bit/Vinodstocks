import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
import pickle
from datetime import datetime
import telebot
from datasets import load_dataset

# ============================================
# BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('DOUBLE_BOTTOM_BOT_TOKEN', "8845742478:AAFQ_WRTUeMa5brPkiJHYevnWjLyg-fo6aQ")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)
CACHE_FILE = "double_bottom_cache.pkl"

print("=" * 70)
print("🔍 DOUBLE BOTTOM SCANNER (FINAL - WITH DOWTREND)")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
    print(f"✅ Chat ID: {YOUR_CHAT_ID}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# GET ALL NSE STOCKS
# ============================================
def get_all_nse_stocks():
    print("📊 Fetching NSE stock list...")
    try:
        ds = load_dataset("tickertruth/nse-india-security-master", data_files="data/nse_security_master.csv")
        df = ds["train"].to_pandas()
        stocks = df[df["active_flag"] == True]["nse_symbol"].tolist()
        print(f"✅ Loaded {len(stocks)} stocks")
        return stocks
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK']

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
# MACD CALCULATION
# ============================================
def calculate_macd(close_prices):
    if len(close_prices) < 26:
        return False
    
    ema_12 = pd.Series(close_prices).ewm(span=12, adjust=False).mean()
    ema_26 = pd.Series(close_prices).ewm(span=26, adjust=False).mean()
    
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    
    if len(macd_line) > 0 and len(signal_line) > 0:
        return macd_line.iloc[-1] > signal_line.iloc[-1]
    
    return False

# ============================================
# CHECK UPPER WICK CONDITION
# ============================================
def check_upper_wick(ohlc_data, lookback=5, max_wick_percent=5):
    if len(ohlc_data) < lookback:
        return False
    
    recent = ohlc_data[-lookback:]
    
    for candle in recent:
        high = candle[0]
        low = candle[1]
        close = candle[2]
        
        candle_range = high - low
        if candle_range <= 0:
            return False
        
        upper_wick = high - close
        upper_wick_pct = (upper_wick / candle_range) * 100
        
        if upper_wick_pct > max_wick_percent:
            return False
    
    return True

# ============================================
# CHECK DOWNTREND BEFORE DOUBLE BOTTOM
# ============================================
def check_downtrend(close_prices, lookback=90, max_high_drop=0.15):
    """
    Check if there was a downtrend before the double bottom pattern.
    - Lookback: 90 days before the pattern
    - Price must have dropped at least 15% from its high
    """
    if len(close_prices) < lookback + 60:
        return False, 0
    
    # Get prices before the double bottom (first 90 days of the lookback)
    pre_pattern = close_prices[-lookback-60:-60]
    
    if len(pre_pattern) < 30:
        return False, 0
    
    # Find the highest price in the pre-pattern period
    high_price = max(pre_pattern)
    current_price = pre_pattern[-1]
    
    # Calculate drop from high
    drop_pct = (high_price - current_price) / high_price
    
    # Check if drop is at least 15%
    if drop_pct >= max_high_drop:
        return True, drop_pct * 100
    
    return False, 0

# ============================================
# FINAL DOUBLE BOTTOM DETECTION
# ============================================
def detect_double_bottom(ohlc_data, close_prices, lookback=60, max_low_diff=0.03, peak_min_pct=0.05):
    """
    FINAL: Double bottom detection with:
    - Must appear after a downtrend (15%+ drop from high)
    - Minimum 60 days between lows
    - Max 3% difference between lows
    - Peak at least 5% higher than avg of lows
    - Second low higher than first
    - Upper wick condition on last 5 candles
    - Immediate breakout alert
    """
    if len(close_prices) < lookback + 90:
        return False, {}
    
    # First, check if there was a downtrend before the pattern
    has_downtrend, drop_pct = check_downtrend(close_prices)
    if not has_downtrend:
        return False, {}
    
    recent = close_prices[-lookback:]
    
    # Find local minima (bottoms)
    lows = []
    for i in range(5, len(recent) - 5):
        window = recent[i-5:i+6]
        if recent[i] == min(window):
            lows.append((i, recent[i]))
    
    if len(lows) < 2:
        return False, {}
    
    # Get two most recent lows
    low1 = lows[-2]
    low2 = lows[-1]
    
    if low1[1] <= 0 or low2[1] <= 0:
        return False, {}
    
    # CONDITION 1: Second low must be ABOVE first low
    if low2[1] <= low1[1]:
        return False, {}
    
    # CONDITION 2: Lows must be within 3% of each other
    diff_pct = abs((low2[1] - low1[1]) / low1[1])
    if diff_pct > max_low_diff:
        return False, {}
    
    # CONDITION 3: Minimum 60 days between lows
    days_between = low2[0] - low1[0]
    if days_between < 60:
        return False, {}
    
    # Find peak between the two lows
    peak_price = max(recent[low1[0]:low2[0]+1])
    
    # CONDITION 4: Peak must be at least 5% higher than average of two lows
    avg_low = (low1[1] + low2[1]) / 2
    peak_vs_avg = (peak_price - avg_low) / avg_low
    if peak_vs_avg < peak_min_pct:
        return False, {}
    
    # CONDITION 5: Upper wick check on last 5 candles
    if not check_upper_wick(ohlc_data, lookback=5, max_wick_percent=5):
        return False, {}
    
    # CONDITION 6: Immediate breakout alert
    current_price = recent[-1]
    if current_price < peak_price:
        return False, {}
    
    # All conditions passed!
    return True, {
        'low1': low1[1],
        'low2': low2[1],
        'avg_low': avg_low,
        'peak': peak_price,
        'peak_vs_avg_pct': peak_vs_avg * 100,
        'current': current_price,
        'breakout_pct': ((current_price - peak_price) / peak_price) * 100,
        'days_between': days_between,
        'low_diff_pct': diff_pct * 100,
        'drop_pct': drop_pct,
        'low_strength': 'Second low higher than first ✅' if low2[1] > low1[1] else 'Equal lows'
    }

# ============================================
# BUILD CACHE
# ============================================
def build_cache(stocks):
    print("🏗️ Building initial cache...")
    cache = {}
    total = len(stocks)
    
    for i, symbol in enumerate(stocks):
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            hist = ticker.history(period="1y")
            
            if len(hist) >= 200:
                d50 = chartink_dema(hist['Close'], 50)
                d200 = chartink_dema(hist['Close'], 200)
                
                if d50 is not None and d200 is not None:
                    avg_volume = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
                    
                    cache[symbol] = {
                        'dema_50': d50.iloc[-1],
                        'dema_200': d200.iloc[-1],
                        'avg_volume': avg_volume,
                        'last_update': datetime.now().strftime('%Y-%m-%d'),
                        'close_prices': hist['Close'].tolist()[-200:],
                        'ohlc_data': list(zip(hist['High'].tolist()[-80:], 
                                             hist['Low'].tolist()[-80:], 
                                             hist['Close'].tolist()[-80:]))
                    }
        except:
            pass
        
        if (i + 1) % 100 == 0:
            print(f"📊 Cache progress: {i+1}/{total}")
        
        time.sleep(0.05)
    
    print(f"✅ Cache built for {len(cache)} stocks")
    return cache

# ============================================
# CHECK STOCK
# ============================================
def check_double_bottom(symbol, cache):
    try:
        cached = cache.get(symbol)
        if cached is None:
            return {'symbol': symbol, 'passed': False}
        
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        
        if not info:
            return {'symbol': symbol, 'passed': False}
        
        price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        market_cap_raw = info.get('marketCap', 0) / 10000000
        volume = info.get('regularMarketVolume', 0)
        
        close_prices = cached.get('close_prices', [])
        ohlc_data = cached.get('ohlc_data', [])
        avg_volume = cached.get('avg_volume', 0)
        dema_50 = cached.get('dema_50', 0)
        dema_200 = cached.get('dema_200', 0)
        
        # Check double bottom pattern with downtrend check
        has_pattern, pattern_details = detect_double_bottom(ohlc_data, close_prices)
        
        if not has_pattern:
            return {'symbol': symbol, 'passed': False}
        
        # Additional conditions
        cond1 = market_cap_raw >= 1000
        cond2 = price >= 100
        cond3 = volume >= 2.0 * avg_volume if avg_volume > 0 else False
        cond4 = dema_50 > dema_200
        cond5 = calculate_macd(close_prices)
        
        passed = cond1 and cond2 and cond3 and cond4 and cond5
        
        return {
            'symbol': symbol,
            'passed': passed,
            'price': price,
            'volume': volume,
            'avg_volume': avg_volume,
            'volume_ratio': volume / avg_volume if avg_volume > 0 else 0,
            'market_cap': market_cap_raw,
            'golden_cross': cond4,
            'macd_bullish': cond5,
            'low1': pattern_details.get('low1', 0),
            'low2': pattern_details.get('low2', 0),
            'avg_low': pattern_details.get('avg_low', 0),
            'peak': pattern_details.get('peak', 0),
            'peak_vs_avg_pct': pattern_details.get('peak_vs_avg_pct', 0),
            'breakout_pct': pattern_details.get('breakout_pct', 0),
            'days_between': pattern_details.get('days_between', 0),
            'low_diff_pct': pattern_details.get('low_diff_pct', 0),
            'drop_pct': pattern_details.get('drop_pct', 0),
            'low_strength': pattern_details.get('low_strength', '')
        }
        
    except Exception as e:
        return {'symbol': symbol, 'passed': False}

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting Double Bottom scan (WITH DOWNTEND)...")
    print("-" * 70)
    
    stocks = get_all_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
            print(f"✅ Cache loaded: {len(cache)} stocks")
        except:
            pass
    
    if not cache:
        cache = build_cache(stocks)
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
        print("✅ Cache saved")
    
    print("-" * 70)
    print("⚡ Scanning using cached data...")
    print("-" * 70)
    
    alerts = 0
    start_time = time.time()
    
    for i, symbol in enumerate(stocks):
        result = check_double_bottom(symbol, cache)
        
        if result.get('passed', False):
            alerts += 1
            details = (
                f"🔔 *DOUBLE BOTTOM DETECTED!*\n"
                f"📊 *{symbol}*\n\n"
                f"📉 Prior Drop: {result['drop_pct']:.1f}% (Downtrend ✅)\n"
                f"📉 First Bottom: ₹{result['low1']:.2f}\n"
                f"📉 Second Bottom: ₹{result['low2']:.2f} (Higher ✅)\n"
                f"📊 Low Diff: {result['low_diff_pct']:.2f}% (≤3% ✅)\n"
                f"📅 Days Between: {result['days_between']} days (≥60 ✅)\n"
                f"📊 Avg Low: ₹{result['avg_low']:.2f}\n"
                f"📈 Peak: ₹{result['peak']:.2f}\n"
                f"📈 Peak vs Avg: {result['peak_vs_avg_pct']:.2f}% (≥5% ✅)\n"
                f"💰 Current Price: ₹{result['price']:.2f}\n"
                f"📊 Breakout: {result['breakout_pct']:.2f}%\n"
                f"📈 Volume Spike: {result['volume_ratio']:.2f}x\n"
                f"🟢 Golden Cross: {'✅' if result['golden_cross'] else '❌'}\n"
                f"📊 MACD Bullish: {'✅' if result['macd_bullish'] else '❌'}\n"
                f"💼 Market Cap: ₹{result['market_cap']:.2f} Cr"
            )
            print(f"✅ {symbol} - DOUBLE BOTTOM FOUND!")
            try:
                bot.send_message(YOUR_CHAT_ID, details, parse_mode='Markdown')
            except:
                pass
        
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        
        time.sleep(0.05)
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {alerts} double bottom patterns.")
    print(f"⏱️ Time taken: {time.time() - start_time:.1f} seconds")
    
    if alerts == 0:
        try:
            bot.send_message(YOUR_CHAT_ID, "📊 *No double bottom patterns found* today.", parse_mode='Markdown')
        except:
            pass

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, 
        "🔍 *Double Bottom Scanner (With Downtrend)*\n\n"
        "📊 *Conditions:*\n"
        "• Price must drop ≥15% before pattern (downtrend)\n"
        "• Minimum 60 days between lows\n"
        "• Max 3% difference between lows\n"
        "• Second low HIGHER than first\n"
        "• Peak ≥5% higher than avg of lows\n"
        "• Upper wick ≤5% on last 5 candles\n"
        "• IMMEDIATE alert on breakout\n"
        "• Volume spike ≥ 2.0x\n"
        "• MACD bullish (open)\n"
        "• Golden Cross\n"
        "• Price ≥ ₹100\n"
        "• Market Cap ≥ ₹1000 Cr",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['status'])
def status(message):
    cache_size = 0
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
                cache_size = len(cache)
        except:
            pass
    
    bot.reply_to(message, 
        f"✅ *Scanner Status*\n"
        f"📦 Cache: {cache_size} stocks\n"
        f"🔄 Scans every 10 minutes\n"
        f"📉 Downtrend required: ≥15% drop\n"
        f"📅 Min days between lows: 60\n"
        f"📊 Max low diff: 3%\n"
        f"📈 Volume Spike: ≥ 2.0x",
        parse_mode='Markdown'
    )

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🔍 Double Bottom Scanner (With Downtrend) is running!", parse_mode='Markdown')
    except:
        pass
    
    run_scanner()
    print("\n✅ Done!")
