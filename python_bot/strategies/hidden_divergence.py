import pandas as pd
import numpy as np
from . import BaseStrategy

class HiddenDivergenceStrategy(BaseStrategy):
    """
    Estrategia de Divergencia Oculta (M15)
    Identifica retrocesos a favor de la tendencia usando divergencias entre el Precio y el RSI.
    """
    def __init__(self, ema_period=100, rsi_period=14, name="HiddenDivergence"):
        super().__init__(name=name)
        self.ema_period = ema_period
        self.rsi_period = rsi_period

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.ema_period:
            df['signal'] = 0
            return df
            
        # 1. EMA 100
        df['ema'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()
        
        # 2. RSI 14 (Cálculo Vectorial Exacto)
        delta = df['close'].diff()
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        
        avg_gain = pd.Series(gain).ewm(alpha=1/self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        avg_loss = pd.Series(loss).ewm(alpha=1/self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 3. Identificación de Fractales (Swings)
        # Un fractal en MT5 (defecto) son 5 velas (2 menores antes, 2 menores después)
        # Usamos rolling con center=True. Para evitar lookahead bias, confirmamos en t+2
        is_swing_low = (df['low'] == df['low'].rolling(window=5, center=True).min())
        is_swing_high = (df['high'] == df['high'].rolling(window=5, center=True).max())
        
        # Swing Lows confirmados (t-2)
        df['known_swing_low'] = is_swing_low.shift(2)
        df['swing_low_price'] = np.where(df['known_swing_low'], df['low'].shift(2), np.nan)
        df['swing_low_rsi'] = np.where(df['known_swing_low'], df['rsi'].shift(2), np.nan)
        df['swing_low_price'] = df['swing_low_price'].ffill()
        df['swing_low_rsi'] = df['swing_low_rsi'].ffill()
        
        # Swing Highs confirmados (t-2)
        df['known_swing_high'] = is_swing_high.shift(2)
        df['swing_high_price'] = np.where(df['known_swing_high'], df['high'].shift(2), np.nan)
        df['swing_high_rsi'] = np.where(df['known_swing_high'], df['rsi'].shift(2), np.nan)
        df['swing_high_price'] = df['swing_high_price'].ffill()
        df['swing_high_rsi'] = df['swing_high_rsi'].ffill()
        
        # 4. Lógica de Divergencia Oculta (Pullback actual vs Último Swing confirmado)
        # Compras
        bull_trend = (df['close'] > df['ema']) & (df['close'] > df['open'])
        # Higher Low en Precio, Lower Low en RSI
        hidden_bull_div = (df['low'] > df['swing_low_price']) & (df['rsi'] < df['swing_low_rsi'])
        buy_cond = bull_trend & hidden_bull_div
        
        # Ventas
        bear_trend = (df['close'] < df['ema']) & (df['close'] < df['open'])
        # Lower High en Precio, Higher High en RSI
        hidden_bear_div = (df['high'] < df['swing_high_price']) & (df['rsi'] > df['swing_high_rsi'])
        sell_cond = bear_trend & hidden_bear_div
        
        # 5. Generación de Señales
        df['signal'] = 0
        df.loc[buy_cond, 'signal'] = 1
        df.loc[sell_cond, 'signal'] = -1
        
        # 6. Cálculo Estructural de Stop Loss y Take Profit
        pip = 0.0001 # Aproximación (el orquestador lo refina)
        
        # SL: 2 pips por debajo del mínimo de la vela gatillo (o por encima del máximo)
        df['sl'] = np.where(df['signal'] == 1, df['low'] - (2 * pip), 
                   np.where(df['signal'] == -1, df['high'] + (2 * pip), 0.0))
                   
        # TP: Al último Swing opuesto (último máximo para compras, último mínimo para ventas)
        df['tp'] = np.where(df['signal'] == 1, df['swing_high_price'], 
                   np.where(df['signal'] == -1, df['swing_low_price'], 0.0))
                   
        # Cálculo del RR Ratio esperado (Forzando mínimo 1.5 matemático)
        risk = np.abs(df['close'] - df['sl'])
        reward = np.abs(df['tp'] - df['close'])
        
        # Si el reward es menor a 1.5x el riesgo, ajustamos el TP dinámicamente
        min_reward = risk * 1.5
        reward = np.maximum(reward, min_reward)
        
        # Re-ajuste de TP basado en el mínimo RR
        df['tp'] = np.where(df['signal'] == 1, df['close'] + reward, 
                   np.where(df['signal'] == -1, df['close'] - reward, df['tp']))
                   
        df['rr_ratio'] = reward / np.where(risk == 0, 1e-9, risk)
        df['rr_ratio'] = df['rr_ratio'].fillna(0.0)
        
        return df
