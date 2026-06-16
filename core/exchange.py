import math
import asyncio
import time
from binance import AsyncClient
from binance.exceptions import BinanceAPIException
import pandas as pd
from .api_health import ApiHealthTracker
from .config import Config

class BinanceExecutor:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = None
        self.rules = {}
        self._pos_cache = None
        self._last_pos_time = 0
        self._last_rules_time = 0
        self.health = ApiHealthTracker()

    async def connect(self):
        if self.client and hasattr(self.client, 'close_connection'):
            try:
                await self.client.close_connection()
            except: pass
            try:
                if hasattr(self.client, 'session') and self.client.session:
                    await self.client.session.close()
            except: pass
        self.client = AsyncClient(self.api_key, self.api_secret, testnet=Config.TESTNET)
        # VULN R: Sincronização Quântica de Tempo (RecvWindow Ban Immunization)
        try:
            await self.client.load_time_difference()
            print("⏳ [Exchange] Offset de tempo sincronizado com a Binance.")
        except Exception as e:
            print(f"⚠️ [Exchange] Falha ao sincronizar tempo: {e}")
            
        await self.refresh_exchange_info()

    async def refresh_exchange_info(self):
        """Atualiza filtros de lote e nocional (Executado a cada 1h)."""
        now = time.time()
        if now - self._last_rules_time < 3600: return # Cache de 1h
        
        try:
            info = await self.client.futures_exchange_info()
            for s in info['symbols']:
                lot_filter = next((f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                notional_filter = next((f for f in s['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
                self.rules[s['symbol']] = {
                    'stepSize': float(lot_filter['stepSize']) if lot_filter else 1.0,
                    'minNotional': float(notional_filter['notional']) if notional_filter else 5.0
                }
            self._last_rules_time = now
            print("🔄 [Exchange] Filtros de negociação atualizados.")
        except Exception as e:
            print(f"⚠️ Erro ao atualizar regras: {e}")

    async def validate_pair_pre_flight(self, sym_a, amt_a, sym_b, amt_b, lev_a=None, lev_b=None):
        """Impede o disparo se o par for financeiramente inviável."""
        await self.refresh_exchange_info() # Garante regras frescas
        from .config import Config
        rules_a = self.rules.get(sym_a)
        rules_b = self.rules.get(sym_b)
        if not rules_a or not rules_b: return False, "Erro nas regras de API"
        
        if amt_a < rules_a['minNotional'] or amt_b < rules_b['minNotional']:
            m = max(rules_a['minNotional'], rules_b['minNotional'])
            return False, f"Nocional abaixo do mín (Exige: {m})"
            
        # VULN G: Usa alavancagem real da corretora se disponível, senão a da config.
        la = lev_a or Config.LEVERAGE
        lb = lev_b or Config.LEVERAGE
        total_needed = (amt_a / la) + (amt_b / lb)
        
        # VULN K: Validação de Liquidez e Slippage Oculto (Spread BBA)
        try:
            bba_a = await self.client.futures_orderbook_ticker(symbol=sym_a)
            bba_b = await self.client.futures_orderbook_ticker(symbol=sym_b)
            spread_a = ((float(bba_a['askPrice']) - float(bba_a['bidPrice'])) / float(bba_a['bidPrice'])) * 100
            spread_b = ((float(bba_b['askPrice']) - float(bba_b['bidPrice'])) / float(bba_b['bidPrice'])) * 100
            if spread_a > 0.3 or spread_b > 0.3:
                return False, f"Slippage Ruin Bloqueado: Spread {sym_a}={spread_a:.2f}%, {sym_b}={spread_b:.2f}% (Máx 0.3%)"
        except Exception:
            return False, "Falha ao checar Livro de Ofertas"
        
        balance = await self.get_usdt_balance()
        if balance is None: return False, "Falha ao consultar saldo"
        
        if balance < (total_needed * 1.15): # 15% de margem de segurança
            return False, f"Saldo {balance:.2f} insuficiente para margem requerida {total_needed:.2f}"
            
        return True, "OK"

    async def execute_market_order(self, symbol: str, side: str, qty_usd: float):
        """Executa ordem a mercado e retorna detalhes do preenchimento."""
        try:
            ticker = await self.client.futures_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            qty_coins = qty_usd / price
            
            step_size = self.rules[symbol]['stepSize']
            precision = int(round(-math.log10(step_size), 0))
            final_qty = math.floor((qty_coins / step_size) + 1e-8) * step_size
            
            # VULN F: Força Cast para Inteiro se precisão for 0 (Binance restringe .0 em moedas meme)
            if precision <= 0:
                final_qty = int(final_qty)
            else:
                final_qty = round(final_qty, precision)
            
            if final_qty <= 0: return None

            order = await self.client.futures_create_order(
                symbol=symbol, side=side.upper(), type='MARKET', quantity=final_qty
            )
            self._pos_cache = None # VULN Z: Invalidação de Cache
            
            # Extrai dados reais do preenchimento
            fill_qty = float(order.get('executedQty', final_qty))
            fill_price = float(order.get('avgPrice', price))
            
            self.health.record(True)
            return {
                'symbol': symbol,
                'qty': fill_qty,
                'price': fill_price,
                'notional': fill_qty * fill_price
            }
        except BinanceAPIException as e:
            self.health.record(False)
            print(f"❌ Erro oficial Binance em {symbol}: {e}")
            return None
        except Exception as e:
            self.health.record(False)
            # VULN Q: O Falso Negativo de Execução (Timeout Silencioso)
            print(f"⚠️ [VULN Q] Falha de Rede na ordem de {symbol} ({e}). Verificando estado na corretora...")
            await asyncio.sleep(2) # Espera o motor da Binance assentar
            try:
                pos = await self.client.futures_position_information(symbol=symbol)
                for p in pos:
                    if p['symbol'] == symbol and abs(float(p['positionAmt'])) > 0:
                        print(f"✅ [VULN Q] Resgate HFT! A ordem {symbol} executou silenciosamente.")
                        return {
                            'symbol': symbol,
                            'qty': abs(float(p['positionAmt'])),
                            'price': float(p['entryPrice']),
                            'notional': abs(float(p['positionAmt'])) * float(p['entryPrice'])
                        }
            except: pass
            print(f"❌ Ordem {symbol} de fato não executada na corretora.")
            return None

    async def get_total_equity(self):
        try:
            account = await self.client.futures_account()
            if not account or not account.get('assets') or account.get('totalMarginBalance') == "":
                return None
            return float(account.get('totalMarginBalance', 0))
        except Exception as e:
            print(f"❌ [Exchange] Erro ao obter saldo: {e}")
            return None

    async def get_usdt_balance(self):
        try:
            balances = await self.client.futures_account_balance()
            if not balances:
                return None
            for b in balances:
                if b['asset'] == 'USDT':
                    return float(b['balance'])
            return 0.0
        except:
            return None

    async def setup_symbol(self, symbol: str, leverage: int):
        try:
            res = await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            actual_leverage = float(res['leverage'])
            await self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
            return actual_leverage
        except BinanceAPIException: 
            try:
                # Se falhar, busca a alavancagem que já está configurada
                pos = await self.client.futures_position_information(symbol=symbol)
                return float(pos[0]['leverage']) if pos else float(leverage)
            except:
                return float(leverage)

    async def get_klines(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        try:
            klines = await self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'v', 'ct', 'qa', 'nt', 'tb', 'tq', 'i'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            self.health.record(True)
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].astype(float)
            
            # Remove o último candle pois ele ainda não fechou (evita falsos positivos por Repaint)
            return df.iloc[:-1][['open', 'high', 'low', 'close']]
        except BinanceAPIException as e:
            self.health.record(False)
            raise e

    async def get_positions_pnl(self, symbol_a: str, symbol_b: str):
        """Obtém PnL das posições com cache de 2s para evitar spam de API."""
        now = time.time()
        if not self._pos_cache or (now - self._last_pos_time > 2):
            self._pos_cache = await self.client.futures_position_information()
            self._last_pos_time = now
            
        pos_a = next((p for p in self._pos_cache if p['symbol'] == symbol_a), None)
        pos_b = next((p for p in self._pos_cache if p['symbol'] == symbol_b), None)
        
        amt_a = float(pos_a.get('positionAmt') or 0.0) if pos_a else 0.0
        amt_b = float(pos_b.get('positionAmt') or 0.0) if pos_b else 0.0
        pnl_a = float(pos_a.get('unRealizedProfit') or 0.0) if pos_a else 0.0
        pnl_b = float(pos_b.get('unRealizedProfit') or 0.0) if pos_b else 0.0
        
        is_open = abs(amt_a) > 1e-8 or abs(amt_b) > 1e-8
        return is_open, (pnl_a + pnl_b), pos_a, pos_b

    async def cancel_all_orders(self, symbol: str):
        await self.client.futures_cancel_all_open_orders(symbol=symbol)

    async def close_position(self, pos_data: dict):
        amt = float(pos_data['positionAmt'])
        if abs(amt) < 1e-8: return
        symbol = pos_data['symbol']
        side = 'SELL' if amt > 0 else 'BUY'
        
        try:
            step_size = self.rules[symbol]['stepSize']
            precision = int(round(-math.log10(step_size), 0))
            final_qty = abs(amt)
            
            if precision <= 0:
                final_qty = int(final_qty)
            else:
                final_qty = math.floor((final_qty / step_size) + 1e-8) * step_size
                final_qty = round(final_qty, precision)
            
            await self.client.futures_create_order(
                symbol=symbol, side=side, type='MARKET', quantity=final_qty, reduceOnly=True
            )
            self._pos_cache = None # VULN Z: Invalidação de Cache
        except Exception as e:
            print(f"❌ Erro ao fechar posição de {symbol}: {e}")