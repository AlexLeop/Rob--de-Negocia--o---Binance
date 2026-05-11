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
        self.rules = {}  # Cache de stepSize, tickSize e minNotional

    async def connect(self):
        self.client = await AsyncClient.create(self.api_key, self.api_secret)
        print("📥 Carregando regras de execução e filtros da Binance...")
        info = await self.client.futures_exchange_info()
        for s in info['symbols']:
            lot_filter = next((f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            price_filter = next((f for f in s['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
            notional_filter = next((f for f in s['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
            
            self.rules[s['symbol']] = {
                'stepSize': float(lot_filter['stepSize']) if lot_filter else 1.0,
                'tickSize': float(price_filter['tickSize']) if price_filter else 0.01,
                'minQty': float(lot_filter['minQty']) if lot_filter else 0.0,
                'minNotional': float(notional_filter['notional']) if notional_filter else 5.0
            }

    async def get_total_equity(self) -> float:
        """Retorna o Patrimônio Líquido Total (Saldo + PnL Não Realizado)."""
        try:
            acc = await self.client.futures_account()
            return float(acc['totalMarginBalance'])
        except Exception as e:
            print(f"⚠️ Erro ao buscar Equity Total: {e}")
            return 0.0

    async def get_usdt_balance(self) -> float:
        try:
            balances = await self.client.futures_account_balance()
            for b in balances:
                if b['asset'] == 'USDT':
                    return float(b['balance'])
        except Exception as e:
            print(f"Erro ao buscar saldo: {e}")
        return 0.0

    async def setup_symbol(self, symbol: str, leverage: int):
        """Configura alavancagem e modo de margem CRUZADA (CROSSED) para permitir proteção mútua das pernas."""
        try:
            await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            # Revertido para CROSSED para evitar "Perna Manca" por liquidação isolada
            await self.client.futures_change_margin_type(symbol=symbol, marginType='CROSSED')
        except BinanceAPIException as e:
            if e.code == -4046: # Já está em CROSSED
                pass
            else:
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
            
            has_position = abs(amt_a) > 1e-8 or abs(amt_b) > 1e-8
            total_pnl = pnl_a + pnl_b if has_position else 0.0
            
            return has_position, total_pnl, pos_a, pos_b
        except Exception as e:
            print(f"⚠️ Erro ao buscar posições: {e}")
            return False, 0.0, None, None

    def _format_quantity(self, symbol: str, qty: float) -> float:
        rules = self.rules.get(symbol, {'stepSize': 1.0, 'minQty': 0.0})
        step_size = rules['stepSize']
        precision = int(round(-math.log10(step_size), 0))
        formatted_qty = math.floor(qty / step_size) * step_size
        return round(formatted_qty, precision)

    async def validate_pre_flight(self, symbol: str, amount_usd: float) -> bool:
        """Verifica regras de notional e saldo antes de disparar ordens."""
        rules = self.rules.get(symbol)
        if not rules:
            return False
        
        # Check 1: Mínimo Nocional (Regra da Binance)
        if amount_usd < rules['minNotional']:
            print(f"❌ Abortando: {symbol} exige nocional mín de US$ {rules['minNotional']}. Tentado: US$ {amount_usd}")
            return False
            
        # Check 2: Saldo Livre (Margem)
        balance = await self.get_usdt_balance()
        if balance < amount_usd * 0.2: # Assumindo margem de segurança
             print(f"❌ Saldo Insuficiente para margem de {symbol}")
             return False
             
        return True

    async def execute_market_order(self, symbol: str, side: str, qty_usd: float):
        """Executa ordem a mercado com Pre-Flight Check e retorno detalhado."""
        try:
            if not await self.validate_pre_flight(symbol, qty_usd):
                raise ValueError(f"Falha na validação pré-execução para {symbol}")

            ticker = await self.client.futures_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            
            qty_coins = qty_usd / price
            final_qty = self._format_quantity(symbol, qty_coins)
            
            if final_qty <= 0:
                raise ValueError(f"Quantidade abaixo do lote mínimo para {symbol}")

            order = await self.client.futures_create_order(
                symbol=symbol,
                side=side.upper(),
                type='MARKET',
                quantity=final_qty
            )
            print(f"✅ [{symbol}] Ordem {side.upper()} de {final_qty} executada.")
            return order
        except Exception as e:
            print(f"❌ Erro Crítico em {symbol}: {e}")
            raise e

    async def place_stop_market_order(self, symbol: str, side: str, qty: float, stop_price: float):
        """Envia uma ordem de Stop Loss Nativa para o servidor da Binance."""
        try:
            # Garante formatação correta do preço de stop
            rules = self.rules.get(symbol, {'tickSize': 0.01})
            tick_size = rules['tickSize']
            precision = int(round(-math.log10(tick_size), 0))
            formatted_stop = round(stop_price, precision)

            order = await self.client.futures_create_order(
                symbol=symbol,
                side=side.upper(),
                type='STOP_MARKET',
                stopPrice=formatted_stop,
                quantity=qty,
                reduceOnly=True
            )
            print(f"🛡️ [OMS] Stop Nativo pendurado em {symbol} a US$ {formatted_stop}.")
            return order
        except Exception as e:
            print(f"⚠️ Erro ao pendurar Stop Nativo em {symbol}: {e}")
            return None

    async def cancel_all_orders(self, symbol: str):
        """Cancela todas as ordens abertas para um símbolo (ex: limpa stops pendentes)."""
        try:
            await self.client.futures_cancel_all_open_orders(symbol=symbol)
            print(f"🧹 [OMS] Todas as ordens de {symbol} foram canceladas.")
        except Exception as e:
            print(f"⚠️ Erro ao cancelar ordens de {symbol}: {e}")

    async def close_position(self, pos_data: dict):
        """Zera uma posição garantindo o reduceOnly."""
        if not pos_data: return
        
        amt = float(pos_data['positionAmt'])
        if abs(amt) < 1e-8: return
        
        side = 'SELL' if amt > 0 else 'BUY'
        symbol = pos_data['symbol']
        abs_qty = abs(amt)
        
        try:
            order = await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=abs_qty,
                reduceOnly=True
            )
            print(f"🏁 [{symbol}] Posição ZERADA ({side} {abs_qty}).")
            return order
        except Exception as e:
            print(f"🚨 Erro ao fechar {symbol}: {e}")
            raise e
