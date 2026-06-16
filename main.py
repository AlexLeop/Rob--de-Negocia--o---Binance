import asyncio
import time
import json
import core.database as db
from core.config import Config
from core.exchange import BinanceExecutor
from core.strategy import PairsStrategy
from core.scanner import run_market_scan_async

async def safe_close_pair(executor, symbol_a, symbol_b):
    """Zera posições de forma agressiva e limpa ordens pendentes."""
    print(f"🧹 [OMS] Neutralizando par {symbol_a}/{symbol_b}...")
    for _ in range(3): # 3 tentativas de limpeza
        is_open, _, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)
        if not is_open: break
        if pos_a and abs(float(pos_a['positionAmt'])) > 1e-8:
            await executor.cancel_all_orders(symbol_a)
            await executor.close_position(pos_a)
        if pos_b and abs(float(pos_b['positionAmt'])) > 1e-8:
            await executor.cancel_all_orders(symbol_b)
            await executor.close_position(pos_b)
        await asyncio.sleep(1)
        
    for sym in [symbol_a, symbol_b]:
        await db.update_config_async(f"TREND_SURFING_{sym}", "")
        await db.update_config_async(f"MAX_PNL_{sym}", "")

async def monitorar_par(executor, pair_idx, symbol_a, symbol_b, initial_amount, initial_target, initial_stop, initial_adx, initial_z, initial_tf, delay):
    await asyncio.sleep(delay)
    print(f"🚀 [Par {pair_idx}] Scanner Ativo: {symbol_a}/{symbol_b}")
    lev_a = await executor.setup_symbol(symbol_a, Config.LEVERAGE)
    lev_b = await executor.setup_symbol(symbol_b, Config.LEVERAGE)

    # VULN M: Amnésia de Posição (Double Exposure Recovery)
    is_open_init, _, pos_a_init, pos_b_init = await executor.get_positions_pnl(symbol_a, symbol_b)
    qty_a = float(pos_a_init['positionAmt']) if pos_a_init else 0.0
    qty_b = float(pos_b_init['positionAmt']) if pos_b_init else 0.0
    
    if abs(qty_a) > 0 or abs(qty_b) > 0:
        is_open = True
        print(f"⚠️ [Par {pair_idx}] Sincronização (Amnésia Evitada)! Posições ativas recuperadas da corretora.")
    else:
        is_open = False


    in_critical_section = False
    peak_z_score = 0.0

    while True:
        try:
            if await db.get_config_async("BOT_STATUS") != "ON":
                await asyncio.sleep(5); continue
            
            base_amount = float(await db.get_config_async("TRADE_AMOUNT_USD") or initial_amount)
            bonus_amount = float(await db.get_config_async(f"CICLO_BONUS_{pair_idx}") or 0.0)
            # Limita a exposição máxima com bônus para nunca exceder o dobro do valor base (Controle de Risco)
            amount = min(base_amount + bonus_amount, base_amount * 2.0)
            
            target = float(await db.get_config_async("TARGET_PNL_USD") or initial_target)
            stop = float(await db.get_config_async("STOP_LOSS_USD") or initial_stop)
            adx_limit = float(await db.get_config_async("ADX_LIMIT") or initial_adx)
            z_limit = float(await db.get_config_async("Z_SCORE_LIMIT") or initial_z)
            timeframe = await db.get_config_async("TIMEFRAME") or initial_tf

            # 1. Obter estado das posições (Rápido, não depende de indicadores)
            is_open, pnl, pos_a, pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)
            
            # VULN S: Deteção de Liquidação Fantasma
            if is_open:
                qty_a_live = float(pos_a['positionAmt']) if pos_a else 0.0
                qty_b_live = float(pos_b['positionAmt']) if pos_b else 0.0
                
                # Checa se é apenas um Trend Surfing legítimo
                is_surfing_a = await db.get_config_async(f"TREND_SURFING_{symbol_a}") == "ACTIVE"
                is_surfing_b = await db.get_config_async(f"TREND_SURFING_{symbol_b}") == "ACTIVE"
                
                if (qty_a_live == 0.0 or qty_b_live == 0.0) and not (is_surfing_a or is_surfing_b):
                    print(f"💀💀 [Par {pair_idx}] ALERTA QUÂNTICO (VULN S)! Perna desapareceu misteriosamente na Binance. Liquidação ou fechamento externo detectado! Executando resgate.")
                    await safe_close_pair(executor, symbol_a, symbol_b)
                    is_open = False
                    in_critical_section = False
                    await db.update_config_async(f"TRADE_STATUS_{symbol_a}", "FECHADO")
                    continue

            # --- ESSÊNCIA MQL5 / PILAR 4: Proteção Anti-Perna Solta e Trailing Stop ---
            if is_open:
                amt_a = float(pos_a.get('positionAmt') or 0.0) if pos_a else 0.0
                amt_b = float(pos_b.get('positionAmt') or 0.0) if pos_b else 0.0
                is_surfing_a = await db.get_config_async(f"TREND_SURFING_{symbol_a}") == "ACTIVE"
                is_surfing_b = await db.get_config_async(f"TREND_SURFING_{symbol_b}") == "ACTIVE"

                if (abs(amt_a) > 1e-8 and abs(amt_b) <= 1e-8) or (abs(amt_b) > 1e-8 and abs(amt_a) <= 1e-8):
                    # Se for Legging Out (Pilar 4), nós toleramos a perna solta e aplicamos Trailing Stop
                    if is_surfing_a:
                        pnl_a = float(pos_a.get('unRealizedProfit', 0)) if pos_a else 0.0
                        max_pnl = float(await db.get_config_async(f"MAX_PNL_{symbol_a}") or pnl_a)
                        if pnl_a > max_pnl: await db.update_config_async(f"MAX_PNL_{symbol_a}", str(pnl_a))
                        
                        # VULN A: Trailing Stop agressivo (Guarda 85% do lucro máximo, mas apenas se lucrou mais de $1)
                        if max_pnl >= 1.00 and pnl_a < max_pnl * 0.85:
                            print(f"🏄 [Trend Surfing] Trailing Stop acionado em {symbol_a}! Fechando lucro de ${pnl_a:.2f}")
                            await safe_close_pair(executor, symbol_a, symbol_b)
                            await db.update_config_async(f"TREND_SURFING_{symbol_a}", "")
                            await db.update_config_async(f"MAX_PNL_{symbol_a}", "")
                        await asyncio.sleep(5)
                        continue
                    
                    elif is_surfing_b:
                        pnl_b = float(pos_b.get('unRealizedProfit', 0)) if pos_b else 0.0
                        max_pnl = float(await db.get_config_async(f"MAX_PNL_{symbol_b}") or pnl_b)
                        if pnl_b > max_pnl: await db.update_config_async(f"MAX_PNL_{symbol_b}", str(pnl_b))
                        
                        if max_pnl >= 1.00 and pnl_b < max_pnl * 0.85:
                            print(f"🏄 [Trend Surfing] Trailing Stop acionado em {symbol_b}! Fechando lucro de ${pnl_b:.2f}")
                            await safe_close_pair(executor, symbol_a, symbol_b)
                            await db.update_config_async(f"TREND_SURFING_{symbol_b}", "")
                            await db.update_config_async(f"MAX_PNL_{symbol_b}", "")
                        await asyncio.sleep(5)
                        continue
                        
                    else:
                        print(f"🚨 [Par {pair_idx}] PERNA SOLTA DETECTADA (Acidental)! Acionando fechamento de emergência...")
                        await safe_close_pair(executor, symbol_a, symbol_b)
                        await asyncio.sleep(10)
                        continue

            # 2. Health check (só bloqueia entradas)
            if not executor.health.is_healthy() and not is_open:
                print(f"⚠️ [Par {pair_idx}] API instável ({executor.health.fail_rate():.0%} falhas). Pausando entradas...")
                await asyncio.sleep(60)
                continue

            # 3. Calcular indicadores
            df_a, df_b = await asyncio.gather(executor.get_klines(symbol_a, timeframe, limit=250), executor.get_klines(symbol_b, timeframe, limit=250))
            result = PairsStrategy.calculate_indicators(df_a, df_b, Config)
            if result[0] is None:
                await asyncio.sleep(5); continue
            
            df_spread, beta = result
            sig = PairsStrategy.get_signals(df_spread, Config)
            if sig is None:
                await asyncio.sleep(5); continue
            
            current_candle_ts = df_spread.index[-1]
            
            # Atualizar radar
            await db.update_config_async(f"LIVE_ZSCORE_{pair_idx}", f"{sig['z_score']:.2f}")
            await db.update_config_async(f"LIVE_ADX_{pair_idx}", f"{sig['adx']:.2f}")
            status_desc = 'POSIÇÃO ABERTA' if is_open else ('Armado (Aguardando Hook)' if peak_z_score != 0.0 else 'Monitorando')
            status_txt = f"Par {pair_idx}: {symbol_a}/{symbol_b} | {status_desc}"
            await db.update_config_async(f"LIVE_STATUS_{pair_idx}", status_txt)

            # 4. Gestão de Saída
            if is_open:
                entry_z_str = await db.get_config_async(f"ENTRY_Z_{symbol_a}")
                entry_z = float(entry_z_str) if entry_z_str else 0.0
                
                reverteu_media = False
                if entry_z > 0 and sig['z_score'] <= 0.0: reverteu_media = True
                if entry_z < 0 and sig['z_score'] >= 0.0: reverteu_media = True
                
                # Calcula duração
                entry_time_str = await db.get_config_async(f"ENTRY_TIME_{symbol_a}")
                duration = 0.0
                if entry_time_str:
                    try:
                        duration = (time.time() - float(entry_time_str)) / 60.0
                    except: pass
                
                # Calcula ROI%
                invested_str = await db.get_config_async(f"INVESTED_{symbol_a}")
                roi = 0.0
                if invested_str:
                    try:
                        invested = float(invested_str)
                        if invested > 0:
                            roi = (pnl / invested) * 100.0
                    except: pass
                
                # VULN N: Half-Life Time Stop (Substitui 48h fixo)
                half_life = sig.get('half_life', 999.0)
                tf_min = int(''.join(filter(str.isdigit, timeframe))) if any(c.isdigit() for c in timeframe) else 5
                hl_limit_min = half_life * tf_min * 3 # Tolera até 3x o Half-Life
                if hl_limit_min <= 0 or hl_limit_min > (48 * 60): hl_limit_min = 48 * 60 # Cap máximo de 48h
                
                if duration > hl_limit_min and is_open:
                    print(f"⏰ [Time Stop] Par {symbol_a}/{symbol_b} atingiu {hl_limit_min:.1f} minutos (3x Half-Life). Equação desfeita.")
                    await safe_close_pair(executor, symbol_a, symbol_b)
                    await db.save_trade_async(symbol_a, symbol_b, pnl, "TIME_STOP_HALFLIFE", sig['z_score'], duration, roi)
                    await asyncio.sleep(5)
                    continue
                
                if abs(sig['z_score']) >= 4.0 or pnl >= target or pnl <= -stop or reverteu_media:
                    in_critical_section = True
                    motivo = "Reversão à Média" if reverteu_media else ("Take Profit" if pnl >= target else "Stop Loss")
                    if abs(sig['z_score']) >= 4.0 and not reverteu_media:
                        motivo = "Stop Z-Score Extremo"
                        
                    print(f"🧹 [Par {pair_idx}] Fechando Posição. Motivo: {motivo} | PnL: {pnl:.2f} | ROI: {roi:.2f}% | Z: {sig['z_score']:.2f}")
                    
                    # --- PILAR 4: TREND SURFING (Legging Out Direcional) ---
                    # Só tenta leg out se a causa for um rompimento contra a cointegração
                    if motivo == "Stop Loss" or motivo == "Stop Z-Score Extremo":
                        adx_a = PairsStrategy.calc_adx(df_a['high'], df_a['low'], df_a['close'], period=14).iloc[-1]
                        adx_b = PairsStrategy.calc_adx(df_b['high'], df_b['low'], df_b['close'], period=14).iloc[-1]
                        
                        pnl_a = float(pos_a.get('unRealizedProfit', 0)) if pos_a else 0.0
                        pnl_b = float(pos_b.get('unRealizedProfit', 0)) if pos_b else 0.0
                        
                        # Se A estiver puxando forte pro lucro e B afundando o par (Ruptura Estrutural)
                        if pnl_a > 0 and pnl_b < 0 and abs(sig['z_score']) >= 4.0 and sig['adx'] > 30:
                            print(f"🚀 [Par {pair_idx}] PIVOT DIRECCIONAL! Cortando {symbol_b} (Perdedora) e surfando tendência em {symbol_a} (ADX: {adx_a:.1f})")
                            await executor.cancel_all_orders(symbol_b)
                            if pos_b: await executor.close_position(pos_b)
                            await db.update_config_async(f"TREND_SURFING_{symbol_a}", "ACTIVE")
                            
                            # Micro-Loop de Trailing Stop Isolado (Bypass VULN S e Z-Score)
                            print(f"🌊 [Trend Surfing] Ativando Trailing Stop isolado para {symbol_a}...")
                            highest_pnl = pnl_a
                            while True:
                                await asyncio.sleep(5)
                                if await db.get_config_async("BOT_STATUS") != "ON": break
                                
                                _, _, current_pos_a, _ = await executor.get_positions_pnl(symbol_a, symbol_b)
                                if not current_pos_a or abs(float(current_pos_a['positionAmt'])) < 1e-8:
                                    print(f"🛑 [Trend Surfing] Posição {symbol_a} encerrada externamente.")
                                    break
                                
                                current_pnl = float(current_pos_a['unRealizedProfit'])
                                if current_pnl > highest_pnl: highest_pnl = current_pnl
                                
                                if current_pnl < (highest_pnl * 0.85): # Trailing de 15%
                                    print(f"🛑 [Trend Surfing] Trailing Stop acionado em {symbol_a}! Lucro Retido: ${current_pnl:.2f} (Topo: ${highest_pnl:.2f})")
                                    await executor.cancel_all_orders(symbol_a)
                                    await executor.close_position(current_pos_a)
                                    break
                                    
                            await db.update_config_async(f"TREND_SURFING_{symbol_a}", "")
                            in_critical_section = False
                            continue
                        # Se B estiver puxando forte pro lucro e A afundando o par (Ruptura Estrutural)
                        elif pnl_b > 0 and pnl_a < 0 and abs(sig['z_score']) >= 4.0 and sig['adx'] > 30:
                            print(f"🚀 [Par {pair_idx}] PIVOT DIRECCIONAL! Cortando {symbol_a} (Perdedora) e surfando tendência em {symbol_b} (ADX: {adx_b:.1f})")
                            await executor.cancel_all_orders(symbol_a)
                            if pos_a: await executor.close_position(pos_a)
                            await db.update_config_async(f"TREND_SURFING_{symbol_b}", "ACTIVE")
                            
                            # Micro-Loop de Trailing Stop Isolado (Bypass VULN S e Z-Score)
                            print(f"🌊 [Trend Surfing] Ativando Trailing Stop isolado para {symbol_b}...")
                            highest_pnl = pnl_b
                            while True:
                                await asyncio.sleep(5)
                                if await db.get_config_async("BOT_STATUS") != "ON": break
                                
                                _, _, _, current_pos_b = await executor.get_positions_pnl(symbol_a, symbol_b)
                                if not current_pos_b or abs(float(current_pos_b['positionAmt'])) < 1e-8:
                                    print(f"🛑 [Trend Surfing] Posição {symbol_b} encerrada externamente.")
                                    break
                                
                                current_pnl = float(current_pos_b['unRealizedProfit'])
                                if current_pnl > highest_pnl: highest_pnl = current_pnl
                                
                                if current_pnl < (highest_pnl * 0.85): # Trailing de 15%
                                    print(f"🛑 [Trend Surfing] Trailing Stop acionado em {symbol_b}! Lucro Retido: ${current_pnl:.2f} (Topo: ${highest_pnl:.2f})")
                                    await executor.cancel_all_orders(symbol_b)
                                    await executor.close_position(current_pos_b)
                                    break
                                    
                            await db.update_config_async(f"TREND_SURFING_{symbol_b}", "")
                            in_critical_section = False
                            continue

                    # Fechamento normal
                    await safe_close_pair(executor, symbol_a, symbol_b)
                    await db.save_trade_async(symbol_a, symbol_b, pnl, motivo, sig['z_score'], duration, roi)
                    
                    # Atualiza PnL Total Acumulado para o Dashboard
                    total_pnl = float(await db.get_config_async("TOTAL_PNL") or 0.0) + pnl
                    await db.update_config_async("TOTAL_PNL", str(total_pnl))
                    
                    # --- ESSÊNCIA MQL5: Gestão de Ciclos (Reinvestimento) ---
                    if pnl > 0 and motivo != "Stop Loss" and motivo != "Stop Z-Score Extremo":
                        ciclo = int(await db.get_config_async(f"CICLO_CONTADOR_{pair_idx}") or 0)
                        if ciclo < 3:
                            ciclo += 1
                            incremento = pnl * 0.5
                            await db.update_config_async(f"CICLO_BONUS_{pair_idx}", str(bonus_amount + incremento))
                            await db.update_config_async(f"CICLO_CONTADOR_{pair_idx}", str(ciclo))
                            print(f"🔄 [Ciclos] Vitória! Ciclo {ciclo}/3 - Bônus margem adicionado: +${incremento:.2f}")
                        else:
                            await db.update_config_async(f"CICLO_BONUS_{pair_idx}", "0")
                            await db.update_config_async(f"CICLO_CONTADOR_{pair_idx}", "0")
                            print(f"🔄 [Ciclos] Ciclo Completo (3/3)! Resetando lotes para a base.")
                    else:
                        await db.update_config_async(f"CICLO_BONUS_{pair_idx}", "0")
                        await db.update_config_async(f"CICLO_CONTADOR_{pair_idx}", "0")
                        print(f"🔄 [Ciclos] RESET | Margens resetadas para a base.")
                    
                    # Limpa cache
                    await db.update_config_async(f"ENTRY_TIME_{symbol_a}", "")
                    await db.update_config_async(f"INVESTED_{symbol_a}", "")
                    await db.update_config_async(f"ENTRY_Z_{symbol_a}", "")
                    
                    in_critical_section = False
                    
                    if pnl <= -stop:
                        print(f"📉 [Par {pair_idx}] Stop Loss atingido. Cooldown de 60s...")
                        await asyncio.sleep(60)
                    else:
                        await asyncio.sleep(15)
                else: 
                    await asyncio.sleep(3)
                continue

            # 5. Gestão de Entrada
            TIMEFRAME_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60}
            minutes_per_candle = TIMEFRAME_MINUTES.get(timeframe, 5)
            max_halflife_candles = 240 / minutes_per_candle
            pearson_ok = sig.get('correlation', 0) >= 0.70
            
            if abs(sig['z_score']) > z_limit or peak_z_score != 0.0:
                if abs(sig['z_score']) > abs(peak_z_score) and abs(sig['z_score']) > z_limit:
                    peak_z_score = sig['z_score']
                    await asyncio.sleep(1); continue
                
                # Desarma se a anomalia já passou do ponto (evita entrar atrasado)
                if abs(peak_z_score) - abs(sig['z_score']) > 0.5:
                    peak_z_score = 0.0
                    await asyncio.sleep(5); continue
                
                # Gatilho de Confirmação (Z-Score Hook): Recuo de 0.1 do pico
                if abs(peak_z_score) - abs(sig['z_score']) >= 0.1:
                    if not pearson_ok:
                        print(f"⚠️ [Par {pair_idx}] Aguardando: Correlação Quebrada (Pearson < 0.70). Abortando armadilha.")
                        peak_z_score = 0.0 # Cancela o gatilho se a correlação morreu
                        await asyncio.sleep(5); continue
                    elif sig['adx'] >= adx_limit:
                        print(f"📈 [Par {pair_idx}] Aguardando: ADX alto (Tendência forte: {sig['adx']:.1f} >= {adx_limit})")
                        peak_z_score = 0.0
                        await asyncio.sleep(5); continue
                    elif sig['half_life'] >= max_halflife_candles:
                        print(f"⏳ [Par {pair_idx}] Aguardando: Half-life alto ({sig['half_life']:.1f} > {max_halflife_candles})")
                        peak_z_score = 0.0
                        await asyncio.sleep(5); continue
                    else:
                        in_critical_section = True
                        peak_z_score = 0.0 # Reset
                        
                        if sig['beta'] < 0:
                            print(f"⚠️ [Par {pair_idx}] Beta negativo ({sig['beta']:.3f}). Par anti-correlacionado. Abortando.")
                            in_critical_section = False
                            await asyncio.sleep(10)
                            continue

                        amt_a = amount
                        amt_b = amount * abs(sig['beta'])
                        
                        if min(amt_a, amt_b) < 5.5:
                            f = 5.5 / min(amt_a, amt_b)
                            amt_a *= f; amt_b *= f

                        # VULN G: Passa a alavancagem efetiva da corretora para o validador
                        valid, msg = await executor.validate_pair_pre_flight(symbol_a, amt_a, symbol_b, amt_b, lev_a, lev_b)
                        if not valid:
                            print(f"⚠️ [Par {pair_idx}] Abortado: {msg}. Cooldown 60s."); in_critical_section = False; await asyncio.sleep(60); continue

                        side_a = 'SELL' if sig['z_score'] > 0 else 'BUY'
                        side_b = 'BUY' if sig['z_score'] > 0 else 'SELL'
                        
                        current_z = sig['z_score']
                        if abs(current_z) > (z_limit + 1.0):
                            print(f"⚠️ [Par {pair_idx}] Gap de Spread detectado (Z:{current_z:.2f}). Abortando por segurança."); in_critical_section = False; await asyncio.sleep(10); continue

                        # --- ESSÊNCIA MQL5: Execução Crédito/Débito ---
                        perna_venda = symbol_a if side_a == 'SELL' else symbol_b
                        perna_compra = symbol_b if side_b == 'BUY' else symbol_a
                        amt_venda = amt_a if side_a == 'SELL' else amt_b
                        
                        print(f"⚡ [Par {pair_idx}] Executando Crédito (Venda/Short) em {perna_venda}...")
                        res_venda = await executor.execute_market_order(perna_venda, 'SELL', amt_venda)
                        
                        if res_venda:
                            real_notional_venda = res_venda['notional']
                            if perna_venda == symbol_a:
                                adjusted_amt_compra = real_notional_venda * abs(beta)
                            else:
                                adjusted_amt_compra = real_notional_venda / abs(beta)
                                
                            print(f"⚡ [Par {pair_idx}] Executando Débito (Compra/Long financiado) em {perna_compra} (Ajustado: ${adjusted_amt_compra:.2f})...")
                            res_compra = await executor.execute_market_order(perna_compra, 'BUY', adjusted_amt_compra)
                            
                            if not res_compra:
                                print(f"🚨 Falha na Perna de Compra! Neutralizando Venda emergencialmente..."); await safe_close_pair(executor, symbol_a, symbol_b)
                            else:
                                await db.update_config_async(f"ENTRY_TIME_{symbol_a}", str(time.time()))
                                await db.update_config_async(f"INVESTED_{symbol_a}", str(real_notional_venda + res_compra['notional']))
                                await db.update_config_async(f"ENTRY_Z_{symbol_a}", str(current_z))
                        else:
                            print(f"🚨 Falha no Crédito (Venda)! Operação abortada."); 
                        
                        in_critical_section = False
                        consecutive_triggers = 0; await asyncio.sleep(15)
            else:
                consecutive_triggers = 0; await asyncio.sleep(5)

        except asyncio.CancelledError:
            if in_critical_section:
                print(f"⚠️ [Par {pair_idx}] Cancelamento recebido em SEÇÃO CRÍTICA! Blindando fechamento fantasma...")
                try:
                    await asyncio.shield(safe_close_pair(executor, symbol_a, symbol_b))
                except Exception:
                    pass
            raise
        except Exception as e:
            if in_critical_section:
                print(f"🚨 Exceção em seção crítica no Par {pair_idx}: {e}. Tentando neutralizar...")
                try:
                    await safe_close_pair(executor, symbol_a, symbol_b)
                except Exception:
                    pass
            in_critical_section = False
            raise # Propaga para o supervisor

