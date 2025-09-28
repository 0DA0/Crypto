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
from collections import defaultdict, deque

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

# ------------------ SIMPLE RSI ANALYZER ------------------
class SimpleRSIAnalyzer:
    def __init__(self):
        self.price_history = defaultdict(lambda: deque(maxlen=30))  # 30 fiyat yeterli RSI için
        
    def add_price_data(self, symbol, price):
        """Fiyat verisi ekle"""
        try:
            self.price_history[symbol].append(float(price))
        except:
            pass
    
    def calculate_rsi(self, symbol, period=14):
        """RSI hesapla"""
        try:
            prices = list(self.price_history[symbol])
            if len(prices) < period + 1:
                return None
                
            # Fiyat değişimleri
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            
            # Kazanç ve kayıplar
            gains = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            
            # Ortalamalar
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            
            if avg_loss == 0:
                return 100
            
            # RSI hesaplama
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi
        except Exception as e:
            logging.error(f"RSI hesaplama hatası {symbol}: {e}")
            return None
    
    def is_rsi_extreme(self, rsi):
        """RSI extreme seviyede mi kontrol et"""
        if rsi is None:
            return False, None
            
        if rsi >= 85:
            return True, "OVERBOUGHT"
        elif rsi <= 25:
            return True, "OVERSOLD"
        else:
            return False, None

rsi_analyzer = SimpleRSIAnalyzer()

