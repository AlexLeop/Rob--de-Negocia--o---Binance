import sqlite3
import pandas as pd
import asyncio
from datetime import datetime

DB_PATH = "bot_data.db"

def _get_conn():
    """Retorna uma conexão com modo WAL habilitado para suportar concorrência."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = _get_conn()
    cursor = conn.cursor()
    
    # Tabela de Configurações Dinâmicas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Tabela de Histórico de Trades para o Gráfico de PnL
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            symbol_a TEXT,
            symbol_b TEXT,
            pnl_usd REAL
        )
    ''')
    
    # Inserir configurações padrão caso o banco esteja vazio
    default_configs = {
        "BOT_STATUS": "OFF",
        "SYMBOL_A": "ADAUSDT",
        "SYMBOL_B": "XRPUSDT",
        "TRADE_AMOUNT_USD": "15.0",
        "TARGET_PNL_USD": "0.50",
        "STOP_LOSS_USD": "15.00",
        "ADX_LIMIT": "25.0"
    }
    
    for k, v in default_configs.items():
        cursor.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (k, v))
        
    conn.commit()
    conn.close()

# --- FUNÇÕES SÍNCRONAS (Para Streamlit) ---

def get_config(key: str) -> str:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
        result = cursor.fetchone()
        return result[0] if result else None

def update_config(key: str, value: str):
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE config SET value = ? WHERE key = ?', (value, key))
        conn.commit()

# --- FUNÇÕES ASSÍNCRONAS (Para o Robô - Evitam bloquear o Event Loop) ---

async def get_config_async(key: str) -> str:
    return await asyncio.to_thread(get_config, key)

async def save_trade_async(symbol_a: str, symbol_b: str, pnl: float):
    def _save():
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO trades (timestamp, symbol_a, symbol_b, pnl_usd) VALUES (?, ?, ?, ?)',
                (datetime.now(), symbol_a, symbol_b, pnl)
            )
            conn.commit()
    await asyncio.to_thread(_save)

def get_pnl_history() -> pd.DataFrame:
    with _get_conn() as conn:
        df = pd.read_sql_query("SELECT timestamp, pnl_usd FROM trades ORDER BY timestamp ASC", conn)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['Capital Acumulado'] = df['pnl_usd'].cumsum()
        return df


    