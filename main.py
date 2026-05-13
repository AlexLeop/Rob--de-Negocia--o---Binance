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

async def monitorar_par(executor, pair_idx, symbol_a, symbol_b, amount, target, stop, adx_limit, z_limit, timeframe, delay):
    await asyncio.sleep(delay)
    print(f"🚀 [Par {pair_idx}] Scanner Ativo: {symbol_a}/{symbol_b}")
    await executor.setup_symbol(symbol_a, Config.LEVERAGE)
    await executor.setup_symbol(symbol_b, Config.LEVERAGE)

    consecutive_triggers = 0 

    while True:
        try:
            if await db.get_config_async("BOT_STATUS") != "ON":
                await asyncio.sleep(5); continue

            # 1. Indicadores com Pearson
            df_a, df_b = await asyncio.gather(executor.get_klines(symbol_a, timeframe), executor.get_klines(symbol_b, timeframe))
            df_spread, beta = PairsStrategy.calculate_indicators(df_a, df_b, Config)
            sig = PairsStrategy.get_signals(df_spread, Config)
            
            is_open, pnl, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)

            # 2. Gestão de Saída
            if is_open:
                consecutive_triggers = 0
                if abs(sig['z_score']) >= 4.0 or pnl >= target or pnl <= -stop:
                    await safe_close_pair(executor, symbol_a, symbol_b)
                    await db.save_trade_async(symbol_a, symbol_b, pnl)
                    await asyncio.sleep(15)
                else: await asyncio.sleep(3)
                continue

            # 3. FIREWALL DE ENTRADA (Anti-Loop SOL)
            if abs(sig['z_score']) > z_limit and sig['adx'] < adx_limit and sig['half_life'] < 15.0:
                consecutive_triggers += 1
                print(f"⏱️ [Par {pair_idx}] Sinal ({consecutive_triggers}/3) Z:{sig['z_score']:.2f}")

                if consecutive_triggers >= 3:
                    amt_a = amount
                    amt_b = amount * abs(beta)
                    if min(amt_a, amt_b) < 5.5:
                        f = 5.5 / min(amt_a, amt_b)
                        amt_a *= f; amt_b *= f

                    # --- VALIDAÇÃO ATÔMICA DO PAR ---
                    valid, msg = await executor.validate_pair_pre_flight(symbol_a, amt_a, symbol_b, amt_b)
                    if not valid:
                        print(f"⚠️ [Par {pair_idx}] Abortado: {msg}. Cooldown 60s."); await asyncio.sleep(60); continue

                    # --- FILTRO DE CORRELAÇÃO DE PEARSON ---
                    if sig.get('correlation', 0) < 0.70:
                        print(f"⚠️ [Par {pair_idx}] Correlação baixa ({sig['correlation']:.2f}). Ignorando..."); await asyncio.sleep(10); continue

                    # --- EXECUÇÃO SEQUENCIAL BLINDADA ---
                    side_a = 'SELL' if sig['z_score'] > 0 else 'BUY'
                    side_b = 'BUY' if sig['z_score'] > 0 else 'SELL'
                    
                    print(f"⚡ [Par {pair_idx}] Executando Perna B...")
                    order_b = await executor.execute_market_order(symbol_b, side_b, amt_b)
                    if order_b:
                        print(f"⚡ [Par {pair_idx}] Executando Perna A...")
                        order_a = await executor.execute_market_order(symbol_a, side_a, amt_a)
                        if not order_a:
                            print(f"🚨 Falha na Perna A! Neutralizando..."); await safe_close_pair(executor, symbol_a, symbol_b)
                    else:
                        print(f"🚨 Falha na Perna B! Operação cancelada."); await asyncio.sleep(60)
                    
                    consecutive_triggers = 0; await asyncio.sleep(15)
            else:
                consecutive_triggers = 0; await asyncio.sleep(5)

        except Exception as e:
            print(f"⚠️ Erro Par {pair_idx}: {e}. Cooldown 30s..."); await asyncio.sleep(30)

async def main():
    db.init_db()
    executor = BinanceExecutor(Config.API_KEY, Config.API_SECRET)
    await executor.connect()
    last_a, last_b, tarefas = [], [], []

    while True:
        try:
            bot_status = await db.get_config_async("BOT_STATUS")
            eq = await executor.get_total_equity()
            await db.update_config_async("LIVE_BALANCE", f"{eq:.2f}")

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
                for t in tarefas: t.cancel()
                tarefas = []
                if len(la) == len(lb) > 0:
                    for i in range(len(la)):
                        t = asyncio.create_task(monitorar_par(executor, i, la[i], lb[i], float(await db.get_config_async("TRADE_AMOUNT_USD")), float(await db.get_config_async("TARGET_PNL_USD")), float(await db.get_config_async("STOP_LOSS_USD")), float(await db.get_config_async("ADX_LIMIT")), float(await db.get_config_async("Z_SCORE_LIMIT")), await db.get_config_async("TIMEFRAME"), i * 2))
                        tarefas.append(t)
                    last_a, last_b = la.copy(), lb.copy()
            await asyncio.sleep(10)
        except Exception as e: print(f"⚠️ Erro Mestre: {e}"); await asyncio.sleep(10)

if __name__ == "__main__": asyncio.run(main())