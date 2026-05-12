import pandas as pd
import numpy as np
import statsmodels.api as sm
import pandas_ta as ta

class PairsStrategy:
    @staticmethod
    def calculate_half_life(spread):
        """Calcula o tempo médio de reversão à média (Ornstein-Uhlenbeck)"""
        df_spread = pd.DataFrame(spread, columns=['spread'])
        spread_lag = df_spread['spread'].shift(1)
        spread_lag.iloc[0] = spread_lag.iloc[1]
        spread_ret = df_spread['spread'] - spread_lag
        spread_ret.iloc[0] = spread_ret.iloc[1]
        
        spread_lag2 = sm.add_constant(spread_lag)
        model = sm.OLS(spread_ret, spread_lag2)
        res = model.fit()
        
        # Prevenção contra divisão por zero ou se a série não for estacionária
        if res.params.iloc[1] >= 0:
            return 999.0 
            
        halflife = -np.log(2) / res.params.iloc[1]
        return halflife

    @staticmethod
    def calculate_indicators(df_a, df_b, config):
        # --- VACINA ANTI-ERRO: Alinhamento Perfeito de Índices ---
        # Cria um DataFrame temporário que une apenas os minutos onde AMBAS as moedas existem
        df_temp = pd.DataFrame({
            'close_a': df_a['close'],
            'close_b': df_b['close'],
            'high_a': df_a['high'],
            'low_a': df_a['low']
        }).dropna()
        
        df = pd.DataFrame(index=df_temp.index)
        
        # 1. Transformação Logarítmica
        log_a = np.log(df_temp['close_a'])
        log_b = np.log(df_temp['close_b'])
        
        # 2. Cálculo do Beta Dinâmico (Hedge Ratio) via OLS
        x = sm.add_constant(log_b)
        model = sm.OLS(log_a, x).fit()
        beta = model.params.iloc[1]
        
        # 3. O Verdadeiro Spread de Cointegração
        df['spread'] = log_a - (beta * log_b)
        
        # 4. Z-Score Clássico
        mean = df['spread'].rolling(window=30).mean()
        std = df['spread'].rolling(window=30).std()
        df['z_score'] = (df['spread'] - mean) / std
        
        # 5. Tempo de Reversão (Half-Life)
        hl = PairsStrategy.calculate_half_life(df['spread'].dropna())
        df['half_life'] = hl
        
        # 6. ADX (Filtro de Tendência)
        adx_a = ta.adx(df_temp['high_a'], df_temp['low_a'], df_temp['close_a'], length=14)
        df['adx'] = adx_a['ADX_14'] if adx_a is not None else 0

        return df, beta

    @staticmethod
    def get_signals(df, config):
        # Lendo a vela atual (iloc[-1]) para reagir em tempo real
        last_row = df.iloc[-1] 
        return {
            'z_score': last_row['z_score'],
            'adx': last_row['adx'],
            'half_life': last_row['half_life']
        }