async def supervisor_par(executor, pair_idx, symbol_a, symbol_b, initial_amount, initial_target, initial_stop, initial_adx, initial_z, initial_tf, delay):
    RESTART_DELAY = 30
    falhas_consecutivas = 0
    MAX_FALHAS = 5
    while falhas_consecutivas < MAX_FALHAS:
        start_time = time.time()
        try:
            await monitorar_par(executor, pair_idx, symbol_a, symbol_b, initial_amount, initial_target, initial_stop, initial_adx, initial_z, initial_tf, delay)
            falhas_consecutivas = 0  # reset se saiu limpo
        except asyncio.CancelledError:
            raise  # propaga cancelamento limpo
        except Exception as e:
            # Se a task sobreviveu por mais de 5 minutos, consideramos um crash isolado de rede e resetamos o contador.
            if time.time() - start_time > 300:
                falhas_consecutivas = 0
                
            falhas_consecutivas += 1
            print(f"🔴 [Par {pair_idx}] Crash #{falhas_consecutivas}: {e}. Restart em {RESTART_DELAY}s")
            await asyncio.sleep(RESTART_DELAY)
            try:
                if hasattr(executor, 'connect'):
                    await executor.connect()
            except: pass
    
    # Notifica circuit breaker global após MAX_FALHAS
    await db.update_config_async("BOT_STATUS", "OFF")
    print(f"🛑 [Par {pair_idx}] MAX_FALHAS atingido. Bot desligado.")


