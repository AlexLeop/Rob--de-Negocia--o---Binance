#!/bin/bash
# Inicia o robô em background
python main.py &
# Inicia a interface web na porta principal
streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0