import pandas as pd
import numpy as np
from . import BaseStrategy

class VolatilityBreakoutStrategy(BaseStrategy):
    """
    Estrategia Volatility Breakout (H1)
    Opera rupturas de canales de Donchian cuando el ATR está en expansión (ATR > SMA ATR).
    """
    def __init__(self, donchian_period=20, atr_period=14, atr_sma_period=14, atr_mult_sl=1.5, atr_mult_tp=3.0, name="VolatilityBreakout"):
        super().__init__(name=name)
        self.donchian_period = donchian_period
        self.atr_period = atr_period
        self.atr_sma_period = atr_sma_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df['signal'] = 0
        if len(df) < self.donchian_period + 1:
            return df
            
        # 1. Bandas de Donchian (Cálculo con desplazamiento para no incluir la vela actual)
        df['upper_band'] = df['high'].shift(1).rolling(window=self.donchian_period).max()
        df['lower_band'] = df['low'].shift(1).rolling(window=self.donchian_period).min()
        
        # 2. True Range y ATR
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = np.abs(df['high'] - df['close'].shift(1))
        df['tr3'] = np.abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # El ATR original de J. Welles Wilder usa suavizado exponencial (RMA o SMMA) con alpha = 1/N
        df['atr'] = df['tr'].ewm(alpha=1/self.atr_period, min_periods=self.atr_period, adjust=False).mean()
        
        # SMA del ATR para medir si la volatilidad está en expansión
        df['atr_sma'] = df['atr'].rolling(window=self.atr_sma_period).mean()
        
        # 3. Gatillos de Ruptura y Volatilidad
        # Compras
        buy_cond = (df['close'] > df['upper_band']) & (df['atr'] > df['atr_sma'])
        
        # Ventas
        sell_cond = (df['close'] < df['lower_band']) & (df['atr'] > df['atr_sma'])
        
        df.loc[buy_cond, 'signal'] = 1
        df.loc[sell_cond, 'signal'] = -1
        
        # 4. Cálculo de SL y TP Dinámicos (Basados en el ATR actual)
        sl_dist = df['atr'] * self.atr_mult_sl
        tp_dist = df['atr'] * self.atr_mult_tp
        
        df['sl'] = np.where(df['signal'] == 1, df['close'] - sl_dist,
                   np.where(df['signal'] == -1, df['close'] + sl_dist, 0.0))
                   
        df['tp'] = np.where(df['signal'] == 1, df['close'] + tp_dist,
                   np.where(df['signal'] == -1, df['close'] - tp_dist, 0.0))
                   
        # El RR Ratio es la relación de los multiplicadores (por defecto 1:2 si SL 1.5 y TP 3.0)
        df['rr_ratio'] = self.atr_mult_tp / self.atr_mult_sl
        
        return df
