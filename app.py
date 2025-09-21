from flask import Flask, jsonify, render_template, request
import requests
import time
import json
import os
import smtplib
import ssl
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import numpy as np
from collections import defaultdict, deque
import statistics

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# Logging ayarları
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ------------------ KEEP-ALIVE SİSTEMİ ------------------
class KeepAliveService:
    def __init__(self, app_url=None):
        self.app_url = app_url or os.getenv('RENDER_APP_URL', 'https://crypto-cnc6.onrender.com')
        self.ping_interval = 14 * 60
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        self.logger = logging.getLogger('KeepAlive')
        
    def ping_server(self):
        try:
            response = requests.get(
                f"{self.app_url}/keepalive", 
                timeout=10,
                headers={
                    'User-Agent': 'KeepAlive-Bot/1.0',
                    'Accept': 'application/json'
                }
            )
            
            if response.status_code == 200:
                self.logger.info(f"✅ Keep-alive ping başarılı")
            else:
                self.logger.warning(f"⚠️ Keep-alive ping - Status: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"❌ Keep-alive ping hatası: {e}")
    
    def start(self):
        if self.is_running:
            return
            
        try:
            self.logger.info(f"🚀 Keep-alive servisi başlatılıyor...")
            
            self.scheduler.add_job(
                self.ping_server,
                'interval',
                seconds=self.ping_interval,
                id='keepalive_ping',
                replace_existing=True
            )
            
            self.scheduler.start()
            self.is_running = True
            
            threading.Timer(5.0, self.ping_server).start()
            self.logger.info(f"✅ Keep-alive aktif")
            
        except Exception as e:
            self.logger.error(f"❌ Keep-alive başlatma hatası: {e}")

keep_alive_service = KeepAliveService()
keep_alive_service.start()

# ------------------ TECHNICAL ANALYSIS ------------------
class TechnicalAnalyzer:
    def __init__(self):
        self.price_history = defaultdict(lambda: deque(maxlen=100))
        self.volume_history = defaultdict(lambda: deque(maxlen=100))
        
    def add_data_point(self, symbol, price, volume, timestamp):
        try:
            self.price_history[symbol].append(float(price))
            self.volume_history[symbol].append(float(volume))
        except:
            pass
    
    def calculate_rsi(self, symbol, period=14):
        try:
            prices = list(self.price_history[symbol])
            if len(prices) < period + 1:
                return None
                
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            
            if avg_loss == 0:
                return 100
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        except:
            return None
    
    def calculate_volume_profile(self, symbol):
        try:
            volumes = list(self.volume_history[symbol])
            if len(volumes) < 10:
                return None
                
            recent_avg = sum(volumes[-10:]) / 10
            current_volume = volumes[-1] if volumes else 0
            
            volume_spike = (current_volume / recent_avg) if recent_avg > 0 else 0
            return volume_spike
        except:
            return None
    
    def detect_price_breakout(self, symbol):
        try:
            prices = list(self.price_history[symbol])
            if len(prices) < 20:
                return False, 0
                
            current_price = prices[-1]
            recent_high = max(prices[-20:-1])
            recent_low = min(prices[-20:-1])
            
            if current_price > recent_high:
                breakout_percent = ((current_price - recent_high) / recent_high) * 100
                return True, breakout_percent
            elif current_price < recent_low:
                breakout_percent = ((current_price - recent_low) / recent_low) * 100
                return True, breakout_percent
                
            return False, 0
        except:
            return False, 0

    def is_strong_signal(self, rsi, volume_spike, change_percent, breakout_percent):
        """Çok seçici sinyal kontrolü"""
        try:
            strength_score = 0
            
            # RSI extreme levels
            if rsi and (rsi < 32 or rsi > 68):
                strength_score += 2
            
            # Volume spike
            if volume_spike and volume_spike > 2.0:
                strength_score += 2
            
            # Price change
            if abs(change_percent) > 3:
                strength_score += 1
            
            # Breakout
            if abs(breakout_percent) > 2:
                strength_score += 1
            
            # Minimum gerekli puan
            return strength_score >= 2
        except:
            return False

    def calculate_trading_levels(self, current_price, signal_type):
        try:
            if signal_type == 'RSI_OVERSOLD':
                return {
                    'direction': 'LONG',
                    'entry_price': current_price,
                    'tp1': current_price * 1.025,
                    'tp2': current_price * 1.05,
                    'tp3': current_price * 1.08,
                    'stop_loss': current_price * 0.98,
                    'risk_reward': '1:2.5',
                    'confidence': 'HIGH'
                }
            elif signal_type == 'RSI_OVERBOUGHT':
                return {
                    'direction': 'SHORT',
                    'entry_price': current_price,
                    'tp1': current_price * 0.975,
                    'tp2': current_price * 0.95,
                    'tp3': current_price * 0.92,
                    'stop_loss': current_price * 1.02,
                    'risk_reward': '1:2.5',
                    'confidence': 'HIGH'
                }
            elif signal_type == 'BREAKOUT':
                return {
                    'direction': 'LONG',
                    'entry_price': current_price,
                    'tp1': current_price * 1.03,
                    'tp2': current_price * 1.06,
                    'tp3': current_price * 1.1,
                    'stop_loss': current_price * 0.975,
                    'risk_reward': '1:2.8',
                    'confidence': 'HIGH'
                }
            elif signal_type == 'VOLUME_SPIKE':
                return {
                    'direction': 'LONG',
                    'entry_price': current_price,
                    'tp1': current_price * 1.025,
                    'tp2': current_price * 1.05,
                    'tp3': current_price * 1.08,
                    'stop_loss': current_price * 0.98,
                    'risk_reward': '1:2.4',
                    'confidence': 'HIGH'
                }
            else:
                return {
                    'direction': 'LONG',
                    'entry_price': current_price,
                    'tp1': current_price * 1.02,
                    'tp2': current_price * 1.04,
                    'tp3': current_price * 1.06,
                    'stop_loss': current_price * 0.985,
                    'risk_reward': '1:2',
                    'confidence': 'MEDIUM'
                }
        except:
            return {
                'direction': 'LONG',
                'entry_price': current_price,
                'tp1': current_price,
                'tp2': current_price,
                'tp3': current_price,
                'stop_loss': current_price,
                'risk_reward': '1:1',
                'confidence': 'LOW'
            }

analyzer = TechnicalAnalyzer()

# ------------------ EMAIL ALERT ------------------
class EmailAlertService:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.port = 587
        self.sender_email = os.getenv('GMAIL_USER')
        self.sender_password = os.getenv('GMAIL_PASSWORD')
        self.receiver_email = os.getenv('RECEIVER_EMAIL', self.sender_email)
        self.last_alert_time = {}
        
    def should_send_alert(self, symbol, signal_type, min_interval=900):  # 15 dakika
        key = f"{symbol}_{signal_type}"
        current_time = time.time()
        if key in self.last_alert_time:
            if current_time - self.last_alert_time[key] < min_interval:
                return False
        self.last_alert_time[key] = current_time
        return True
    
    def send_futures_alert(self, alert_data):
        if not self.sender_email or not self.sender_password:
            logging.warning("Email ayarları yapılmamış!")
            return
            
        symbol = alert_data['symbol']
        signal_type = alert_data['signal_type']
        
        if not self.should_send_alert(symbol, signal_type):
            logging.info(f"Spam önleme: {symbol} {signal_type}")
            return
        
        subject = f"🚀 {alert_data['direction']} {symbol} - {signal_type} SİNYALİ!"
        html_content = self._create_futures_alert_html(alert_data)
        
        self._send_email(subject, html_content)
    
    def _create_futures_alert_html(self, alert):
        direction_emoji = "📈" if alert['direction'] == 'LONG' else "📉"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #1a1a2e; color: white; }}
                .container {{ max-width: 600px; margin: 0 auto; background: #16213e; border-radius: 15px; padding: 30px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .symbol {{ font-size: 28px; font-weight: bold; color: #4ecdc4; }}
                .levels {{ background: #f8f9fa; color: #333; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                .btn {{ display: inline-block; padding: 12px 25px; margin: 10px; border-radius: 8px; text-decoration: none; font-weight: bold; background: #667eea; color: white; }}
                .warning {{ background: rgba(255,193,7,0.1); padding: 15px; border-radius: 8px; margin: 20px 0; border: 1px solid #ffc107; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="symbol">{direction_emoji} {alert['symbol']} - {alert['direction']} FUTURES</div>
                    <div style="color: #2ed573; font-weight: bold;">HIGH CONFIDENCE</div>
                </div>
                
                <div class="levels">
                    <h3>🎯 TRADING LEVELS</h3>
                    <p><strong>Entry:</strong> ${alert['entry_price']:.4f}</p>
                    <p><strong>TP1:</strong> ${alert['tp1']:.4f}</p>
                    <p><strong>TP2:</strong> ${alert['tp2']:.4f}</p>
                    <p><strong>TP3:</strong> ${alert['tp3']:.4f}</p>
                    <p><strong>Stop Loss:</strong> ${alert['stop_loss']:.4f}</p>
                    <p><strong>Risk/Reward:</strong> {alert['risk_reward']}</p>
                    <p><strong>24h Volume:</strong> ${alert.get('volume_24h', 0)/1000000:.1f}M USD</p>
                </div>
                
                <div style="text-align: center;">
                    <a href="https://www.gate.io/futures_trade/{alert['symbol']}" class="btn">
                        📈 Gate.io Futures
                    </a>
                    <a href="https://www.tradingview.com/chart/?symbol=GATEIO:{alert['symbol']}" class="btn">
                        📊 TradingView
                    </a>
                </div>
                
                <div class="levels">
                    <h3>📊 SİNYAL DETAYLARI</h3>
                    <p><strong>Sinyal:</strong> {alert['description']}</p>
                    <p><strong>RSI:</strong> {alert.get('rsi', 50):.1f}</p>
                    <p><strong>Hacim Çarpanı:</strong> {alert.get('volume_spike', 1):.1f}x</p>
                    <p><strong>24s Değişim:</strong> {alert.get('change_percent', 0):.2f}%</p>
                </div>
                
                <div class="warning">
                    <strong>⚠️ RİSK UYARISI:</strong> Futures trading yüksek risk içerir. 
                    Stop-loss kullanmayı unutmayın!
                </div>
            </div>
        </body>
        </html>
        """
        return html
    
    def _send_email(self, subject, html_content):
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
            logging.error(f"❌ Email hatası: {e}")

email_service = EmailAlertService()

# ------------------ GATE.IO FUTURES MONITOR ------------------
class GateioFuturesMonitor:
    def __init__(self):
        self.active_signals = []
        self.gateio_base_url = "https://api.gateio.ws/api/v4"
        self.futures_contracts = set()
        
    def safe_convert(self, value, default=0.0):
        """Ultra güvenli dönüşüm"""
        try:
            if value is None or value == '' or value == '0':
                return default
            return float(str(value).strip())
        except:
            return default
        
    def get_futures_contracts(self):
        """Gate.io Futures kontratlarını al"""
        try:
            response = requests.get(f"{self.gateio_base_url}/futures/usdt/contracts", timeout=10)
            if response.status_code == 200:
                contracts = response.json()
                self.futures_contracts = {c.get('name', '') for c in contracts if c.get('in_delisting') == False and c.get('name', '').endswith('_USDT')}
                logging.info(f"Gate.io Futures: {len(self.futures_contracts)} aktif kontrat")
                return True
            return False
        except Exception as e:
            logging.error(f"Kontrat listesi hatası: {e}")
            return False
    
    def get_futures_tickers(self):
        """Gate.io Futures ticker verilerini al"""
        try:
            response = requests.get(f"{self.gateio_base_url}/futures/usdt/tickers", timeout=15)
            if response.status_code == 200:
                data = response.json()
                filtered_data = [t for t in data if t.get('contract', '') in self.futures_contracts]
                logging.info(f"Gate.io Futures: {len(filtered_data)} ticker alındı")
                return filtered_data
            else:
                logging.error(f"Ticker API hata kodu: {response.status_code}")
                return []
        except Exception as e:
            logging.error(f"Ticker alma hatası: {e}")
            return []
    
    def get_kline_data(self, contract, limit=20):
        """Kline verisi al"""
        try:
            params = {
                'contract': contract,
                'interval': '1m',
                'limit': limit
            }
            response = requests.get(f"{self.gateio_base_url}/futures/usdt/candlesticks", params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except:
            return []
    
    def analyze_ticker(self, ticker):
        """Ticker analizi - tamamen güvenli"""
        try:
            contract = ticker.get('contract', '')
            if not contract or not contract.endswith('_USDT') or contract not in self.futures_contracts:
                return None
                
            # Güvenli veri çıkarma
            volume_24h = self.safe_convert(ticker.get('volume_24h'))
            price = self.safe_convert(ticker.get('last'))
            change_percent = self.safe_convert(ticker.get('change_percentage'))
            
            # Temel filtreler
            if volume_24h < 1000000 or price <= 0:
                return None
            
            # Kline verisi al
            klines = self.get_kline_data(contract, limit=20)
            for kline in klines:
                try:
                    if len(kline) >= 7:
                        close_price = self.safe_convert(kline[4])
                        volume = max(self.safe_convert(kline[6]), 1)
                        if close_price > 0:
                            analyzer.add_data_point(contract, close_price, volume, int(time.time()))
                except:
                    continue
            
            # Teknik analiz
            rsi = analyzer.calculate_rsi(contract)
            volume_spike = analyzer.calculate_volume_profile(contract)
            breakout_detected, breakout_percent = analyzer.detect_price_breakout(contract)
            
            # Güçlü sinyal kontrolü
            if not analyzer.is_strong_signal(rsi, volume_spike, change_percent, breakout_percent):
                return None
            
            # Sinyal türünü belirle
            signal_type = 'BREAKOUT'
            description = f'Güçlü sinyal tespit edildi!'
            
            if rsi and rsi < 32:
                signal_type = 'RSI_OVERSOLD'
                description = f'RSI kritik seviyede ({rsi:.1f}). Güçlü geri dönüş!'
            elif rsi and rsi > 68:
                signal_type = 'RSI_OVERBOUGHT'  
                description = f'RSI aşırı yüksek ({rsi:.1f}). Düzeltme sinyali!'
            elif volume_spike and volume_spike > 2.0:
                signal_type = 'VOLUME_SPIKE'
                description = f'Hacimde {volume_spike:.1f}x artış!'
            elif breakout_detected and abs(breakout_percent) > 2:
                direction = "yükseliş" if breakout_percent > 0 else "düşüş"
                description = f'%{abs(breakout_percent):.1f} {direction} kırılımı!'
            
            # Trading seviyelerini hesapla
            trading_levels = analyzer.calculate_trading_levels(price, signal_type)
            
            return {
                'symbol': contract.replace('_USDT', 'USDT'),
                'price': price,
                'change_percent': change_percent,
                'signal_type': signal_type,
                'description': description,
                'rsi': rsi if rsi else 50,
                'volume_spike': volume_spike if volume_spike else 1,
                'volume_24h': volume_24h,
                'timestamp': datetime.now().isoformat(),
                'direction': trading_levels['direction'],
                'entry_price': trading_levels['entry_price'],
                'tp1': trading_levels['tp1'],
                'tp2': trading_levels['tp2'],
                'tp3': trading_levels['tp3'],
                'stop_loss': trading_levels['stop_loss'],
                'risk_reward': trading_levels['risk_reward'],
                'confidence': trading_levels['confidence']
            }
            
        except Exception as e:
            # Hataları loglamayın, sadece None döndürün
            return None
    
    def scan_futures_market(self):
        """Piyasa taraması - hatasız"""
        logging.info("🔍 Gate.io Futures taraması başlıyor...")
        
        # Kontratları güncelle
        if not self.get_futures_contracts():
            logging.error("Kontrat listesi alınamadı")
            return
        
        # Ticker verilerini al
        tickers = self.get_futures_tickers()
        if not tickers:
            logging.error("Ticker verisi alınamadı")
            return
        
        new_signals = []
        total_checked = 0
        volume_filtered = 0
        
        for ticker in tickers:
            total_checked += 1
            
            # Hacim kontrolü
            volume_24h = self.safe_convert(ticker.get('volume_24h'))
            if volume_24h < 1000000:
                volume_filtered += 1
                continue
            
            # Analiz yap
            alert = self.analyze_ticker(ticker)
            if alert:
                new_signals.append(alert)
                # Email gönder
                try:
                    email_service.send_futures_alert(alert)
                    logging.info(f"🚀 GÜÇLÜ SİNYAL: {alert['symbol']} (${volume_24h/1000000:.1f}M) - {alert['signal_type']}")
                except Exception as e:
                    logging.error(f"Email gönderme hatası: {e}")
        
        self.active_signals = new_signals
        logging.info(f"✅ Tarama bitti. {total_checked} kontrol, {volume_filtered} düşük hacim, {len(new_signals)} güçlü sinyal")

# Monitor instance
gateio_futures_monitor = GateioFuturesMonitor()

# ------------------ SCHEDULER ------------------
scheduler = BackgroundScheduler()
scheduler.add_job(
    gateio_futures_monitor.scan_futures_market, 
    'interval', 
    minutes=3,
    id='futures_scan'
)
scheduler.start()

# İlk tarama
threading.Timer(15.0, gateio_futures_monitor.scan_futures_market).start()

# ------------------ ROUTES ------------------
@app.route('/')
def index():
    return render_template('futures_dashboard.html')

@app.route('/api/signals')
def get_signals():
    return jsonify(gateio_futures_monitor.active_signals)

@app.route('/api/market_overview')
def market_overview():
    tickers = gateio_futures_monitor.get_futures_tickers()
    
    safe_tickers = []
    for t in tickers:
        try:
            change_pct = gateio_futures_monitor.safe_convert(t.get('change_percentage'))
            volume_24h = gateio_futures_monitor.safe_convert(t.get('volume_24h'))
            contract = t.get('contract', '')
            
            if contract:
                safe_tickers.append({
                    'contract': contract,
                    'change_percentage': change_pct,
                    'volume_24h': volume_24h
                })
        except:
            continue
    
    top_gainers = sorted(safe_tickers, key=lambda x: x['change_percentage'], reverse=True)[:10]
    top_losers = sorted(safe_tickers, key=lambda x: x['change_percentage'])[:10]
    volume_leaders = sorted(safe_tickers, key=lambda x: x['volume_24h'], reverse=True)[:10]
    
    return jsonify({
        'top_gainers': [{'symbol': t['contract'], 'priceChangePercent': t['change_percentage']} for t in top_gainers],
        'top_losers': [{'symbol': t['contract'], 'priceChangePercent': t['change_percentage']} for t in top_losers],
        'volume_leaders': [{'symbol': t['contract'], 'quoteVolume': t['volume_24h']} for t in volume_leaders],
        'total_symbols': len(safe_tickers)
    })

@app.route('/test_email')
def test_email():
    test_alert = {
        'symbol': 'BTCUSDT',
        'price': 45234.56,
        'change_percent': 12.5,
        'signal_type': 'BREAKOUT',
        'description': 'Test sinyali - Güçlü yükseliş kırılımı!',
        'rsi': 75.4,
        'volume_spike': 6.8,
        'volume_24h': 2560000000,
        'timestamp': datetime.now().isoformat(),
        'direction': 'LONG',
        'entry_price': 45234.56,
        'tp1': 46591.80,
        'tp2': 47949.04,
        'tp3': 49306.28,
        'stop_loss': 44103.19,
        'risk_reward': '1:2.4',
        'confidence': 'HIGH'
    }
    
    email_service.send_futures_alert(test_alert)
    return jsonify({"message": "Test email gönderildi!"})

@app.route('/system_status')
def system_status():
    return jsonify({
        "system": "Gate.io Futures Monitor v2.0",
        "keepalive_active": keep_alive_service.is_running,
        "email_configured": bool(email_service.sender_email and email_service.sender_password),
        "scanner_active": scheduler.running,
        "scan_interval": "5 dakika",
        "active_signals_count": len(gateio_futures_monitor.active_signals),
        "volume_filter": "1M USD minimum",
        "data_source": "Gate.io Futures API",
        "contracts_count": len(gateio_futures_monitor.futures_contracts)
    })

@app.route('/keepalive')
def keepalive_endpoint():
    return {
        'status': 'alive',
        'timestamp': time.time(),
        'system': 'Gate.io Futures Active',
        'signals': len(gateio_futures_monitor.active_signals)
    }, 200

@app.route('/manual_scan')
def manual_scan():
    try:
        gateio_futures_monitor.scan_futures_market()
        return jsonify({
            "message": "Manuel tarama başlatıldı",
            "active_signals": len(gateio_futures_monitor.active_signals)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))