import asyncio
import database as db
from config import Config
from exchange import BinanceExecutor
from strategy import PairsStrategy

async def monitorar_par(executor, pair_idx, symbol_a, symbol_b, amount, target, stop_loss, adx_limit, z_limit, timeframe, delay):
    await asyncio.sleep(delay) 
    print(f"🚀 [Par {pair_idx}] Iniciando monitorização: {symbol_a} x {symbol_b} (Gráfico: {timeframe} | Gatilho Z: {z_limit})")

    await executor.setup_symbol(symbol_a, Config.LEVERAGE)
    await executor.setup_symbol(symbol_b, Config.LEVERAGE)

    while True:
        try:
            bot_status = await db.get_config_async("BOT_STATUS")
            if bot_status != "ON":
                await asyncio.sleep(5)
                continue

            is_open, current_pnl, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)

            if is_open:
                print(f"[{symbol_a} x {symbol_b}] Posição Aberta | PnL Atual: US$ {current_pnl:.4f}")

                if current_pnl >= target or current_pnl <= -stop_loss:
                    motivo = "LUCRO (TARGET)" if current_pnl >= target else "PREJUÍZO (STOP LOSS)"
                    print(f"🏁 [Par {pair_idx}] Fim do Ciclo por {motivo}. A fechar posições a mercado...")

                    await asyncio.gather(
                        executor.close_position(pos_a),
                        executor.close_position(pos_b)
                    )

                    await db.save_trade_async(symbol_a, symbol_b, current_pnl)
                    print(f"✅ [Par {pair_idx}] Ciclo encerrado e gravado. A aguardar 5s para próxima oportunidade...")
                    await asyncio.sleep(5) # Reduzido para scalping mais rápido
                else:
                    await asyncio.sleep(3)
                continue

            # Agora utiliza o Timeframe dinâmico vindo do painel
            df_a, df_b = await asyncio.gather(
                executor.get_klines(symbol_a, timeframe),
                executor.get_klines(symbol_b, timeframe)
            )

            Config.ADX_LIMIT = adx_limit
            df_spread = PairsStrategy.calculate_indicators(df_a, df_b, Config)
            signals = PairsStrategy.get_signals(df_spread, Config)

            # Verifica contra o Limite Z-Score dinâmico vindo do painel
            if abs(signals['z_score']) > z_limit and signals['adx'] < adx_limit:
                
                margem_necessaria = amount * 2
                saldo_atual = await executor.get_usdt_balance()

                if saldo_atual < margem_necessaria:
                    print(f"⚠️ [Par {pair_idx}] Sinal em {symbol_a}/{symbol_b}, mas saldo insuficiente (US$ {saldo_atual:.2f}). Ignorando...")
                    await asyncio.sleep(10)
                    continue

                side_a = 'BUY' if signals['z_score'] > 0 else 'SELL'
                side_b = 'SELL' if signals['z_score'] > 0 else 'BUY'

                print(f"🚀 [Par {pair_idx}] DISTORÇÃO IDENTIFICADA! Z-Score: {signals['z_score']:.2f}. A executar ordens...")

                results = await asyncio.gather(
                    executor.execute_market_order(symbol_a, side_a, amount),
                    executor.execute_market_order(symbol_b, side_b, amount),
                    return_exceptions=True
                )

                if any(isinstance(r, Exception) for r in results):
                    print(f"🚨 [Par {pair_idx}] FALHA CRÍTICA: Perna manca. A abortar operação!")
                    _, _, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)
                    if not isinstance(results[0], Exception):
                        await executor.close_position(pos_a)
                    if not isinstance(results[1], Exception):
                        await executor.close_position(pos_b)
                    print(f"🛡️ [Par {pair_idx}] Posição neutralizada com sucesso. Margem salva.")

                await asyncio.sleep(10)
            else:
                if pair_idx == 0:
                    status_msg = f"Aguardando {symbol_a}/{symbol_b} (+{max(0, len(str(db.get_config('SYMBOL_A')).split(',')) - 1)} par(es))"
                    await db.update_config_async("LIVE_STATUS", status_msg)
                    await db.update_config_async("LIVE_ZSCORE", f"{signals['z_score']:.2f}")
                    await db.update_config_async("LIVE_ADX", f"{signals['adx']:.2f}")

                print(f"📡 [Par {pair_idx}] A monitorizar {symbol_a}/{symbol_b} | Z-Score: {signals['z_score']:.2f} | ADX: {signals['adx']:.2f}")
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"⚠️ Erro no ciclo do Par {pair_idx} ({symbol_a}/{symbol_b}): {e}. Reiniciando em 5s...")
            await asyncio.sleep(5)

