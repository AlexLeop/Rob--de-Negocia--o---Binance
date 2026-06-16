import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("BINANCE_API_KEY")
    API_SECRET = os.getenv("BINANCE_API_SECRET")
    TESTNET = os.getenv("USE_TESTNET", "False").lower() == "true"
    
    SYMBOL_A = os.getenv("SYMBOL_A", "ADAUSDT")
    SYMBOL_B = os.getenv("SYMBOL_B", "XRPUSDT")
    TIMEFRAME = os.getenv("TIMEFRAME", "5m")
    
    LEVERAGE = int(os.getenv("LEVERAGE", 10))
    TRADE_AMOUNT_USD = float(os.getenv("TRADE_AMOUNT_USD", 30.0)) # Exposição por perna
    
    Z_WINDOW = int(os.getenv("Z_SCORE_WINDOW", 60)) # Aumentado para maior estabilidade estatística
    Z_ENTRY = float(os.getenv("Z_SCORE_ENTRY", 2.5))
    ADX_PERIOD = int(os.getenv("ADX_PERIOD", 14))
    ADX_LIMIT = float(os.getenv("ADX_LIMIT", 25.0))
    
    TARGET_PNL = float(os.getenv("TARGET_PNL_USD", 1.50))
    STOP_LOSS = float(os.getenv("STOP_LOSS_USD", 1.00))
    GLOBAL_STOP_LOSS_PCT = float(os.getenv("GLOBAL_STOP_LOSS_PCT", 20.0))