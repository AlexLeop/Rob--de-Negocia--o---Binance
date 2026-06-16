import pandas as pd
import numpy as np
import statsmodels.api as sm

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
    def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        up_move = high - high.shift()
        down_move = low.shift() - low
        
        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

        tr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / tr_smooth.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / tr_smooth.replace(0, np.nan)
        
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/period, adjust=False).mean()
        return adx.fillna(0)

    @staticmethod
    def rolling_beta_vectorized(log_a: pd.Series, log_b: pd.Series, window: int) -> pd.Series:
        """Rolling OLS beta via fórmula fechada: β = Cov(a,b) / Var(b)"""
        cov = log_a.rolling(window).cov(log_b)
        var = log_b.rolling(window).var()
        beta = cov / var.replace(0, np.nan)
        return beta.ffill().fillna(1.0)

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
        
        df = pd.DataFrame(index=df_temp.index)
        df['beta'] = PairsStrategy.rolling_beta_vectorized(log_a, log_b, config.Z_WINDOW)
        df['spread'] = log_a - (df['beta'] * log_b)
        
        mean = df['spread'].rolling(window=config.Z_WINDOW).mean()
        std = df['spread'].rolling(window=config.Z_WINDOW).std().replace(0, 1e-8)
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
        adx_a = PairsStrategy.calc_adx(df_temp['high_a'], df_temp['low_a'], df_temp['close_a'], period=config.ADX_PERIOD)
        adx_b = PairsStrategy.calc_adx(df_temp['high_b'], df_temp['low_b'], df_temp['close_b'], period=config.ADX_PERIOD)
        
        df['adx'] = np.maximum(adx_a, adx_b)

        return df, df['beta'].iloc[-1]

    @staticmethod
    def get_signals(df, config):
        if df.empty or df.iloc[-1][['z_score','adx','correlation']].isna().any():
            return None
        last_row = df.dropna(subset=['z_score', 'adx', 'correlation']).iloc[-1]
        return {
            'z_score': last_row['z_score'],
            'adx': last_row['adx'],
            'half_life': last_row['half_life'],
            'correlation': last_row['correlation'],
            'beta': last_row['beta']
        }