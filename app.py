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

# ------------------ BALANCED QUALITY ANALYZER ------------------
class BalancedQualityAnalyzer:
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

    def calculate_momentum(self, symbol, period=10):
        """Momentum hesaplama"""
        try:
            prices = list(self.price_history[symbol])
            if len(prices) < period + 1:
                return 0
            
            current_price = prices[-1]
            past_price = prices[-(period+1)]
            momentum = ((current_price - past_price) / past_price) * 100
            return momentum
        except:
            return 0

    def calculate_confidence_score(self, rsi, volume_spike, change_percent, breakout_percent, momentum):
        """GÜVEN SKORU HESAPLAMA"""
        try:
            confidence_factors = []
            total_score = 0
            
            # RSI Güven Faktörü (25 puan)
            if rsi:
                if rsi <= 30 or rsi >= 70:  # Strong levels
                    rsi_score = 25
                    confidence_factors.append(f"RSI Strong Level ({rsi:.1f}) (+25)")
                elif rsi <= 35 or rsi >= 65:  # Moderate levels
                    rsi_score = 15
                    confidence_factors.append(f"RSI Moderate Level ({rsi:.1f}) (+15)")
                elif 40 <= rsi <= 60:  # Neutral momentum
                    if abs(momentum) > 3:
                        rsi_score = 10
                        confidence_factors.append(f"RSI Neutral + Strong Momentum ({momentum:.1f}%) (+10)")
                    else:
                        rsi_score = 0
                else:
                    rsi_score = 0
                total_score += rsi_score
            
            # Volume Güven Faktörü (25 puan)
            if volume_spike:
                if volume_spike >= 3.0:  # Güçlü
                    volume_score = 25
                    confidence_factors.append(f"Strong Volume Spike {volume_spike:.1f}x (+25)")
                elif volume_spike >= 2.0:  # Orta
                    volume_score = 18
                    confidence_factors.append(f"Moderate Volume Spike {volume_spike:.1f}x (+18)")
                elif volume_spike >= 1.5:  # Hafif
                    volume_score = 10
                    confidence_factors.append(f"Light Volume Spike {volume_spike:.1f}x (+10)")
                else:
                    volume_score = 0
                total_score += volume_score
            
            # Fiyat Momentum Faktörü (20 puan)
            if abs(change_percent) >= 5:  # Güçlü hareket
                momentum_score = 20
                confidence_factors.append(f"Strong Price Movement {abs(change_percent):.1f}% (+20)")
            elif abs(change_percent) >= 3:  # Orta hareket
                momentum_score = 12
                confidence_factors.append(f"Moderate Price Movement {abs(change_percent):.1f}% (+12)")
            elif abs(change_percent) >= 2:  # Hafif hareket
                momentum_score = 8
                confidence_factors.append(f"Light Price Movement {abs(change_percent):.1f}% (+8)")
            else:
                momentum_score = 0
            total_score += momentum_score
            
            # Breakout Güven Faktörü (15 puan)
            if abs(breakout_percent) >= 2.5:  # Güçlü kırılım
                breakout_score = 15
                confidence_factors.append(f"Strong Breakout {abs(breakout_percent):.1f}% (+15)")
            elif abs(breakout_percent) >= 1.5:  # Orta kırılım
                breakout_score = 10
                confidence_factors.append(f"Moderate Breakout {abs(breakout_percent):.1f}% (+10)")
            elif abs(breakout_percent) >= 1.0:  # Hafif kırılım
                breakout_score = 6
                confidence_factors.append(f"Light Breakout {abs(breakout_percent):.1f}% (+6)")
            else:
                breakout_score = 0
            total_score += breakout_score
            
            # Momentum Güven Faktörü (15 puan)
            if abs(momentum) >= 4:  # Güçlü momentum
                mom_score = 15
                confidence_factors.append(f"Strong Momentum {abs(momentum):.1f}% (+15)")
            elif abs(momentum) >= 2.5:  # Orta momentum
                mom_score = 10
                confidence_factors.append(f"Moderate Momentum {abs(momentum):.1f}% (+10)")
            elif abs(momentum) >= 1.5:  # Hafif momentum
                mom_score = 5
                confidence_factors.append(f"Light Momentum {abs(momentum):.1f}% (+5)")
            else:
                mom_score = 0
            total_score += mom_score
            
            # Final confidence calculation
            confidence_percentage = min(total_score, 100)
            
            # Confidence level belirleme
            if confidence_percentage >= 75:
                confidence_level = "VERY HIGH"
                confidence_emoji = "🔥"
            elif confidence_percentage >= 60:
                confidence_level = "HIGH" 
                confidence_emoji = "⭐"
            elif confidence_percentage >= 45:
                confidence_level = "MEDIUM"
                confidence_emoji = "📊"
            else:
                confidence_level = "LOW"
                confidence_emoji = "⚠️"
            
            return confidence_percentage, confidence_level, confidence_emoji, confidence_factors
            
        except:
            return 30, "LOW", "⚠️", ["Error in calculation"]

    def is_quality_signal(self, rsi, volume_spike, change_percent, breakout_percent, momentum):
        """DENGELI KALİTE SİNYAL KONTROLÜ - Günde 20-30 sinyal hedefi"""
        try:
            confidence_score, confidence_level, confidence_emoji, factors = self.calculate_confidence_score(
                rsi, volume_spike, change_percent, breakout_percent, momentum
            )
            
            # DENGELI EŞIK - Günde 20-30 sinyal için uygun
            MIN_CONFIDENCE = 45  # %45 minimum güven (önceden 70)
            
            quality_conditions = 0
            signal_reasons = []
            
            # Condition 1: Strong RSI + Any volume
            if rsi and ((rsi <= 30 and volume_spike >= 1.5) or (rsi >= 70 and volume_spike >= 1.5)):
                quality_conditions += 1
                signal_reasons.append(f"Strong RSI ({rsi:.1f}) + Volume ({volume_spike:.1f}x)")
            
            # Condition 2: Moderate RSI + Strong Volume
            elif rsi and ((rsi <= 35 and volume_spike >= 2.0) or (rsi >= 65 and volume_spike >= 2.0)):
                quality_conditions += 1
                signal_reasons.append(f"Moderate RSI + Strong Volume")
            
            # Condition 3: Breakout + Volume
            if abs(breakout_percent) >= 1.5 and volume_spike >= 1.5:
                quality_conditions += 1
                signal_reasons.append(f"Breakout ({abs(breakout_percent):.1f}%) + Volume")
            
            # Condition 4: Strong Price Movement  
            if abs(change_percent) >= 4 and volume_spike >= 1.3:
                quality_conditions += 1
                signal_reasons.append(f"Strong Movement ({change_percent:.1f}%)")
            
            # Condition 5: Strong Momentum + RSI
            if abs(momentum) >= 3 and rsi and (45 <= rsi <= 55):
                quality_conditions += 1
                signal_reasons.append(f"Strong Momentum + Neutral RSI")
            
            # Condition 6: Multiple Moderate Factors
            moderate_factors = 0
            if rsi and (rsi <= 35 or rsi >= 65): moderate_factors += 1
            if volume_spike and volume_spike >= 1.8: moderate_factors += 1  
            if abs(change_percent) >= 2.5: moderate_factors += 1
            if abs(breakout_percent) >= 1.0: moderate_factors += 1
            if abs(momentum) >= 2: moderate_factors += 1
            
            if moderate_factors >= 2:
                quality_conditions += 1
                signal_reasons.append(f"Multiple Factors ({moderate_factors}/5)")
            
            # FINAL DECISION
            is_quality = (confidence_score >= MIN_CONFIDENCE and quality_conditions >= 1)
            
            if is_quality:
                # Sinyal türü belirleme
                if rsi and rsi <= 30:
                    signal_type = "RSI_OVERSOLD"
                elif rsi and rsi >= 70:
                    signal_type = "RSI_OVERBOUGHT"
                elif abs(breakout_percent) >= 2:
                    signal_type = "BREAKOUT"
                elif volume_spike >= 2.5:
                    signal_type = "VOLUME_SPIKE"
                elif abs(momentum) >= 3:
                    signal_type = "MOMENTUM"
                else:
                    signal_type = "MULTI_FACTOR"
                    
                description = f"{confidence_emoji} Quality Signal: " + " + ".join(signal_reasons)
                
                return True, signal_type, description, confidence_score, confidence_level, factors
            
            return False, None, None, confidence_score, confidence_level, factors
            
        except Exception as e:
            return False, None, f"Analysis error: {str(e)}", 0, "ERROR", []

    def calculate_trading_levels(self, current_price, signal_type, confidence_score):
        """Trading seviyeleri hesaplama"""
        try:
            # Confidence'a göre multiplier ayarla
            confidence_multiplier = 1.0 + (confidence_score - 50) / 200  # Hafif bonus
            
            base_configs = {
                'RSI_OVERSOLD': {
                    'direction': 'LONG',
                    'tp_multipliers': [1.018, 1.04, 1.07],
                    'sl_multiplier': 0.985,
                    'risk_reward': '1:2.2'
                },
                'RSI_OVERBOUGHT': {
                    'direction': 'SHORT',
                    'tp_multipliers': [0.982, 0.96, 0.93],
                    'sl_multiplier': 1.015,
                    'risk_reward': '1:2.2'
                },
                'VOLUME_SPIKE': {
                    'direction': 'LONG',
                    'tp_multipliers': [1.02, 1.045, 1.08],
                    'sl_multiplier': 0.98,
                    'risk_reward': '1:2.4'
                },
                'BREAKOUT': {
                    'direction': 'LONG',
                    'tp_multipliers': [1.025, 1.05, 1.085],
                    'sl_multiplier': 0.975,
                    'risk_reward': '1:2.6'
                },
                'MOMENTUM': {
                    'direction': 'LONG',
                    'tp_multipliers': [1.02, 1.042, 1.075],
                    'sl_multiplier': 0.982,
                    'risk_reward': '1:2.3'
                },
                'MULTI_FACTOR': {
                    'direction': 'LONG',
                    'tp_multipliers': [1.022, 1.048, 1.082],
                    'sl_multiplier': 0.978,
                    'risk_reward': '1:2.5'
                }
            }
            
            config = base_configs.get(signal_type, base_configs['MULTI_FACTOR'])
            
            # Confidence'a göre hafif optimizasyon
            optimized_tps = [
                current_price * (tp_mult * confidence_multiplier)
                for tp_mult in config['tp_multipliers']
            ]
            
            return {
                'direction': config['direction'],
                'entry_price': current_price,
                'tp1': optimized_tps[0],
                'tp2': optimized_tps[1],
                'tp3': optimized_tps[2],
                'stop_loss': current_price * config['sl_multiplier'],
                'risk_reward': config['risk_reward']
            }
            
        except:
            return {
                'direction': 'LONG',
                'entry_price': current_price,
                'tp1': current_price * 1.02,
                'tp2': current_price * 1.04,
                'tp3': current_price * 1.07,
                'stop_loss': current_price * 0.98,
                'risk_reward': '1:2'
            }

