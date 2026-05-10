import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("BINANCE_API_KEY")
    API_SECRET = os.getenv("BINANCE_API_SECRET")
    
    SYMBOL_A = os.getenv("SYMBOL_A", "ADAUSDT")
    SYMBOL_B = os.getenv("SYMBOL_B", "XRPUSDT")
    TIMEFRAME = os.getenv("TIMEFRAME", "5m")
    
    LEVERAGE = int(os.getenv("LEVERAGE", 10))
    TRADE_AMOUNT_USD = float(os.getenv("TRADE_AMOUNT_USD", 15.0)) # Exposição por perna
    
    Z_WINDOW = int(os.getenv("Z_SCORE_WINDOW", 20))
    Z_ENTRY = float(os.getenv("Z_SCORE_ENTRY", 2.5))
    ADX_PERIOD = int(os.getenv("ADX_PERIOD", 14))
    ADX_LIMIT = float(os.getenv("ADX_LIMIT", 25.0))
    
    TARGET_PNL = float(os.getenv("TARGET_PNL_USD", 0.50))
    STOP_LOSS = float(os.getenv("STOP_LOSS_USD", 15.00))