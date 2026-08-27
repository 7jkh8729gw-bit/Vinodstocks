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
CACHE_FILE = "pattern_score_cache.pkl"

print("=" * 70)
print("🎯 FINAL PATTERN SCORING SCREENER")
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

# ============================================
# PATTERN DETECTION
# ============================================
def detect_double_bottom_market(close_prices, high_prices, low_prices, lookback=120):
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
        'diff_pct': diff_pct * 100,
        'peak_vs_avg': peak_vs_avg * 100,
        'volatility_pct': volatility_pct
    }

def detect_inverse_head_shoulders(close_prices, lookback=90):
    if len(close_prices) < lookback:
        return False, 0
    recent = close_prices[-lookback:]
    lows = []
    for i in range(5, len(recent) - 5):
        if recent[i] == min(recent[i-5:i+6]):
            lows.append((i, recent[i]))
    if len(lows) < 3:
        return False, 0
    left_shoulder = lows[-3]
    head = lows[-2]
    right_shoulder = lows[-1]
    if head[1] >= left_shoulder[1] or head[1] >= right_shoulder[1]:
        return False, 0
    shoulder_diff = abs((right_shoulder[1] - left_shoulder[1]) / left_shoulder[1])
    if shoulder_diff > 0.05:
        return False, 0
    neckline_left = max(recent[left_shoulder[0]:head[0]+1])
    neckline_right = max(recent[head[0]:right_shoulder[0]+1])
    neckline = min(neckline_left, neckline_right)
    if right_shoulder[1] >= neckline:
        return False, 0
    if recent[-1] < neckline:
        return False, 0
    return True, 25

def detect_triple_bottom(close_prices, lookback=90):
    if len(close_prices) < lookback:
        return False, 0
    recent = close_prices[-lookback:]
    lows = []
    for i in range(5, len(recent) - 5):
        if recent[i] == min(recent[i-5:i+6]):
            lows.append((i, recent[i]))
    if len(lows) < 3:
        return False, 0
    bottom1 = lows[-3]
    bottom2 = lows[-2]
    bottom3 = lows[-1]
    avg_bottom = (bottom1[1] + bottom2[1] + bottom3[1]) / 3
    diff1 = abs((bottom1[1] - avg_bottom) / avg_bottom)
    diff2 = abs((bottom2[1] - avg_bottom) / avg_bottom)
    diff3 = abs((bottom3[1] - avg_bottom) / avg_bottom)
    if diff1 > 0.03 or diff2 > 0.03 or diff3 > 0.03:
        return False, 0
    if len(close_prices) > lookback + 30:
        high_before = max(close_prices[-lookback-30:-lookback])
        if high_before > bottom1[1] * 1.15:
            return True, 20
    return False, 0

def detect_bullish_engulfing(open_prices, close_prices):
    if len(open_prices) < 2 or len(close_prices) < 2:
        return False, 0
    last_open = open_prices[-1]
    prev_open = open_prices[-2]
    last_close = close_prices[-1]
    prev_close = close_prices[-2]
    if prev_close >= prev_open:
        return False, 0
    if last_close <= last_open:
        return False, 0
    if last_open > prev_close and last_close < prev_open:
        return False, 0
    if last_open <= prev_close and last_close >= prev_open:
        return True, 10
    return False, 0

def detect_morning_star(open_prices, close_prices, high_prices, low_prices):
    if len(open_prices) < 3:
        return False, 0
    if close_prices[-3] >= open_prices[-3]:
        return False, 0
    body2 = abs(close_prices[-2] - open_prices[-2])
    range2 = high_prices[-2] - low_prices[-2]
    if range2 == 0 or body2 / range2 > 0.3:
        return False, 0
    if open_prices[-2] >= close_prices[-3]:
        return False, 0
    if close_prices[-1] <= open_prices[-1]:
        return False, 0
    mid_point = (open_prices[-3] + close_prices[-3]) / 2
    if close_prices[-1] < mid_point:
        return False, 0
    return True, 10

