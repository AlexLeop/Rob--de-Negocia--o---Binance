import asyncio
import database as db
from config import Config
from exchange import BinanceExecutor
from strategy import PairsStrategy

async def safe_close_pair(executor, symbol_a, symbol_b):
    """Garante que ambas as posições sejam zeradas, tentando repetidamente se necessário."""
    print(f"🔄 [OMS] Iniciando fechamento garantido para {symbol_a} e {symbol_b}...")
    
    while True:
        try:
            is_open, _, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)
            if not is_open:
                print(f"✅ [OMS] Par {symbol_a}/{symbol_b} neutralizado com sucesso.")
                break
            
            # Tenta fechar o que estiver aberto e limpa ordens
            tasks = []
            if pos_a and abs(float(pos_a['positionAmt'])) > 1e-8:
                tasks.append(executor.close_position(pos_a))
                tasks.append(executor.cancel_all_orders(symbol_a))
            if pos_b and abs(float(pos_b['positionAmt'])) > 1e-8:
                tasks.append(executor.close_position(pos_b))
                tasks.append(executor.cancel_all_orders(symbol_b))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            await asyncio.sleep(1)
        except Exception as e:
            print(f"⚠️ [OMS] Erro durante fecho garantido: {e}. Retentando...")
            await asyncio.sleep(2)

