import asyncio
import database as db
from config import Config
from exchange import BinanceExecutor
from strategy import PairsStrategy

async def safe_close_pair(executor, symbol_a, symbol_b):
    """Zera posições de forma agressiva e limpa ordens pendentes."""
    print(f"🧹 [OMS] Neutralizando par {symbol_a}/{symbol_b}...")
    for _ in range(3): # 3 tentativas de limpeza
        is_open, _, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)
        if not is_open: break
        if pos_a and abs(float(pos_a['positionAmt'])) > 1e-8:
            await executor.close_position(pos_a)
            await executor.cancel_all_orders(symbol_a)
        if pos_b and abs(float(pos_b['positionAmt'])) > 1e-8:
            await executor.close_position(pos_b)
            await executor.cancel_all_orders(symbol_b)
        await asyncio.sleep(1)

async def monitorar_par(executor, pair_idx, symbol_a, symbol_b, initial_amount, initial_target, initial_stop, initial_adx, initial_z, initial_tf, delay):
    await asyncio.sleep(delay)
    print(f"🚀 [Par {pair_idx}] Scanner Ativo: {symbol_a}/{symbol_b}")
    await executor.setup_symbol(symbol_a, Config.LEVERAGE)
    await executor.setup_symbol(symbol_b, Config.LEVERAGE)

    consecutive_triggers = 0 
    in_critical_section = False # BUG-SÉRIO: Proteção contra cancelamento no meio da execução

    while True:
        try:
            if await db.get_config_async("BOT_STATUS") != "ON":
                await asyncio.sleep(5); continue
            
            # BUG-02: Parâmetros Dinâmicos (Lê do DB a cada ciclo)
            amount = float(await db.get_config_async("TRADE_AMOUNT_USD") or initial_amount)
            target = float(await db.get_config_async("TARGET_PNL_USD") or initial_target)
            stop = float(await db.get_config_async("STOP_LOSS_USD") or initial_stop)
            adx_limit = float(await db.get_config_async("ADX_LIMIT") or initial_adx)
            z_limit = float(await db.get_config_async("Z_SCORE_LIMIT") or initial_z)
            timeframe = await db.get_config_async("TIMEFRAME") or initial_tf

            # 1. Indicadores com Pearson
            df_a, df_b = await asyncio.gather(executor.get_klines(symbol_a, timeframe), executor.get_klines(symbol_b, timeframe))
            result = PairsStrategy.calculate_indicators(df_a, df_b, Config)
            if result[0] is None:
                await asyncio.sleep(5); continue
            
            df_spread, beta = result
            sig = PairsStrategy.get_signals(df_spread, Config)
            
            is_open, pnl, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)

            # BUG-08: Visibilidade (Radar Ao Vivo)
            await db.update_config_async("LIVE_ZSCORE", f"{sig['z_score']:.2f}")
            await db.update_config_async("LIVE_ADX", f"{sig['adx']:.2f}")
            status_txt = f"Par {pair_idx}: {symbol_a}/{symbol_b} | {'POSIÇÃO ABERTA' if is_open else 'Monitorando'}"
            await db.update_config_async("LIVE_STATUS", status_txt)

            # 2. Gestão de Saída
            if is_open:
                consecutive_triggers = 0
                if abs(sig['z_score']) >= 4.0 or pnl >= target or pnl <= -stop:
                    in_critical_section = True
                    await safe_close_pair(executor, symbol_a, symbol_b)
                    await db.save_trade_async(symbol_a, symbol_b, pnl)
                    in_critical_section = False
                    
                    # Se foi Stop Loss, aplica cooldown maior (60s) para evitar repetição de erro
                    if pnl <= -stop:
                        print(f"📉 [Par {pair_idx}] Stop Loss atingido. Entrando em Cooldown de 60s...")
                        await asyncio.sleep(60)
                    else:
                        await asyncio.sleep(15)
                else: await asyncio.sleep(3)
                continue

            # BUG-11: Threshold de Half-Life Dinâmico (Máximo 2h de reversão)
            TIMEFRAME_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60}
            minutes_per_candle = TIMEFRAME_MINUTES.get(timeframe, 5)
            max_halflife_candles = 120 / minutes_per_candle

            # BUG-03: Filtro de Pearson Posicionado Corretamente
            pearson_ok = sig.get('correlation', 0) >= 0.70
            
            if abs(sig['z_score']) > z_limit and sig['adx'] < adx_limit and sig['half_life'] < max_halflife_candles and pearson_ok:
                consecutive_triggers += 1
                print(f"⏱️ [Par {pair_idx}] Sinal ({consecutive_triggers}/3) Z:{sig['z_score']:.2f} Corr:{sig.get('correlation', 0):.2f}")

                if consecutive_triggers >= 3:
                    in_critical_section = True
                    amt_a = amount
                    amt_b = amount * abs(beta)
                    if min(amt_a, amt_b) < 5.5:
                        f = 5.5 / min(amt_a, amt_b)
                        amt_a *= f; amt_b *= f

                    # --- VALIDAÇÃO ATÔMICA DO PAR ---
                    valid, msg = await executor.validate_pair_pre_flight(symbol_a, amt_a, symbol_b, amt_b)
                    if not valid:
                        print(f"⚠️ [Par {pair_idx}] Abortado: {msg}. Cooldown 60s."); in_critical_section = False; await asyncio.sleep(60); continue

                    # --- EXECUÇÃO SEQUENCIAL BLINDADA ---
                    side_a = 'SELL' if sig['z_score'] > 0 else 'BUY'
                    side_b = 'BUY' if sig['z_score'] > 0 else 'SELL'
                    
                    # BUG-PREVENÇÃO: Verificação de Gap de Spread (Slippage Pre-Flight)
                    # Se o Z-Score saltou demais (ex: de 2.5 para 3.5) entre o sinal e a execução, aborta.
                    current_z = sig['z_score']
                    if abs(current_z) > (z_limit + 1.0):
                        print(f"⚠️ [Par {pair_idx}] Gap de Spread detectado (Z:{current_z:.2f}). Abortando por segurança."); in_critical_section = False; await asyncio.sleep(10); continue

                    print(f"⚡ [Par {pair_idx}] Executando Perna B...")
                    res_b = await executor.execute_market_order(symbol_b, side_b, amt_b)
                    
                    if res_b:
                        real_notional_b = res_b['notional']
                        adjusted_amt_a = real_notional_b / abs(beta)
                        
                        print(f"⚡ [Par {pair_idx}] Executando Perna A (Ajustada: ${adjusted_amt_a:.2f})...")
                        res_a = await executor.execute_market_order(symbol_a, side_a, adjusted_amt_a)
                        
                        if not res_a:
                            print(f"🚨 Falha na Perna A! Neutralizando..."); await safe_close_pair(executor, symbol_a, symbol_b)
                    else:
                        print(f"🚨 Falha na Perna B! Operação cancelada."); 
                    
                    in_critical_section = False
                    consecutive_triggers = 0; await asyncio.sleep(15)
            else:
                consecutive_triggers = 0; await asyncio.sleep(5)

        except asyncio.CancelledError:
            if in_critical_section:
                print(f"⚠️ [Par {pair_idx}] Cancelamento recebido em SEÇÃO CRÍTICA! Finalizando execução pendente...")
                # Tenta garantir que a Perna A seja executada ou o par seja fechado antes de morrer
                # Como é uma CancelledError, temos pouco tempo. O ideal é que o executor não morra.
                continue 
            raise
        except Exception as e:
            in_critical_section = False
            print(f"⚠️ Erro Par {pair_idx}: {e}. Cooldown 30s..."); await asyncio.sleep(30)

