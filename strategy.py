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
        common_index = df_a.index.intersection(df_b.index)
        if len(common_index) < 30:
            return None, 1.0

        # Sincronização estrita por timestamp
        # Reindexa para garantir que não existam lacunas (missing candles) que quebrem a série temporal
        # O freq é inferido ou assume-se o padrão da sessão
        try:
            freq = pd.infer_freq(common_index) or '5min'
            full_index = pd.date_range(start=common_index.min(), end=common_index.max(), freq=freq)
        except:
            full_index = common_index

        df_temp = pd.DataFrame(index=full_index)
        df_temp['close_a'] = df_a['close'].reindex(full_index).ffill()
        df_temp['close_b'] = df_b['close'].reindex(full_index).ffill()
        df_temp['high_a'] = df_a['high'].reindex(full_index).ffill()
        df_temp['low_a'] = df_a['low'].reindex(full_index).ffill()
        df_temp['high_b'] = df_b['high'].reindex(full_index).ffill()
        df_temp['low_b'] = df_b['low'].reindex(full_index).ffill()
        
        df_temp = df_temp.dropna() 
        if len(df_temp) < 30:
            return None, 1.0
        
        log_a = np.log(df_temp['close_a'])
        log_b = np.log(df_temp['close_b'])
        
        # BUG-04: Rolling OLS para Beta Dinâmico (Sintonizado com Z_WINDOW)
        betas = []
        for i in range(len(log_a)):
            if i < config.Z_WINDOW:
                betas.append(np.nan)
                continue
            # Janela deslizante para o cálculo do Beta
            window_b = sm.add_constant(log_b.iloc[i-config.Z_WINDOW:i])
            window_a = log_a.iloc[i-config.Z_WINDOW:i]
            try:
                model = sm.OLS(window_a, window_b).fit()
                betas.append(model.params.iloc[1])
            except:
                betas.append(betas[-1] if betas else 1.0)
        
        df = pd.DataFrame(index=df_temp.index)
        df['beta'] = betas
        df['spread'] = log_a - (df['beta'] * log_b)
        
        mean = df['spread'].rolling(window=config.Z_WINDOW).mean()
        std = df['spread'].rolling(window=config.Z_WINDOW).std()
        df['z_score'] = (df['spread'] - mean) / std
        
        # BUG-12: Half-life como valor escalar único (último calculado)
        hl_series = df['spread'].dropna()
        latest_hl = PairsStrategy.calculate_half_life(hl_series) if len(hl_series) > 30 else 999.0
        df['half_life'] = latest_hl
        
        # BUG-10: Correlação de Pearson em Log-Retornos (Estatisticamente correto)
        ret_a = log_a.diff()
        ret_b = log_b.diff()
        df['correlation'] = ret_a.rolling(window=config.Z_WINDOW).corr(ret_b)
        
        # BUG-09: ADX Combinado (Máximo entre Ativo A e B)
        adx_a = ta.adx(df_temp['high_a'], df_temp['low_a'], df_temp['close_a'], length=config.ADX_PERIOD)
        adx_b = ta.adx(df_temp['high_b'], df_temp['low_b'], df_temp['close_b'], length=config.ADX_PERIOD)
        
        val_a = adx_a['ADX_14'] if adx_a is not None else pd.Series(0, index=df.index)
        val_b = adx_b['ADX_14'] if adx_b is not None else pd.Series(0, index=df.index)
        df['adx'] = np.maximum(val_a, val_b)

        return df, df['beta'].iloc[-1]

    @staticmethod
    def get_signals(df, config):
        last_row = df.iloc[-1] 
        return {
            'z_score': last_row['z_score'],
            'adx': last_row['adx'],
            'half_life': last_row['half_life'],
            'correlation': last_row['correlation']
        }