async def monitorar_par(executor, pair_idx, symbol_a, symbol_b, amount, target, stop_loss, adx_limit, z_limit, timeframe, delay):
    await asyncio.sleep(delay) 
    print(f"🚀 [Par {pair_idx}] Iniciando monitorização: {symbol_a} x {symbol_b} (Gráfico: {timeframe} | Gatilho Z: {z_limit})")

    await executor.setup_symbol(symbol_a, Config.LEVERAGE)
    await executor.setup_symbol(symbol_b, Config.LEVERAGE)

    # Memória de persistência contra Repainting (Falsos Spikes)
    consecutive_triggers = 0 

    while True:
        try:
            bot_status = await db.get_config_async("BOT_STATUS")
            if bot_status != "ON":
                await asyncio.sleep(5)
                continue

            # 1. OBTENÇÃO E CÁLCULO ESTATÍSTICO (O Cérebro atua primeiro)
            df_a, df_b = await asyncio.gather(
                executor.get_klines(symbol_a, timeframe),
                executor.get_klines(symbol_b, timeframe)
            )

            df_spread, beta_dinamico = PairsStrategy.calculate_indicators(df_a, df_b, Config)
            signals = PairsStrategy.get_signals(df_spread, Config)
            z_atual = signals['z_score']

            # 2. VERIFICAÇÃO DE POSIÇÕES E GESTÃO DE SAÍDA
            is_open, current_pnl, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)

            if is_open:
                consecutive_triggers = 0 # Reinicia o contador se já estiver posicionado
                print(f"[{symbol_a} x {symbol_b}] Posição Aberta | PnL Atual: US$ {current_pnl:.4f}")

                # --- STOP TÉCNICO (Quebra de Cointegração) ---
                if abs(z_atual) >= 4.0:
                    print(f"🚨 [Par {pair_idx}] STOP TÉCNICO! Z-Score atingiu {z_atual:.2f}. Tese quebrada. Acionando OMS Safe Close...")
                    await safe_close_pair(executor, symbol_a, symbol_b)
                    await db.save_trade_async(symbol_a, symbol_b, current_pnl)
                    print(f"✅ [Par {pair_idx}] Ciclo encerrado por falha matemática. Aguardando 15s...")
                    await asyncio.sleep(15)
                    continue

                if current_pnl >= target or current_pnl <= -stop_loss:
                    motivo = "LUCRO (TARGET)" if current_pnl >= target else "PREJUÍZO (STOP LOSS)"
                    print(f"🏁 [Par {pair_idx}] Fim do Ciclo por {motivo}. Acionando OMS Safe Close...")
                    await safe_close_pair(executor, symbol_a, symbol_b)
                    
                    await db.save_trade_async(symbol_a, symbol_b, current_pnl)
                    print(f"✅ [Par {pair_idx}] Ciclo encerrado. Aguardando próxima oportunidade...")
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(3)
                continue

            # --- 3. LÓGICA DE ENTRADA (Hedge Ratio, Half-Life e Filtro de Persistência) ---
            if abs(z_atual) > z_limit and signals['adx'] < adx_limit and signals['half_life'] < 12.0:
                
                consecutive_triggers += 1
                print(f"⏱️ [Par {pair_idx}] Anomalia detetada ({consecutive_triggers}/3) | Z={z_atual:.2f}")

                if consecutive_triggers >= 3:
                    # APLICAÇÃO DO BETA (Exposição Delta Neutral)
                    amount_a_base = amount
                    amount_b_base = amount * abs(beta_dinamico)

                    # --- NOVA SOLUÇÃO: AUTO-ESCALA PROPORCIONAL ---
                    # Se uma das pernas for menor que 5.5, calculamos um fator de escala 
                    # para puxar a perna mais fraca para o mínimo exigido e subimos a outra na mesma proporção.
                    min_leg = min(amount_a_base, amount_b_base)
                    
                    if min_leg < 5.5:
                        fator_escala = 5.5 / min_leg
                        amount_a = amount_a_base * fator_escala
                        amount_b = amount_b_base * fator_escala
                        print(f"⚖️ [Par {pair_idx}] Auto-Escala ativada (Fator: {fator_escala:.2f}). Novos Lotes -> A: {amount_a:.2f} | B: {amount_b:.2f}")
                    else:
                        amount_a = amount_a_base
                        amount_b = amount_b_base

                    # --- LIMITADOR DE ANOMALIA EXTREMA ---
                    # Se o Beta for tão distorcido que a Perna Maior passe de US$ 80 de nocional, aí sim abortamos.
                    if amount_a > 80.0 or amount_b > 80.0:
                        print(f"⚠️ [Par {pair_idx}] Abortado: Beta extremo exigiu um lote perigosamente alto (A: {amount_a:.2f} | B: {amount_b:.2f}).")
                        consecutive_triggers = 0
                        await asyncio.sleep(20)
                        continue

                    # --- CORREÇÃO DO DIRETOR: MARGEM REAL ---
                    margem_real_necessaria = (amount_a + amount_b) / Config.LEVERAGE
                    saldo_atual = await executor.get_usdt_balance()

                    if saldo_atual < margem_real_necessaria:
                        print(f"⚠️ [Par {pair_idx}] Saldo insuficiente para o Hedge (Requer US$ {margem_real_necessaria:.2f} | Atual: US$ {saldo_atual:.2f}). A ignorar...")
                        consecutive_triggers = 0
                        await asyncio.sleep(10)
                        continue

                    side_a = 'SELL' if z_atual > 0 else 'BUY'
                    side_b = 'BUY' if z_atual > 0 else 'SELL'

                    print(f"🚀 [Par {pair_idx}] DISTORÇÃO CONFIRMADA! Z={z_atual:.2f} | Beta={beta_dinamico:.2f}. Executando via OMS...")

                    # Execução Atômica
                    try:
                        results = await asyncio.gather(
                            executor.execute_market_order(symbol_a, side_a, amount_a),
                            executor.execute_market_order(symbol_b, side_b, amount_b),
                            return_exceptions=True
                        )
                        
                        if any(isinstance(r, Exception) for r in results):
                            raise Exception("Falha numa das pernas da execução.")
                            
                        print(f"✅ [Par {pair_idx}] Entrada concluída. A colocar proteção nativa...")
                        consecutive_triggers = 0 # Reinicia após entrar
                        
                        for order in results:
                            if isinstance(order, dict) and 'symbol' in order:
                                symbol = order['symbol']
                                side = order['side']
                                qty = float(order['origQty'])
                                avg_price = float(order.get('avgPrice', 0))
                                
                                if avg_price == 0:
                                    t = await executor.client.futures_symbol_ticker(symbol=symbol)
                                    avg_price = float(t['price'])
                                
                                stop_side = 'SELL' if side == 'BUY' else 'BUY'
                                distancia = 0.10
                                stop_price = avg_price * (1 - distancia) if side == 'BUY' else avg_price * (1 + distancia)
                                
                                await executor.place_stop_market_order(symbol, stop_side, qty, stop_price)

                    except Exception as e:
                        print(f"🚨 [Par {pair_idx}] ERRO NA ENTRADA: {e}. A neutralizar capital...")
                        await safe_close_pair(executor, symbol_a, symbol_b)
                        consecutive_triggers = 0

                    await asyncio.sleep(10)
                else:
                    # Pausa mais curta para validar a persistência da anomalia rapidamente
                    await asyncio.sleep(3)
            else:
                consecutive_triggers = 0 # Reinicia o contador se o sinal desaparecer
                
                if pair_idx == 0:
                    status_msg = f"Aguardando {symbol_a}/{symbol_b} (+{max(0, len(str(db.get_config('SYMBOL_A')).split(',')) - 1)} par(es))"
                    await db.update_config_async("LIVE_STATUS", status_msg)
                    await db.update_config_async("LIVE_ZSCORE", f"{z_atual:.2f}")
                    await db.update_config_async("LIVE_ADX", f"{signals['adx']:.2f}")

                print(f"📡 [Par {pair_idx}] A monitorizar {symbol_a}/{symbol_b} | Z: {z_atual:.2f} | ADX: {signals['adx']:.2f} | HL: {signals['half_life']:.1f}")
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"⚠️ Erro no ciclo do Par {pair_idx} ({symbol_a}/{symbol_b}): {e}. A reiniciar em 5s...")
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
            
            # --- GESTÃO DE CAPITAL E DISJUNTOR DE EQUITY ---
            current_equity = await executor.get_total_equity()
            await db.update_config_async("LIVE_BALANCE", f"{current_equity:.2f}")

            if bot_status == "ON":
                db_initial = await db.get_config_async("INITIAL_EQUITY")
                if db_initial is None or db_initial == "None":
                    await db.update_config_async("INITIAL_EQUITY", str(current_equity))
                    initial_equity = current_equity
                    print(f"💎 [OMS] Capital Inicial REGISTADO no DB: US$ {initial_equity:.2f}")
                else:
                    initial_equity = float(db_initial)

                drawdown_max = initial_equity * (Config.GLOBAL_STOP_LOSS_PCT / 100)
                perda_atual = initial_equity - current_equity

                if perda_atual >= drawdown_max:
                    print(f"🚨🚨🚨 [DISJUNTOR GLOBAL ACIONADO] 🚨🚨🚨")
                    print(f"Perda de US$ {perda_atual:.2f} atingiu o limite de {Config.GLOBAL_STOP_LOSS_PCT}%")
                    await db.update_config_async("BOT_STATUS", "OFF")
                    await db.update_config_async("INITIAL_EQUITY", "None") 
                    
                    for t in tarefas_ativas:
                        t.cancel()
                    tarefas_ativas.clear()
                    
                    print("🛡️ [OMS] Executando Safe Close em todos os pares ativos...")
                    for i in range(len(last_lista_a)):
                        asyncio.create_task(safe_close_pair(executor, last_lista_a[i], last_lista_b[i]))
                    
                    continue

            if bot_status == "OFF":
                await db.update_config_async("INITIAL_EQUITY", "None") 
                if tarefas_ativas:
                    print("💤 Robô pausado pelo Painel. A desligar o Polvo...")
                    for t in tarefas_ativas:
                        t.cancel()
                    tarefas_ativas.clear()
                    last_lista_a = []
                    last_lista_b = []
                await asyncio.sleep(5)
                continue

            # --- GESTÃO DINÂMICA DE PARÂMETROS ---
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
                if last_lista_a:
                    print("🔄 [OMS] Mudança de parâmetros detetada. A verificar posições abertas...")
                    posicoes_abertas = False
                    for i in range(len(last_lista_a)):
                        is_open, _, _, _ = await executor.get_positions_pnl(last_lista_a[i], last_lista_b[i])
                        if is_open:
                            posicoes_abertas = True
                            print(f"⚠️ [OMS] Impossível mudar par {last_lista_a[i]}/{last_lista_b[i]} agora: Posição Ativa.")
                    
                    if posicoes_abertas:
                        print("❌ [OMS] Reconfiguração abortada para proteger capital exposto.")
                        await asyncio.sleep(10)
                        continue

                print("🔄 [OMS] Mudança detetada e segura. A reconfigurar...")
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