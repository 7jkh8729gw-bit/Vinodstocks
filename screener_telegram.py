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
print("🎯 NSE SCREENER - TECHNICAL TRADE PLAN")
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
# CHARTINK-STYLE DEMA (Verified)
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

# ============================================
# TECHNICAL INDICATORS
# ============================================
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
    return np.mean(dx)

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
# PATTERN DETECTION (Bonus)
# ============================================
def detect_double_bottom(close_prices, lookback=120):
    if len(close_prices) < lookback:
        return False, {}
    recent = close_prices[-lookback:]
    lows = []
    for i in range(5, len(recent) - 5):
        if recent[i] == min(recent[i-5:i+6]):
            lows.append((i, recent[i]))
    if len(lows) < 2:
        return False, {}
    low1 = lows[-2]
    low2 = lows[-1]
    if low2[1] <= low1[1]:
        return False, {}
    diff = abs((low2[1] - low1[1]) / low1[1])
    if diff > 0.05:
        return False, {}
    days = low2[0] - low1[0]
    if days < 10 or days > 90:
        return False, {}
    avg_low = (low1[1] + low2[1]) / 2
    peak = max(recent[low1[0]:low2[0]+1])
    if (peak - avg_low) / avg_low < 0.03:
        return False, {}
    if recent[-1] < peak:
        return False, {}
    return True, {'low1': low1[1], 'low2': low2[1], 'avg_low': avg_low, 'peak': peak}

def detect_bullish_engulfing(open_prices, close_prices):
    if len(open_prices) < 2:
        return False, {}
    last_open = open_prices[-1]
    prev_open = open_prices[-2]
    last_close = close_prices[-1]
    prev_close = close_prices[-2]
    if prev_close >= prev_open:
        return False, {}
    if last_close <= last_open:
        return False, {}
    if last_open > prev_close and last_close < prev_open:
        return False, {}
    if last_open <= prev_close and last_close >= prev_open:
        return True, {}
    return False, {}

