import streamlit as st
import database as db
import scanner

db.init_db()

st.set_page_config(page_title="Quant Bot Manager", layout="wide")
st.title("⚡ Painel de Controle - Arbitragem Estatística")

# --- MEMÓRIA DO PAINEL ---
if "sym_a" not in st.session_state:
    st.session_state.sym_a = db.get_config("SYMBOL_A") or "ADAUSDT"
if "sym_b" not in st.session_state:
    st.session_state.sym_b = db.get_config("SYMBOL_B") or "XRPUSDT"
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None

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

# --- SALDO DA CONTA ---
current_balance = db.get_config("LIVE_BALANCE") or "0.00"
st.sidebar.metric("Saldo Binance (Futuros)", f"US$ {current_balance}")
st.sidebar.divider()

# --- AJUSTE DINÂMICO DE PARÂMETROS ---
st.sidebar.subheader("Configuração da Operação")

new_sym_a = st.sidebar.text_input("Ativo A (Ex: FETUSDT, ADAUSDT)", value=st.session_state.sym_a)
new_sym_b = st.sidebar.text_input("Ativo B (Ex: GRTUSDT, XRPUSDT)", value=st.session_state.sym_b)

# Novos Parâmetros HFT (High Frequency Trading) expostos no painel
opcoes_tempo = ["1m", "3m", "5m", "15m", "1h"]
tempo_atual = db.get_config("TIMEFRAME") or "5m"
new_timeframe = st.sidebar.selectbox("Tempo Gráfico", opcoes_tempo, index=opcoes_tempo.index(tempo_atual))

new_z_score = st.sidebar.number_input("Gatilho Z-Score (Padrão: 2.5)", value=float(db.get_config("Z_SCORE_LIMIT") or 2.5), step=0.10)

new_amount = st.sidebar.number_input("Exposição por Perna (US$)", value=float(db.get_config("TRADE_AMOUNT_USD") or 6.0), step=1.0)
new_target = st.sidebar.number_input("Alvo de Lucro (US$)", value=float(db.get_config("TARGET_PNL_USD") or 0.25), step=0.10)
new_stop = st.sidebar.number_input("Stop Loss (US$)", value=float(db.get_config("STOP_LOSS_USD") or 1.50), step=1.0)
new_adx = st.sidebar.number_input("Limite Máximo do ADX", value=float(db.get_config("ADX_LIMIT") or 25.0), step=1.0)

if st.sidebar.button("💾 Salvar Parâmetros"):
    st.session_state.sym_a = new_sym_a.upper()
    st.session_state.sym_b = new_sym_b.upper()
    db.update_config("SYMBOL_A", new_sym_a.upper())
    db.update_config("SYMBOL_B", new_sym_b.upper())
    db.update_config("TIMEFRAME", new_timeframe)
    db.update_config("Z_SCORE_LIMIT", str(new_z_score))
    db.update_config("TRADE_AMOUNT_USD", str(new_amount))
    db.update_config("TARGET_PNL_USD", str(new_target))
    db.update_config("STOP_LOSS_USD", str(new_stop))
    db.update_config("ADX_LIMIT", str(new_adx))
    st.sidebar.success("Salvo com sucesso!")

# --- ABAS PRINCIPAIS ---
tab1, tab2 = st.tabs(["📈 Dashboard de Resultados", "📡 Radar de Cointegração"])

with tab1:
    st.subheader("📡 Radar Ao Vivo do Robô")
    
    z_score = db.get_config("LIVE_ZSCORE") or "0.00"
    adx_val = db.get_config("LIVE_ADX") or "0.00"
    live_status = db.get_config("LIVE_STATUS") or "Aguardando primeira leitura..."
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Z-Score Atual", z_score)
    c2.metric("ADX Atual", adx_val)
    c3.info(f"**Status:** {live_status}")
    
    if st.button("🔄 Atualizar Leitura"):
        st.rerun()

    st.divider()

    st.subheader("📊 Histórico de Operações")
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
            current_tf = db.get_config("TIMEFRAME") or "5m"
            st.session_state.scan_results = scanner.run_market_scan(interval=current_tf)
            
    if st.session_state.scan_results is not None:
        df_scan = st.session_state.scan_results
        
        def color_status(val):
            if '✅' in val: return 'color: green; font-weight: bold'
            if '⚠️' in val: return 'color: orange'
            return 'color: red'
        
        st.dataframe(
            df_scan.style.map(color_status, subset=['Status']),
            width='stretch',
            hide_index=True
        )
        
        st.markdown("#### ⚡ Seleção Rápida")
        st.write("Clique em um dos melhores pares abaixo para autopreencher a barra lateral.")
        
        df_top = df_scan[df_scan['Status'].str.contains('✅|⚠️')].head(3)
        
        if not df_top.empty:
            cols = st.columns(len(df_top))
            for idx, row in enumerate(df_top.to_dict('records')):
                with cols[idx]:
                    btn_label = f"Carregar {row['Ativo A']} x {row['Ativo B']}"
                    if st.button(btn_label, use_container_width=True):
                        st.session_state.sym_a = row['Ativo A']
                        st.session_state.sym_b = row['Ativo B']
                        st.rerun()
        else:
            st.info("Nenhum par com status aceitável no momento.")