async def main():
    db.init_db()
    executor = BinanceExecutor(Config.API_KEY, Config.API_SECRET)
    await executor.connect()
    last_a, last_b, tarefas = [], [], []
    
    # BUG-01: Inicialização do Circuit Breaker
    INITIAL_EQUITY = float(await db.get_config_async("LIVE_BALANCE") or 0.0)
    if INITIAL_EQUITY == 0.0:
        INITIAL_EQUITY = await executor.get_total_equity()

    while True:
        try:
            bot_status = await db.get_config_async("BOT_STATUS")
            eq = await executor.get_total_equity()
            await db.update_config_async("LIVE_BALANCE", f"{eq:.2f}")

            # BUG-01: Circuit Breaker Global (Trailing)
            if INITIAL_EQUITY > 0:
                # Proteção Trailing: Se o capital cresceu, o novo "piso" de stop sobe junto
                if eq > INITIAL_EQUITY:
                    INITIAL_EQUITY = eq
                
                drawdown_pct = ((INITIAL_EQUITY - eq) / INITIAL_EQUITY) * 100
                if drawdown_pct >= Config.GLOBAL_STOP_LOSS_PCT:
                    await db.update_config_async("BOT_STATUS", "OFF")
                    print(f"🛑 CIRCUIT BREAKER: Drawdown de {drawdown_pct:.1f}% atingido. Bot desligado.")
                    # Cancela tarefas ativas
                    for t in tarefas: t.cancel()
                    tarefas, last_a, last_b = [], [], []
                    await asyncio.sleep(60); continue

            if bot_status == "OFF":
                if tarefas:
                    for t in tarefas: t.cancel()
                    tarefas, last_a, last_b = [], [], []
                await asyncio.sleep(5); continue

            # Gestão de Parâmetros
            str_a = await db.get_config_async("SYMBOL_A") or ""
            str_b = await db.get_config_async("SYMBOL_B") or ""
            la = [s.strip().upper() for s in str_a.split(",") if s.strip()]
            lb = [s.strip().upper() for s in str_b.split(",") if s.strip()]
            
            if la != last_a or lb != last_b:
                # BUG-PREVENÇÃO: Verificação de Sobreposição de Ativos
                # Evita que o mesmo ativo seja usado em pares diferentes, o que contaminaria o PnL
                all_assets = la + lb
                if len(all_assets) != len(set(all_assets)):
                    print("🚨 [Erro] Sobreposição de ativos detectada! Cada par deve ter ativos únicos para evitar contaminação de PnL.")
                    await asyncio.sleep(10); continue

                for t in tarefas: t.cancel()
                tarefas = []
                if len(la) == len(lb) > 0:
                    for i in range(len(la)):
                        t = asyncio.create_task(monitorar_par(
                            executor, i, la[i], lb[i], 
                            float(await db.get_config_async("TRADE_AMOUNT_USD") or 6.0), 
                            float(await db.get_config_async("TARGET_PNL_USD") or 0.25), 
                            float(await db.get_config_async("STOP_LOSS_USD") or 1.50), 
                            float(await db.get_config_async("ADX_LIMIT") or 25.0), 
                            float(await db.get_config_async("Z_SCORE_LIMIT") or 2.5), 
                            await db.get_config_async("TIMEFRAME") or "5m", 
                            i * 2
                        ))
                        tarefas.append(t)
                    last_a, last_b = la.copy(), lb.copy()
            await asyncio.sleep(10)
        except Exception as e: print(f"⚠️ Erro Mestre: {e}"); await asyncio.sleep(10)

if __name__ == "__main__": asyncio.run(main())