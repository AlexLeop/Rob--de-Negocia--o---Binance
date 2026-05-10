import math
import asyncio
from pybit.unified_trading import HTTP
import pandas as pd

class BybitExecutor:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = None
        self.rules = {}

    async def connect(self):
        # A pybit é síncrona por natureza, o HTTP client é rápido
        self.session = HTTP(testnet=False, api_key=self.api_key, api_secret=self.api_secret)
        
        print("📥 Carregando regras de execução da Bybit...")
        # Busca os tamanhos de lote em thread paralela para não travar
        info = await asyncio.to_thread(self.session.get_instruments_info, category="linear")
        
        for s in info['result']['list']:
            self.rules[s['symbol']] = {
                'stepSize': float(s['lotSizeFilter']['qtyStep']),
                'tickSize': float(s['priceFilter']['tickSize']),
                'minQty': float(s['lotSizeFilter']['minOrderQty'])
            }

    async def setup_symbol(self, symbol: str, leverage: int):
        try:
            await asyncio.to_thread(
                self.session.set_leverage, 
                category="linear", symbol=symbol, 
                buyLeverage=str(leverage), sellLeverage=str(leverage)
            )
        except Exception as e:
            if "leverage not modified" not in str(e).lower():
                print(f"⚠️ Aviso no setup de alavancagem de {symbol}: {e}")
        
        try:
            # Força o modo Cross Margin (0)
            await asyncio.to_thread(
                self.session.switch_margin_mode, 
                category="linear", symbol=symbol, 
                tradeMode=0, buyLeverage=str(leverage), sellLeverage=str(leverage)
            )
        except Exception as e:
            if "not modified" not in str(e).lower() and "cross margin" not in str(e).lower():
                pass # Contas UTA já são Cross por padrão

    async def get_klines(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        # Mapeamento do timeframe (ex: '5m' para '5' da Bybit)
        interval_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
        bybit_int = interval_map.get(interval, "5")
        
        res = await asyncio.to_thread(
            self.session.get_kline, 
            category="linear", symbol=symbol, interval=bybit_int, limit=limit
        )
        
        # Bybit retorna o mais novo primeiro. Precisamos inverter para o Pandas
        data = res['result']['list']
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
        df['timestamp'] = pd.to_numeric(df['timestamp'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.sort_index()
        return df[['open', 'high', 'low', 'close']].astype(float)

    async def get_positions_pnl(self, symbol_a: str, symbol_b: str):
        try:
            res_a = await asyncio.to_thread(self.session.get_positions, category="linear", symbol=symbol_a)
            res_b = await asyncio.to_thread(self.session.get_positions, category="linear", symbol=symbol_b)
            
            pos_a = res_a['result']['list'][0] if res_a['result']['list'] else None
            pos_b = res_b['result']['list'][0] if res_b['result']['list'] else None
            
            # Na Bybit, 'size' é sempre positivo. Descobrimos se é long/short pelo 'side'
            amt_a = float(pos_a['size']) * (1 if pos_a['side'] == 'Buy' else -1) if pos_a and float(pos_a['size']) > 0 else 0.0
            amt_b = float(pos_b['size']) * (1 if pos_b['side'] == 'Buy' else -1) if pos_b and float(pos_b['size']) > 0 else 0.0
            
            pnl_a = float(pos_a['unrealisedPnl']) if pos_a else 0.0
            pnl_b = float(pos_b['unrealisedPnl']) if pos_b else 0.0
            
            has_position = abs(amt_a) > 0 or abs(amt_b) > 0
            total_pnl = pnl_a + pnl_b if has_position else 0.0
            
            # Formata para o padrão que o main.py espera
            dict_a = {'symbol': symbol_a, 'positionAmt': amt_a}
            dict_b = {'symbol': symbol_b, 'positionAmt': amt_b}
            
            return has_position, total_pnl, dict_a, dict_b
        except Exception as e:
            print(f"⚠️ Erro ao buscar posições na Bybit: {e}")
            return False, 0.0, None, None

    def _format_quantity(self, symbol: str, qty: float) -> float:
        rules = self.rules.get(symbol, {'stepSize': 1.0, 'minQty': 0.0})
        step_size = rules['stepSize']
        precision = int(round(-math.log10(step_size), 0))
        formatted_qty = math.floor(qty / step_size) * step_size
        return round(formatted_qty, precision)

    async def execute_market_order(self, symbol: str, side: str, qty_usd: float):
        try:
            ticker = await asyncio.to_thread(self.session.get_tickers, category="linear", symbol=symbol)
            price = float(ticker['result']['list'][0]['lastPrice'])
            
            qty_coins = qty_usd / price
            final_qty = self._format_quantity(symbol, qty_coins)
            
            if final_qty <= 0:
                print(f"❌ Erro: Quantidade calculada para {symbol} é zero (Abaixo do Lote Mínimo).")
                return None

            bybit_side = "Buy" if side.upper() == "BUY" else "Sell"

            order = await asyncio.to_thread(
                self.session.place_order,
                category="linear",
                symbol=symbol,
                side=bybit_side,
                orderType="Market",
                qty=str(final_qty)
            )
            print(f"✅ [{symbol}] Ordem {bybit_side} de {final_qty} executada.")
            return order
        except Exception as e:
            print(f"❌ Erro Crítico ao executar ordem em {symbol}: {e}")
            raise e

    async def close_position(self, pos_data: dict):
        if not pos_data: return
        
        amt = float(pos_data['positionAmt'])
        if amt == 0: return
        
        symbol = pos_data['symbol']
        side = "Sell" if amt > 0 else "Buy"
        abs_qty = abs(amt)
        
        try:
            # reduceOnly=True é uma defesa extra: garante que esta ordem APENAS feche posições
            await asyncio.to_thread(
                self.session.place_order,
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(abs_qty),
                reduceOnly=True
            )
            print(f"🏁 [{symbol}] Posição ZERADA ({side} {abs_qty}).")
        except Exception as e:
            print(f"🚨 Erro ao fechar posição em {symbol}: {e}")