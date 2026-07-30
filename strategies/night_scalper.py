import pandas as pd
import numpy as np
import pytz
from datetime import datetime, time
from . import BaseStrategy

class NightScalperStrategy(BaseStrategy):
    """
    Estrategia Night Scalper (M15)
    Reversión a la media nocturna con Bandas de Bollinger y RSI.
    """
    def __init__(self, bb_period=20, bb_dev=2.5, rsi_period=14, fixed_sl_pips=15.0, name="NightScalper"):
        super().__init__(name=name)
        self.bb_period = bb_period
        self.bb_dev = bb_dev
        self.rsi_period = rsi_period
        self.fixed_sl_pips = fixed_sl_pips

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        # Filtro de Sesión Descentralizado (23:00 a 02:00 CET)
        tz = pytz.timezone('Europe/Prague')
        current_time = datetime.now(tz).time()
        
        # Como cruza la medianoche, la lógica de ventana es diferente
        if not (current_time >= time(23, 0) or current_time <= time(2, 0)):
            return None
            
        if len(df) < max(self.bb_period, self.rsi_period):
            df['signal'] = 0
            return df
            
        # 1. Bollinger Bands
        df['bb_mid'] = df['close'].rolling(window=self.bb_period).mean()
        # En MT5 la desviación por defecto no asume muestra (-1), usa ddof=0 o ddof=1 dependiendo
        # Usaremos ddof=0 por defecto estadístico
        df['bb_std'] = df['close'].rolling(window=self.bb_period).std(ddof=0)
        
        df['bb_upper'] = df['bb_mid'] + (self.bb_dev * df['bb_std'])
        df['bb_lower'] = df['bb_mid'] - (self.bb_dev * df['bb_std'])
        
        # 2. RSI 14 (Vectorizado puro)
        delta = df['close'].diff()
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        
        avg_gain = pd.Series(gain).ewm(alpha=1/self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        avg_loss = pd.Series(loss).ewm(alpha=1/self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 3. Lógica de Reversión
        # Compras
        buy_cond = (df['close'] < df['bb_lower']) & (df['rsi'] < 30.0)
        
        # Ventas
        sell_cond = (df['close'] > df['bb_upper']) & (df['rsi'] > 70.0)
        
        # Generación
        df['signal'] = 0
        df.loc[buy_cond, 'signal'] = 1
        df.loc[sell_cond, 'signal'] = -1
        
        # 4. Cálculo Estructural de Stop Loss y Take Profit
        # En la estrategia, el SL es fijo en pips (15 pips)
        pip = 0.0001
        sl_dist = self.fixed_sl_pips * pip
        
        df['sl'] = np.where(df['signal'] == 1, df['close'] - sl_dist,
                   np.where(df['signal'] == -1, df['close'] + sl_dist, 0.0))
                   
        # El TP es dinámico a la banda media. Lo calculamos aquí de manera proyectada
        # para que el orquestador pueda evaluar el R:R esperado
        df['tp'] = np.where(df['signal'] != 0, df['bb_mid'], 0.0)
        
        risk = np.abs(df['close'] - df['sl'])
        reward = np.abs(df['tp'] - df['close'])
        
        df['rr_ratio'] = reward / np.where(risk == 0, 1e-9, risk)
        df['rr_ratio'] = df['rr_ratio'].fillna(0.0)
        
        return df
