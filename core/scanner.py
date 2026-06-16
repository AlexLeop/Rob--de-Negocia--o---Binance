import asyncio
import aiohttp
import pandas as pd
from statsmodels.tsa.stattools import coint
import itertools
import numpy as np
import time
from concurrent.futures import ThreadPoolExecutor
from .config import Config

BASE_URL = "https://testnet.binancefuture.com" if Config.TESTNET else "https://fapi.binance.com"

scanner_sem = asyncio.Semaphore(20)

async def _fetch_klines(session, symbol, interval="5m", limit=250):
    async with scanner_sem:
        url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        try:
            async with session.get(url, timeout=5) as response:
                data = await response.json()
                if isinstance(data, dict) and 'msg' in data: return None
                df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
                return symbol, df['close'].astype(float).values
        except Exception:
            return None

def _compute_coint_chunk(pairs_chunk, valid_data):
    # Roda em uma thread separada (Numpy/Scipy libera o GIL em operações pesadas)
    results = []
    for a, b in pairs_chunk:
        try:
            arr_a = valid_data[a]
            arr_b = valid_data[b]
            
            # Blindagem 1: array constantes travam o coint
            if np.all(arr_a == arr_a[0]) or np.all(arr_b == arr_b[0]):
                continue
                
            if len(arr_a) != len(arr_b):
                min_l = min(len(arr_a), len(arr_b))
                arr_a = arr_a[-min_l:]
                arr_b = arr_b[-min_l:]
            
            score, p_value, _ = coint(arr_a, arr_b)
            if p_value < 0.05:
                log_a = np.log(arr_a)
                log_b = np.log(arr_b)
                ret_a = np.diff(log_a)
                ret_b = np.diff(log_b)
                corr = np.corrcoef(ret_a, ret_b)[0, 1]
                
                if corr > 0.50:
                    status = "✅ Excelente" if p_value < 0.01 else "⚠️ Aceitável"
                    
                    window = 240
                    # Rolling Beta idêntico ao strategy.py
                    df_log_a = pd.Series(log_a)
                    df_log_b = pd.Series(log_b)
                    
                    cov = df_log_a.rolling(window).cov(df_log_b)
                    var = df_log_b.rolling(window).var()
                    beta = cov / var.replace(0, np.nan)
                    beta = beta.ffill().fillna(1.0).values
                    
                    spread = log_a - (beta * log_b)
                    
                    spread_window = spread[-window:]
                    mean = np.mean(spread_window)
                    std = np.std(spread_window)
                    z_score = (spread[-1] - mean) / std if std > 0 else 0.0
                    
                    # Filtro Ativo: Só retorna se o Z-score for expressivo
                    if abs(z_score) >= 1.0:
                        results.append({
                            "Ativo A": a,
                            "Ativo B": b,
                            "P-Value": round(p_value, 5),
                            "Score": round(score, 2),
                            "Z-Score": round(z_score, 2),  # Salva com sinal original
                            "Status": status
                        })
        except Exception:
            pass
    return results

async def run_market_scan_async(interval="5m", limit=250):
    print(f"🔍 [Scanner] Iniciando Scan Global em {interval} (Limite: {limit} candles)...")
    
    # 1. Fetch Top 150 ativos por Volume (Mais abrangência de mercado)
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/fapi/v1/ticker/24hr") as resp:
            tickers = await resp.json()
            
        usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]
        usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
        top_symbols = [t['symbol'] for t in usdt_pairs[:150]] # 150 ativos = ~11.175 cruzamentos
        
        # 2. Fetch K-lines assincronamente (Extremamente rápido)
        tasks = [_fetch_klines(session, sym, interval, limit) for sym in top_symbols]
        results = await asyncio.gather(*tasks)
        
    valid_data = {res[0]: res[1] for res in results if res is not None and len(res[1]) >= limit * 0.9}
    symbols = list(valid_data.keys())
    pairs = list(itertools.combinations(symbols, 2))
    
    # 3. Processamento Matemático em ThreadPool para não travar o Main Event Loop do bot
    loop = asyncio.get_event_loop()
    chunk_size = max(1, len(pairs) // 4)
    chunks = [pairs[i:i + chunk_size] for i in range(0, len(pairs), chunk_size)]
    
    final_results = []
    # Usando 2 workers para evitar pico de memória (OOMKilled) em VPS pequena
    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = [loop.run_in_executor(executor, _compute_coint_chunk, chunk, valid_data) for chunk in chunks]
        res_chunks = await asyncio.gather(*tasks)
        for rc in res_chunks:
            final_results.extend(rc)
            
    if not final_results:
        return pd.DataFrame(columns=["Ativo A", "Ativo B", "P-Value", "Score", "Z-Score", "Status"])

    df_results = pd.DataFrame(final_results)
    df_results['Z_Abs'] = df_results['Z-Score'].abs()
    df_results = df_results.sort_values(by="Z_Abs", ascending=False).drop(columns=['Z_Abs'])
    return df_results

# Função Síncrona de fallback para ser chamada pelo Streamlit Dashboard
def run_market_scan(interval="5m", limit=250):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(run_market_scan_async(interval, limit))