# VULN C & D: Global Circuit Breaker rodando em Loop Isolado
async def global_circuit_breaker(executor):
    print("🛡️ [Circuit Breaker] Ativado em vigilância máxima (1s).")
    while True:
        try:
            eq = await executor.get_total_equity()
            if eq is not None:
                await db.update_config_async("LIVE_BALANCE", f"{eq:.2f}")

            if await db.get_config_async("BOT_STATUS") == "OFF":
                await asyncio.sleep(5); continue

            if eq is None: 
                await asyncio.sleep(2); continue # Proteção Alucinação

            hwm_str = await db.get_config_async("HIGH_WATER_MARK_USD")
            hwm = float(hwm_str) if hwm_str else eq

            if eq > hwm:
                hwm = eq
                await db.update_config_async("HIGH_WATER_MARK_USD", str(hwm))
            
            if hwm > 0:
                drawdown_pct = ((hwm - eq) / hwm) * 100
                global_stop = float(await db.get_config_async("GLOBAL_STOP_LOSS_PCT") or Config.GLOBAL_STOP_LOSS_PCT)
                
                if drawdown_pct >= global_stop:
                    await db.update_config_async("BOT_STATUS", "OFF")
                    print(f"🛑🛑 CIRCUIT BREAKER GLOBAL ACIONADO: Drawdown de {drawdown_pct:.1f}% atingiu o limite de {global_stop}%! 🛑🛑")
                    
            # VULN P: Dormência ampliada para 2.5s reduz o peso de API de 300/min para 120/min
            await asyncio.sleep(2.5)
        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                print("🛑 VULN P: Limite de API da Binance (Weight) atingido. Dormência Forçada de 60s!")
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(3)

