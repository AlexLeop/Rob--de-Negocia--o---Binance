import sqlite3
import pandas as pd
import asyncio
import time
from datetime import datetime
import os

# MUDANÇA CRÍTICA 1: Caminho Dinâmico
# Detecta se está em Docker ou local e ajusta o caminho do banco de dados.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.exists("/app/data"):
    DB_PATH = "/app/data/bot_data.db"
else:
    DB_PATH = os.path.join(BASE_DIR, "bot_data.db")

def _get_conn():
    """Retorna uma conexão com modo WAL habilitado para suportar concorrência."""
    # Timeout de 10s e retries manuais para robustez extrema
    for i in range(5):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL;")
            return conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and i < 4:
                time.sleep(0.2)
                continue
            raise e

def init_db():
    conn = _get_conn()
    try:
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
        
        default_configs = {
            "BOT_STATUS": "OFF",
            "SYMBOL_A": "ADAUSDT",
            "SYMBOL_B": "XRPUSDT",
            "TRADE_AMOUNT_USD": "6.0",
            "TARGET_PNL_USD": "0.25",
            "STOP_LOSS_USD": "1.50",
            "ADX_LIMIT": "25.0",
            "Z_SCORE_LIMIT": "2.5",
            "TIMEFRAME": "5m"
        }
        
        for k, v in default_configs.items():
            cursor.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (k, v))
            
        conn.commit()
    finally:
        # MUDANÇA CRÍTICA 2: Libertação imediata do ficheiro
        conn.close()

# --- FUNÇÕES SÍNCRONAS (Para Streamlit) ---

def get_config(key: str) -> str:
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()

def update_config(key: str, value: str):
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        # O segredo é o REPLACE: Atualiza se existir, Cria se for nova.
        cursor.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
    finally:
        conn.close()

# --- FUNÇÕES ASSÍNCRONAS (Para o Robô) ---

async def get_config_async(key: str) -> str:
    return await asyncio.to_thread(get_config, key)

async def save_trade_async(symbol_a: str, symbol_b: str, pnl: float):
    def _save():
        conn = _get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO trades (timestamp, symbol_a, symbol_b, pnl_usd) VALUES (?, ?, ?, ?)',
                (datetime.now(), symbol_a, symbol_b, pnl)
            )
            conn.commit()
        finally:
            conn.close()
    await asyncio.to_thread(_save)

def get_pnl_history() -> pd.DataFrame:
    conn = _get_conn()
    try:
        df = pd.read_sql_query("SELECT timestamp, pnl_usd FROM trades ORDER BY timestamp ASC", conn)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['Capital Acumulado'] = df['pnl_usd'].cumsum()
        return df
    finally:
        conn.close()

async def update_config_async(key: str, value: str):
    await asyncio.to_thread(update_config, key, value)        