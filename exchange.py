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
        self.rules = {}

    async def connect(self):
        self.client = await AsyncClient.create(self.api_key, self.api_secret)
        info = await self.client.futures_exchange_info()
        for s in info['symbols']:
            lot_filter = next((f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            notional_filter = next((f for f in s['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
            self.rules[s['symbol']] = {
                'stepSize': float(lot_filter['stepSize']) if lot_filter else 1.0,
                'minNotional': float(notional_filter['notional']) if notional_filter else 5.0
            }

    async def validate_pair_pre_flight(self, sym_a, amt_a, sym_b, amt_b):
        """Impede o disparo se o par for financeiramente inviável."""
        from config import Config
        rules_a = self.rules.get(sym_a)
        rules_b = self.rules.get(sym_b)
        if not rules_a or not rules_b: return False, "Erro nas regras de API"
        
        if amt_a < rules_a['minNotional'] or amt_b < rules_b['minNotional']:
            m = max(rules_a['minNotional'], rules_b['minNotional'])
            return False, f"Nocional abaixo do mín (Exige: {m})"
            
        # BUG-05: Leverage Dinâmico (Removido hardcoded /10)
        total_needed = (amt_a + amt_b) / Config.LEVERAGE 
        balance = await self.get_usdt_balance()
        if balance < (total_needed * 1.15): # 15% de margem de segurança
            return False, "Saldo insuficiente para margem do par"
            
        return True, "OK"

    async def execute_market_order(self, symbol: str, side: str, qty_usd: float):
        """Executa ordem a mercado e retorna detalhes do preenchimento."""
        try:
            ticker = await self.client.futures_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            qty_coins = qty_usd / price
            
            step_size = self.rules[symbol]['stepSize']
            precision = int(round(-math.log10(step_size), 0))
            final_qty = math.floor(qty_coins / step_size) * step_size
            final_qty = round(final_qty, precision)
            
            if final_qty <= 0: return None

            order = await self.client.futures_create_order(
                symbol=symbol, side=side.upper(), type='MARKET', quantity=final_qty
            )
            
            # Extrai dados reais do preenchimento
            fill_qty = float(order.get('executedQty', final_qty))
            fill_price = float(order.get('avgPrice', price))
            return {
                'symbol': symbol,
                'qty': fill_qty,
                'price': fill_price,
                'notional': fill_qty * fill_price
            }
        except Exception as e:
            print(f"❌ Erro de execução em {symbol}: {e}")
            return None

    async def get_total_equity(self) -> float:
        acc = await self.client.futures_account()
        return float(acc['totalMarginBalance'])

    async def get_usdt_balance(self) -> float:
        balances = await self.client.futures_account_balance()
        for b in balances:
            if b['asset'] == 'USDT': return float(b['balance'])
        return 0.0

    async def setup_symbol(self, symbol: str, leverage: int):
        try:
            await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            await self.client.futures_change_margin_type(symbol=symbol, marginType='CROSSED')
        except BinanceAPIException: pass

    async def get_klines(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        klines = await self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'v', 'ct', 'qa', 'nt', 'tb', 'tq', 'i'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df[['close', 'high', 'low']].astype(float)

    async def get_positions_pnl(self, symbol_a: str, symbol_b: str):
        positions = await self.client.futures_position_information()
        pos_a = next((p for p in positions if p['symbol'] == symbol_a), None)
        pos_b = next((p for p in positions if p['symbol'] == symbol_b), None)
        
        amt_a = float(pos_a['positionAmt']) if pos_a else 0.0
        amt_b = float(pos_b['positionAmt']) if pos_b else 0.0
        pnl_a = float(pos_a['unRealizedProfit']) if pos_a else 0.0
        pnl_b = float(pos_b['unRealizedProfit']) if pos_b else 0.0
        
        is_open = abs(amt_a) > 1e-8 or abs(amt_b) > 1e-8
        return is_open, (pnl_a + pnl_b), pos_a, pos_b

    async def cancel_all_orders(self, symbol: str):
        await self.client.futures_cancel_all_open_orders(symbol=symbol)

    async def close_position(self, pos_data: dict):
        amt = float(pos_data['positionAmt'])
        if abs(amt) < 1e-8: return
        side = 'SELL' if amt > 0 else 'BUY'
        await self.client.futures_create_order(
            symbol=pos_data['symbol'], side=side, type='MARKET', quantity=abs(amt), reduceOnly=True
        )