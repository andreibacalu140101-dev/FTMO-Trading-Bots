import pandas as pd
import numpy as np
from . import BaseStrategy

class TrendMomentumStrategy(BaseStrategy):
    """
    Estrategia Trend & Momentum (M15)
    Seguimiento de tendencia (EMA 50 y 200) y momentum usando el cruce del histograma MACD.
    """
    def __init__(self, ema_fast=50, ema_slow=200, macd_fast=12, macd_slow=26, macd_signal=9, start_hour=8, end_hour=16, end_min=30, name="TrendMomentum"):
        super().__init__(name=name)
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        
        self.start_time = pd.to_datetime(f'{start_hour:02d}:00:00').time()
        self.end_time = pd.to_datetime(f'{end_hour:02d}:{end_min:02d}:00').time()

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df['signal'] = 0
        if len(df) < self.ema_slow:
            return df
            
        if not pd.api.types.is_datetime64_any_dtype(df['time']):
            df['time'] = pd.to_datetime(df['time'])
            
        # 1. EMAs
        df['ema50'] = df['close'].ewm(span=self.ema_fast, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=self.ema_slow, adjust=False).mean()
        
        # 2. MACD y OsMA (Histograma)
        macd_ema_fast = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
        macd_ema_slow = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
        df['macd_line'] = macd_ema_fast - macd_ema_slow
        df['macd_signal'] = df['macd_line'].ewm(span=self.macd_signal, adjust=False).mean()
        df['osma'] = df['macd_line'] - df['macd_signal']
        
        # Valor previo del histograma
        df['osma_prev'] = df['osma'].shift(1)
        
        # 3. Horario Operativo
        time_mask = (df['time'].dt.time >= self.start_time) & (df['time'].dt.time < self.end_time)
        
        # 4. Gatillos (Cruce 0 del OsMA)
        buy_cross = (df['osma_prev'] < 0) & (df['osma'] > 0)
        buy_trend = (df['close'] > df['ema200']) & (df['close'] > df['ema50'])
        buy_cond = time_mask & buy_cross & buy_trend
        
        sell_cross = (df['osma_prev'] > 0) & (df['osma'] < 0)
        sell_trend = (df['close'] < df['ema200']) & (df['close'] < df['ema50'])
        sell_cond = time_mask & sell_cross & sell_trend
        
        df.loc[buy_cond, 'signal'] = 1
        df.loc[sell_cond, 'signal'] = -1
        
        # 5. Cálculo Dinámico de SL y TP
        pip = 0.0001
        
        # Mínimo de las últimas 15 velas para compras
        df['lowest_15'] = df['low'].rolling(window=15).min()
        # Máximo de las últimas 15 velas para ventas
        df['highest_15'] = df['high'].rolling(window=15).max()
        
        # SL base
        sl_base = np.where(df['signal'] == 1, df['lowest_15'],
                  np.where(df['signal'] == -1, df['highest_15'], 0.0))
                  
        sl_dist = np.abs(df['close'] - sl_base)
        
        # Restricciones de SL (10 pips mínimo, 25 pips máximo)
        min_sl = 10 * pip
        max_sl = 25 * pip
        
        sl_dist = np.clip(sl_dist, min_sl, max_sl)
        
        # SL Final aplicando restricciones
        df['sl'] = np.where(df['signal'] == 1, df['close'] - sl_dist,
                   np.where(df['signal'] == -1, df['close'] + sl_dist, 0.0))
                   
        # Anulamos señales cuyo SL técnico original superaba el máximo (Rechazo técnico por MQL5)
        # (El MQL5 decía: si sl_dist > 25, return. En vez de clip, se invalida)
        orig_sl_dist = np.abs(df['close'] - sl_base)
        invalid_signal = orig_sl_dist > max_sl
        df.loc[invalid_signal, 'signal'] = 0
        
        # Actualizamos el TP a ratio 1:2 basado en el nuevo sl_dist
        risk = np.abs(df['close'] - df['sl'])
        df['tp'] = np.where(df['signal'] == 1, df['close'] + (risk * 2.0),
                   np.where(df['signal'] == -1, df['close'] - (risk * 2.0), 0.0))
                   
        df['rr_ratio'] = 2.0
        
        return df
