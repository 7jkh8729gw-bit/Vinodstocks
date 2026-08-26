import yfinance as yf
import pandas as pd
import numpy as np

def calculate_dema(data, period):
    """Calculate Double Exponential Moving Average (DEMA)"""
    ema1 = data.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    dema = 2 * ema1 - ema2
    return dema

def check_stock_conditions(symbol):
    """
    Check if a stock meets all screening conditions
    Returns: (bool, dict) - (pass/fail, details)
    """
    try:
        # Fetch stock data
        ticker = yf.Ticker(symbol)
        info = ticker.info
        hist = ticker.history(period="6mo")  # Enough for 200-day DEMA
        
        # 1. Market Cap > 1000 (in millions or crores, adjust as needed)
        market_cap = info.get('marketCap', 0)
        if market_cap == 0:
            # Try alternative field
            market_cap = info.get('enterpriseValue', 0)
        market_cap_in_millions = market_cap / 1_000_000  # Convert to millions
        
        # 2. Close Price > 100
        current_price = info.get('regularMarketPrice', info.get('currentPrice', 0))
        
        # 3. Day % Change: 0 to 15%
        previous_close = info.get('regularMarketPreviousClose', 0)
        if previous_close > 0:
            day_change_pct = ((current_price - previous_close) / previous_close) * 100
        else:
            day_change_pct = 0
            
        # 4. Daily Volume > 200,000
        daily_volume = info.get('regularMarketVolume', 0)
        
        # 5. Month Average Volume > 500,000
        avg_volume_3m = info.get('averageDailyVolume3Month', 0)
        
        # 6. % Away from 52-Week High: 0-10%
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        if high_52w > 0:
            pct_from_high = ((high_52w - current_price) / high_52w) * 100
        else:
            pct_from_high = 100  # Fail if no data
        
        # 7. Calculate DEMAs (need at least 200 days of data)
        if len(hist) >= 200:
            dema_10 = calculate_dema(hist['Close'], 10)
            dema_50 = calculate_dema(hist['Close'], 50)
            dema_200 = calculate_dema(hist['Close'], 200)
            
            latest_dema_10 = dema_10.iloc[-1]
            latest_dema_50 = dema_50.iloc[-1]
            latest_dema_200 = dema_200.iloc[-1]
            
            cond_10_50 = latest_dema_10 > latest_dema_50
            cond_50_200 = latest_dema_50 > latest_dema_200
        else:
            cond_10_50 = False
            cond_50_200 = False
        
        # Check ALL conditions
        conditions_met = (
            market_cap_in_millions > 1000 and
            current_price > 100 and
            0 <= day_change_pct <= 15 and
            daily_volume > 200000 and
            avg_volume_3m > 500000 and
            0 <= pct_from_high <= 10 and
            cond_10_50 and
            cond_50_200
        )
        
        # Prepare details for alert message
        details = {
            'symbol': symbol,
            'price': current_price,
            'market_cap_millions': market_cap_in_millions,
            'day_change_pct': day_change_pct,
            'volume': daily_volume,
            'avg_volume_3m': avg_volume_3m,
            'pct_from_high': pct_from_high,
            'dema_10': latest_dema_10 if len(hist) >= 200 else 'N/A',
            'dema_50': latest_dema_50 if len(hist) >= 200 else 'N/A',
            'dema_200': latest_dema_200 if len(hist) >= 200 else 'N/A'
        }
        
        return conditions_met, details
        
    except Exception as e:
        print(f"Error checking {symbol}: {e}")
        return False, {}

def format_alert_message(details):
    """Format the alert message for Telegram"""
    message = f"🚨 *SCREENER ALERT: {details['symbol']}* 🚨\n\n"
    message += f"📊 *Current Price:* ${details['price']:.2f}\n"
    message += f"💼 *Market Cap:* ${details['market_cap_millions']:.1f}M\n"
    message += f"📈 *Day Change:* {details['day_change_pct']:.2f}%\n"
    message += f"📊 *Volume:* {details['volume']:,}\n"
    message += f"📊 *3M Avg Volume:* {details['avg_volume_3m']:,}\n"
    message += f"📉 *From 52W High:* {details['pct_from_high']:.2f}%\n"
    message += f"📈 *10 DEMA:* {details['dema_10']:.2f} (50 DEMA: {details['dema_50']:.2f})\n"
    message += f"📈 *50 DEMA:* {details['dema_50']:.2f} (200 DEMA: {details['dema_200']:.2f})\n"
    message += "\n✅ *All screening conditions met!*"
    return message
