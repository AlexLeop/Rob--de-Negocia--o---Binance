import asyncio
import database as db
from config import Config
from exchange import BinanceExecutor
from strategy import PairsStrategy

async def main():
    print("🚀 Iniciando Sistema de Arbitragem Quantitativa (Nível Produção)...")
    
    # Garante que o banco de dados e as tabelas existam antes de começar
    db.init_db()
    
    # Inicializa a conexão com a Binance e carrega as regras de trading
    executor = BinanceExecutor(Config.API_KEY, Config.API_SECRET)
    await executor.connect()
    
    print("✅ Conexão com a Binance e regras de mercado carregadas. Entrando no loop...")

    last_symbol_a = ""
    last_symbol_b = ""
    
    while True:
        try:
            # ---------------------------------------------------------
            # 1. LEITURA DE PARÂMETROS DO PAINEL (Chamadas Assíncronas)
            # ---------------------------------------------------------
            bot_status = await db.get_config_async("BOT_STATUS")
            if bot_status == "OFF":
                print("💤 Robô pausado pelo Painel. Aguardando...")
                await asyncio.sleep(5)
                continue
            
            # Puxa os valores atualizados do painel em tempo real
            # Usando gather para ler configs em paralelo e ganhar milissegundos
            config_keys = ["SYMBOL_A", "SYMBOL_B", "TRADE_AMOUNT_USD", "TARGET_PNL_USD", "STOP_LOSS_USD", "ADX_LIMIT"]
            config_vals = await asyncio.gather(*(db.get_config_async(k) for k in config_keys))
            
            current_symbol_a = config_vals[0]
            current_symbol_b = config_vals[1]
            trade_amount = float(config_vals[2])
            target_pnl = float(config_vals[3])
            stop_loss = float(config_vals[4])
            Config.ADX_LIMIT = float(config_vals[5])

            # Configura a alavancagem apenas se você trocou de moeda no painel
            if current_symbol_a != last_symbol_a or current_symbol_b != last_symbol_b:
                print(f"🔄 Configurando novos ativos: {current_symbol_a} e {current_symbol_b}")
                await asyncio.gather(
                    executor.setup_symbol(current_symbol_a, Config.LEVERAGE),
                    executor.setup_symbol(current_symbol_b, Config.LEVERAGE)
                )
                last_symbol_a = current_symbol_a
                last_symbol_b = current_symbol_b

            # ---------------------------------------------------------
            # 2. GESTÃO DE SAÍDA (ALVO DE LUCRO OU STOP LOSS)
            # ---------------------------------------------------------
            is_open, current_pnl, pos_a, pos_b = await executor.get_positions_pnl(current_symbol_a, current_symbol_b)
            
            if is_open:
                print(f"[{current_symbol_a} x {current_symbol_b}] Posição Aberta | PnL Atual: US$ {current_pnl:.4f}")
                
                if current_pnl >= target_pnl or current_pnl <= -stop_loss:
                    motivo = "LUCRO (TARGET)" if current_pnl >= target_pnl else "PREJUÍZO (STOP LOSS)"
                    print(f"🏁 Fim do Ciclo por {motivo}. Fechando posições a mercado...")
                    
                    await asyncio.gather(
                        executor.close_position(pos_a),
                        executor.close_position(pos_b)
                    )
                    
                    await db.save_trade_async(current_symbol_a, current_symbol_b, current_pnl)
                    print("✅ Ciclo encerrado e gravado. Aguardando 15s...")
                    await asyncio.sleep(15) 
                else:
                    await asyncio.sleep(3)
                continue 

            # ---------------------------------------------------------
            # 3. LÓGICA DE ENTRADA (PROCURANDO DISTORÇÕES)
            # ---------------------------------------------------------
            df_a, df_b = await asyncio.gather(
                executor.get_klines(current_symbol_a, Config.TIMEFRAME),
                executor.get_klines(current_symbol_b, Config.TIMEFRAME)
            )
            
            df_spread = PairsStrategy.calculate_indicators(df_a, df_b, Config)
            signals = PairsStrategy.get_signals(df_spread, Config)
            
            if signals['go_long_spread'] or signals['go_short_spread']:
                side_a = 'BUY' if signals['go_long_spread'] else 'SELL'
                side_b = 'SELL' if signals['go_long_spread'] else 'BUY'
                
                print(f"🚀 DISTORÇÃO IDENTIFICADA! Z-Score: {signals['z_score']:.2f}. Executando orders...")
                
                # Execução Atômica (Tentativa)
                results = await asyncio.gather(
                    executor.execute_market_order(current_symbol_a, side_a, trade_amount),
                    executor.execute_market_order(current_symbol_b, side_b, trade_amount),
                    return_exceptions=True
                )
                
                # Verificação de segurança: se uma perna falhou, tentamos fechar a outra imediatamente
                if any(isinstance(r, Exception) for r in results):
                    # Verificação de segurança: A temível "Perna Manca"
                    print("🚨 FALHA CRÍTICA: Perna manca detectada. Abortando operação!")
                    
                    # Puxa o status real da Binance no mesmo segundo
                    _, _, pos_a, pos_b = await executor.get_positions_pnl(current_symbol_a, current_symbol_b)
                    
                    # Identifica quem sobreviveu e executa a ordem a mercado para fechar
                    if not isinstance(results[0], Exception):
                        print(f"Desfazendo compra/venda de {current_symbol_a}...")
                        await executor.close_position(pos_a)
                    if not isinstance(results[1], Exception):
                        print(f"Desfazendo compra/venda de {current_symbol_b}...")
                        await executor.close_position(pos_b)
                        
                    print("🛡️ Posição neutralizada com sucesso. Margem salva.")
                
                await asyncio.sleep(10) # Pausa para a Binance processar as posições
            else:
                # Log de monitoramento
                print(f"📡 Monitorando {current_symbol_a}/{current_symbol_b} | Z-Score: {signals['z_score']:.2f} | ADX: {signals['adx']:.2f}", end='\r')
                await asyncio.sleep(5)

        except Exception as e:
            print(f"⚠️ Erro no ciclo principal: {e}. Reiniciando em 5s...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    # Inicia o loop assíncrono do Python
    asyncio.run(main())