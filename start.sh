#!/bin/bash
# Inicia o robô em background com Watchdog de sobrevivência
while true; do
    python main.py
    echo "🚨 [Watchdog] O motor principal (main.py) caiu. Reiniciando em 10 segundos..."
    sleep 10
done &

# Inicia a interface web Flask na porta principal via Gunicorn (Production Grade)
# Suporte a provedores serverless/PaaS usando a variável $PORT
gunicorn --bind 0.0.0.0:${PORT:-5000} dashboard:app