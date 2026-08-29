import os
import yfinance as yf
import pandas as pd
import numpy as np
import time
import pickle
import requests
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
WATCHLIST_FILE = "morning_watchlist.pkl"

print("=" * 70)
print("🌅 MORNING SCREENER - NSE API + FALLBACK")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
except Exception as e:
    print(f"❌ Bot connection failed: {e}")
    exit(1)

# ============================================
# NSE API HELPERS
# ============================================
def get_nse_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    session.get('https://www.nseindia.com', timeout=10)
    time.sleep(1)
    return session

def fetch_nse_live(symbol):
    try:
        session = get_nse_session()
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            price_info = data.get('priceInfo', {})
            return {
                'price': price_info.get('lastPrice', 0),
                'prev_close': price_info.get('previousClose', 0),
                'volume': data.get('totalTradedVolume', 0),
                'high_52w': price_info.get('weekHigh52', 0),
                'market_cap': data.get('marketCap', 0) / 10000000,
            }
    except:
        return None

def fetch_nse_historical(symbol, days=365):
    end = datetime.now()
    start = end - timedelta(days=days)
    from_date = start.strftime('%d-%m-%Y')
    to_date = end.strftime('%d-%m-%Y')
    try:
        session = get_nse_session()
        url = f"https://www.nseindia.com/api/historical/cm/equity?symbol={symbol}&series=EQ&from={from_date}&to={to_date}"
        resp = session.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data:
                df = pd.DataFrame(data['data'])
                df['DATE'] = pd.to_datetime(df['DATE'], format='%d-%m-%Y')
                df = df.sort_values('DATE')
                df['Close'] = df['CH_CLOSING'].astype(float)
                df['Volume'] = df['CH_VOLUME'].astype(float)
                return df[['DATE', 'Close', 'Volume']]
    except:
        return None

def get_data(symbol):
    # Try NSE live
    live = fetch_nse_live(symbol)
    if live:
        hist = fetch_nse_historical(symbol)
        if hist is not None and len(hist) >= 200:
            return {'live': live, 'hist': hist}
    # Fallback to yfinance
    for suffix in ['.NS', '.BO']:
        try:
            ticker = yf.Ticker(f"{symbol}{suffix}")
            info = ticker.info
            hist = ticker.history(period="1y")
            if len(hist) >= 200 and info:
                price = info.get('regularMarketPrice', info.get('currentPrice', 0))
                prev_close = info.get('regularMarketPreviousClose', 0)
                volume = info.get('regularMarketVolume', 0)
                high_52w = info.get('fiftyTwoWeekHigh', 0)
                market_cap = info.get('marketCap', 0) / 10000000
                live = {'price': price, 'prev_close': prev_close, 'volume': volume,
                        'high_52w': high_52w, 'market_cap': market_cap}
                return {'live': live, 'hist': hist}
        except:
            continue
    return None

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
# CHARTINK-STYLE DEMA
# ============================================
def chartink_dema(data, period):
    if len(data) < period:
        return None
    ema = data.ewm(span=period, adjust=False).mean()
    ema2 = ema.ewm(span=period, adjust=False).mean()
    return 2 * ema - ema2

# ============================================
# BUILD CACHE
# ============================================
def build_cache(stocks):
    print("🏗️ Building initial cache (this may take time)...")
    cache = {}
    total = len(stocks)
    built = 0
    for i, symbol in enumerate(stocks):
        try:
            data = get_data(symbol)
            if data is None:
                continue
            hist = data['hist']
            if len(hist) < 200:
                continue
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
                    'market_cap': data['live']['market_cap'],
                    'last_update': datetime.now().strftime('%Y-%m-%d')
                }
                built += 1
        except:
            pass
        if (i + 1) % 50 == 0:
            print(f"📊 Cache progress: {i+1}/{total} (built: {built})")
        time.sleep(0.05)
    print(f"✅ Cache built for {built} stocks")
    return cache

# ============================================
# SAVE WATCHLIST FOR VOLUME MONITOR
# ============================================
def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, 'wb') as f:
            pickle.dump(watchlist, f)
        print(f"✅ Watchlist saved to {WATCHLIST_FILE}")
    except Exception as e:
        print(f"⚠️ Error saving watchlist: {e}")

# ============================================
# CHECK STOCK
# ============================================
def check_stock(symbol, cached):
    try:
        data = get_data(symbol)
        if data is None:
            return None
        live = data['live']
        price = live['price']
        prev_close = live['prev_close']
        volume = live['volume']
        high_52w = live['high_52w']
        market_cap = live['market_cap']
        avg_volume = cached.get('avg_volume', 0)
        dema_10 = cached.get('dema_10', 0)
        dema_50 = cached.get('dema_50', 0)
        dema_200 = cached.get('dema_200', 0)

        if prev_close > 0 and price > 0:
            day_change = ((price - prev_close) / prev_close) * 100
        else:
            day_change = 0

        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        pct_from_high = ((high_52w - price) / high_52w) * 100 if high_52w > 0 else 100

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

        if all_pass:
            return {
                'symbol': symbol,
                'price': price,
                'day_change': day_change,
                'volume_ratio': volume_ratio,
                'market_cap': market_cap,
                'pct_from_high': pct_from_high,
                'avg_volume': avg_volume,
                'volume': volume
            }
        return None
    except:
        return None

# ============================================
# MAIN SCANNER
# ============================================
def run_scanner():
    print("\n🚀 Starting scan...")
    print("-" * 70)

    # Send start message
    bot.send_message(YOUR_CHAT_ID, "🌅 *Morning Screener is running!*", parse_mode='Markdown')

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
        time.sleep(0.05)

    print("-" * 70)
    print(f"✅ Scan complete! Found {len(results)} stocks passing ALL 10 filters")
    print(f"⏱️ Time taken: {time.time() - start_time:.1f} seconds")

    # Save watchlist for volume monitor
    if results:
        save_watchlist(results)

    if results:
        summary = "📊 *Morning Screener Results ({})*\n\n".format(len(results))
        for r in results[:15]:
            summary += f"✅ {r['symbol']} - ₹{r['price']:.2f} ({r['day_change']:.2f}%)\n"
        bot.send_message(YOUR_CHAT_ID, summary, parse_mode='Markdown')

        for r in results[:10]:
            details = (
                f"🚨 *{r['symbol']}*\n"
                f"💰 Price: ₹{r['price']:.2f}\n"
                f"📈 Day Change: {r['day_change']:.2f}%\n"
                f"📊 Volume: {r['volume_ratio']:.2f}x\n"
                f"📊 From 52W High: {r['pct_from_high']:.1f}%\n"
                f"💼 Market Cap: ₹{r['market_cap']:.2f} Cr"
            )
            bot.send_message(YOUR_CHAT_ID, details, parse_mode='Markdown')
    else:
        bot.send_message(YOUR_CHAT_ID, "📊 *No stocks found in Morning Screener today.*", parse_mode='Markdown')

if __name__ == "__main__":
    run_scanner()
    print("\n✅ Done!")