RESCAN_INTERVAL = 3 * 60 # 3 Minutos (Busca Ativa Dinâmica)
_last_scan = 0

async def auto_scan_pairs(db_conn, executor):
    global _last_scan
    if time.time() - _last_scan < RESCAN_INTERVAL:
        return
    
    try:
        positions = await executor.client.futures_position_information()
        abertas = [p['symbol'] for p in positions if abs(float(p['positionAmt'])) > 1e-8]
        
        # Preservar pares que já estão em operação
        str_a = await db.get_config_async("SYMBOL_A") or ""
        str_b = await db.get_config_async("SYMBOL_B") or ""
        la_current = [s.strip().upper() for s in str_a.split(",") if s.strip()]
        lb_current = [s.strip().upper() for s in str_b.split(",") if s.strip()]
        
        MAX_PARES = 8
        novos_a = [None] * MAX_PARES
        novos_b = [None] * MAX_PARES
        ativos_usados = set()
        
        # 1. Trava pares ativos (posição fixa)
        for i, (a, b) in enumerate(zip(la_current, lb_current)):
            if i >= MAX_PARES: break
            if a in abertas or b in abertas:
                novos_a[i] = a
                novos_b[i] = b
                ativos_usados.add(a)
                ativos_usados.add(b)
                print(f"🛡️ [Scanner] Protegendo trade ativo: {a}/{b}")
            
        _last_scan = time.time()
        print("🔍 [Scanner] Iniciando re-scan de cointegração para preencher frota...")
        df = await run_market_scan_async("5m", 250)
        
        if df is not None and not df.empty:
            # Ordenamos por Z-Score Absoluto
            df_sorted = df.copy()
            df_sorted['abs_z'] = df_sorted['Z-Score'].abs()
            df_sorted = df_sorted.sort_values(by='abs_z', ascending=False).drop(columns=['abs_z'])
            
            scan_json = df_sorted.head(50).to_json(orient="records")
            await db.update_config_async("LATEST_SCAN_RESULTS", scan_json)
            
            if await db.get_config_async("AUTO_SCAN") == "OFF":
                print("✅ [Scanner] Radar Quantitativo atualizado (Auto-Deploy DESLIGADO).")
                return

            # 2. Mantém os pares antigos nos MESMOS SLOTS se ainda estiverem entre os Top 15
            # Isso evita matar a thread e resetar o 'peak_z_score' (Hook) a cada 3 minutos
            top_15_scanner = [(r['Ativo A'], r['Ativo B']) for _, r in df_sorted.head(15).iterrows()]
            for i, (a, b) in enumerate(zip(la_current, lb_current)):
                if i >= MAX_PARES: break
                if novos_a[i] is None:
                    if (a, b) in top_15_scanner and a not in ativos_usados and b not in ativos_usados:
                        novos_a[i] = a
                        novos_b[i] = b
                        ativos_usados.add(a)
                        ativos_usados.add(b)

            # 3. Preenche os slots vazios restantes com os melhores do scanner
            for _, row in df_sorted.iterrows():
                a, b = row['Ativo A'], row['Ativo B']
                if a not in ativos_usados and b not in ativos_usados:
                    try:
                        idx = novos_a.index(None)
                        novos_a[idx] = a
                        novos_b[idx] = b
                        ativos_usados.add(a)
                        ativos_usados.add(b)
                    except ValueError:
                        break # Sem mais slots vazios
                        
            # Limpa Nones residuais
            novos_a = [x for x in novos_a if x is not None]
            novos_b = [x for x in novos_b if x is not None]
            
            str_novos_a = ",".join(novos_a)
            str_novos_b = ",".join(novos_b)
            await db.update_config_async("SYMBOL_A", str_novos_a)
            await db.update_config_async("SYMBOL_B", str_novos_b)
            print(f"✅ [Scanner] Frota montada automaticamente: {str_novos_a} / {str_novos_b}")
    except Exception as e:
        print(f"⚠️ [Scanner] Erro no auto-scan: {e}")

