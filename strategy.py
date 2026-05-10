import pandas as pd
import pandas_ta as ta
import numpy as np

class PairsStrategy:
    @staticmethod
    def calculate_indicators(df_a: pd.DataFrame, df_b: pd.DataFrame, config) -> pd.DataFrame:
        df = pd.DataFrame(index=df_a.index)
        
        # Proteção contra divisão por zero usando numpy
        close_b = df_b['close'].replace(0, np.nan)
        
        # Criação do Spread Sintético com precisão HLC
        df['high'] = df_a['high'] / df_b['low'].replace(0, np.nan)
        df['low'] = df_a['low'] / df_b['high'].replace(0, np.nan)
        df['close'] = df_a['close'] / close_b
        
        # Filtra valores infinitos ou nulos resultantes da divisão
        df = df.replace([np.inf, -np.inf], np.nan).dropna()
        
        if df.empty:
            return df

        # Z-Score
        df['mean'] = df['close'].rolling(window=config.Z_WINDOW).mean()
        df['std'] = df['close'].rolling(window=config.Z_WINDOW).std()
        df['z_score'] = (df['close'] - df['mean']) / df['std']
        
        # ADX
        adx_df = ta.adx(df['high'], df['low'], df['close'], length=config.ADX_PERIOD)
        if adx_df is not None:
            df = pd.concat([df, adx_df], axis=1)
            
        return df.dropna()

    @staticmethod
    def get_signals(df: pd.DataFrame, config) -> dict:
        if len(df) < 2:
            return {"z_score": 0, "adx": 0, "go_long_spread": False, "go_short_spread": False}

        # CRÍTICO: Em produção, usa-se o candle FECHADO (iloc[-2]) para evitar "repainting"
        # O último candle (iloc[-1]) ainda está em formação e o sinal pode mudar/sumir.
        last_row = df.iloc[-2]
        
        z_score = last_row['z_score']
        adx_col = f"ADX_{config.ADX_PERIOD}"
        adx_val = last_row[adx_col] if adx_col in last_row else 100
        
        can_trade = adx_val < config.ADX_LIMIT
        
        return {
            "z_score": z_score,
            "adx": adx_val,
            "go_long_spread": z_score < -config.Z_ENTRY and can_trade,
            "go_short_spread": z_score > config.Z_ENTRY and can_trade
        }