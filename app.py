from flask import Flask, jsonify, render_template, request
import requests
import time
import json
import os
import re
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# Logging ayarları
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ------------------ EMAIL ALERT SINIFI ------------------
class EmailAlertService:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.port = 587
        self.sender_email = os.getenv('GMAIL_USER')
        self.sender_password = os.getenv('GMAIL_PASSWORD') 
        self.receiver_email = os.getenv('RECEIVER_EMAIL', self.sender_email)
        self.last_alert_time = {}  # Spam önleme için
        
    def should_send_alert(self, pair, min_interval=300):  # 5 dakika spam önleme
        """Aynı coin için çok sık alert göndermeyi önle"""
        current_time = time.time()
        if pair in self.last_alert_time:
            if current_time - self.last_alert_time[pair] < min_interval:
                return False
        self.last_alert_time[pair] = current_time
        return True
        
    def send_detailed_alert(self, alert_data):
        """Detaylı price alert gönder"""
        if not self.sender_email or not self.sender_password:
            logging.warning("Email ayarları yapılmamış!")
            return
            
        pair = alert_data['pair']
        if not self.should_send_alert(pair):
            logging.info(f"Spam önleme: {pair} için alert atlandı")
            return
            
        subject = f"🚀 {pair} - %{alert_data['five_minute_change']:.1f} YÜKSELİŞ!"
        html_content = self._create_detailed_alert_html(alert_data)
        
        self._send_email(subject, html_content)
        
    def _create_detailed_alert_html(self, alert):
        """Detaylı alert HTML'i oluştur"""
        
        # Renk kodları
        change_color = "#28a745" if alert['five_minute_change'] > 0 else "#dc3545"
        daily_color = "#28a745" if alert.get('daily_change', 0) > 0 else "#dc3545"
        sustained_badge = "🔥 DEVAM EDİYOR" if alert.get('sustained') else "⏳ İlk Tespit"
        sustained_color = "#dc3545" if alert.get('sustained') else "#ffc107"
        
        # Buy/Sell momentum analizi
        buy_dominance = alert['buy_percentage']
        momentum_text = "🟢 GÜÇLÜ ALIM BASKISI" if buy_dominance > 60 else "🔴 SATIŞ BASKISI VAR" if buy_dominance < 40 else "🟡 DENGE DURUMU"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f8f9fa; }}
                .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 25px; }}
                .coin-title {{ font-size: 24px; font-weight: bold; margin: 0; }}
                .timestamp {{ opacity: 0.9; margin-top: 5px; }}
                
                .main-stats {{ display: flex; justify-content: space-between; margin: 20px 0; gap: 15px; }}
                .stat-box {{ flex: 1; background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; }}
                .stat-value {{ font-size: 18px; font-weight: bold; margin-bottom: 5px; }}
                .stat-label {{ color: #6c757d; font-size: 12px; text-transform: uppercase; }}
                
                .volume-section {{ background: #e7f3ff; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .volume-title {{ font-weight: bold; color: #0066cc; margin-bottom: 15px; }}
                .volume-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }}
                .volume-item {{ background: white; padding: 12px; border-radius: 6px; }}
                .volume-value {{ font-weight: bold; color: #333; }}
                .volume-label {{ color: #666; font-size: 12px; }}
                
                .momentum-section {{ background: #f0f8f0; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .progress-bar {{ background: #e9ecef; height: 20px; border-radius: 10px; overflow: hidden; margin: 10px 0; }}
                .progress-fill {{ background: linear-gradient(90deg, #28a745, #20c997); height: 100%; transition: width 0.3s; }}
                
                .alert-footer {{ background: #fff3cd; padding: 15px; border-radius: 8px; border-left: 4px solid #ffc107; margin-top: 20px; }}
                .warning {{ color: #856404; font-size: 13px; }}
                
                .sustained {{ background: #ffe6e6; border-left: 4px solid #dc3545; }}
                
                @media (max-width: 600px) {{
                    .main-stats {{ flex-direction: column; }}
                    .volume-grid {{ grid-template-columns: 1fr; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="coin-title">{alert['pair']}</div>
                    <div class="timestamp">{datetime.now().strftime('%d %B %Y - %H:%M:%S')}</div>
                </div>
                
                <div class="content">
                    <!-- Ana İstatistikler -->
                    <div class="main-stats">
                        <div class="stat-box">
                            <div class="stat-value" style="color: {change_color}">
                                %{alert['five_minute_change']:.2f}
                            </div>
                            <div class="stat-label">5 Dakika Değişim</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-value" style="color: {daily_color}">
                                %{alert.get('daily_change', 0):.2f}
                            </div>
                            <div class="stat-label">Günlük Değişim</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-value">${alert['last_price']:.6f}</div>
                            <div class="stat-label">Anlık Fiyat</div>
                        </div>
                    </div>
                    
                    <!-- Durum Badge -->
                    <div style="text-align: center; margin: 20px 0;">
                        <span style="background: {sustained_color}; color: white; padding: 8px 16px; border-radius: 20px; font-weight: bold; font-size: 14px;">
                            {sustained_badge}
                        </span>
                    </div>
                    
                    <!-- Volume Bilgileri -->
                    <div class="volume-section">
                        <div class="volume-title">📊 HACIM ANALİZİ (Son 5 Dakika)</div>
                        <div class="volume-grid">
                            <div class="volume-item">
                                <div class="volume-value">${alert['buy_volume']:.0f}</div>
                                <div class="volume-label">Toplam Alım Hacmi</div>
                            </div>
                            <div class="volume-item">
                                <div class="volume-value">${alert['sell_volume']:.0f}</div>
                                <div class="volume-label">Toplam Satım Hacmi</div>
                            </div>
                            <div class="volume-item">
                                <div class="volume-value">${alert['buy_volume'] + alert['sell_volume']:.0f}</div>
                                <div class="volume-label">Toplam İşlem Hacmi</div>
                            </div>
                            <div class="volume-item">
                                <div class="volume-value">{alert.get('volume_1h', 'N/A')}</div>
                                <div class="volume-label">1 Saatlik Hacim</div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Momentum Analizi -->
                    <div class="momentum-section">
                        <div class="volume-title">⚡ MOMENTUM ANALİZİ</div>
                        <div style="margin: 15px 0;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                                <span>Alım Baskısı</span>
                                <span><strong>{alert['buy_percentage']:.1f}%</strong></span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: {alert['buy_percentage']}%;"></div>
                            </div>
                        </div>
                        <div style="text-align: center; font-weight: bold; color: {'#28a745' if buy_dominance > 60 else '#dc3545' if buy_dominance < 40 else '#ffc107'};">
                            {momentum_text}
                        </div>
                        
                        <!-- Ek Volume Metrikleri -->
                        <div style="margin-top: 15px; font-size: 14px;">
                            <div>🔸 <strong>Alım/Satım Oranı:</strong> {alert['buy_percentage']/alert['sell_percentage']:.2f}</div>
                            <div>🔸 <strong>Ortalama İşlem:</strong> ${(alert['buy_volume'] + alert['sell_volume']) / max(alert.get('trade_count', 1), 1):.0f}</div>
                        </div>
                    </div>
                    
                    <!-- Hızlı Aksiyon Linkleri -->
                    <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
                        <div style="font-weight: bold; color: #1976d2; margin-bottom: 10px;">⚡ HIZLI ERİŞİM</div>
                        <div style="display: flex; justify-content: center; gap: 15px; flex-wrap: wrap;">
                            <a href="https://www.gate.io/trade/{alert['pair']}" style="background: #1976d2; color: white; padding: 8px 16px; text-decoration: none; border-radius: 5px; font-size: 12px;">
                                📈 Gate.io'da Aç
                            </a>
                            <a href="https://coinmarketcap.com/currencies/{alert['pair'].replace('_', '-').replace('-usdt', '').replace('-btc', '')}" style="background: #17a2b8; color: white; padding: 8px 16px; text-decoration: none; border-radius: 5px; font-size: 12px;">
                                📊 CoinMarketCap
                            </a>
                        </div>
                    </div>
                    
                    <!-- Uyarı -->
                    <div class="alert-footer">
                        <div class="warning">
                            <strong>⚠️ UYARI:</strong> Bu sadece teknik bir uyarıdır. Yatırım kararlarınızı kendi araştırmanızla destekleyin. 
                            Kripto paralar yüksek volatiliteye sahiptir ve kayıp riski bulunmaktadır.
                        </div>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html
        
    def _send_email(self, subject, html_content):
        """Email gönder"""
        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self.sender_email
            message["To"] = self.receiver_email
            
            html_part = MIMEText(html_content, "html")
            message.attach(html_part)
            
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_server, self.port) as server:
                server.starttls(context=context)
                server.login(self.sender_email, self.sender_password)
                server.send_message(message)
                
            logging.info(f"✅ Email gönderildi: {subject}")
            
        except Exception as e:
            logging.error(f"❌ Email gönderme hatası: {e}")

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

# Email service instance
email_service = EmailAlertService()

# ------------------ PARAMETERS ------------------
FIVE_MINUTE_THRESHOLD = 10.0   # %10 threshold over 5 minutes
MIN_TRADE_VOLUME     = 250.0   # Min $250 volume
EMAIL_ALERT_THRESHOLD = 15.0   # %15+ değişim için email gönder

# ------------------ NEWS API ------------------
NEWS_API_KEY = os.getenv('NEWS_API_KEY')

# ------------------ ENHANCED DATA SOURCES ------------------
def get_gateio_tickers():
    try:
        r = requests.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        logging.error(f"Gate.io ticker hatası: {e}")
        return []

combine_tickers = get_gateio_tickers

# ------------------ ENHANCED TRADE VOLUME ANALYSIS ------------------
def get_enhanced_trade_volumes(pair, period_seconds):
    """Gelişmiş volume analizi - 1 saat ve 5 dakika karşılaştırması"""
    cutoff = time.time() - period_seconds
    buy_vol = sell_vol = trade_count = 0.0
    
    try:
        trades = requests.get(
            f"https://api.gateio.ws/api/v4/spot/trades?currency_pair={pair}&limit=1000",
            timeout=10
        ).json()
    except Exception as e:
        logging.error(f"Trade volume hatası {pair}: {e}")
        return 0, 0, 0, 0, 0
        
    for t in trades:
        ts = float(t.get('create_time', 0))
        if ts < cutoff: continue
        
        price = float(t.get('price', 0))
        amount = float(t.get('amount', 0))
        trade_count += 1
        
        if t.get('side','').lower() == 'buy':
            buy_vol += price * amount
        else:
            sell_vol += price * amount
            
    total = buy_vol + sell_vol
    if total < MIN_TRADE_VOLUME:
        return 0, 0, 0, 0, 0
        
    buy_percentage = (buy_vol/total)*100 if total > 0 else 0
    sell_percentage = (sell_vol/total)*100 if total > 0 else 0
    
    return buy_vol, sell_vol, buy_percentage, sell_percentage, trade_count

def get_1hour_volume(pair):
    """1 saatlik hacim al"""
    try:
        # Gate.io'dan 1 saatlik klines verisi al
        r = requests.get(
            f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&limit=1&interval=1h",
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                # Volume candlestick verisinin 5. elemanı
                return float(data[0][5]) if len(data[0]) > 5 else "N/A"
    except Exception as e:
        logging.error(f"1h volume hatası {pair}: {e}")
    return "N/A"

# ------------------ ENHANCED PRICE ALERT & "SUSTAINED" LOGIC ------------------
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

        # Enhanced volume analysis
        buy_v, sell_v, bp, sp, trade_count = get_enhanced_trade_volumes(pair, 300)  # 5 dakika
        if buy_v == 0 and sell_v == 0:
            continue

        # 1 saatlik volume
        volume_1h = get_1hour_volume(pair)

        # Daily change
        daily_change = ((last - daily_baseline[pair]) / daily_baseline[pair]) * 100

        alert_data = {
            'pair': pair,
            'last_price': last,
            'five_minute_change': change5,
            'daily_change': daily_change,
            'buy_volume': buy_v,
            'sell_volume': sell_v,
            'buy_percentage': bp,
            'sell_percentage': sp,
            'trade_count': trade_count,
            'volume_1h': volume_1h,
            'sustained': (len(hist) == 2),
            'timestamp': datetime.now().isoformat()
        }

        alerts.append(alert_data)
        
        # EMAIL ALERT GÖNDER - Yüksek değişimler için
        if change5 >= EMAIL_ALERT_THRESHOLD:
            logging.info(f"📧 Email alert gönderiliyor: {pair} %{change5:.1f}")
            email_service.send_detailed_alert(alert_data)

    price_alerts = alerts
    logging.info(f"✅ {len(alerts)} alert işlendi, email threshold: %{EMAIL_ALERT_THRESHOLD}")

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
check_price_changes()  # İlk çalıştırma

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
    pair = request.args.get('pair')
    period = request.args.get('period','1h')
    mapping = {
        '1m':60,'5m':300,'10m':600,'15m':900,'30m':1800,
        '1h':3600,'2h':7200,'6h':21600,'12h':43200,'24h':86400
    }
    sec = mapping.get(period, 3600)
    b,s,bp,sp,tc = get_enhanced_trade_volumes(pair, sec)
    return jsonify(pair=pair, period=period,
                   buy_volume=b, sell_volume=s,
                   buy_percentage=bp, sell_percentage=sp,
                   trade_count=tc)

@app.route('/new_listings')
def new_listings_page():
    listings = get_listing_announcements()
    return render_template('new_listings.html', listings=listings)

# ------------------ TEST ROUTES ------------------
@app.route('/test_email')
def test_email():
    """Email sistemini test et"""
    test_alert = {
        'pair': 'TEST_USDT',
        'last_price': 0.123456,
        'five_minute_change': 25.5,
        'daily_change': 45.2,
        'buy_volume': 15000,
        'sell_volume': 8500,
        'buy_percentage': 63.8,
        'sell_percentage': 36.2,
        'trade_count': 150,
        'volume_1h': '$125,000',
        'sustained': True,
        'timestamp': datetime.now().isoformat()
    }
    email_service.send_detailed_alert(test_alert)
    return jsonify({"message": "Test email gönderildi! Email'inizi kontrol edin."})

@app.route('/email_settings')
def email_settings():
    """Email ayarlarını kontrol et"""
    return jsonify({
        "email_configured": bool(email_service.sender_email and email_service.sender_password),
        "sender_email": email_service.sender_email,
        "receiver_email": email_service.receiver_email,
        "email_threshold": EMAIL_ALERT_THRESHOLD
    })

if __name__ == '__main__':
    app.run(debug=True)