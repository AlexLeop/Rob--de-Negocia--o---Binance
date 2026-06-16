from flask import Flask, render_template, jsonify, request
import core.database as db
import pandas as pd
import logging

# Desativar logs excessivos do Flask
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# Certificar que o DB está inicializado
db.init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def api_data():
    # Coletar estatísticas básicas
    df_trades = db.get_pnl_history()
    
    current_balance = float(db.get_config("LIVE_BALANCE") or 0.0)
    total_pnl = float(db.get_config("TOTAL_PNL") or 0.0)
    
    win_rate = 0.0
    if not df_trades.empty:
        total_trades = len(df_trades)
        wins = len(df_trades[df_trades['pnl_usd'] > 0])
        win_rate = (wins / total_trades) * 100

    # Coletar estado global
    bot_status = db.get_config("BOT_STATUS") or "OFF"
    is_running = (bot_status == "ON")
    
    # Obter os parâmetros dinâmicos
    num_pairs = 0
    pairs_data = []
    
    str_a = db.get_config("SYMBOL_A") or ""
    str_b = db.get_config("SYMBOL_B") or ""
    
    la = [x.strip() for x in str_a.split(',') if x.strip()]
    lb = [x.strip() for x in str_b.split(',') if x.strip()]
    
    num_pairs = min(len(la), len(lb))
    for i in range(num_pairs):
        live_z = db.get_config(f"LIVE_ZSCORE_{i}") or "0.00"
        live_adx = db.get_config(f"LIVE_ADX_{i}") or "0.00"
        live_status = db.get_config(f"LIVE_STATUS_{i}") or "Inicializando..."
        
        pairs_data.append({
            "slot": i,
            "symbol_a": la[i],
            "symbol_b": lb[i],
            "zscore": live_z,
            "adx": live_adx,
            "status": live_status
        })
        
    # Coletar os trades para o chart e tabela
    trades_json = []
    if not df_trades.empty:
        # Pega as ultimas 50 operações para não pesar
        df_recent = df_trades.tail(50).fillna("").to_dict('records')
        trades_json = df_recent
        
    # Obter configurações operacionais atuais
    config_data = {
        "AUTO_SCAN": db.get_config("AUTO_SCAN") or "ON",
        "TIMEFRAME": db.get_config("TIMEFRAME") or "5m",
        "Z_SCORE_LIMIT": float(db.get_config("Z_SCORE_LIMIT") or 2.5),
        "ADX_LIMIT": int(float(db.get_config("ADX_LIMIT") or 40)),
        "TRADE_AMOUNT_USD": float(db.get_config("TRADE_AMOUNT_USD") or 1000.0),
        "TARGET_PNL_USD": float(db.get_config("TARGET_PNL_USD") or 0.5),
        "STOP_LOSS_USD": float(db.get_config("STOP_LOSS_USD") or 1.5),
        "GLOBAL_STOP_LOSS_PCT": float(db.get_config("GLOBAL_STOP_LOSS_PCT") or 20.0),
        "SYMBOL_A": str_a,
        "SYMBOL_B": str_b
    }

    return jsonify({
        "balance": current_balance,
        "total_pnl": total_pnl,
        "is_running": is_running,
        "win_rate": win_rate,
        "num_pairs": num_pairs,
        "pairs": pairs_data,
        "config": config_data,
        "trades": trades_json
    })

@app.route('/api/toggle', methods=['POST'])
def api_toggle():
    current = db.get_config("BOT_STATUS")
    new_status = "OFF" if current == "ON" else "ON"
    db.update_config("BOT_STATUS", new_status)
    return jsonify({"status": new_status})

@app.route('/api/config', methods=['POST'])
def api_config():
    data = request.json
    for k, v in data.items():
        db.update_config(k, str(v).upper() if "SYMBOL" in k else str(v))
    return jsonify({"success": True})

if __name__ == '__main__':
    print("Iniciando Dashboard HFT Avançado na porta 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)