analyzer = BalancedQualityAnalyzer()

# ------------------ IMPROVED EMAIL ALERT ------------------
class ImprovedEmailAlertService:
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
        
        subject = f"📊 {alert_data['confidence_emoji']} {alert_data['direction']} {symbol} - {alert_data['confidence_level']} ({alert_data['confidence_score']}%)"
        html_content = self._create_alert_html(alert_data)
        
        self._send_email(subject, html_content)
    
    def _create_alert_html(self, alert):
        direction_emoji = "📈" if alert['direction'] == 'LONG' else "📉"
        confidence_color = "#00ff88" if alert['confidence_score'] >= 75 else "#ffd700" if alert['confidence_score'] >= 60 else "#ff8c42"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #0a0e27; color: white; }}
                .container {{ max-width: 600px; margin: 0 auto; background: linear-gradient(145deg, #1a1d3e, #252847); border-radius: 15px; padding: 30px; }}
                .header {{ text-align: center; margin-bottom: 25px; }}
                .symbol {{ font-size: 26px; font-weight: bold; color: #4ecdc4; margin: 10px 0; }}
                .confidence-section {{ background: rgba(255,255,255,0.05); padding: 20px; border-radius: 12px; margin: 20px 0; border-left: 4px solid {confidence_color}; }}
                .confidence-score {{ font-size: 24px; font-weight: bold; color: {confidence_color}; text-align: center; margin-bottom: 15px; }}
                .confidence-factors {{ margin-top: 10px; }}
                .factor-item {{ background: rgba(255,255,255,0.08); padding: 6px 10px; margin: 4px 0; border-radius: 6px; font-size: 0.85rem; }}
                .levels {{ background: #f8f9fa; color: #333; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                .level-row {{ display: flex; justify-content: space-between; margin: 6px 0; padding: 4px 0; }}
                .btn {{ display: inline-block; padding: 12px 24px; margin: 8px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.3s ease; }}
                .btn-gateio {{ background: linear-gradient(45deg, #f0b90b, #ffd700); color: #000; }}
                .btn-tradingview {{ background: linear-gradient(45deg, #2962ff, #4fc3f7); color: white; }}
                .warning {{ background: rgba(255,193,7,0.1); padding: 15px; border-radius: 8px; margin: 15px 0; border: 1px solid #ffc107; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="symbol">{direction_emoji} {alert['symbol']}</div>
                    <div style="color: #4ecdc4; font-size: 1.1rem; font-weight: bold;">{alert['direction']} FUTURES SIGNAL</div>
                </div>
                
                <div class="confidence-section">
                    <div class="confidence-score">{alert['confidence_emoji']} {alert['confidence_score']}% {alert['confidence_level']}</div>
                    <div class="confidence-factors">
                        <strong>📊 Signal Analysis:</strong>
                        {'\n'.join([f'<div class="factor-item">• {factor}</div>' for factor in alert.get('confidence_factors', [])])}
                    </div>
                </div>
                
                <div class="levels">
                    <h3>💰 TRADING SETUP</h3>
                    <div class="level-row">
                        <span><strong>📌 Entry:</strong></span>
                        <span style="color: #4ecdc4; font-weight: bold;">${alert['entry_price']:.4f}</span>
                    </div>
                    <div class="level-row">
                        <span><strong>🎯 TP1:</strong></span>
                        <span style="color: #2ed573; font-weight: bold;">${alert['tp1']:.4f} (+{((alert['tp1']/alert['entry_price']-1)*100):.1f}%)</span>
                    </div>
                    <div class="level-row">
                        <span><strong>🎯 TP2:</strong></span>
                        <span style="color: #2ed573; font-weight: bold;">${alert['tp2']:.4f} (+{((alert['tp2']/alert['entry_price']-1)*100):.1f}%)</span>
                    </div>
                    <div class="level-row">
                        <span><strong>🎯 TP3:</strong></span>
                        <span style="color: #2ed573; font-weight: bold;">${alert['tp3']:.4f} (+{((alert['tp3']/alert['entry_price']-1)*100):.1f}%)</span>
                    </div>
                    <div class="level-row">
                        <span><strong>🛡️ Stop Loss:</strong></span>
                        <span style="color: #ff4757; font-weight: bold;">${alert['stop_loss']:.4f} ({((alert['stop_loss']/alert['entry_price']-1)*100):.1f}%)</span>
                    </div>
                    <div class="level-row">
                        <span><strong>⚡ Risk/Reward:</strong></span>
                        <span style="color: #ffa502; font-weight: bold;">{alert['risk_reward']}</span>
                    </div>
                </div>
                
                <div style="text-align: center; margin: 25px 0;">
                    <a href="https://www.gate.io/futures_trade/{alert['symbol']}" class="btn btn-gateio">
                        🚀 Gate.io Futures
                    </a>
                    <a href="https://www.tradingview.com/chart/?symbol=GATEIO:{alert['symbol']}" class="btn btn-tradingview">
                        📈 TradingView
                    </a>
                </div>
                
                <div class="levels">
                    <h3>📊 TECHNICAL DATA</h3>
                    <div class="level-row">
                        <span>Signal Type:</span>
                        <span style="font-weight: bold;">{alert['signal_type'].replace('_', ' ')}</span>
                    </div>
                    <div class="level-row">
                        <span>RSI:</span>
                        <span style="font-weight: bold;">{alert.get('rsi', 50):.1f}</span>
                    </div>
                    <div class="level-row">
                        <span>Volume Spike:</span>
                        <span style="font-weight: bold;">{alert.get('volume_spike', 1):.1f}x</span>
                    </div>
                    <div class="level-row">
                        <span>24h Change:</span>
                        <span style="font-weight: bold;">{alert.get('change_percent', 0):.2f}%</span>
                    </div>
                    <div class="level-row">
                        <span>24h Volume:</span>
                        <span style="font-weight: bold;">${alert.get('volume_24h', 0)/1000000:.1f}M</span>
                    </div>
                </div>
                
                <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin: 15px 0;">
                    <h4>🎯 Signal Description:</h4>
                    <p>{alert['description']}</p>
                </div>
                
                <div class="warning">
                    <strong>⚠️ TRADING UYARISI:</strong> Bu sinyal %{alert['confidence_score']} güven seviyesine sahiptir. 
                    Risk yönetimi uygulayın ve stop-loss kullanın!
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

email_service = ImprovedEmailAlertService()

# ------------------ BALANCED FUTURES MONITOR ------------------
class BalancedFuturesMonitor:
    def __init__(self):
        self.active_signals = []
        self.gateio_base_url = "https://api.gateio.ws/api/v4"
        self.futures_contracts = set()
        self.hourly_signal_count = defaultdict(int)
        self.last_hour_reset = datetime.now().hour
        
    def safe_convert(self, value, default=0.0):
        """Ultra güvenli dönüşüm"""
        try:
            if value is None or value == '' or value == '0':
                return default
            return float(str(value).strip())
        except:
            return default
        
    def reset_hourly_counter(self):
        """Saatlik sayacı sıfırla"""
        current_hour = datetime.now().hour
        if current_hour != self.last_hour_reset:
            self.hourly_signal_count.clear()
            self.last_hour_reset = current_hour
            logging.info(f"🕐 Saatlik sinyal sayacı sıfırlandı: {current_hour}:00")
        
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
    
    def get_kline_data(self, contract, limit=30):
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
        """DENGELI ticker analizi"""
        try:
            contract = ticker.get('contract', '')
            if not contract or not contract.endswith('_USDT') or contract not in self.futures_contracts:
                return None
                
            # Güvenli veri çıkarma
            volume_24h = self.safe_convert(ticker.get('volume_24h'))
            price = self.safe_convert(ticker.get('last'))
            change_percent = self.safe_convert(ticker.get('change_percentage'))
            
            # DENGELI HACIM FİLTRESİ - Günde 20-30 sinyal için uygun
            MIN_VOLUME = 800000  # 800K USD (önceden 2M)
            if volume_24h < MIN_VOLUME or price <= 0:
                return None
            
            # Kline verisi al
            klines = self.get_kline_data(contract, limit=30)
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
            momentum = analyzer.calculate_momentum(contract)
            
            # DENGELI KALİTE SINYAL KONTROLÜ
            is_quality, signal_type, description, confidence_score, confidence_level, confidence_factors = analyzer.is_quality_signal(
                rsi, volume_spike, change_percent, breakout_percent, momentum
            )
            
            if not is_quality:
                return None
            
            # Trading seviyelerini hesapla
            trading_levels = analyzer.calculate_trading_levels(price, signal_type, confidence_score)
            
            return {
                'symbol': contract.replace('_USDT', 'USDT'),
                'price': price,
                'change_percent': change_percent,
                'signal_type': signal_type,
                'description': description,
                'rsi': rsi if rsi else 50,
                'volume_spike': volume_spike if volume_spike else 1,
                'volume_24h': volume_24h,
                'momentum': momentum,
                'confidence_score': confidence_score,
                'confidence_level': confidence_level,
                'confidence_emoji': confidence_factors[0] if confidence_factors else "📊",
                'confidence_factors': confidence_factors,
                'timestamp': datetime.now().isoformat(),
                'direction': trading_levels['direction'],
                'entry_price': trading_levels['entry_price'],
                'tp1': trading_levels['tp1'],
                'tp2': trading_levels['tp2'],
                'tp3': trading_levels['tp3'],
                'stop_loss': trading_levels['stop_loss'],
                'risk_reward': trading_levels['risk_reward']
            }
            
        except Exception as e:
            return None
    
    def scan_futures_market(self):
        """DENGELI piyasa taraması - Günde 20-30 sinyal"""
        self.reset_hourly_counter()
        
        # Saatlik spam koruması - Maksimum 2-3 sinyal/saat
        MAX_HOURLY_SIGNALS = 3
        current_hour_count = self.hourly_signal_count[datetime.now().hour]
        
        if current_hour_count >= MAX_HOURLY_SIGNALS:
            logging.info(f"📊 Saatlik sinyal limiti ({MAX_HOURLY_SIGNALS}) doldu. Saat: {datetime.now().hour}:xx")
            return
        
        logging.info("📊 Dengeli Futures taraması başlıyor (Günde 20-30 sinyal hedefi)...")
        
        # Kontratları güncelle
        if not self.get_futures_contracts():
            logging.error("Kontrat listesi alınamadı")
            return
        
        # Ticker verilerini al
        tickers = self.get_futures_tickers()
        if not tickers:
            logging.error("Ticker verisi alınamadı")
            return
        
        # Volume'a göre sırala - Yüksek hacimli coinler öncelikli
        tickers.sort(key=lambda x: self.safe_convert(x.get('volume_24h', 0)), reverse=True)
        
        new_signals = []
        total_checked = 0
        volume_filtered = 0
        
        for ticker in tickers:
            total_checked += 1
            
            # DENGELI hacim kontrolü
            volume_24h = self.safe_convert(ticker.get('volume_24h'))
            if volume_24h < 800000:  # 800K USD
                volume_filtered += 1
                continue
            
            # Analiz yap
            alert = self.analyze_ticker(ticker)
            if alert:
                new_signals.append(alert)
                self.hourly_signal_count[datetime.now().hour] += 1
                
                # Email gönder
                try:
                    email_service.send_futures_alert(alert)
                    logging.info(f"📊 KALİTE SİNYAL: {alert['symbol']} (${volume_24h/1000000:.1f}M) - {alert['signal_type']} - Güven: {alert['confidence_score']}% ({alert['confidence_level']})")
                except Exception as e:
                    logging.error(f"Email gönderme hatası: {e}")
                
                # Saatlik limite ulaştık mı?
                if self.hourly_signal_count[datetime.now().hour] >= MAX_HOURLY_SIGNALS:
                    logging.info(f"🕐 Saatlik limit ({MAX_HOURLY_SIGNALS}) tamamlandı!")
                    break
        
        self.active_signals = new_signals
        logging.info(f"✅ Dengeli tarama bitti. {total_checked} kontrol, {volume_filtered} düşük hacim, {len(new_signals)} kalite sinyal")

# Monitor instance
balanced_futures_monitor = BalancedFuturesMonitor()

# ------------------ SCHEDULER - DENGELI SIKLIK ------------------
scheduler = BackgroundScheduler()
scheduler.add_job(
    balanced_futures_monitor.scan_futures_market, 
    'interval', 
    minutes=5,  # 5 dakikada bir - dengeli
    id='balanced_futures_scan'
)
scheduler.start()

# İlk tarama
threading.Timer(15.0, balanced_futures_monitor.scan_futures_market).start()

# ------------------ ROUTES ------------------
@app.route('/')
def index():
    return render_template('futures_dashboard.html')

@app.route('/api/signals')
def get_signals():
    return jsonify(balanced_futures_monitor.active_signals)

@app.route('/api/market_overview')
def market_overview():
    tickers = balanced_futures_monitor.get_futures_tickers()
    
    safe_tickers = []
    for t in tickers:
        try:
            change_pct = balanced_futures_monitor.safe_convert(t.get('change_percentage'))
            volume_24h = balanced_futures_monitor.safe_convert(t.get('volume_24h'))
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
        'change_percent': 4.2,
        'signal_type': 'RSI_OVERSOLD',
        'description': '⭐ Quality Signal: Strong RSI (28.3) + Volume (2.1x) + Light Price Movement 4.2% (+8)',
        'rsi': 28.3,
        'volume_spike': 2.1,
        'volume_24h': 1250000000,
        'momentum': 3.8,
        'confidence_score': 68,
        'confidence_level': 'HIGH',
        'confidence_emoji': '⭐',
        'confidence_factors': [
            'RSI Strong Level (28.3) (+25)',
            'Moderate Volume Spike 2.1x (+18)',
            'Moderate Price Movement 4.2% (+12)',
            'Light Breakout 1.2% (+6)',
            'Strong Momentum 3.8% (+15)'
        ],
        'timestamp': datetime.now().isoformat(),
        'direction': 'LONG',
        'entry_price': 45234.56,
        'tp1': 46049.51,
        'tp2': 47046.62,
        'tp3': 48400.18,
        'stop_loss': 44581.04,
        'risk_reward': '1:2.2'
    }
    
    email_service.send_futures_alert(test_alert)
    return jsonify({"message": "Dengeli kalite test email gönderildi!", "alert": test_alert})

@app.route('/system_status')
def system_status():
    current_hour = datetime.now().hour
    return jsonify({
        "system": "Balanced Gate.io Futures Monitor v2.5 - Dengeli Kalite",
        "keepalive_active": keep_alive_service.is_running,
        "email_configured": bool(email_service.sender_email and email_service.sender_password),
        "scanner_active": scheduler.running,
        "scan_interval": "5 dakika",
        "active_signals_count": len(balanced_futures_monitor.active_signals),
        "hourly_signal_count": f"{balanced_futures_monitor.hourly_signal_count[current_hour]}/3",
        "volume_filter": "800K USD minimum (Dengeli)",
        "data_source": "Gate.io Futures API",
        "contracts_count": len(balanced_futures_monitor.futures_contracts),
        "balanced_criteria": {
            "min_confidence": "45% (Dengeli Seçicilik)",
            "min_volume": "800K USD",
            "max_hourly_signals": "3 (Saatlik Limit)",
            "daily_target": "20-30 kalite sinyal",
            "email_cooldown": "15 dakika",
            "technical_analysis": "5-faktör weighted scoring"
        },
        "signal_distribution": {
            "target_per_day": "20-30",
            "target_per_hour": "1-3",
            "quality_focus": "Balanced confidence scoring",
            "spam_protection": "Hourly limits + email cooldown"
        }
    })

@app.route('/keepalive')
def keepalive_endpoint():
    return {
        'status': 'alive',
        'timestamp': time.time(),
        'system': 'Balanced Gate.io Futures Active',
        'signals': len(balanced_futures_monitor.active_signals),
        'hourly_count': f"{balanced_futures_monitor.hourly_signal_count[datetime.now().hour]}/3",
        'version': 'Balanced 2.5'
    }, 200

@app.route('/manual_scan')
def manual_scan():
    try:
        logging.info("📊 Manuel dengeli tarama başlatıldı...")
        balanced_futures_monitor.scan_futures_market()
        return jsonify({
            "message": "Dengeli manuel tarama tamamlandı",
            "active_signals": len(balanced_futures_monitor.active_signals),
            "hourly_signal_count": f"{balanced_futures_monitor.hourly_signal_count[datetime.now().hour]}/3",
            "signals": balanced_futures_monitor.active_signals,
            "scan_time": datetime.now().isoformat(),
            "quality": "DENGELI - Günde 20-30 hedef"
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Dengeli manuel tarama sırasında hata oluştu"
        }), 500

@app.route('/reset_hourly_limit')
def reset_hourly_limit():
    """Manuel olarak saatlik limiti sıfırla"""
    try:
        current_hour = datetime.now().hour
        old_count = balanced_futures_monitor.hourly_signal_count[current_hour]
        balanced_futures_monitor.hourly_signal_count.clear()
        
        return jsonify({
            "message": f"Saatlik limit sıfırlandı ({current_hour}:00)",
            "old_count": old_count,
            "new_count": balanced_futures_monitor.hourly_signal_count[current_hour]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/signal_stats')
def signal_stats():
    """Sinyal istatistikleri"""
    try:
        signals = balanced_futures_monitor.active_signals
        
        if not signals:
            return jsonify({
                "message": "Aktif sinyal yok",
                "stats": {}
            })
        
        # İstatistikler hesapla
        confidence_scores = [s.get('confidence_score', 0) for s in signals]
        volume_ranges = [s.get('volume_24h', 0) for s in signals]
        signal_types = [s.get('signal_type', 'UNKNOWN') for s in signals]
        
        return jsonify({
            "total_signals": len(signals),
            "avg_confidence": round(sum(confidence_scores) / len(confidence_scores), 1),
            "min_confidence": min(confidence_scores),
            "max_confidence": max(confidence_scores),
            "avg_volume": round(sum(volume_ranges) / len(volume_ranges) / 1000000, 1),
            "signal_types": {
                signal_type: signal_types.count(signal_type) 
                for signal_type in set(signal_types)
            },
            "confidence_distribution": {
                "high_75+": len([s for s in confidence_scores if s >= 75]),
                "medium_60-74": len([s for s in confidence_scores if 60 <= s < 75]),
                "moderate_45-59": len([s for s in confidence_scores if 45 <= s < 60]),
                "low_below_45": len([s for s in confidence_scores if s < 45])
            },
            "hourly_count": dict(balanced_futures_monitor.hourly_signal_count),
            "system_target": "20-30 signals/day"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("📊 Balanced Gate.io Futures Monitor v2.5 başlatılıyor...")
    print("🎯 DENGELI KALİTE SİSTEMİ:")
    print("   - Günlük hedef: 20-30 kalite sinyal")
    print("   - Saatlik limit: Maksimum 3 sinyal")
    print("   - Minimum güven: %45 (dengeli)")
    print("   - Minimum hacim: 800K USD")
    print("   - Email spam koruması: 15 dakika")
    print("   - Tarama aralığı: 5 dakika")
    print("   - 5 faktörlü confidence scoring")
    print("   - Otomatik saatlik reset")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)