async def main():
    print("🚀 A iniciar Sistema de Arbitragem Quantitativa MULTI-PARES (Nível Produção)...")
    db.init_db()

    executor = BinanceExecutor(Config.API_KEY, Config.API_SECRET)
    await executor.connect()
    print("✅ Conexão com a Binance e regras de mercado carregadas.")

    last_lista_a = []
    last_lista_b = []
    tarefas_ativas = []

    while True:
        try:
            bot_status = await db.get_config_async("BOT_STATUS")
            
            current_balance = await executor.get_usdt_balance()
            await db.update_config_async("LIVE_BALANCE", f"{current_balance:.2f}")

            if bot_status == "OFF":
                if tarefas_ativas:
                    print("💤 Robô pausado pelo Painel. A desligar o Polvo...")
                    for t in tarefas_ativas:
                        t.cancel()
                    tarefas_ativas.clear()
                    last_lista_a = []
                    last_lista_b = []
                await asyncio.sleep(5)
                continue

            # Puxa os novos parâmetros adicionados à base de dados
            config_keys = ["SYMBOL_A", "SYMBOL_B", "TRADE_AMOUNT_USD", "TARGET_PNL_USD", "STOP_LOSS_USD", "ADX_LIMIT", "Z_SCORE_LIMIT", "TIMEFRAME"]
            config_vals = await asyncio.gather(*(db.get_config_async(k) for k in config_keys))

            str_sym_a = config_vals[0] or ""
            str_sym_b = config_vals[1] or ""
            
            lista_a = [s.strip().upper() for s in str_sym_a.split(",") if s.strip()]
            lista_b = [s.strip().upper() for s in str_sym_b.split(",") if s.strip()]
            
            amount = float(config_vals[2])
            target = float(config_vals[3])
            stop = float(config_vals[4])
            adx_limit = float(config_vals[5])
            z_limit = float(config_vals[6] or 2.0)
            timeframe = config_vals[7] or "5m"

            if lista_a != last_lista_a or lista_b != last_lista_b:
                print("🔄 Mudança detetada nos parâmetros. A reconfigurar o Polvo...")
                
                for t in tarefas_ativas:
                    t.cancel()
                tarefas_ativas.clear()

                if len(lista_a) == len(lista_b) and len(lista_a) > 0:
                    print(f"🐙 A iniciar MODO MULTI-PARES ({len(lista_a)} pares em simultâneo)...")
                    
                    for i in range(len(lista_a)):
                        delay_inicial = i * 1.5 
                        tarefa = asyncio.create_task(
                            monitorar_par(executor, i, lista_a[i], lista_b[i], amount, target, stop, adx_limit, z_limit, timeframe, delay_inicial)
                        )
                        tarefas_ativas.append(tarefa)
                    
                    last_lista_a = lista_a.copy()
                    last_lista_b = lista_b.copy()
                else:
                    print("❌ Erro: O número de ativos A é diferente de B ou a lista está vazia.")
                    await db.update_config_async("BOT_STATUS", "OFF")
                    last_lista_a = []
                    last_lista_b = []
            
            await asyncio.sleep(5)

        except Exception as e:
            print(f"⚠️ Erro no gestor mestre: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())