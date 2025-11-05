import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
from threading import Thread
from flask import Flask, render_template
import numpy as np  # For RSI calculation
from dotenv import load_dotenv

app = Flask(__name__)

# Load .env file
load_dotenv()

GMAIL_USER = os.getenv('GMAIL_USER')  # Now used as sender email for Brevo
BREVO_API_KEY = os.getenv('BREVO_API_KEY')
RECEIVER_EMAIL = os.getenv('RECEIVER_EMAIL') or GMAIL_USER  # If empty, use sender

# Global lists
error_logs = []
signals = []

# Requests session with enhanced retry
session = requests.Session()
retries = Retry(total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504, 104])
session.mount('https://', HTTPAdapter(max_retries=retries))

def log_error(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error_logs.append(f"{timestamp} - {message}")
    if len(error_logs) > 100:
        error_logs.pop(0)
    # Send email for critical errors
    if "Failed to fetch" in message:
        send_email("Critical Error: Data Fetch Failed", f"<p>{message}</p>")

def calculate_rsi(prices, period=6):
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100 if avg_gain > 0 else 50
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def send_email(subject, body):
    try:
        # HTML format for better aesthetics
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2 style="color: #007BFF;">{subject}</h2>
            <table style="border-collapse: collapse; width: 100%; max-width: 600px;">
                <tr><th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2;">Alan</th><th style="border: 1px solid #ddd; padding: 8px; background-color: #f2f2f2;">Değer</th></tr>
                {body}
            </table>
            <p style="font-size: 12px; color: #888;">Bu e-posta otomatik olarak oluşturulmuştur.</p>
        </body>
        </html>
        """
        
        # Brevo API payload
        payload = {
            "sender": {"name": "Grok Futures", "email": GMAIL_USER},
            "to": [{"email": RECEIVER_EMAIL}],
            "subject": subject,
            "htmlContent": html_body
        }
        
        headers = {
            "accept": "application/json",
            "api-key": BREVO_API_KEY,
            "content-type": "application/json"
        }
        
        response = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers)
        response.raise_for_status()
        print(f"Mail sent via Brevo: {subject}")
    except Exception as e:
        log_error(f"Email sending failed: {str(e)}")
        print(f"Mail error: {str(e)}")

def fetch_contracts():
    url = "https://api.gateio.ws/api/v4/futures/usdt/contracts"  # Alternatif: "https://fx-api.gateio.ws/..." dene eğer sorun devam ederse
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        print(f"Fetched {len(data)} contracts")
        return data
    except Exception as e:
        log_error(f"Failed to fetch contracts: {str(e)}")
        print(f"Contracts fetch error: {str(e)}")
        return []

def fetch_tickers():
    url = "https://api.gateio.ws/api/v4/futures/usdt/tickers"
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        print(f"Fetched {len(data)} tickers")
        return {ticker['contract']: ticker for ticker in data}
    except Exception as e:
        log_error(f"Failed to fetch tickers: {str(e)}")
        print(f"Tickers fetch error: {str(e)}")
        return {}

def fetch_candlesticks(contract, interval='5m', limit=7):
    url = f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={contract}&interval={interval}&limit={limit}"
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        if len(data) >= 7:
            print(f"Fetched candlesticks for {contract}")
        return data
    except Exception as e:
        log_error(f"Failed to fetch candlesticks for {contract}: {str(e)}")
        print(f"Candlesticks error for {contract}: {str(e)}")
        return []  # Hata durumunda boş dön, skip et

def fetch_trades(contract, limit=100):  # Increased limit for filtering
    url = f"https://api.gateio.ws/api/v4/futures/usdt/trades?contract={contract}&limit={limit}"
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        print(f"Fetched {len(data)} trades for {contract}")
        return data
    except Exception as e:
        log_error(f"Failed to fetch trades for {contract}: {str(e)}")
        print(f"Trades error for {contract}: {str(e)}")
        return []

def check_rsi_and_notify():
    print(f"Starting RSI check at {datetime.now()}")
    contracts = fetch_contracts()
    tickers = fetch_tickers()
    processed = 0
    skipped_volume = 0
    signals_found = 0

    if not contracts or not tickers:
        print("No data fetched, skipping check")
        return

    for contract in contracts:
        symbol = contract['name']
        if symbol not in tickers:
            continue

        ticker = tickers[symbol]
        volume_24h = float(ticker.get('volume_24h_quote', 0))
        if volume_24h < 1_000_000:
            skipped_volume += 1
            continue

        candlesticks = fetch_candlesticks(symbol)
        if not candlesticks or len(candlesticks) < 7:
            continue  # Hata veya yetersiz veri, skip et

        closes = [float(candle['c']) for candle in candlesticks]
        rsi = calculate_rsi(closes)
        if rsi is None:
            continue

        processed += 1
        current_price = closes[-1]
        signal_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Last candle details for %3 movement and time filter
        last_candle = candlesticks[-1]
        open_price = float(last_candle['o'])
        close_price = float(last_candle['c'])
        change_percent = (close_price - open_price) / open_price if open_price != 0 else 0
        candle_start_time = int(last_candle['t'])  # Unix timestamp in seconds

        signal = None
        table_rows = f"""
        <tr><td style="border: 1px solid #ddd; padding: 8px;">Coin</td><td style="border: 1px solid #ddd; padding: 8px;">{symbol}</td></tr>
        <tr><td style="border: 1px solid #ddd; padding: 8px;">RSI Değeri</td><td style="border: 1px solid #ddd; padding: 8px;">{rsi:.2f}</td></tr>
        <tr><td style="border: 1px solid #ddd; padding: 8px;">Giriş Değeri</td><td style="border: 1px solid #ddd; padding: 8px;">{current_price}</td></tr>
        <tr><td style="border: 1px solid #ddd; padding: 8px;">Fiyat</td><td style="border: 1px solid #ddd; padding: 8px;">{current_price}</td></tr>
        <tr><td style="border: 1px solid #ddd; padding: 8px;">Sinyal Zamanı</td><td style="border: 1px solid #ddd; padding: 8px;">{signal_time}</td></tr>
        """

        if rsi < 25 and change_percent <= -0.03:  # Oversold and at least 3% drop
            signal_type = "Alım Sinyali"
            entry = current_price
            stop = entry * (1 - 0.025)
            subject = f"{symbol} - RSI(6) Alım Sinyali"
            table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">Stop Değeri</td><td style="border: 1px solid #ddd; padding: 8px;">{stop}</td></tr>'

            # Fetch last 100 trades and filter by last 5min candle time
            trades = fetch_trades(symbol, limit=100)
            if trades:
                # Filter trades within the last candle's time (approx 5min)
                candle_end_time = candle_start_time + 300  # 5min in seconds
                filtered_trades = [trade for trade in trades if candle_start_time <= int(trade['create_time_ms']) / 1000 <= candle_end_time]

                if filtered_trades:
                    # Separate buy and sell (assuming 'side' is 'buy' or 'sell', adjust if 'bid'/'ask')
                    buy_trades = [trade for trade in filtered_trades if trade.get('side') == 'buy']  # or 'bid'
                    sell_trades = [trade for trade in filtered_trades if trade.get('side') == 'sell']  # or 'ask'

                    # For buy: top 5 by amount = size * price
                    top_buy = sorted([(float(trade['size']) * float(trade['price']), float(trade['price'])) for trade in buy_trades], reverse=True)[:5]
                    top_sell = sorted([(float(trade['size']) * float(trade['price']), float(trade['price'])) for trade in sell_trades], reverse=True)[:5]

                    table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">En Büyük 5 Buy İşlem (Tutar @ Fiyat)</td><td style="border: 1px solid #ddd; padding: 8px;">{", ".join([f"{amt:.2f} USDT @ {price:.4f}" for amt, price in top_buy])}</td></tr>'
                    table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">En Büyük 5 Sell İşlem (Tutar @ Fiyat)</td><td style="border: 1px solid #ddd; padding: 8px;">{", ".join([f"{amt:.2f} USDT @ {price:.4f}" for amt, price in top_sell])}</td></tr>'

                    total_buy = sum(amt for amt, _ in top_buy)
                    total_sell = sum(amt for amt, _ in top_sell)
                    table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">Toplam Buy Tutar (En Büyük 5)</td><td style="border: 1px solid #ddd; padding: 8px;">{total_buy:.2f} USDT</td></tr>'
                    table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">Toplam Sell Tutar (En Büyük 5)</td><td style="border: 1px solid #ddd; padding: 8px;">{total_sell:.2f} USDT</td></tr>'

            send_email(subject, table_rows)
            signal = {"symbol": symbol, "type": signal_type, "rsi": rsi, "entry": entry, "stop": stop, "price": current_price, "time": signal_time}
            signals_found += 1

        elif rsi > 85 and change_percent >= 0.03:  # Overbought and at least 3% rise
            signal_type = "Satım Sinyali"
            entry = current_price
            stop = entry * (1 + 0.025)
            subject = f"{symbol} - RSI(6) Satım Sinyali"
            table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">Stop Değeri</td><td style="border: 1px solid #ddd; padding: 8px;">{stop}</td></tr>'

            # Fetch last 100 trades and filter by last 5min candle time
            trades = fetch_trades(symbol, limit=100)
            if trades:
                # Filter trades within the last candle's time (approx 5min)
                candle_end_time = candle_start_time + 300  # 5min in seconds
                filtered_trades = [trade for trade in trades if candle_start_time <= int(trade['create_time_ms']) / 1000 <= candle_end_time]

                if filtered_trades:
                    # Separate buy and sell (assuming 'side' is 'buy' or 'sell', adjust if 'bid'/'ask')
                    buy_trades = [trade for trade in filtered_trades if trade.get('side') == 'buy']  # or 'bid'
                    sell_trades = [trade for trade in filtered_trades if trade.get('side') == 'sell']  # or 'ask'

                    # For buy: top 5 by amount = size * price
                    top_buy = sorted([(float(trade['size']) * float(trade['price']), float(trade['price'])) for trade in buy_trades], reverse=True)[:5]
                    top_sell = sorted([(float(trade['size']) * float(trade['price']), float(trade['price'])) for trade in sell_trades], reverse=True)[:5]

                    table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">En Büyük 5 Buy İşlem (Tutar @ Fiyat)</td><td style="border: 1px solid #ddd; padding: 8px;">{", ".join([f"{amt:.2f} USDT @ {price:.4f}" for amt, price in top_buy])}</td></tr>'
                    table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">En Büyük 5 Sell İşlem (Tutar @ Fiyat)</td><td style="border: 1px solid #ddd; padding: 8px;">{", ".join([f"{amt:.2f} USDT @ {price:.4f}" for amt, price in top_sell])}</td></tr>'

                    total_buy = sum(amt for amt, _ in top_buy)
                    total_sell = sum(amt for amt, _ in top_sell)
                    table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">Toplam Buy Tutar (En Büyük 5)</td><td style="border: 1px solid #ddd; padding: 8px;">{total_buy:.2f} USDT</td></tr>'
                    table_rows += f'<tr><td style="border: 1px solid #ddd; padding: 8px;">Toplam Sell Tutar (En Büyük 5)</td><td style="border: 1px solid #ddd; padding: 8px;">{total_sell:.2f} USDT</td></tr>'

            send_email(subject, table_rows)
            signal = {"symbol": symbol, "type": signal_type, "rsi": rsi, "entry": entry, "stop": stop, "price": current_price, "time": signal_time}
            signals_found += 1

        if signal:
            signals.append(signal)

    print(f"Finished RSI check: Processed {processed} coins, skipped {skipped_volume} due to low volume, found {signals_found} signals")

def rsi_monitor_loop():
    while True:
        check_rsi_and_notify()
        time.sleep(300)  # 5 min

@app.route('/')
def index():
    return render_template('index.html', logs=error_logs)

if __name__ == '__main__':
    monitor_thread = Thread(target=rsi_monitor_loop)
    monitor_thread.daemon = True
    monitor_thread.start()
    app.run(debug=True, use_reloader=False)