async def main():
    db.init_db()
    executor = BinanceExecutor(Config.API_KEY, Config.API_SECRET)
    await executor.connect()
    last_a, last_b, tarefas = [], [], []
    
    # Inicia o Circuit Breaker Global Assíncrono
    asyncio.create_task(global_circuit_breaker(executor))

    try:
        while True:
            try:
                bot_status = await db.get_config_async("BOT_STATUS")
                
                if bot_status == "OFF":
                    if tarefas:
                        for t in tarefas: t.cancel()
                        tarefas, last_a, last_b = [], [], []
                        
                        # LIQUIDAÇÃO DE EMERGÊNCIA (O Falso Circuit Breaker)
                        print("🛑 [Emergência] Circuit Breaker acionado! Liquidando todas as posições na corretora...")
                        try:
                            positions = await executor.client.futures_position_information()
                            abertas = [p for p in positions if abs(float(p['positionAmt'])) > 1e-8 and (p['symbol'] in la or p['symbol'] in lb)]
                            for p in abertas:
                                print(f"🧹 [Circuit Breaker] Fechando {p['symbol']}...")
                                await executor.cancel_all_orders(p['symbol'])
                                await executor.close_position(p)
                                await db.update_config_async(f"TRADE_STATUS_{p['symbol']}", "FECHADO")
                                await db.update_config_async(f"TREND_SURFING_{p['symbol']}", "")
                                await db.update_config_async(f"MAX_PNL_{p['symbol']}", "")
                        except Exception as e:
                            print(f"🚨 [ERRO CRÍTICO] Falha ao liquidar carteira no Circuit Breaker: {e}")

                    await asyncio.sleep(5); continue

                # Roda o Scanner Automaticamente sempre para preencher a aba "Market Scanner"
                # A decisão de injetar ou não na frota é controlada internamente
                await auto_scan_pairs(db, executor)

                str_a = await db.get_config_async("SYMBOL_A") or ""
                str_b = await db.get_config_async("SYMBOL_B") or ""
                la = [s.strip().upper() for s in str_a.split(",") if s.strip()]
                lb = [s.strip().upper() for s in str_b.split(",") if s.strip()]
                
                if la != last_a or lb != last_b:
                    all_assets = la + lb
                    if len(all_assets) != len(set(all_assets)):
                        print("🚨 [Erro] Sobreposição de ativos detectada! Cada par deve ter ativos únicos para evitar contaminação de PnL.")
                        await asyncio.sleep(10); continue

                    if len(la) == len(lb) > 0:
                        novas_tarefas = []
                        for i in range(len(la)):
                            # Mantém a thread antiga se o par no slot não mudou
                            if i < len(last_a) and (la[i] == last_a[i] and lb[i] == last_b[i]) and i < len(tarefas) and not tarefas[i].done():
                                novas_tarefas.append(tarefas[i])
                            else:
                                if i < len(tarefas) and not tarefas[i].done():
                                    tarefas[i].cancel()
                                
                                t = asyncio.create_task(supervisor_par(
                                    executor, i, la[i], lb[i], 
                                    float(await db.get_config_async("TRADE_AMOUNT_USD") or 30.0), 
                                    float(await db.get_config_async("TARGET_PNL_USD") or 1.50), 
                                    float(await db.get_config_async("STOP_LOSS_USD") or 1.00), 
                                    float(await db.get_config_async("ADX_LIMIT") or 25.0), 
                                    float(await db.get_config_async("Z_SCORE_LIMIT") or 2.5), 
                                    await db.get_config_async("TIMEFRAME") or "5m", 
                                    i * 2
                                ))
                                novas_tarefas.append(t)
                        
                        # Cancela tarefas excedentes se a lista encolheu
                        for i in range(len(la), len(tarefas)):
                            if not tarefas[i].done():
                                tarefas[i].cancel()
                                
                        tarefas = novas_tarefas
                        last_a, last_b = la.copy(), lb.copy()
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
            except Exception as e: print(f"⚠️ Erro Mestre: {e}"); await asyncio.sleep(10)
    finally:
        print("🛑 Fechando conexões...")
        if hasattr(executor.client, 'close_connection'):
            await executor.client.close_connection()

if __name__ == "__main__": 
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutdown manual...")