import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
import pickle
from datetime import datetime, timedelta
import telebot
from datasets import load_dataset

# ============================================
# BOT DETAILS
# ============================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8752957835:AAGGIz2F17tIviD_lDRmEcVSRIvBScew_bY")
YOUR_CHAT_ID = os.environ.get('CHAT_ID', "5261154533")
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)
CACHE_FILE = "screener_cache.pkl"

print("=" * 70)
print("🎯 NSE SCREENER - FINAL VERSION")
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
# CACHE FUNCTIONS
# ============================================
def load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
            print(f"✅ Cache loaded: {len(cache)} stocks")
            return cache
        else:
            print("ℹ️ No cache found, will build new")
            return {}
    except Exception as e:
        print(f"⚠️ Error loading cache: {e}")
        return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
        print(f"✅ Cache saved: {len(cache)} stocks")
    except Exception as e:
        print(f"⚠️ Error saving cache: {e}")

# ============================================
# TECHNICAL INDICATORS
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

def calculate_rsi(close_prices, period=14):
    if len(close_prices) < period + 1:
        return None
    deltas = np.diff(close_prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    if down == 0:
        return 100
    rs = up / down
    return 100 - (100 / (1 + rs))

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

def calculate_atr(high_prices, low_prices, close_prices, period=14):
    if len(close_prices) < period + 1:
        return 0
    high = np.array(high_prices[-period-1:])
    low = np.array(low_prices[-period-1:])
    close = np.array(close_prices[-period-1:])
    tr1 = high[1:] - low[1:]
    tr2 = abs(high[1:] - close[:-1])
    tr3 = abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return np.mean(tr)

def calculate_adx(high_prices, low_prices, close_prices, period=14):
    if len(close_prices) < period + 1:
        return 0
    high = np.array(high_prices[-period-1:])
    low = np.array(low_prices[-period-1:])
    close = np.array(close_prices[-period-1:])
    
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    tr1 = high[1:] - low[1:]
    tr2 = abs(high[1:] - close[:-1])
    tr3 = abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    
    atr = np.mean(tr)
    if atr == 0:
        return 0
    
    plus_di = 100 * (np.mean(plus_dm) / atr)
    minus_di = 100 * (np.mean(minus_dm) / atr)
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = np.mean(dx)
    
    return adx

# ============================================
# CORE 10 FILTERS (MUST PASS ALL)
# ============================================
def check_core_filters(info, cached):
    try:
        price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        market_cap = cached.get('market_cap', 0)
        prev_close = info.get('regularMarketPreviousClose', 0)
        volume = info.get('regularMarketVolume', 0)
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        
        avg_volume = cached.get('avg_volume', 0)
        dema_10 = cached.get('dema_10', 0)
        dema_50 = cached.get('dema_50', 0)
        dema_200 = cached.get('dema_200', 0)
        
        if prev_close > 0 and price > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        
        # ALL 10 filters
        cond1 = market_cap >= 1000
        cond2 = price >= 100
        cond3 = day_change >= 0
        cond4 = day_change < 15
        cond5 = volume >= 200000
        cond6 = avg_volume > 500000
        cond7 = high_52w > 0 and (high_52w / price) - 1 <= 0.10
        cond8 = dema_200 > 0 and (dema_50 / dema_200) >= 1.0
        cond9 = dema_50 > 0 and (dema_10 / dema_50) >= 1.0
        cond10 = volume_ratio >= 1.5
        
        all_pass = cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10
        
        return {
            'all_pass': all_pass,
            'price': price,
            'day_change': day_change,
            'volume_ratio': volume_ratio,
            'market_cap': market_cap,
            'volume': volume,
            'avg_volume': avg_volume,
            'cond1': cond1, 'cond2': cond2, 'cond3': cond3, 'cond4': cond4,
            'cond5': cond5, 'cond6': cond6, 'cond7': cond7, 'cond8': cond8,
            'cond9': cond9, 'cond10': cond10
        }
    except:
        return None

# ============================================
# PATTERN DETECTION (Bonus)
# ============================================
def detect_double_bottom(close_prices, high_prices, low_prices, lookback=120):
    if len(close_prices) < lookback:
        return False, 0, {}
    
    atr = calculate_atr(high_prices, low_prices, close_prices)
    avg_price = np.mean(close_prices[-50:])
    volatility_pct = (atr / avg_price) * 100 if avg_price > 0 else 2
    drop_threshold = max(0.08, min(0.20, 0.12 + (volatility_pct - 2) * 0.02))
    
    pre_pattern = close_prices[-lookback-30:-30]
    if len(pre_pattern) >= 20:
        high_price = max(pre_pattern)
        current_price = pre_pattern[-1]
        drop_pct = (high_price - current_price) / high_price
        if drop_pct < drop_threshold:
            return False, 0, {}
    else:
        return False, 0, {}
    
    recent = close_prices[-lookback:]
    lows = []
    for i in range(3, len(recent) - 3):
        if recent[i] == min(recent[i-3:i+4]):
            lows.append((i, recent[i]))
    
    if len(lows) < 2:
        return False, 0, {}
    
    low1 = lows[-2]
    low2 = lows[-1]
    
    if low1[1] <= 0 or low2[1] <= 0:
        return False, 0, {}
    if low2[1] <= low1[1]:
        return False, 0, {}
    
    diff_pct = abs((low2[1] - low1[1]) / low1[1])
    if diff_pct > 0.05:
        return False, 0, {}
    
    days_between = low2[0] - low1[0]
    if days_between < 10 or days_between > 90:
        return False, 0, {}
    
    avg_low = (low1[1] + low2[1]) / 2
    peak_price = max(recent[low1[0]:low2[0]+1])
    peak_vs_avg = (peak_price - avg_low) / avg_low
    if peak_vs_avg < 0.03:
        return False, 0, {}
    
    current_price = recent[-1]
    if current_price < peak_price:
        return False, 0, {}
    
    score = 25
    if diff_pct < 0.02:
        score += 5
    if peak_vs_avg > 0.07:
        score += 5
    if days_between > 40:
        score += 5
    
    return True, min(score, 35), {
        'low1': low1[1],
        'low2': low2[1],
        'avg_low': avg_low,
        'peak': peak_price,
        'drop_pct': drop_pct * 100,
        'days_between': days_between,
        'pattern_type': 'Double Bottom'
    }

def detect_bullish_engulfing(open_prices, close_prices):
    if len(open_prices) < 2 or len(close_prices) < 2:
        return False, 0, {}
    
    last_open = open_prices[-1]
    prev_open = open_prices[-2]
    last_close = close_prices[-1]
    prev_close = close_prices[-2]
    
    if prev_close >= prev_open:
        return False, 0, {}
    if last_close <= last_open:
        return False, 0, {}
    if last_open > prev_close and last_close < prev_open:
        return False, 0, {}
    if last_open <= prev_close and last_close >= prev_open:
        return True, 10, {'pattern_type': 'Bullish Engulfing'}
    
    return False, 0, {}

def detect_morning_star(open_prices, close_prices, high_prices, low_prices):
    if len(open_prices) < 3:
        return False, 0, {}
    
    if close_prices[-3] >= open_prices[-3]:
        return False, 0, {}
    
    body2 = abs(close_prices[-2] - open_prices[-2])
    range2 = high_prices[-2] - low_prices[-2]
    if range2 == 0 or body2 / range2 > 0.3:
        return False, 0, {}
    
    if open_prices[-2] >= close_prices[-3]:
        return False, 0, {}
    if close_prices[-1] <= open_prices[-1]:
        return False, 0, {}
    
    mid_point = (open_prices[-3] + close_prices[-3]) / 2
    if close_prices[-1] < mid_point:
        return False, 0, {}
    
    return True, 10, {'pattern_type': 'Morning Star'}

# ============================================
# BUILD CACHE
# ============================================
def build_cache(stocks):
    print("🏗️ Building initial cache (this will take ~15-20 minutes)...")
    cache = {}
    total = len(stocks)
    built = 0
    
    for i, symbol in enumerate(stocks):
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            info = ticker.info
            hist = ticker.history(period="1y")
            
            if len(hist) >= 200 and info:
                d10 = chartink_dema(hist['Close'], 10)
                d50 = chartink_dema(hist['Close'], 50)
                d200 = chartink_dema(hist['Close'], 200)
                
                if d10 is not None and d50 is not None and d200 is not None:
                    cache[symbol] = {
                        'dema_10': d10.iloc[-1],
                        'dema_50': d50.iloc[-1],
                        'dema_200': d200.iloc[-1],
                        'avg_volume': hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0,
                        'close_prices': hist['Close'].tolist()[-200:],
                        'open_prices': hist['Open'].tolist()[-200:],
                        'high_prices': hist['High'].tolist()[-200:],
                        'low_prices': hist['Low'].tolist()[-200:],
                        'market_cap': info.get('marketCap', 0) / 10000000,
                        'last_update': datetime.now().strftime('%Y-%m-%d')
                    }
                    built += 1
        except:
            pass
        
        if (i + 1) % 50 == 0:
            print(f"📊 Cache progress: {i+1}/{total} (built: {built})")
        
        time.sleep(0.03)
    
    print(f"✅ Cache built for {built} stocks")
    return cache

# ============================================
# SCORE STOCK
# ============================================
def score_stock(symbol, cached):
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        
        if not info:
            return None
        
        # Check core filters
        filter_result = check_core_filters(info, cached)
        if not filter_result or not filter_result['all_pass']:
            return None
        
        # Get data for patterns
        close_prices = cached.get('close_prices', [])
        open_prices = cached.get('open_prices', [])
        high_prices = cached.get('high_prices', [])
        low_prices = cached.get('low_prices', [])
        
        if len(close_prices) < 100:
            return None
        
        # Calculate indicators
        rsi = calculate_rsi(close_prices)
        macd_bullish = calculate_macd(close_prices)
        adx = calculate_adx(high_prices, low_prices, close_prices)
        atr = calculate_atr(high_prices, low_prices, close_prices)
        price = filter_result['price']
        
        # Pattern detection (bonus)
        patterns = []
        pattern_score = 0
        pattern_details = {}
        
        # Double Bottom
        db_pass, db_score, db_details = detect_double_bottom(close_prices, high_prices, low_prices)
        if db_pass:
            patterns.append(db_details['pattern_type'])
            pattern_score += db_score
            pattern_details['double_bottom'] = db_details
        
        # Bullish Engulfing
        be_pass, be_score, be_details = detect_bullish_engulfing(open_prices, close_prices)
        if be_pass:
            patterns.append(be_details['pattern_type'])
            pattern_score += be_score
            pattern_details['engulfing'] = be_details
        
        # Morning Star
        ms_pass, ms_score, ms_details = detect_morning_star(open_prices, close_prices, high_prices, low_prices)
        if ms_pass:
            patterns.append(ms_details['pattern_type'])
            pattern_score += ms_score
            pattern_details['morning_star'] = ms_details
        
        # Determine grade
        if pattern_score >= 25:
            grade = "🚨 STRONG BUY + PATTERN"
        elif pattern_score >= 15:
            grade = "📈 BUY + PATTERN"
        else:
            grade = "📈 STRONG FILTER PASS"
        
        # Trade Plan
        buy_price = price
        stop_loss = price - (atr * 1.5)
        target1 = price + (atr * 2.0)
        target2 = price + (atr * 3.5)
        target3 = price + (atr * 5.0)
        
        return {
            'symbol': symbol,
            'grade': grade,
            'pattern_score': pattern_score,
            'patterns': patterns,
            'pattern_details': pattern_details,
            'price': price,
            'day_change': filter_result['day_change'],
            'volume_ratio': filter_result['volume_ratio'],
            'market_cap': filter_result['market_cap'],
            'rsi': rsi,
            'macd_bullish': macd_bullish,
            'adx': adx,
            'atr': atr,
            'buy_price': round(buy_price, 2),
            'stop_loss': round(stop_loss, 2),
            'target1': round(target1, 2),
            'target2': round(target2, 2),
            'target3': round(target3, 2),
            'risk_reward': round((target1 - buy_price) / (buy_price - stop_loss), 2) if buy_price > stop_loss else 0
        }
        
    except Exception as e:
        return None

# ============================================
# FORMAT ALERT
# ============================================
def format_alert(result):
    details = (
        f"{result['grade']}\n"
        f"📊 *{result['symbol']}*\n\n"
        f"💰 Price: ₹{result['price']:.2f}\n"
        f"📈 Day Change: {result['day_change']:.2f}%\n"
        f"📊 Volume: {result['volume_ratio']:.2f}x\n"
        f"📊 RSI: {result['rsi']:.1f}\n"
        f"📊 MACD: {'✅ Bullish' if result['macd_bullish'] else '❌'}\n"
        f"📊 ADX: {result['adx']:.1f}\n"
        f"💼 Market Cap: ₹{result['market_cap']:.2f} Cr\n"
        f"📊 Pattern Score: {result['pattern_score']}\n"
    )
    
    if result['patterns']:
        details += f"🔔 *Patterns: {', '.join(result['patterns'])}*\n"
    
    details += (
        f"\n📈 *Trade Plan*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Buy: ₹{result['buy_price']:.2f}\n"
        f"🛑 Stop Loss: ₹{result['stop_loss']:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 T1: ₹{result['target1']:.2f} (R:R {result['risk_reward']:.2f})\n"
        f"🎯 T2: ₹{result['target2']:.2f}\n"
        f"🎯 T3: ₹{result['target3']:.2f}\n"
    )
    
    return details

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting scan...")
    print("-" * 70)
    
    stocks = get_all_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    
    cache = load_cache()
    
    if not cache:
        cache = build_cache(stocks)
        save_cache(cache)
    else:
        last_update = cache.get('_last_update', '')
        if last_update:
            try:
                last_date = datetime.strptime(last_update, '%Y-%m-%d')
                if (datetime.now() - last_date).days >= 1:
                    print("📅 Cache is old, rebuilding...")
                    cache = build_cache(stocks)
                    save_cache(cache)
            except:
                pass
    
    cache['_last_update'] = datetime.now().strftime('%Y-%m-%d')
    save_cache(cache)
    
    print("-" * 70)
    print("⚡ Scoring stocks...")
    print("-" * 70)
    
    results = []
    start_time = time.time()
    
    for i, symbol in enumerate(stocks):
        cached = cache.get(symbol)
        if cached is None:
            continue
        
        result = score_stock(symbol, cached)
        if result:
            results.append(result)
        
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        
        time.sleep(0.03)
    
    # Sort by pattern score
    results.sort(key=lambda x: x['pattern_score'], reverse=True)
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {len(results)} stocks passing ALL 10 filters")
    print(f"⏱️ Time taken: {time.time() - start_time:.1f} seconds")
    
    if results:
        top_stocks = results[:15]
        
        summary = f"📊 *TOP {len(top_stocks)} STOCKS (ALL 10 FILTERS)*\n\n"
        for r in top_stocks:
            summary += f"{r['grade']}\n"
            summary += f"📊 {r['symbol']} - Pattern Score: {r['pattern_score']}\n"
            summary += f"   Patterns: {', '.join(r['patterns']) if r['patterns'] else 'None'}\n"
            summary += f"   R:R: {r['risk_reward']:.2f}\n"
            summary += "\n"
        
        try:
            bot.send_message(YOUR_CHAT_ID, summary, parse_mode='Markdown')
        except:
            pass
        
        # Detailed alerts for top performers
        for r in top_stocks[:10]:
            if r['pattern_score'] >= 15 or len(r['patterns']) >= 2:
                details = format_alert(r)
                try:
                    bot.send_message(YOUR_CHAT_ID, details, parse_mode='Markdown')
                except:
                    pass
    
    else:
        try:
            bot.send_message(YOUR_CHAT_ID, "📊 *No stocks passed ALL 10 filters today.*", parse_mode='Markdown')
        except:
            pass

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, 
        "🎯 *NSE Screener - Final Version*\n\n"
        "📊 *10 Filters (MUST pass all)*\n"
        "🔔 *Patterns as bonus advantage*\n"
        "📈 *Trade Plan with Targets*\n\n"
        "• Market Cap ≥ 1000 Cr\n"
        "• Price ≥ 100\n"
        "• Day Change 0-15%\n"
        "• Volume ≥ 200,000\n"
        "• Avg Vol > 500,000\n"
        "• Within 10% of 52W High\n"
        "• 50 DEMA > 200 DEMA\n"
        "• 10 DEMA > 50 DEMA\n"
        "• Volume Ratio ≥ 1.5x",
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
        f"🔄 Scans every 10 minutes",
        parse_mode='Markdown'
    )

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🎯 NSE Screener is running!", parse_mode='Markdown')
    except:
        pass
    
    run_scanner()
    print("\n✅ Done!")
