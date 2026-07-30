import pandas as pd
import numpy as np
from datetime import datetime, time
from . import BaseStrategy

class NY_ORB_Strategy(BaseStrategy):
    """
    Estrategia NY ORB (Opening Range Breakout) - M5
    Observación del rango 15:30 - 16:00. Ejecución del breakout 16:00 - 17:00.
    """
    def __init__(self, name="NY_ORB"):
        super().__init__(name=name)

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df['signal'] = 0
        if len(df) < 20:
            return df
            
        df['time'] = pd.to_datetime(df['time'])
        df['hour'] = df['time'].dt.hour
        df['minute'] = df['time'].dt.minute
        df['date'] = df['time'].dt.date
        
        # 1. Definición del bloque de observación (15:30 a 16:00)
        obs_mask = (df['hour'] == 15) & (df['minute'] >= 30)
        
        # 2. Obtenemos el High y Low de esta ventana por día
        df['obs_high'] = np.where(obs_mask, df['high'], np.nan)
        df['obs_low'] = np.where(obs_mask, df['low'], np.nan)
        
        range_high = df.groupby('date')['obs_high'].transform('max')
        range_low = df.groupby('date')['obs_low'].transform('min')
        
        # 3. Definición del bloque de ejecución (16:00 a 17:00)
        exec_mask = (df['hour'] == 16)
        
        # 4. Lógica de Breakout
        buy_cond = exec_mask & (df['close'] > range_high)
        sell_cond = exec_mask & (df['close'] < range_low)
        
        df.loc[buy_cond, 'signal'] = 1
        df.loc[sell_cond, 'signal'] = -1
        
        # SL estructural (centro del rango). El Orquestador sumará el Buffer.
        df['midpoint'] = (range_high + range_low) / 2.0
        df['sl'] = df['midpoint']
        
        return df
