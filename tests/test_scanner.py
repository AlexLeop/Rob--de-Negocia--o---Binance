import asyncio
import aiohttp
import pandas as pd
import time
from statsmodels.tsa.stattools import coint
import itertools

async def fetch_klines(session, symbol, interval="5m", limit=200):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        async with session.get(url, timeout=5) as response:
            data = await response.json()
            if isinstance(data, dict) and 'msg' in data: return None
            df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
            return symbol, df['close'].astype(float).values
    except Exception:
        return None

async def main():
    print("Fetching 24hr ticker to find top 100 USDT pairs by volume...")
    async with aiohttp.ClientSession() as session:
        async with session.get("https://fapi.binance.com/fapi/v1/ticker/24hr") as resp:
            tickers = await resp.json()
            
        usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]
        usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
        top_symbols = [t['symbol'] for t in usdt_pairs[:100]]
        
        print(f"Fetching K-lines for {len(top_symbols)} symbols...")
        t0 = time.time()
        tasks = [fetch_klines(session, sym) for sym in top_symbols]
        results = await asyncio.gather(*tasks)
        print(f"K-lines fetched in {time.time() - t0:.2f}s")
        
    valid_data = {res[0]: res[1] for res in results if res is not None and len(res[1]) >= 100}
    symbols = list(valid_data.keys())
    
    pairs = list(itertools.combinations(symbols, 2))
    print(f"Computing cointegration for {len(pairs)} pairs...")
    
    t1 = time.time()
    best_pairs = []
    
    for a, b in pairs:
        try:
            arr_a = valid_data[a]
            arr_b = valid_data[b]
            
            if len(arr_a) != len(arr_b):
                min_l = min(len(arr_a), len(arr_b))
                arr_a = arr_a[-min_l:]
                arr_b = arr_b[-min_l:]
                
            score, p_value, _ = coint(arr_a, arr_b)
            if p_value < 0.01:
                best_pairs.append((a, b, p_value))
        except Exception:
            pass
            
    print(f"Computed in {time.time() - t1:.2f}s")
    best_pairs.sort(key=lambda x: x[2])
    for a, b, p in best_pairs[:5]:
        print(f"{a}/{b}: P-Value = {p:.5f}")

if __name__ == '__main__':
    asyncio.run(main())
