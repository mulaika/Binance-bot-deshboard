import time
import pandas as pd
import numpy as np
import os
from binance.client import Client
from ta.trend import EMAIndicator
from ta.momentum import CCIIndicator
from flask import Flask, render_template_string
from dotenv import load_dotenv

# Load API keys from .env
load_dotenv()
api_key = os.getenv("API_KEY")
api_secret = os.getenv("API_SECRET")
client = Client(api_key, api_secret)

# Settings
symbols = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT']  # Add your symbols
interval = Client.KLINE_INTERVAL_5MINUTE
quantity = 10  # USDT equivalent trade size

app = Flask(__name__)
signals = {s: {'signal': 'NONE', 'price': 0} for s in symbols}

def heikin_ashi(df):
    ha = df.copy()
    ha['HA_Close'] = (df[['open', 'high', 'low', 'close']].sum(axis=1)) / 4
    ha_open = [(df['open'][0] + df['close'][0]) / 2]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i-1] + ha['HA_Close'][i-1]) / 2)
    ha['HA_Open'] = ha_open
    ha['HA_High'] = ha[['high', 'HA_Open', 'HA_Close']].max(axis=1)
    ha['HA_Low'] = ha[['low', 'HA_Open', 'HA_Close']].min(axis=1)
    return ha[['HA_Open', 'HA_High', 'HA_Low', 'HA_Close']]

def get_klines(symbol):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=100)
    df = pd.DataFrame(klines, columns=[
        'timestamp','open','high','low','close','volume',
        'close_time','qav','not','tbbav','tbqav','ignore'
    ])
    df[['open','high','low','close']] = df[['open','high','low','close']].astype(float)
    return df

def check_signal(df):
    df['ema9'] = EMAIndicator(df['close'], window=9).ema_indicator()
    df['ema30'] = EMAIndicator(df['close'], window=30).ema_indicator()
    df['cci'] = CCIIndicator(df['high'], df['low'], df['close'], window=20).cci()
    ha = heikin_ashi(df)
    df = df.join(ha)

    if len(df) < 5:
        return 'NONE'

    prev, curr, nxt = df.iloc[-3], df.iloc[-2], df.iloc[-1]

    # SELL condition
    if (
        prev['ema9'] > prev['ema30'] and curr['ema9'] < curr['ema30'] and
        curr['HA_High'] > curr['HA_Open'] and curr['HA_Low'] < curr['HA_Open'] and
        nxt['HA_High'] == nxt['HA_Open'] and nxt['HA_Low'] < nxt['HA_Open'] and
        nxt['HA_Close'] < nxt['ema30'] and nxt['cci'] < 0
    ):
        return 'SELL'

    # BUY condition
    if (
        prev['ema9'] < prev['ema30'] and curr['ema9'] > curr['ema30'] and
        curr['HA_High'] > curr['HA_Open'] and curr['HA_Low'] < curr['HA_Open'] and
        nxt['HA_Low'] == nxt['HA_Open'] and nxt['HA_High'] > nxt['HA_Open'] and
        nxt['HA_Close'] > nxt['ema30'] and nxt['cci'] > 0
    ):
        return 'BUY'

    return 'NONE'

def update_signals():
    for sym in symbols:
        try:
            df = get_klines(sym)
            sig = check_signal(df)
            signals[sym] = {'signal': sig, 'price': df['close'].iloc[-1]}
        except Exception as e:
            signals[sym] = {'signal': 'ERROR', 'price': 0}
            print(f"Error for {sym}: {e}")

@app.route('/')
def index():
    update_signals()
    html = """
    <html><head><title>Binance Multi-Coin Dashboard</title></head><body>
    <h2>Trading Signals</h2>
    <table border=1 cellpadding=10>
    <tr><th>Symbol</th><th>Price</th><th>Signal</th></tr>
    {% for sym, info in signals.items() %}
       <tr><td>{{ sym }}</td><td>{{ info.price }}</td>
         <td><b style="color:{% if info.signal=='BUY' %}green{% elif info.signal=='SELL' %}red{% else %}gray{% endif %}">
           {{ info.signal }}</b></td></tr>
    {% endfor %}
    </table></body></html>
    """
    return render_template_string(html, signals=signals)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