def detect_morning_star(open_prices, close_prices, high_prices, low_prices):
    if len(open_prices) < 3:
        return False, {}
    if close_prices[-3] >= open_prices[-3]:
        return False, {}
    body2 = abs(close_prices[-2] - open_prices[-2])
    range2 = high_prices[-2] - low_prices[-2]
    if range2 == 0 or body2 / range2 > 0.3:
        return False, {}
    if open_prices[-2] >= close_prices[-3]:
        return False, {}
    if close_prices[-1] <= open_prices[-1]:
        return False, {}
    mid = (open_prices[-3] + close_prices[-3]) / 2
    if close_prices[-1] < mid:
        return False, {}
    return True, {}

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
                    avg_vol = hist['Volume'].tail(21).mean() if len(hist) >= 21 else 0
                    cache[symbol] = {
                        'dema_10': d10.iloc[-1],
                        'dema_50': d50.iloc[-1],
                        'dema_200': d200.iloc[-1],
                        'avg_volume': avg_vol,
                        'market_cap': info.get('marketCap', 0) / 10000000,
                        'close_prices': hist['Close'].tolist()[-200:],
                        'open_prices': hist['Open'].tolist()[-200:],
                        'high_prices': hist['High'].tolist()[-200:],
                        'low_prices': hist['Low'].tolist()[-200:],
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
# CHECK STOCK (CORE 10 FILTERS + BONUS + TECHNICAL TRADE PLAN)
# ============================================
def check_stock(symbol, cached):
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        if not info:
            return None

        price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        prev_close = info.get('regularMarketPreviousClose', 0)
        volume = info.get('regularMarketVolume', 0)
        high_52w = info.get('fiftyTwoWeekHigh', 0)

        market_cap = cached.get('market_cap', 0)
        avg_volume = cached.get('avg_volume', 0)
        dema_10 = cached.get('dema_10', 0)
        dema_50 = cached.get('dema_50', 0)
        dema_200 = cached.get('dema_200', 0)

        # Core metrics
        day_change = ((price - prev_close) / prev_close) * 100 if prev_close > 0 and price > 0 else 0
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        pct_from_high = ((high_52w - price) / high_52w) * 100 if high_52w > 0 and price > 0 else 100

        # CORE 10 FILTERS (MUST PASS ALL)
        cond1 = market_cap >= 1000
        cond2 = price >= 100
        cond3 = day_change >= 0
        cond4 = day_change < 15
        cond5 = volume >= 200000
        cond6 = avg_volume > 500000
        cond7 = pct_from_high <= 10
        cond8 = dema_50 > dema_200
        cond9 = dema_10 > dema_50
        cond10 = volume_ratio >= 1.5

        all_pass = cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10

        if not all_pass:
            return None

        # ----- BONUS INDICATORS (Information only) -----
        close_prices = cached.get('close_prices', [])
        high_prices = cached.get('high_prices', [])
        low_prices = cached.get('low_prices', [])
        open_prices = cached.get('open_prices', [])

        if len(close_prices) < 50:
            rsi = None
            macd = False
            adx = 0
            atr = 0
        else:
            rsi = calculate_rsi(close_prices)
            macd = calculate_macd(close_prices)
            adx = calculate_adx(high_prices, low_prices, close_prices)
            atr = calculate_atr(high_prices, low_prices, close_prices)

        # ----- PATTERN DETECTION (Bonus) -----
        patterns = []
        pattern_details = {}
        db, db_det = detect_double_bottom(close_prices)
        if db:
            patterns.append("Double Bottom")
            pattern_details['db'] = db_det
        engulf, _ = detect_bullish_engulfing(open_prices, close_prices)
        if engulf:
            patterns.append("Bullish Engulfing")
        ms, _ = detect_morning_star(open_prices, close_prices, high_prices, low_prices)
        if ms:
            patterns.append("Morning Star")

        # ----- TECHNICAL TRADE PLAN -----
        # Entry: Current price (or breakout level)
        buy_price = price

        # Stop Loss: Based on ATR (1.5x ATR below entry) or recent swing low
        if atr > 0:
            stop_loss = buy_price - (1.5 * atr)
        else:
            stop_loss = buy_price * 0.95  # fallback 5%

        # If Double Bottom pattern exists, use its peak as breakout and low as SL reference
        if 'db' in pattern_details:
            db_info = pattern_details['db']
            # Use peak as a reference for target
            peak = db_info.get('peak', buy_price)
            avg_low = db_info.get('avg_low', buy_price)
            measured_move = peak - avg_low
            # Targets based on measured move
            target1 = peak + (measured_move * 0.5)
            target2 = peak + measured_move
            target3 = peak + (measured_move * 1.5)
            # Override buy price to breakout above peak
            buy_price = max(price, peak * 1.01)
            # Adjust stop loss to below the lower low
            lowest = min(db_info.get('low1', buy_price), db_info.get('low2', buy_price))
            stop_loss = lowest * 0.98
        else:
            # For other patterns or no pattern, use ATR multiples
            if atr > 0:
                target1 = buy_price + (2.0 * atr)
                target2 = buy_price + (3.5 * atr)
                target3 = buy_price + (5.0 * atr)
            else:
                target1 = buy_price * 1.05
                target2 = buy_price * 1.10
                target3 = buy_price * 1.15

        # Ensure stop loss is below buy price
        if stop_loss >= buy_price:
            stop_loss = buy_price * 0.95

        # Ensure targets are above buy price
        target1 = max(target1, buy_price * 1.02)
        target2 = max(target2, target1 * 1.02)
        target3 = max(target3, target2 * 1.02)

        risk = buy_price - stop_loss
        reward1 = target1 - buy_price
        reward2 = target2 - buy_price
        rr1 = round(reward1 / risk, 2) if risk > 0 else 0
        rr2 = round(reward2 / risk, 2) if risk > 0 else 0

        # ----- GRADE -----
        if patterns:
            grade = "🚨 STRONG BUY + PATTERN"
        else:
            grade = "📈 STRONG FILTER PASS"

        return {
            'symbol': symbol,
            'grade': grade,
            'price': price,
            'day_change': day_change,
            'volume_ratio': volume_ratio,
            'market_cap': market_cap,
            'pct_from_high': pct_from_high,
            'rsi': rsi,
            'macd': macd,
            'adx': adx,
            'atr': atr,
            'patterns': patterns,
            'buy_price': round(buy_price, 2),
            'stop_loss': round(stop_loss, 2),
            'target1': round(target1, 2),
            'target2': round(target2, 2),
            'target3': round(target3, 2),
            'rr1': rr1,
            'rr2': rr2,
            'risk_pct': round((risk / buy_price) * 100, 1),
            'reward1_pct': round((reward1 / buy_price) * 100, 1),
            'reward2_pct': round((reward2 / buy_price) * 100, 1),
        }

    except Exception as e:
        return None

# ============================================
# FORMAT ALERT
# ============================================
def format_alert(result):
    lines = []
    lines.append(f"{result['grade']}")
    lines.append(f"📊 *{result['symbol']}*")
    lines.append("")
    lines.append(f"💰 Current Price: ₹{result['price']:.2f}")
    lines.append(f"📈 Day Change: {result['day_change']:.2f}%")
    lines.append(f"📊 Volume Ratio: {result['volume_ratio']:.2f}x")
    if result['rsi'] is not None:
        lines.append(f"📊 RSI: {result['rsi']:.1f}")
    lines.append(f"📊 MACD: {'✅ Bullish' if result['macd'] else '❌'}")
    if result['adx'] > 0:
        lines.append(f"📊 ADX: {result['adx']:.1f} {'(Trending)' if result['adx'] > 25 else '(Weak)'}")
    lines.append(f"📊 From 52W High: {result['pct_from_high']:.1f}%")
    if result['patterns']:
        lines.append(f"🔔 *Patterns: {', '.join(result['patterns'])}*")
    lines.append("")
    lines.append("📈 *Technical Trade Plan*")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💰 Buy: ₹{result['buy_price']:.2f}")
    lines.append(f"🛑 Stop Loss: ₹{result['stop_loss']:.2f} (Risk: {result['risk_pct']:.1f}%)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🎯 Target 1: ₹{result['target1']:.2f} (+{result['reward1_pct']:.1f}%, R:R {result['rr1']:.2f})")
    lines.append(f"🎯 Target 2: ₹{result['target2']:.2f} (+{result['reward2_pct']:.1f}%, R:R {result['rr2']:.2f})")
    lines.append(f"🎯 Target 3: ₹{result['target3']:.2f}")
    return "\n".join(lines)

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
        result = check_stock(symbol, cached)
        if result:
            results.append(result)
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"📊 Progress: {i+1}/{len(stocks)} ({elapsed:.1f}s)")
        time.sleep(0.03)

    print("-" * 70)
    print(f"✅ Scan complete! Found {len(results)} stocks passing ALL 10 filters")
    print(f"⏱️ Time taken: {time.time() - start_time:.1f} seconds")

    if results:
        # Sort by grade priority
        grade_order = {'🚨 STRONG BUY + PATTERN': 2, '📈 STRONG FILTER PASS': 1}
        results.sort(key=lambda x: (grade_order.get(x['grade'], 0), -x['price']))

        # Send summary to Telegram
        summary = "📊 *Stocks Passing ALL 10 Filters*\n\n"
        for r in results[:10]:
            summary += f"{r['grade']}\n"
            summary += f"📊 {r['symbol']} - ₹{r['price']:.2f} ({r['day_change']:.2f}%)\n"
            summary += f"   Vol: {r['volume_ratio']:.2f}x | 52W: {r['pct_from_high']:.1f}%\n"
            if r['patterns']:
                summary += f"   Patterns: {', '.join(r['patterns'])}\n"
            summary += "\n"
        try:
            bot.send_message(YOUR_CHAT_ID, summary, parse_mode='Markdown')
        except:
            pass

        # Send detailed alerts for each
        for r in results[:10]:
            try:
                bot.send_message(YOUR_CHAT_ID, format_alert(r), parse_mode='Markdown')
                time.sleep(0.5)
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
        "🎯 *NSE Screener - Technical Trade Plan*\n\n"
        "📊 10 Filters (MUST pass all)\n"
        "• Market Cap ≥ 1000 Cr\n"
        "• Price ≥ 100\n"
        "• Day Change 0-15%\n"
        "• Volume ≥ 200,000\n"
        "• Avg Vol > 500,000\n"
        "• Within 10% of 52W High\n"
        "• 50 DEMA > 200 DEMA\n"
        "• 10 DEMA > 50 DEMA\n"
        "• Volume Ratio ≥ 1.5x\n\n"
        "🔔 Patterns: Double Bottom, Engulfing, Morning Star (bonus)\n"
        "📈 Technical Trade Plan based on ATR & patterns",
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