def detect_hammer(open_prices, close_prices, high_prices, low_prices):
    if len(open_prices) < 1:
        return False, 0
    last_open = open_prices[-1]
    last_close = close_prices[-1]
    last_high = high_prices[-1]
    last_low = low_prices[-1]
    body = abs(last_close - last_open)
    lower_shadow = min(last_open, last_close) - last_low
    upper_shadow = last_high - max(last_open, last_close)
    if body == 0:
        return False, 0
    if lower_shadow < 2 * body:
        return False, 0
    if upper_shadow > body * 0.1:
        return False, 0
    return True, 5

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
                d50 = chartink_dema(hist['Close'], 50)
                d200 = chartink_dema(hist['Close'], 200)
                
                if d50 is not None and d200 is not None:
                    cache[symbol] = {
                        'dema_50': d50.iloc[-1],
                        'dema_200': d200.iloc[-1],
                        'avg_volume': hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0,
                        'close_prices': hist['Close'].tolist()[-200:],
                        'open_prices': hist['Open'].tolist()[-200:],
                        'high_prices': hist['High'].tolist()[-200:],
                        'low_prices': hist['Low'].tolist()[-200:],
                        'volumes': hist['Volume'].tolist()[-200:],
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
        
        price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        prev_close = info.get('regularMarketPreviousClose', 0)
        volume = info.get('regularMarketVolume', 0)
        market_cap = cached.get('market_cap', 0)
        
        close_prices = cached.get('close_prices', [])
        open_prices = cached.get('open_prices', [])
        high_prices = cached.get('high_prices', [])
        low_prices = cached.get('low_prices', [])
        avg_volume = cached.get('avg_volume', 0)
        dema_50 = cached.get('dema_50', 0)
        dema_200 = cached.get('dema_200', 0)
        
        if len(close_prices) < 100:
            return None
        
        rsi = calculate_rsi(close_prices)
        macd_bullish = calculate_macd(close_prices)
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        
        if prev_close > 0 and price > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0
        
        score = 0
        signals = []
        
        # Double Bottom
        db_pass, db_score, db_details = detect_double_bottom_market(
            close_prices, high_prices, low_prices
        )
        if db_pass:
            score += db_score
            signals.append(f"Double Bottom ({db_details['days_between']}d)")
        
        # Inverse Head & Shoulders
        ihs_pass, ihs_score = detect_inverse_head_shoulders(close_prices)
        if ihs_pass:
            score += ihs_score
            signals.append("Inv H&S")
        
        # Triple Bottom
        tb_pass, tb_score = detect_triple_bottom(close_prices)
        if tb_pass:
            score += tb_score
            signals.append("Triple Bottom")
        
        # Bullish Engulfing
        be_pass, be_score = detect_bullish_engulfing(open_prices, close_prices)
        if be_pass:
            score += be_score
            signals.append("Bullish Engulfing")
        
        # Morning Star
        ms_pass, ms_score = detect_morning_star(open_prices, close_prices, high_prices, low_prices)
        if ms_pass:
            score += ms_score
            signals.append("Morning Star")
        
        # Hammer
        hm_pass, hm_score = detect_hammer(open_prices, close_prices, high_prices, low_prices)
        if hm_pass:
            score += hm_score
            signals.append("Hammer")
        
        # RSI
        if rsi is not None and 30 <= rsi <= 50:
            score += 5
            signals.append(f"RSI: {rsi:.1f}")
        
        # MACD
        if macd_bullish:
            score += 5
            signals.append("MACD Bullish")
        
        # Volume
        if volume_ratio >= 2.0:
            score += 5
            signals.append(f"Vol: {volume_ratio:.1f}x")
        
        # Golden Cross
        if dema_50 > dema_200:
            score += 5
            signals.append("Golden Cross")
        
        # Price
        if price >= 100:
            score += 2
        
        # Market Cap
        if market_cap >= 1000:
            score += 2
        
        # Day Change
        if day_change > 0:
            score += 2
            signals.append("Green Day")
        
        score = min(score, 100)
        
        if score >= 70:
            strength = "🚨 STRONG BUY"
        elif score >= 50:
            strength = "📈 MODERATE BUY"
        elif score >= 30:
            strength = "📊 WATCHLIST"
        else:
            strength = "🔍 MONITOR"
        
        return {
            'symbol': symbol,
            'score': score,
            'strength': strength,
            'signals': signals,
            'price': price,
            'day_change': day_change,
            'volume_ratio': volume_ratio,
            'rsi': rsi,
            'macd_bullish': macd_bullish,
            'market_cap': market_cap,
            'db_pass': db_pass,
            'db_details': db_details if db_pass else {}
        }
        
    except Exception as e:
        return None

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting Pattern Scoring Scan...")
    print("-" * 70)
    
    stocks = get_all_nse_stocks()
    print(f"📊 Checking {len(stocks)} stocks...")
    
    # Load cache
    cache = load_cache()
    
    # Build cache if empty or outdated
    if not cache:
        cache = build_cache(stocks)
        save_cache(cache)
    else:
        # Check if cache needs update (daily)
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
    
    # Add last update timestamp
    cache['_last_update'] = datetime.now().strftime('%Y-%m-%d')
    save_cache(cache)
    
    print("-" * 70)
    print("⚡ Scoring stocks using cached data...")
    print("-" * 70)
    
    results = []
    start_time = time.time()
    
    for i, symbol in enumerate(stocks):
        cached = cache.get(symbol)
        if cached is None:
            continue
        
        result = score_stock(symbol, cached)
        if result and result['score'] >= 30:
            results.append(result)
        
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        
        time.sleep(0.03)
    
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print("-" * 70)
    print(f"✅ Scan complete! Found {len(results)} stocks with score ≥ 30")
    print(f"⏱️ Time taken: {time.time() - start_time:.1f} seconds")
    
    if results:
        top_stocks = results[:10]
        
        # Summary message
        summary = f"📊 *TOP {len(top_stocks)} SIGNALS*\n\n"
        for r in top_stocks:
            summary += f"{r['strength']}\n"
            summary += f"📊 {r['symbol']} - Score: {r['score']}/100\n"
            if r.get('signals'):
                summary += f"   Signals: {', '.join(r['signals'][:4])}\n"
            if r.get('db_details'):
                db = r['db_details']
                summary += f"   DB: {db['days_between']}d, Drop: {db['drop_pct']:.1f}%\n"
            summary += "\n"
        
        try:
            bot.send_message(YOUR_CHAT_ID, summary, parse_mode='Markdown')
        except:
            pass
        
        # Detailed alerts for high score stocks
        for r in top_stocks:
            if r['score'] >= 70:
                details = (
                    f"{r['strength']}\n"
                    f"📊 *{r['symbol']}*\n\n"
                    f"💰 Price: ₹{r['price']:.2f}\n"
                    f"📈 Day Change: {r['day_change']:.2f}%\n"
                    f"📊 Volume: {r['volume_ratio']:.2f}x\n"
                    f"📊 RSI: {r['rsi']:.1f}\n"
                    f"📊 MACD: {'✅' if r['macd_bullish'] else '❌'}\n"
                    f"💼 Market Cap: ₹{r['market_cap']:.2f} Cr\n"
                    f"📊 Score: {r['score']}/100\n\n"
                    f"🎯 Signals: {', '.join(r['signals'])}"
                )
                
                if r.get('db_details'):
                    db = r['db_details']
                    details += (
                        f"\n\n🔔 *Double Bottom Details*\n"
                        f"  Drop: {db['drop_pct']:.1f}%\n"
                        f"  Days: {db['days_between']} days\n"
                        f"  Low Diff: {db['diff_pct']:.2f}%\n"
                        f"  Peak vs Avg: {db['peak_vs_avg']:.2f}%"
                    )
                
                try:
                    bot.send_message(YOUR_CHAT_ID, details, parse_mode='Markdown')
                except:
                    pass
    
    if not results:
        try:
            bot.send_message(YOUR_CHAT_ID, "📊 *No high-confidence signals found* today.", parse_mode='Markdown')
        except:
            pass

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, 
        "🎯 *Pattern Scoring Screener*\n\n"
        "📊 *Scores stocks on:*\n"
        "• Double Bottom (flexible 10-90 days)\n"
        "• Inverse Head & Shoulders (25)\n"
        "• Triple Bottom (20)\n"
        "• Bullish Engulfing (10)\n"
        "• Morning Star (10)\n"
        "• Hammer (5)\n"
        "• RSI, MACD, Volume, etc.\n\n"
        "📈 *Score Levels:*\n"
        "• 70+ = 🚨 STRONG BUY\n"
        "• 50-69 = 📈 MODERATE BUY\n"
        "• 30-49 = 📊 WATCHLIST",
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
        f"📊 Market Guidelines applied",
        parse_mode='Markdown'
    )

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    try:
        bot.send_message(YOUR_CHAT_ID, "🎯 Pattern Scoring Screener is running!", parse_mode='Markdown')
    except:
        pass
    
    run_scanner()
    print("\n✅ Done!")
