import requests
import pandas as pd
from statsmodels.tsa.stattools import coint
import time

# Lista atualizada com os novos tickers da Binance
PAIRS_TO_TEST = [
    ("BTCUSDT", "ETHUSDT"), ("SOLUSDT", "AVAXUSDT"), ("ADAUSDT", "DOTUSDT"),
    ("NEARUSDT", "ATOMUSDT"), ("APTUSDT", "SUIUSDT"), ("OPUSDT", "ARBUSDT"),
    ("UNIUSDT", "AAVEUSDT"), ("MKRUSDT", "COMPUSDT"), ("SANDUSDT", "MANAUSDT"),
    ("GALAUSDT", "IMXUSDT"), ("RENDERUSDT", "TAOUSDT"), ("FETUSDT", "GRTUSDT"),
    ("ARUSDT", "FILUSDT")
]

def get_binance_data(symbol, interval="1h", limit=500):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = requests.get(url)
        data = response.json()
        
        # Trava: Se a Binance retornar um erro (ex: Invalid Symbol), aborta.
        if isinstance(data, dict) and 'msg' in data:
            return None
            
        df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        df['close'] = df['close'].astype(float)
        return df[['time', 'close']].set_index('time')
    except Exception:
        return None

def run_market_scan():
    results = []
    for asset_a, asset_b in PAIRS_TO_TEST:
        df_a = get_binance_data(asset_a)
        time.sleep(0.3)
        df_b = get_binance_data(asset_b)
        time.sleep(0.3)
        
        if df_a is None or df_b is None or df_a.empty or df_b.empty:
            continue
            
        df = df_a.join(df_b, lsuffix='_A', rsuffix='_B').dropna()
        
        # 🚨 NOVA TRAVA DE SEGURANÇA: Garante que sobraram dados suficientes para a matemática
        if df.empty or len(df) < 30:
            print(f"Dados insuficientes para parear {asset_a} e {asset_b}. Pulando...")
            continue
            
        score, p_value, _ = coint(df['close_A'], df['close_B'])
        
        status = "✅ Excelente" if p_value < 0.01 else "⚠️ Aceitável" if p_value < 0.05 else "❌ Descartar"
        
        results.append({
            "Ativo A": asset_a,
            "Ativo B": asset_b,
            "P-Value": round(p_value, 5),
            "Score": round(score, 2),
            "Status": status
        })

    if not results:
        return pd.DataFrame(columns=["Ativo A", "Ativo B", "P-Value", "Score", "Status"])

    df_results = pd.DataFrame(results).sort_values(by="P-Value")
    return df_results