from flask import Flask, jsonify, render_template, request
import requests
import time
import json
import os
import re
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# ------------------ STORAGE ------------------
KNOWN_PAIRS_FILE = 'known_pairs.json'
try:
    with open(KNOWN_PAIRS_FILE, 'r') as f:
        known_pairs = set(json.load(f))
except:
    known_pairs = set()

# ------------------ DATA STRUCTURES ------------------
daily_baseline = {}
five_minute_baseline = {}
price_history = {}
price_alerts = []

# ------------------ PARAMETERS ------------------
FIVE_MINUTE_THRESHOLD = 10.0   # %10 threshold over 5 minutes
MIN_TRADE_VOLUME     = 250.0   # Min $250 volume

# ------------------ NEWS API ------------------
NEWS_API_KEY = os.getenv('NEWS_API_KEY')  # Set your NewsAPI.org key here

# ------------------ DATA SOURCES ------------------
def get_gateio_tickers():
    try:
        r = requests.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=10)
        return r.json() if r.status_code == 200 else []
    except:
        return []
combine_tickers = get_gateio_tickers

# ------------------ TRADE VOLUME ANALYSIS ------------------
def get_trade_volumes(pair, period_seconds):
    cutoff = time.time() - period_seconds
    buy_vol = sell_vol = 0.0
    try:
        trades = requests.get(
            f"https://api.gateio.ws/api/v4/spot/trades?currency_pair={pair}&limit=1000",
            timeout=10
        ).json()
    except:
        trades = []
    for t in trades:
        ts = float(t.get('create_time', 0))
        if ts < cutoff: continue
        price  = float(t.get('price', 0))
        amount = float(t.get('amount', 0))
        if t.get('side','').lower() == 'buy':
            buy_vol += price * amount
        else:
            sell_vol += price * amount
    total = buy_vol + sell_vol
    if total < MIN_TRADE_VOLUME:
        return 0, 0, 0, 0
    return buy_vol, sell_vol, (buy_vol/total)*100, (sell_vol/total)*100

# ------------------ PRICE ALERT & “SUSTAINED” LOGIC ------------------
def check_price_changes():
    global price_alerts
    alerts = []
    for t in combine_tickers():
        pair = t.get('currency_pair')
        try:
            last = float(t.get('last', 0))
        except:
            continue

        # Initialize baselines if first seen
        daily_baseline.setdefault(pair, last)
        prev_baseline = five_minute_baseline.get(pair, last)

        # Compute 5-minute change
        change5 = ((last - prev_baseline) / prev_baseline) * 100 if prev_baseline > 0 else 0

        # Manage history: keep only consecutive threshold breaches
        hist = price_history.setdefault(pair, [])
        if change5 >= FIVE_MINUTE_THRESHOLD:
            hist.append(change5)
            if len(hist) > 2:
                hist.pop(0)
        else:
            hist.clear()

        # Shift baseline forward
        five_minute_baseline[pair] = last

        # If not breaching threshold, skip
        if change5 < FIVE_MINUTE_THRESHOLD:
            continue

        # Check volume
        buy_v, sell_v, bp, sp = get_trade_volumes(pair, 300)
        if buy_v == 0 and sell_v == 0:
            continue

        # Daily change
        daily_change = ((last - daily_baseline[pair]) / daily_baseline[pair]) * 100

        alerts.append({
            'pair': pair,
            'last_price': last,
            'five_minute_change': change5,
            'daily_change': daily_change,
            'buy_volume': buy_v,
            'sell_volume': sell_v,
            'buy_percentage': bp,
            'sell_percentage': sp,
            'sustained': (len(hist) == 2)
        })

    price_alerts = alerts

# ------------------ NEW LISTING ARTICLES ------------------
def get_listing_announcements():
    if not NEWS_API_KEY:
        return []
    url = 'https://newsapi.org/v2/everything'
    params = {
        'q': 'to list on',
        'language': 'en',
        'sortBy': 'publishedAt',
        'apiKey': NEWS_API_KEY,
        'pageSize': 50
    }
    try:
        resp = requests.get(url, params=params, timeout=10).json()
        arts = resp.get('articles', [])
    except:
        return []
    results = []
    for art in arts:
        title = art.get('title','')
        m = re.search(r'(?P<coin>\w+)\s+to\s+list\s+on\s+(?P<exchange>\w+)', title, re.IGNORECASE)
        if m:
            results.append({
                'coin': m.group('coin').upper(),
                'exchange': m.group('exchange').upper(),
                'url': art.get('url')
            })
    return results

# ------------------ SCHEDULER ------------------
scheduler = BackgroundScheduler()
scheduler.add_job(check_price_changes, 'interval', minutes=2)
scheduler.start()
check_price_changes()

# ------------------ ROUTES ------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/pricealerts')
def get_pricealerts():
    return jsonify(price_alerts)

@app.route('/volume_page')
def volume_page():
    pairs = [t['currency_pair'] for t in combine_tickers()]
    return render_template('volume.html', pairs=pairs)

@app.route('/volume')
def volume():
    pair   = request.args.get('pair')
    period = request.args.get('period','1h')
    mapping = {
        '1m':60,'5m':300,'10m':600,'15m':900,'30m':1800,
        '1h':3600,'2h':7200,'6h':21600,'12h':43200,'24h':86400
    }
    sec = mapping.get(period, 3600)
    b,s,bp,sp = get_trade_volumes(pair, sec)
    return jsonify(pair=pair, period=period,
                   buy_volume=b, sell_volume=s,
                   buy_percentage=bp, sell_percentage=sp)

@app.route('/new_listings')
def new_listings_page():
    listings = get_listing_announcements()
    return render_template('new_listings.html', listings=listings)

if __name__ == '__main__':
    app.run(debug=True)