# ------------------ EMAIL ALERT SİSTEMİ ------------------
class SimpleEmailService:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.port = 587
        self.sender_email = os.getenv('GMAIL_USER')
        self.sender_password = os.getenv('GMAIL_PASSWORD')
        self.receiver_email = os.getenv('RECEIVER_EMAIL', self.sender_email)
        
    def should_send_alert(self, symbol, signal_type):
        """Cooldown kaldırıldı - Her RSI extreme sinyalini gönder"""
        return True  # Her zaman True döndür
    
    def send_rsi_alert(self, alert_data):
        """RSI sinyali email gönder"""
        if not self.sender_email or not self.sender_password:
            logging.warning("Email ayarları yapılmamış!")
            return
            
        symbol = alert_data['symbol']
        signal_type = alert_data['signal_type']
        
        if not self.should_send_alert(symbol, signal_type):
            logging.info(f"Her RSI extreme sinyal gönderiliyor: {symbol} {signal_type}")
            return
        
        # Email konu
        rsi_value = alert_data['rsi']
        if signal_type == "OVERSOLD":
            subject = f"🟢 RSI OVERSOLD: {symbol} - RSI {rsi_value:.1f} (ALIM FIRSATI)"
        else:
            subject = f"🔴 RSI OVERBOUGHT: {symbol} - RSI {rsi_value:.1f} (SATIŞ SİNYALİ)"
        
        # HTML içerik
        html_content = self._create_rsi_alert_html(alert_data)
        
        # Email gönder
        self._send_email(subject, html_content)
    
    def _create_rsi_alert_html(self, alert):
        """RSI alert HTML template"""
        
        # Renk ve emoji belirleme
        if alert['signal_type'] == "OVERSOLD":
            signal_color = "#00ff88"
            signal_emoji = "🟢"
            signal_text = "ALIM FIRSATI"
            direction = "LONG"
        else:
            signal_color = "#ff4757"
            signal_emoji = "🔴"  
            signal_text = "SATIŞ SİNYALİ"
            direction = "SHORT"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #0a0e27; color: white; }}
                .container {{ max-width: 600px; margin: 0 auto; background: #1a1d3e; border-radius: 15px; padding: 30px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .rsi-alert {{ background: {signal_color}; color: #000; padding: 20px; border-radius: 12px; text-align: center; margin: 20px 0; }}
                .symbol {{ font-size: 32px; font-weight: bold; color: #4ecdc4; margin: 15px 0; }}
                .rsi-value {{ font-size: 48px; font-weight: bold; color: {signal_color}; }}
                .signal-type {{ font-size: 24px; font-weight: bold; margin: 10px 0; }}
                .data-section {{ background: #f8f9fa; color: #333; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                .data-row {{ display: flex; justify-content: space-between; margin: 10px 0; padding: 5px 0; border-bottom: 1px solid #ddd; }}
                .btn {{ display: inline-block; padding: 15px 30px; margin: 10px; border-radius: 8px; text-decoration: none; font-weight: bold; }}
                .btn-gate {{ background: #f0b90b; color: #000; }}
                .btn-tv {{ background: #2962ff; color: white; }}
                .warning {{ background: rgba(255,193,7,0.1); padding: 15px; border-radius: 8px; margin: 20px 0; border: 1px solid #ffc107; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="symbol">{signal_emoji} {alert['symbol']}</div>
                    <div class="rsi-alert">
                        <div class="signal-type">RSI EXTREME - {signal_text}</div>
                        <div class="rsi-value">RSI {alert['rsi']:.1f}</div>
                    </div>
                </div>
                
                <div class="data-section">
                    <h3>📊 MARKET DATA</h3>
                    <div class="data-row">
                        <span><strong>Coin:</strong></span>
                        <span>{alert['symbol']}</span>
                    </div>
                    <div class="data-row">
                        <span><strong>Fiyat:</strong></span>
                        <span>${alert['price']:.4f}</span>
                    </div>
                    <div class="data-row">
                        <span><strong>RSI Seviyesi:</strong></span>
                        <span style="color: {signal_color}; font-weight: bold;">{alert['rsi']:.2f}</span>
                    </div>
                    <div class="data-row">
                        <span><strong>24h Değişim:</strong></span>
                        <span>{alert['change_24h']:.2f}%</span>
                    </div>
                    <div class="data-row">
                        <span><strong>24h Hacim:</strong></span>
                        <span>${alert['volume_24h']/1000000:.1f}M</span>
                    </div>
                    <div class="data-row">
                        <span><strong>Sinyal Zamanı:</strong></span>
                        <span>{datetime.fromisoformat(alert['timestamp']).strftime('%H:%M:%S')}</span>
                    </div>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://www.gate.io/futures_trade/{alert['symbol']}" class="btn btn-gate">
                        🚀 Gate.io'da Aç
                    </a>
                    <a href="https://www.tradingview.com/chart/?symbol=GATEIO:{alert['symbol']}" class="btn btn-tv">
                        📈 TradingView'da Gör
                    </a>
                </div>
                
                <div class="data-section">
                    <h3>🎯 RSI ANALİZİ</h3>
                    <p><strong>Sinyal Türü:</strong> {alert['signal_description']}</p>
                    <p><strong>RSI Seviyesi:</strong> {alert['rsi']:.2f} ({"Extreme Oversold" if alert['signal_type'] == 'OVERSOLD' else "Extreme Overbought"})</p>
                    <p><strong>Önerilen Yön:</strong> {direction}</p>
                    <p><strong>Güvenilirlik:</strong> Yüksek (RSI extreme seviyelerde)</p>
                    <p><strong>RSI Hesaplama:</strong> 1 dakikalık mumlar (hassas)</p>
                </div>
                
                <div class="warning">
                    <h3>⚠️ ÖNEMLİ UYARI</h3>
                    <p><strong>RSI Extreme Sinyali:</strong></p>
                    <p>• RSI {alert['rsi']:.1f} seviyesinde - {"Aşırı satılmış" if alert['signal_type'] == 'OVERSOLD' else "Aşırı alınmış"} bölge</p>
                    <p>• {"Güçlü geri dönüş potansiyeli" if alert['signal_type'] == 'OVERSOLD' else "Düzeltme beklentisi"}</p>
                    <p>• 1 dakikalık RSI ile hassas hesaplama</p>
                    <p>• Cooldown yok - Her extreme sinyal bildirilir</p>
                    <p>• Risk yönetimi uygulayın</p>
                    <p>• Bu sadece teknik analiz - yatırım tavsiyesi değil</p>
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
                
            logging.info(f"✅ RSI Alert email sent: {subject}")
            
        except Exception as e:
            logging.error(f"❌ Email gönderme hatası: {e}")

email_service = SimpleEmailService()

# ------------------ FUTURES MONITOR ------------------
class SimpleFuturesMonitor:
    def __init__(self):
        self.active_signals = []
        self.gateio_base_url = "https://api.gateio.ws/api/v4"
        self.futures_contracts = set()
        
    def safe_float(self, value, default=0.0):
        """Güvenli float dönüştürme"""
        try:
            if value is None or value == '':
                return default
            return float(str(value).strip())
        except:
            return default
        
    def get_futures_contracts(self):
        """Futures kontratlarını al"""
        try:
            response = requests.get(f"{self.gateio_base_url}/futures/usdt/contracts", timeout=15)
            if response.status_code == 200:
                contracts = response.json()
                # Sadece aktif USDT kontratları
                self.futures_contracts = {
                    c.get('name', '') for c in contracts 
                    if c.get('in_delisting') == False and c.get('name', '').endswith('_USDT')
                }
                logging.info(f"✅ {len(self.futures_contracts)} futures kontratı yüklendi")
                return True
            else:
                logging.error(f"Kontrat API hatası: {response.status_code}")
                return False
        except Exception as e:
            logging.error(f"Kontrat alma hatası: {e}")
            return False
    
    def get_futures_tickers(self):
        """Futures ticker verilerini al"""
        try:
            response = requests.get(f"{self.gateio_base_url}/futures/usdt/tickers", timeout=15)
            if response.status_code == 200:
                data = response.json()
                # Sadece bilinen kontratları filtrele
                filtered_data = [
                    t for t in data 
                    if t.get('contract', '') in self.futures_contracts
                ]
                logging.info(f"✅ {len(filtered_data)} ticker verisi alındı")
                return filtered_data
            else:
                logging.error(f"Ticker API hatası: {response.status_code}")
                return []
        except Exception as e:
            logging.error(f"Ticker alma hatası: {e}")
            return []
    
    def get_candlestick_data(self, contract, limit=20):
        """Mum verilerini al (RSI için) - 1 dakikalık mumlar"""
        try:
            params = {
                'contract': contract,
                'interval': '1m',  # 1 dakikalık mumlar
                'limit': limit
            }
            response = requests.get(
                f"{self.gateio_base_url}/futures/usdt/candlesticks", 
                params=params, 
                timeout=15
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logging.error(f"Candlestick data hatası {contract}: {e}")
            return []
    
    def analyze_rsi_signals(self):
        """RSI sinyallerini analiz et"""
        logging.info("🔍 RSI Extreme sinyalleri taranıyor...")
        
        # Kontratları güncelle
        if not self.get_futures_contracts():
            logging.error("Kontratlar alınamadı, taramaya devam edilemiyor")
            return
        
        # Ticker verilerini al
        tickers = self.get_futures_tickers()
        if not tickers:
            logging.error("Ticker verileri alınamadı")
            return
        
        new_signals = []
        total_checked = 0
        volume_filtered = 0
        rsi_signals_found = 0
        
        # Volume'a göre sırala (büyükten küçüğe)
        tickers.sort(key=lambda x: self.safe_float(x.get('volume_24h', 0)), reverse=True)
        
        for ticker in tickers:
            total_checked += 1
            
            contract = ticker.get('contract', '')
            volume_24h = self.safe_float(ticker.get('volume_24h'))
            price = self.safe_float(ticker.get('last'))
            change_24h = self.safe_float(ticker.get('change_percentage'))
            
            # Volume filtresi - Minimum 1M USD
            if volume_24h < 1000000:
                volume_filtered += 1
                continue
                
            # Fiyat kontrolü
            if price <= 0:
                continue
            
            # Mum verilerini al
            candles = self.get_candlestick_data(contract, limit=20)
            if len(candles) < 15:  # Yeterli veri yok
                continue
            
            # Fiyat verilerini RSI analyzer'a ekle
            for candle in candles:
                try:
                    if len(candle) >= 5:
                        close_price = self.safe_float(candle[4])  # Close price
                        if close_price > 0:
                            rsi_analyzer.add_price_data(contract, close_price)
                except:
                    continue
            
            # RSI hesapla
            rsi_value = rsi_analyzer.calculate_rsi(contract)
            if rsi_value is None:
                continue
            
            # RSI extreme kontrolü
            is_extreme, signal_type = rsi_analyzer.is_rsi_extreme(rsi_value)
            
            if is_extreme:
                rsi_signals_found += 1
                
                # Sinyal detayları
                signal_data = {
                    'symbol': contract.replace('_USDT', 'USDT'),
                    'price': price,
                    'rsi': rsi_value,
                    'signal_type': signal_type,
                    'change_24h': change_24h,
                    'volume_24h': volume_24h,
                    'timestamp': datetime.now().isoformat(),
                    'signal_description': f"RSI {rsi_value:.1f} - {'Aşırı satılmış, güçlü alım fırsatı' if signal_type == 'OVERSOLD' else 'Aşırı alınmış, düzeltme beklentisi'}"
                }
                
                new_signals.append(signal_data)
                
                # Email gönder (cooldown yok, her sinyal gönderilir)
                try:
                    email_service.send_rsi_alert(signal_data)
                    logging.info(f"🎯 RSI EXTREME SIGNAL: {signal_data['symbol']} - RSI {rsi_value:.1f} ({signal_type}) - Volume: ${volume_24h/1000000:.1f}M")
                except Exception as e:
                    logging.error(f"Email gönderme hatası: {e}")
        
        # Sonuçları kaydet
        self.active_signals = new_signals
        
        logging.info(f"✅ RSI tarama tamamlandı: {total_checked} kontrol, {volume_filtered} düşük hacim, {rsi_signals_found} RSI EXTREME sinyal")
        
        if rsi_signals_found == 0:
            logging.info("ℹ️ RSI extreme seviyesinde sinyal bulunamadı (RSI ≤25 veya ≥85)")

# Monitor instance
futures_monitor = SimpleFuturesMonitor()

# ------------------ SCHEDULER ------------------
scheduler = BackgroundScheduler()
scheduler.add_job(
    futures_monitor.analyze_rsi_signals, 
    'interval', 
    minutes=2,  # 2 dakikada bir tarama (daha sık)
    id='rsi_scan'
)
scheduler.start()

# İlk taramayı başlat
threading.Timer(20.0, futures_monitor.analyze_rsi_signals).start()

# ------------------ ROUTES ------------------
@app.route('/')
def index():
    return render_template('futures_dashboard.html')

@app.route('/api/signals')
def get_signals():
    """Aktif RSI sinyalleri"""
    return jsonify(futures_monitor.active_signals)

@app.route('/api/market_overview')
def market_overview():
    """Piyasa genel görünümü"""
    tickers = futures_monitor.get_futures_tickers()
    
    safe_tickers = []
    for t in tickers:
        try:
            change_pct = futures_monitor.safe_float(t.get('change_percentage'))
            volume_24h = futures_monitor.safe_float(t.get('volume_24h'))
            contract = t.get('contract', '')
            
            if contract and volume_24h >= 1000000:  # 1M+ volume
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
    """Test email gönder"""
    test_alert = {
        'symbol': 'BTCUSDT',
        'price': 45234.56,
        'rsi': 23.5,
        'signal_type': 'OVERSOLD',
        'change_24h': -8.2,
        'volume_24h': 2500000000,
        'timestamp': datetime.now().isoformat(),
        'signal_description': 'RSI 23.5 - Aşırı satılmış, güçlü alım fırsatı'
    }
    
    email_service.send_rsi_alert(test_alert)
    return jsonify({
        "message": "RSI test email gönderildi!",
        "test_data": test_alert
    })

@app.route('/system_status')
def system_status():
    """Sistem durumu"""
    return jsonify({
        "system": "Simple RSI Extreme Signal Monitor",
        "version": "2.0 - No Cooldown + 1min RSI",
        "keepalive_active": keep_alive_service.is_running,
        "email_configured": bool(email_service.sender_email and email_service.sender_password),
        "scanner_active": scheduler.running,
        "scan_interval": "2 minutes",
        "active_rsi_signals": len(futures_monitor.active_signals),
        "futures_contracts_loaded": len(futures_monitor.futures_contracts),
        "criteria": {
            "rsi_oversold": "≤ 25 (Extreme)",
            "rsi_overbought": "≥ 85 (Extreme)", 
            "minimum_volume": "1M USD",
            "email_cooldown": "YOK - Her sinyal gönderilir",
            "candlestick_interval": "1 minute"
        },
        "data_source": "Gate.io Futures API"
    })

@app.route('/keepalive')
def keepalive_endpoint():
    return {
        'status': 'alive',
        'timestamp': time.time(),
        'system': 'Simple RSI Monitor Active',
        'rsi_signals': len(futures_monitor.active_signals)
    }, 200

@app.route('/manual_scan')
def manual_scan():
    """Manuel RSI taraması"""
    try:
        logging.info("🔍 Manuel RSI taraması başlatıldı...")
        futures_monitor.analyze_rsi_signals()
        return jsonify({
            "message": "Manuel RSI taraması tamamlandı",
            "rsi_signals_found": len(futures_monitor.active_signals),
            "signals": futures_monitor.active_signals,
            "scan_time": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Manuel tarama sırasında hata oluştu"
        }), 500

@app.route('/rsi_debug')
def rsi_debug():
    """RSI debug bilgileri"""
    try:
        tickers = futures_monitor.get_futures_tickers()
        if not tickers:
            return jsonify({"error": "Ticker verileri alınamadı"})
        
        # Volume'a göre sırala
        tickers.sort(key=lambda x: futures_monitor.safe_float(x.get('volume_24h', 0)), reverse=True)
        
        debug_info = []
        rsi_values = []
        
        # İlk 20 coin için debug
        for ticker in tickers[:20]:
            contract = ticker.get('contract', '')
            volume_24h = futures_monitor.safe_float(ticker.get('volume_24h'))
            price = futures_monitor.safe_float(ticker.get('last'))
            
            if volume_24h >= 1000000:  # 1M+ volume
                # RSI hesapla
                candles = futures_monitor.get_candlestick_data(contract, limit=20)
                if len(candles) >= 15:
                    for candle in candles:
                        try:
                            close_price = futures_monitor.safe_float(candle[4])
                            if close_price > 0:
                                rsi_analyzer.add_price_data(contract, close_price)
                        except:
                            continue
                    
                    rsi_value = rsi_analyzer.calculate_rsi(contract)
                    is_extreme, signal_type = rsi_analyzer.is_rsi_extreme(rsi_value) if rsi_value else (False, None)
                    
                    debug_info.append({
                        'contract': contract,
                        'volume_24h_usd': volume_24h,
                        'price': price,
                        'rsi': rsi_value,
                        'is_extreme': is_extreme,
                        'signal_type': signal_type,
                        'candles_count': len(candles)
                    })
                    
                    if rsi_value:
                        rsi_values.append(rsi_value)
        
        return jsonify({
            "total_tickers": len(tickers),
            "volume_threshold": "1M USD",
            "rsi_extreme_thresholds": "≤25 or ≥85",
            "candlestick_interval": "1 minute",
            "cooldown": "NONE - Every signal sent",
            "top_20_analysis": debug_info,
            "rsi_stats": {
                "count": len(rsi_values),
                "min": min(rsi_values) if rsi_values else None,
                "max": max(rsi_values) if rsi_values else None,
                "avg": sum(rsi_values) / len(rsi_values) if rsi_values else None
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)