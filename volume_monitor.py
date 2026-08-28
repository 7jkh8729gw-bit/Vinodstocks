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
print("📊 INTRADAY MONITOR - WITH ORDER FLOW SIMULATION")
print("=" * 70)

try:
    bot_info = bot.get_me()
    print(f"✅ Bot connected: @{bot_info.username}")
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
# LOAD CACHE
# ============================================
def load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        return {}
    except:
        return {}

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
# CHECK STOCK (10 FILTERS)
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

        day_change = ((price - prev_close) / prev_close) * 100 if prev_close > 0 and price > 0 else 0
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        pct_from_high = ((high_52w - price) / high_52w) * 100 if high_52w > 0 and price > 0 else 100

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
                'avg_volume': avg_volume,
                'market_cap': market_cap
            }
        return None

    except:
        return None

# ============================================
# ORDER FLOW SIMULATION
# ============================================
def simulate_order_flow(intraday_data):
    if len(intraday_data) < 30:
        return None

    close = intraday_data['Close']
    high = intraday_data['High']
    low = intraday_data['Low']
    volume = intraday_data['Volume']
    open_price = intraday_data['Open']

    # Volume Delta Simulation
    price_change = close.diff()
    up_volume = volume.where(price_change > 0, 0).sum()
    down_volume = volume.where(price_change < 0, 0).sum()

    total_volume = up_volume + down_volume
    if total_volume > 0:
        delta_pct = ((up_volume - down_volume) / total_volume) * 100
    else:
        delta_pct = 0

    recent_up = volume[-5:].where(close.diff()[-5:] > 0, 0).sum()
    recent_down = volume[-5:].where(close.diff()[-5:] < 0, 0).sum()
    recent_total = recent_up + recent_down
    if recent_total > 0:
        recent_delta_pct = ((recent_up - recent_down) / recent_total) * 100
    else:
        recent_delta_pct = 0

    # Absorption Detection
    price_range = (close[-1] - close[-20]) / close[-20] * 100
    avg_vol_20 = volume[-20:].mean()
    latest_vol = volume[-1]

    absorption = False
    if latest_vol > avg_vol_20 * 1.5 and abs(price_range) < 1.0:
        absorption = True

    # Exhaustion Detection
    vol_trend = volume[-5:].mean() / volume[-10:-5].mean() if volume[-10:-5].mean() > 0 else 1
    price_trend = close[-1] > close[-5]

    exhaustion = False
    if price_trend and vol_trend < 0.7:
        exhaustion = True

    # Imbalance Detection
    imbalance = False
    if abs(recent_delta_pct) > 50:
        imbalance = True

    return {
        'delta_pct': round(delta_pct, 1),
        'recent_delta_pct': round(recent_delta_pct, 1),
        'buy_dominance': delta_pct > 20,
        'sell_dominance': delta_pct < -20,
        'absorption': absorption,
        'exhaustion': exhaustion,
        'imbalance': imbalance,
        'volume_surge': latest_vol > avg_vol_20 * 1.5
    }

# ============================================
# INTRADAY INDICATORS WITH ORDER FLOW
# ============================================
def get_intraday_indicators_with_flow(symbol):
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        intraday = ticker.history(period="2d", interval="5m")

        if len(intraday) < 30:
            return None

        # RSI
        delta = intraday['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else None

        # MACD
        ema12 = intraday['Close'].ewm(span=12, adjust=False).mean()
        ema26 = intraday['Close'].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_bullish = macd_line.iloc[-1] > signal_line.iloc[-1] if len(macd_line) > 0 else False

        # ADX (Simplified)
        high = intraday['High']
        low = intraday['Low']
        close = intraday['Close']
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift()), abs(low - close.shift())))
        atr = tr.rolling(14).mean()
        current_atr = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0

        price_range = close.iloc[-1] - close.iloc[-20]
        if current_atr > 0:
            adx = min(100, max(0, abs(price_range) / current_atr * 10))
        else:
            adx = 0

        trending = adx > 20

        # Order Flow
        flow = simulate_order_flow(intraday)

        return {
            'rsi': round(current_rsi, 1) if current_rsi else None,
            'macd_bullish': macd_bullish,
            'adx': round(adx, 1),
            'trending': trending,
            'order_flow': flow
        }

    except Exception as e:
        print(f"⚠️ Error for {symbol}: {e}")
        return None

# ============================================
# GET MORNING SCREENER RESULTS
# ============================================
def get_morning_results():
    print("🌅 Running morning screener...")
    stocks = get_all_nse_stocks()
    cache = load_cache()

    results = []
    for symbol in stocks:
        cached = cache.get(symbol)
        if cached:
            result = check_stock(symbol, cached)
            if result:
                results.append(result)
        time.sleep(0.01)

    print(f"✅ Found {len(results)} stocks passing all 10 filters")
    return results

