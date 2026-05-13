import pandas as pd
import numpy as np
import statsmodels.api as sm
import pandas_ta as ta

class PairsStrategy:
    @staticmethod
    def calculate_half_life(spread):
        """Calcula o tempo médio de reversão à média."""
        df_spread = pd.DataFrame(spread, columns=['spread'])
        spread_lag = df_spread['spread'].shift(1)
        spread_lag.iloc[0] = spread_lag.iloc[1]
        spread_ret = df_spread['spread'] - spread_lag
        spread_ret.iloc[0] = spread_ret.iloc[1]
        
        spread_lag2 = sm.add_constant(spread_lag)
        model = sm.OLS(spread_ret, spread_lag2)
        res = model.fit()
        
        if res.params.iloc[1] >= 0:
            return 999.0 
            
        halflife = -np.log(2) / res.params.iloc[1]
        return halflife

    @staticmethod
    def calculate_indicators(df_a, df_b, config):
        # Alinhamento Perfeito de Índices (Vacina anti-erro de matriz)
        df_temp = pd.DataFrame({
            'close_a': df_a['close'],
            'close_b': df_b['close'],
            'high_a': df_a['high'],
            'low_a': df_a['low']
        }).dropna()
        
        df = pd.DataFrame(index=df_temp.index)
        log_a = np.log(df_temp['close_a'])
        log_b = np.log(df_temp['close_b'])
        
        # OLS para Beta Dinâmico
        x = sm.add_constant(log_b)
        model = sm.OLS(log_a, x).fit()
        beta = model.params.iloc[1]
        
        df['spread'] = log_a - (beta * log_b)
        mean = df['spread'].rolling(window=config.Z_WINDOW).mean()
        std = df['spread'].rolling(window=config.Z_WINDOW).std()
        df['z_score'] = (df['spread'] - mean) / std
        
        df['half_life'] = PairsStrategy.calculate_half_life(df['spread'].dropna())
        
        # --- FILTRO CRÍTICO: Correlação de Pearson ---
        # Evita entrar em pares que "se divorciaram" momentaneamente
        df['correlation'] = df_temp['close_a'].rolling(window=config.Z_WINDOW).corr(df_temp['close_b'])
        
        adx_a = ta.adx(df_temp['high_a'], df_temp['low_a'], df_temp['close_a'], length=14)
        df['adx'] = adx_a['ADX_14'] if adx_a is not None else 0

        return df, beta

    @staticmethod
    def get_signals(df, config):
        last_row = df.iloc[-1] 
        return {
            'z_score': last_row['z_score'],
            'adx': last_row['adx'],
            'half_life': last_row['half_life'],
            'correlation': last_row['correlation']
        }