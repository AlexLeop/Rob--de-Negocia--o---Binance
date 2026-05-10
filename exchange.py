import math
import asyncio
from binance.client import AsyncClient
from binance.exceptions import BinanceAPIException
import pandas as pd

class BinanceExecutor:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = None
        self.rules = {}  # Cache de stepSize e tickSize

    async def connect(self):
        self.client = await AsyncClient.create(self.api_key, self.api_secret)
        print("📥 Carregando regras de execução da Binance...")
        info = await self.client.futures_exchange_info()
        for s in info['symbols']:
            lot_filter = next((f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            price_filter = next((f for f in s['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
            
            self.rules[s['symbol']] = {
                'stepSize': float(lot_filter['stepSize']) if lot_filter else 1.0,
                'tickSize': float(price_filter['tickSize']) if price_filter else 0.01,
                'minQty': float(lot_filter['minQty']) if lot_filter else 0.0
            }

    async def setup_symbol(self, symbol: str, leverage: int):
        """Configura alavancagem e modo de margem cruzada (CROSSED)."""
        try:
            await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            await self.client.futures_change_margin_type(symbol=symbol, marginType='CROSSED')
        except BinanceAPIException as e:
            if e.code != -4046: # Ignora erro se já estiver no modo correto
                print(f"⚠️ Aviso no setup de {symbol}: {e}")

    async def get_klines(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        klines = await self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df[['open', 'high', 'low', 'close']].astype(float)

    async def get_positions_pnl(self, symbol_a: str, symbol_b: str):
        """Busca PnL não realizado e dados das posições."""
        try:
            positions = await self.client.futures_position_information()
            pos_a = next((p for p in positions if p['symbol'] == symbol_a), None)
            pos_b = next((p for p in positions if p['symbol'] == symbol_b), None)
            
            amt_a = float(pos_a['positionAmt']) if pos_a else 0.0
            amt_b = float(pos_b['positionAmt']) if pos_b else 0.0
            
            pnl_a = float(pos_a['unRealizedProfit']) if pos_a else 0.0
            pnl_b = float(pos_b['unRealizedProfit']) if pos_b else 0.0
            
            # Estamos posicionados se qualquer uma das pernas tiver saldo
            has_position = abs(amt_a) > 0 or abs(amt_b) > 0
            total_pnl = pnl_a + pnl_b if has_position else 0.0
            
            return has_position, total_pnl, pos_a, pos_b
        except Exception as e:
            print(f"⚠️ Erro ao buscar posições: {e}")
            return False, 0.0, None, None

    def _format_quantity(self, symbol: str, qty: float) -> float:
        """Aplica o arredondamento estrito baseado no stepSize da Binance."""
        rules = self.rules.get(symbol, {'stepSize': 1.0, 'minQty': 0.0})
        step_size = rules['stepSize']
        
        # Calcula a precisão (casas decimais) a partir do stepSize
        precision = int(round(-math.log10(step_size), 0))
        
        # Arredonda para baixo (floor) para evitar ordens maiores que o saldo disponível
        formatted_qty = math.floor(qty / step_size) * step_size
        return round(formatted_qty, precision)

    async def execute_market_order(self, symbol: str, side: str, qty_usd: float):
        """Executa uma ordem a mercado com proteção de arredondamento."""
        try:
            ticker = await self.client.futures_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            
            qty_coins = qty_usd / price
            final_qty = self._format_quantity(symbol, qty_coins)
            
            if final_qty <= 0:
                print(f"❌ Erro: Quantidade calculada para {symbol} é zero (Abaixo do mínimo).")
                return None

            order = await self.client.futures_create_order(
                symbol=symbol,
                side=side.upper(),
                type='MARKET',
                quantity=final_qty
            )
            print(f"✅ [{symbol}] Ordem {side.upper()} de {final_qty} executada.")
            return order
        except Exception as e:
            print(f"❌ Erro Crítico ao executar ordem em {symbol}: {e}")
            raise e

    async def close_position(self, pos_data: dict):
        """Zera uma posição existente a mercado."""
        if not pos_data: return
        
        amt = float(pos_data['positionAmt'])
        if amt == 0: return
        
        side = 'SELL' if amt > 0 else 'BUY'
        symbol = pos_data['symbol']
        abs_qty = abs(amt)
        
        try:
            await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=abs_qty,
                reduceOnly=True  # Defesa extra de produção
            )
            print(f"🏁 [{symbol}] Posição ZERADA ({side} {abs_qty}).")
        except Exception as e:
            print(f"🚨 Erro ao fechar posição em {symbol}: {e}")