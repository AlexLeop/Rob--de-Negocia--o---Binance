import streamlit as st
import database as db
import scanner
import pandas as pd
from datetime import datetime

# Inicialização do Banco de Dados
db.init_db()

# Configuração da Página - Padrão Corporativo
st.set_page_config(
    page_title="Paris Trade HFT | Terminal",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS para Estética Profissional (Trading Desk)
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main {
        background-color: #0d1117;
        color: #c9d1d9;
    }
    
    /* Metrics Styling */
    div[data-testid="stMetric"] {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 10px 15px;
        transition: transform 0.2s ease;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #58a6ff;
    }
    div[data-testid="stMetricValue"] > div {
        color: #f0f6fc !important;
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.8rem !important;
    }
    div[data-testid="stMetricLabel"] > div {
        color: #8b949e !important;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-size: 0.75rem !important;
    }
    
    /* Sidebar Metric */
    section[data-testid="stSidebar"] div[data-testid="stMetricValue"] > div {
        font-size: 1.2rem !important;
        white-space: normal !important;
    }

    /* Input Fields */
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stSelectbox>div>div>div {
        background-color: #0d1117 !important;
        color: #c9d1d9 !important;
        border: 1px solid #30363d !important;
    }
    
    /* Buttons */
    .stButton>button {
        text-transform: uppercase;
        font-weight: 600;
        letter-spacing: 1px;
        border-radius: 4px;
        font-size: 0.8rem;
        border: 1px solid #30363d;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
        border-bottom: 1px solid #30363d;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 40px;
        padding: 0 16px;
        font-weight: 500;
        color: #8b949e;
        border: none;
    }
    
    .stTabs [aria-selected="true"] {
        color: #58a6ff !important;
        background-color: #161b22 !important;
        border-radius: 4px 4px 0 0;
    }

    /* Section Headers */
    h1, h2, h3 {
        color: #f0f6fc !important;
        font-weight: 600 !important;
        border-bottom: none !important;
    }
    
    .status-container {
        display: flex;
        align-items: center;
        background-color: #161b22;
        padding: 10px 15px;
        border-radius: 6px;
        border: 1px solid #30363d;
    }
    
    </style>
    """, unsafe_allow_html=True)

# --- HEADER ---
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("Terminal Paris Trade HFT")
    st.caption("Algoritmo de Arbitragem Estatística | Execução Delta Neutro")

with col_h2:
    current_status = db.get_config("BOT_STATUS")
    is_running = current_status == "ON"
    
    # Botão de Comando Principal
    if st.button("TERMINAR SESSÃO" if is_running else "INICIAR TERMINAL", 
                 type="primary" if not is_running else "secondary",
                 use_container_width=True):
        new_status = "OFF" if is_running else "ON"
        db.update_config("BOT_STATUS", new_status)
        st.rerun()

st.divider()

# --- SIDEBAR: CONTROL PANEL ---
st.sidebar.markdown("### CONFIGURAÇÕES DO SISTEMA")

# Equity Monitor
current_balance = float(db.get_config("LIVE_BALANCE") or 0.0)
st.sidebar.metric("EQUITY DISPONÍVEL", f"USDT {current_balance:.2f}")

st.sidebar.divider()

# Pair Selection
st.sidebar.markdown("**SELEÇÃO DE ATIVOS**")
if "sym_a" not in st.session_state:
    st.session_state.sym_a = db.get_config("SYMBOL_A") or "ADAUSDT"
if "sym_b" not in st.session_state:
    st.session_state.sym_b = db.get_config("SYMBOL_B") or "XRPUSDT"

new_sym_a = st.sidebar.text_input("Ativo Primário", value=st.session_state.sym_a).upper()
new_sym_b = st.sidebar.text_input("Ativo Secundário", value=st.session_state.sym_b).upper()

# Strategy Parameters
st.sidebar.markdown("**PARÂMETROS ESTRATÉGICOS**")
opcoes_tf = ["1m", "3m", "5m", "15m", "1h"]
tf_atual = db.get_config("TIMEFRAME") or "5m"
new_tf = st.sidebar.selectbox("Intervalo de Amostragem", opcoes_tf, index=opcoes_tf.index(tf_atual))

new_z_limit = st.sidebar.slider("Limite Z-Score (Entrada)", 1.5, 4.0, float(db.get_config("Z_SCORE_LIMIT") or 2.5), 0.1)
new_adx_limit = st.sidebar.slider("Filtro de Tendência (ADX)", 15, 40, int(float(db.get_config("ADX_LIMIT") or 25)), 1)

# Risk Management
st.sidebar.markdown("**GESTÃO DE RISCO**")
new_amount = st.sidebar.number_input("Nocional por Perna (USD)", 5.5, 500.0, float(db.get_config("TRADE_AMOUNT_USD") or 6.0), 0.5)
new_target = st.sidebar.number_input("Alvo de Convergência (USD)", 0.05, 50.0, float(db.get_config("TARGET_PNL_USD") or 0.25), 0.05)
new_stop = st.sidebar.number_input("Stop Loss Absoluto (USD)", 0.5, 100.0, float(db.get_config("STOP_LOSS_USD") or 1.5), 0.5)

if st.sidebar.button("SALVAR ALTERAÇÕES", use_container_width=True):
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
    st.sidebar.success("Sincronizado com o Core")

# --- MAIN CONTENT ---
tab_monitor, tab_scanner, tab_history = st.tabs(["MONITORAMENTO", "SCANNER DE MERCADO", "HISTÓRICO OPERACIONAL"])

with tab_monitor:
    # Status Operacional e Conexão
    st.markdown("### MONITORAMENTO")
    live_z = db.get_config("LIVE_ZSCORE") or "0.00"
    live_adx = db.get_config("LIVE_ADX") or "0.00"
    live_status = db.get_config("LIVE_STATUS") or "Iniciando monitoramento..."
    
    col_metrics, col_conn = st.columns([3, 1])
    
    with col_metrics:
        m1, m2 = st.columns(2)
        z_val = float(live_z)
        z_color = "normal"
        if abs(z_val) > new_z_limit: z_color = "inverse"
        m1.metric("Z-SCORE ATUAL", live_z, delta_color=z_color)
        m2.metric("ADX (AGREGADO)", live_adx)
    
    with col_conn:
        status_online = "background-color: #238636; box-shadow: 0 0 10px #238636;"
        status_offline = "background-color: #da3633;"
        current_style = status_online if is_running else status_offline
        
        st.markdown(f"""
            <div class="status-container">
                <div style="width: 10px; height: 10px; border-radius: 50%; margin-right: 12px; {current_style}"></div>
                <div>
                    <div style="font-size: 0.7rem; color: #8b949e; letter-spacing: 1px;">CORE ENGINE</div>
                    <div style="font-size: 0.9rem; font-weight: 600; color: #f0f6fc;">{'CONECTADO' if is_running else 'DESCONECTADO'}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    st.markdown("#### LOG DE EVENTOS")
    st.code(f"{live_status}", language="bash")
    
    st.divider()
    
    # Performance Analytics
    st.markdown("### ANALYTICS DA SESSÃO")
    df_trades = db.get_pnl_history()
    
    if not df_trades.empty:
        total_pnl = df_trades['pnl_usd'].sum()
        total_wins = len(df_trades[df_trades['pnl_usd'] > 0])
        win_rate = (total_wins / len(df_trades)) * 100
        
        p1, p2, p3 = st.columns(3)
        p1.metric("PNL LÍQUIDO", f"USDT {total_pnl:.2f}")
        p2.metric("TAXA DE ACERTO", f"{win_rate:.1f}%")
        p3.metric("CICLOS COMPLETOS", len(df_trades))
        
        st.markdown("**CURVA DE EQUITY**")
        st.line_chart(df_trades.set_index('timestamp')['Capital Acumulado'], color="#58a6ff")
    else:
        st.info("Aguardando finalização do primeiro ciclo operacional para processar analytics.")

with tab_scanner:
    st.markdown("### ANALISADOR DE COINTEGRAÇÃO")
    st.caption("Filtro de Cointegração Engle-Granger para descoberta de pares institucionais.")
    
    if st.button("EXECUTAR SCANNER DE MERCADO", use_container_width=True):
        with st.spinner("Processando dados históricos e matrizes de correlação..."):
            st.session_state.scan_results = scanner.run_market_scan(interval=new_tf)
            
    if "scan_results" in st.session_state and st.session_state.scan_results is not None:
        df_scan = st.session_state.scan_results
        
        def color_status(val):
            if 'Excelente' in val: return 'background-color: #1a2733; color: #58a6ff; font-weight: bold'
            if 'Aceitável' in val: return 'background-color: #21262d; color: #8b949e'
            return 'background-color: #211616; color: #f85149'
        
        st.dataframe(
            df_scan.style.map(color_status, subset=['Status']),
            use_container_width=True,
            hide_index=True
        )
        
        st.markdown("### SELEÇÃO RÁPIDA")
        top_pairs = df_scan[df_scan['Status'].str.contains('Excelente|Aceitável')].head(3)
        if not top_pairs.empty:
            cols = st.columns(len(top_pairs))
            for i, row in enumerate(top_pairs.to_dict('records')):
                with cols[i]:
                    if st.button(f"ALOCAR {row['Ativo A']}/{row['Ativo B']}", key=f"load_{i}"):
                        st.session_state.sym_a = row['Ativo A']
                        st.session_state.sym_b = row['Ativo B']
                        st.rerun()
        else:
            st.info("Nenhuma anomalia de preço detectada no timeframe selecionado.")

with tab_history:
    st.markdown("### LOG DE TRANSAÇÕES")
    if not df_trades.empty:
        df_hist = df_trades.copy().sort_values(by='timestamp', ascending=False)
        st.dataframe(df_hist, use_container_width=True, hide_index=True)
    else:
        st.info("O diário operacional será gerado após o encerramento da primeira posição.")

# Technical Footer
st.sidebar.divider()
st.sidebar.caption(f"SYSTEM_TIME: {datetime.now().strftime('%H:%M:%S')}")
st.sidebar.caption("ENGINE_VERSION: 2.5.0-PRO")
