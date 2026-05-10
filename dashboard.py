import streamlit as st
import database as db
import scanner

db.init_db()

st.set_page_config(page_title="Quant Bot Manager", layout="wide")
st.title("⚡ Painel de Controle - Arbitragem Estatística")

# --- BARRA LATERAL: CONTROLES DO ROBÔ ---
st.sidebar.header("Engrenagens do Robô")

current_status = db.get_config("BOT_STATUS")
is_running = current_status == "ON"

if st.sidebar.button("🔴 DESLIGAR ROBÔ" if is_running else "🟢 LIGAR ROBÔ"):
    new_status = "OFF" if is_running else "ON"
    db.update_config("BOT_STATUS", new_status)
    st.rerun()

st.sidebar.markdown(f"**Status Atual:** {'✅ RODANDO' if is_running else '💤 PAUSADO'}")
st.sidebar.warning("⚠️ Desligue o robô antes de trocar os pares.")
st.sidebar.divider()

# Ajuste Dinâmico de Parâmetros
st.sidebar.subheader("Configuração da Operação")
new_sym_a = st.sidebar.text_input("Ativo A", value=db.get_config("SYMBOL_A"))
new_sym_b = st.sidebar.text_input("Ativo B", value=db.get_config("SYMBOL_B"))
new_amount = st.sidebar.number_input("Exposição (US$)", value=float(db.get_config("TRADE_AMOUNT_USD")), step=1.0)
new_target = st.sidebar.number_input("Alvo (US$)", value=float(db.get_config("TARGET_PNL_USD")), step=0.10)
new_stop = st.sidebar.number_input("Stop Loss (US$)", value=float(db.get_config("STOP_LOSS_USD")), step=1.0)
new_adx = st.sidebar.number_input("Limite Máximo do ADX", value=float(db.get_config("ADX_LIMIT")), step=1.0)

if st.sidebar.button("💾 Salvar Parâmetros"):
    db.update_config("SYMBOL_A", new_sym_a.upper())
    db.update_config("SYMBOL_B", new_sym_b.upper())
    db.update_config("TRADE_AMOUNT_USD", str(new_amount))
    db.update_config("TARGET_PNL_USD", str(new_target))
    db.update_config("STOP_LOSS_USD", str(new_stop))
    db.update_config("ADX_LIMIT", str(new_adx))
    st.sidebar.success("Salvo com sucesso!")

# --- ABAS PRINCIPAIS ---
tab1, tab2 = st.tabs(["📈 Dashboard de Resultados", "📡 Radar de Cointegração"])

with tab1:
    df_trades = db.get_pnl_history()
    col1, col2, col3 = st.columns(3)
    if not df_trades.empty:
        total_trades = len(df_trades)
        total_profit = df_trades['pnl_usd'].sum()
        win_rate = (len(df_trades[df_trades['pnl_usd'] > 0]) / total_trades) * 100
        
        col1.metric("Lucro Líquido Total", f"US$ {total_profit:.2f}")
        col2.metric("Ciclos Fechados", f"{total_trades}")
        col3.metric("Taxa de Acerto", f"{win_rate:.1f}%")
        
        st.subheader("Curva de Crescimento")
        st.line_chart(df_trades.set_index('timestamp')['Capital Acumulado'], color="#00FF00")
    else:
        st.info("Nenhuma operação registrada ainda.")

with tab2:
    st.markdown("### Escaneamento de Mercado em Tempo Real")
    st.write("Identifique os pares com maior força elástica para atualizar seu robô.")
    
    if st.button("🔍 Iniciar Varredura de Cointegração"):
        with st.spinner("Baixando histórico da Binance e calculando Engle-Granger. Isso pode levar alguns segundos..."):
            df_scan = scanner.run_market_scan()
            
            # Estiliza a tabela para facilitar a leitura visual
            def color_status(val):
                if '✅' in val: return 'color: green; font-weight: bold'
                if '⚠️' in val: return 'color: orange'
                return 'color: red'
            
            st.dataframe(
                df_scan.style.map(color_status, subset=['Status']),
                use_container_width=True,
                hide_index=True
            )
            st.success("Varredura concluída! Copie o Ativo A e Ativo B ideais e cole no menu lateral para atualizar o robô.")