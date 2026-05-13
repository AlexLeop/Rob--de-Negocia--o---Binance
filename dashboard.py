import streamlit as st
import database as db
import scanner
import pandas as pd
from datetime import datetime

# Inicialização do Banco de Dados
db.init_db()

# Configuração da Página com Tema Escuro/Profissional
st.set_page_config(
    page_title="Paris Trade HFT | Terminal",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS para Estética Profissional (Dark Mode & Trading Terminal)
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    .stMetric {
        background-color: #1e2130;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #30363d;
    }
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        background-color: #238636;
        color: white;
        border: none;
    }
    .stButton>button:hover {
        background-color: #2ea043;
        border: none;
    }
    .stSidebar {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }
    .status-card {
        padding: 20px;
        border-radius: 10px;
        background-color: #161b22;
        border: 1px solid #30363d;
        margin-bottom: 10px;
    }
    h1, h2, h3 {
        color: #c9d1d9 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- HEADER ---
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("🎯 Terminal Paris Trade HFT")
    st.caption("Algoritmo de Arbitragem Estatística de Alta Frequência | Delta Neutro")

with col_h2:
    current_status = db.get_config("BOT_STATUS")
    is_running = current_status == "ON"
    if st.button("TERMINAR SESSÃO" if is_running else "INICIAR TERMINAL", 
                 type="primary" if not is_running else "secondary",
                 key="toggle_bot"):
        new_status = "OFF" if is_running else "ON"
        db.update_config("BOT_STATUS", new_status)
        st.rerun()

st.divider()

# --- SIDEBAR: CONFIGURAÇÕES E PARÂMETROS ---
st.sidebar.title("⚙️ Painel de Controle")

# Saldo em Tempo Real
current_balance = float(db.get_config("LIVE_BALANCE") or 0.0)
st.sidebar.metric("Equity (USDT)", f"$ {current_balance:.2f}")

st.sidebar.divider()

# Seleção de Ativos
st.sidebar.subheader("🎯 Ativos em Operação")
if "sym_a" not in st.session_state:
    st.session_state.sym_a = db.get_config("SYMBOL_A") or "ADAUSDT"
if "sym_b" not in st.session_state:
    st.session_state.sym_b = db.get_config("SYMBOL_B") or "XRPUSDT"

new_sym_a = st.sidebar.text_input("Ativo A", value=st.session_state.sym_a).upper()
new_sym_b = st.sidebar.text_input("Ativo B", value=st.session_state.sym_b).upper()

# Parâmetros Estratégicos
st.sidebar.subheader("📊 Estratégia")
opcoes_tf = ["1m", "3m", "5m", "15m", "1h"]
tf_atual = db.get_config("TIMEFRAME") or "5m"
new_tf = st.sidebar.selectbox("Timeframe", opcoes_tf, index=opcoes_tf.index(tf_atual))

new_z_limit = st.sidebar.slider("Gatilho Z-Score", 1.5, 4.0, float(db.get_config("Z_SCORE_LIMIT") or 2.5), 0.1)
new_adx_limit = st.sidebar.slider("Filtro ADX (Máx)", 15, 40, int(float(db.get_config("ADX_LIMIT") or 25)), 1)

# Gestão de Risco
st.sidebar.subheader("🛡️ Gestão de Risco")
new_amount = st.sidebar.number_input("Lote por Perna ($)", 5.5, 100.0, float(db.get_config("TRADE_AMOUNT_USD") or 6.0), 0.5)
new_target = st.sidebar.number_input("Alvo de Saída ($)", 0.1, 10.0, float(db.get_config("TARGET_PNL_USD") or 0.25), 0.05)
new_stop = st.sidebar.number_input("Stop Loss ($)", 0.5, 50.0, float(db.get_config("STOP_LOSS_USD") or 1.5), 0.5)

if st.sidebar.button("APLICAR CONFIGURAÇÕES", key="save_params"):
    db.update_config("SYMBOL_A", new_sym_a)
    db.update_config("SYMBOL_B", new_sym_b)
    db.update_config("TIMEFRAME", new_tf)
    db.update_config("Z_SCORE_LIMIT", str(new_z_limit))
    db.update_config("TRADE_AMOUNT_USD", str(new_amount))
    db.update_config("TARGET_PNL_USD", str(new_target))
    db.update_config("STOP_LOSS_USD", str(new_stop))
    db.update_config("ADX_LIMIT", str(new_adx_limit))
    st.session_state.sym_a = new_sym_a
    st.session_state.sym_b = new_sym_b
    st.sidebar.success("Parâmetros atualizados no Core!")

# --- CORPO PRINCIPAL ---
tab_monitor, tab_scanner, tab_history = st.tabs(["🖥️ Monitoramento", "📡 Radar Cointegração", "📜 Histórico"])

with tab_monitor:
    # Radar ao Vivo (Metrics)
    st.subheader("📡 Status em Tempo Real")
    live_z = db.get_config("LIVE_ZSCORE") or "0.00"
    live_adx = db.get_config("LIVE_ADX") or "0.00"
    live_status = db.get_config("LIVE_STATUS") or "Aguardando sinal..."
    
    m1, m2, m3 = st.columns(3)
    
    # Lógica de cor para o Z-Score
    z_val = float(live_z)
    z_color = "normal"
    if abs(z_val) > new_z_limit: z_color = "inverse"
    
    m1.metric("Z-Score", live_z, delta=None, delta_color=z_color)
    m2.metric("ADX Combinado", live_adx)
    m3.metric("Status do Sistema", "ATIVO" if is_running else "STANDBY")
    
    st.info(f"📋 **Log Operacional:** {live_status}")
    
    st.divider()
    
    # Visão de Lucratividade
    st.subheader("💰 Performance da Sessão")
    df_trades = db.get_pnl_history()
    
    if not df_trades.empty:
        total_pnl = df_trades['pnl_usd'].sum()
        total_wins = len(df_trades[df_trades['pnl_usd'] > 0])
        win_rate = (total_wins / len(df_trades)) * 100
        
        p1, p2, p3 = st.columns(3)
        p1.metric("PnL Acumulado", f"$ {total_pnl:.2f}", delta=f"{total_pnl:.2f}")
        p2.metric("Win Rate", f"{win_rate:.1f}%")
        p3.metric("Trades Fechados", len(df_trades))
        
        st.markdown("### Curva de Equidade")
        st.line_chart(df_trades.set_index('timestamp')['Capital Acumulado'], color="#238636")
    else:
        st.warning("Aguardando finalização do primeiro ciclo operacional para gerar métricas.")

with tab_scanner:
    st.subheader("🔍 Scanner de Cointegração Engle-Granger")
    st.caption("Busca por distorções de preços em pares de alta correlação.")
    
    if st.button("INICIAR VARREDURA DE MERCADO", key="scan_btn"):
        with st.spinner("Analisando matrizes de cointegração..."):
            st.session_state.scan_results = scanner.run_market_scan(interval=new_tf)
            
    if "scan_results" in st.session_state and st.session_state.scan_results is not None:
        df_scan = st.session_state.scan_results
        
        def color_status(val):
            if 'Excelente' in val: return 'background-color: #1a3a1a; color: #4ade80'
            if 'Aceitável' in val: return 'background-color: #3a3a1a; color: #fbbf24'
            return 'background-color: #3a1a1a; color: #f87171'
        
        st.dataframe(
            df_scan.style.applymap(color_status, subset=['Status']),
            use_container_width=True,
            hide_index=True
        )
        
        st.markdown("### ⚡ Ações Rápidas")
        top_pairs = df_scan[df_scan['Status'].str.contains('Excelente|Aceitável')].head(3)
        if not top_pairs.empty:
            cols = st.columns(len(top_pairs))
            for i, row in enumerate(top_pairs.to_dict('records')):
                with cols[i]:
                    if st.button(f"CARREGAR {row['Ativo A']}/{row['Ativo B']}", key=f"load_{i}"):
                        st.session_state.sym_a = row['Ativo A']
                        st.session_state.sym_b = row['Ativo B']
                        st.rerun()
        else:
            st.info("Nenhuma oportunidade premium detectada neste timeframe.")

with tab_history:
    st.subheader("📜 Diário de Trades")
    if not df_trades.empty:
        # Formata o histórico para exibição profissional
        df_hist = df_trades.copy().sort_values(by='timestamp', ascending=False)
        st.dataframe(df_hist, use_container_width=True, hide_index=True)
    else:
        st.info("O histórico de operações será populado após o primeiro trade.")

# Rodapé Técnico
st.sidebar.divider()
st.sidebar.caption(f"Última Atualização: {datetime.now().strftime('%H:%M:%S')}")
st.sidebar.caption("v2.5.0 - Auditoria Concluída")
