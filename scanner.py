import requests
import pandas as pd
from statsmodels.tsa.stattools import coint
import time

PAIRS_TO_TEST = [
    # --- CAMADA 1 & VETERANAS (Altíssima Liquidez e Centavos) ---
    ("ADAUSDT", "XRPUSDT"), ("TRXUSDT", "XRPUSDT"), ("XLMUSDT", "ADAUSDT"),
    ("ALGOUSDT", "XTZUSDT"), ("VETUSDT", "HBARUSDT"), ("ONEUSDT", "CELRUSDT"),
    ("ZILUSDT", "BATUSDT"), ("IOSTUSDT", "RVNUSDT"), ("DGBUSDT", "ZILUSDT"),
    ("ONTUSDT", "VETUSDT"), ("IOTAUSDT", "XLMUSDT"), ("EOSUSDT", "TRXUSDT"),
    ("CHZUSDT", "ZILUSDT"), ("THETAUSDT", "XTZUSDT"),

    # --- CAMADA 2 & INFRAESTRUTURA (Abaixo de $3.00) ---
    ("OPUSDT", "ARBUSDT"), ("MATICUSDT", "FTMUSDT"), ("LRCUSDT", "ENJUSDT"),
    ("CTSIUSDT", "SKLUSDT"), ("NKNUSDT", "BANDUSDT"), ("CELRUSDT", "CTSIUSDT"),
    ("MINAUSDT", "LRCUSDT"), ("DUSKUSDT", "CELRUSDT"), ("COTIUSDT", "CHZUSDT"),

    # --- DEFI & CORRETORAS DESCENTRALIZADAS ---
    ("CRVUSDT", "1INCHUSDT"), ("SUSHIUSDT", "CAKEUSDT"), ("KAVAUSDT", "BANDUSDT"),
    ("LINAUSDT", "CTKUSDT"), ("BAKEUSDT", "DODOUSDT"), ("ALPHAUSDT", "AKROUSDT"),
    ("RSRUSDT", "LITUSDT"), ("BELUSDT", "FLMUSDT"), ("RENUSDT", "KNCUSDT"),
    ("RAYUSDT", "SUSHIUSDT"), ("JOEUSDT", "CAKEUSDT"), ("SNXUSDT", "CRVUSDT"),

    # --- METAVERSO, GAMING E NFT ---
    ("SANDUSDT", "MANAUSDT"), ("GALAUSDT", "IMXUSDT"), ("CHZUSDT", "ENJUSDT"),
    ("ALICEUSDT", "DARUSDT"), ("TLMUSDT", "ALICEUSDT"), ("AXSUSDT", "SANDUSDT"),
    ("APEUSDT", "GALAUSDT"), ("MAGICUSDT", "GALAUSDT"), ("WAXPUSDT", "TLMUSDT"),

    # --- INTELIGÊNCIA ARTIFICIAL & DADOS ---
    ("FETUSDT", "GRTUSDT"), ("ROSEUSDT", "GRTUSDT"), ("API3USDT", "GRTUSDT"),
    ("CTXCUSDT", "MDTUSDT"), ("RENDERUSDT", "FETUSDT"), ("THETAUSDT", "GRTUSDT"),
    ("ARPAUSDT", "MDTUSDT"),

    # --- ARMAZENAMENTO DESCENTRALIZADO (STORAGE) ---
    ("FILUSDT", "ARUSDT"), ("STORJUSDT", "FILUSDT"), ("BLZUSDT", "STORJUSDT")
]

def get_binance_data(symbol, interval="1h", limit=500):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = requests.get(url)
        data = response.json()
        
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
        
        if df.empty or len(df) < 30:
            continue
            
        # 🚨 BLINDAGEM 1: Se o preço não oscilou (x is constant), pula o par.
        if df['close_A'].nunique() <= 1 or df['close_B'].nunique() <= 1:
            print(f"⚠️ Preço congelado detectado em {asset_a} ou {asset_b}. Pulando...")
            continue
            
        # 🚨 BLINDAGEM 2: Captura qualquer erro matemático (ex: matriz singular) para não quebrar o painel
        try:
            score, p_value, _ = coint(df['close_A'], df['close_B'])
        except Exception as e:
            print(f"⚠️ Erro matemático ao calcular {asset_a} x {asset_b}: {e}. Pulando...")
            continue
        
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