# ============================================
# MONITOR INTRADAY WITH ORDER FLOW
# ============================================
def monitor_intraday(watchlist, check_interval=60, spike_multiplier=3):
    print(f"\n📊 Monitoring {len(watchlist)} stocks...")
    print(f"⚡ Volume spike threshold: {spike_multiplier}x")
    print(f"📈 RSI 30-70, MACD bullish, ADX > 20")
    print(f"🔍 Order Flow: Delta, Absorption, Exhaustion, Imbalance")
    print(f"⏱️ Check interval: {check_interval} seconds")
    print("=" * 70)

    alerted = {}

    while True:
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"\n🕐 {current_time} - Checking...")

        for stock in watchlist:
            symbol = stock['symbol']
            avg_volume = stock['avg_volume']

            try:
                ticker = yf.Ticker(f"{symbol}.NS")
                info = ticker.info

                current_volume = info.get('regularMarketVolume', 0)
                current_price = info.get('regularMarketPrice', 0)

                if avg_volume > 0 and current_volume > 0:
                    spike_ratio = current_volume / avg_volume

                    if spike_ratio >= spike_multiplier:
                        if symbol not in alerted:
                            data = get_intraday_indicators_with_flow(symbol)

                            if data:
                                rsi = data.get('rsi')
                                macd = data.get('macd_bullish')
                                adx = data.get('adx')
                                trending = data.get('trending')
                                flow = data.get('order_flow')

                                rsi_ok = rsi is not None and 30 <= rsi <= 70
                                macd_ok = macd
                                adx_ok = trending

                                delta_pct = flow.get('recent_delta_pct', 0) if flow else 0
                                buy_dominance = flow.get('buy_dominance', False) if flow else False
                                absorption = flow.get('absorption', False) if flow else False
                                exhaustion = flow.get('exhaustion', False) if flow else False
                                imbalance = flow.get('imbalance', False) if flow else False

                                flow_indicators = []
                                if buy_dominance:
                                    flow_indicators.append("Buy Dominance")
                                if absorption:
                                    flow_indicators.append("Absorption")
                                if exhaustion:
                                    flow_indicators.append("Exhaustion")
                                if imbalance:
                                    flow_indicators.append("Imbalance")

                                flow_status = ", ".join(flow_indicators) if flow_indicators else "Neutral"

                                if rsi_ok and macd_ok and adx_ok:
                                    order_flow_confirmed = buy_dominance or absorption or imbalance

                                    if order_flow_confirmed:
                                        alerted[symbol] = True
                                        print(f"🚨 {symbol} - SPIKE {spike_ratio:.1f}x, RSI {rsi}, MACD ✅, ADX {adx}, Flow: {flow_status}")

                                        msg = (
                                            f"🚨 *STRONG BUY SIGNAL*\n"
                                            f"📊 *{symbol}*\n\n"
                                            f"💰 Price: ₹{current_price:.2f}\n"
                                            f"📈 Day Change: {stock['day_change']:.2f}%\n"
                                            f"📊 Volume Spike: {spike_ratio:.1f}x\n"
                                            f"📊 RSI: {rsi} (30-70 ✅)\n"
                                            f"📊 MACD: {'✅ Bullish' if macd else '❌'}\n"
                                            f"📊 ADX: {adx} (Trending ✅)\n"
                                            f"🔍 *Order Flow: {flow_status}*\n"
                                            f"📊 Delta: {delta_pct:.1f}% {'(Buy)' if buy_dominance else '(Sell)'}\n"
                                        )

                                        if absorption:
                                            msg += "📌 Absorption detected - strong support!\n"
                                        if exhaustion:
                                            msg += "📌 Exhaustion detected - trend losing steam!\n"
                                        if imbalance:
                                            msg += "📌 Imbalance detected - strong directional move!\n"

                                        msg += f"\n✅ Stock passed ALL 10 filters!"
                                        bot.send_message(YOUR_CHAT_ID, msg, parse_mode='Markdown')
                                    else:
                                        print(f"ℹ️ {symbol} spike {spike_ratio:.1f}x but order flow neutral")
                                else:
                                    print(f"ℹ️ {symbol} spike {spike_ratio:.1f}x but indicators not aligned")

                    elif spike_ratio < spike_multiplier:
                        if symbol in alerted:
                            alerted.pop(symbol, None)

            except Exception as e:
                print(f"⚠️ Error checking {symbol}: {e}")

            time.sleep(0.2)

        time.sleep(check_interval)

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    watchlist = get_morning_results()

    if not watchlist:
        print("❌ No stocks passed the morning screener.")
        bot.send_message(YOUR_CHAT_ID, "📊 *No stocks passed the morning screener today.*", parse_mode='Markdown')
        exit(0)

    # Send morning summary
    summary = "📊 *Morning Screener Results*\n\n"
    for s in watchlist[:10]:
        summary += f"✅ {s['symbol']} - ₹{s['price']:.2f} ({s['day_change']:.2f}%)\n"
    bot.send_message(YOUR_CHAT_ID, summary, parse_mode='Markdown')

    bot.send_message(YOUR_CHAT_ID,
        f"🔍 *Monitoring {len(watchlist)} stocks*\n"
        f"⚡ Volume spike ≥ {3}x\n"
        f"📈 RSI 30-70, MACD Bullish, ADX > 20\n"
        f"🔍 Order Flow: Delta, Absorption, Exhaustion, Imbalance",
        parse_mode='Markdown'
    )

    monitor_intraday(watchlist)
