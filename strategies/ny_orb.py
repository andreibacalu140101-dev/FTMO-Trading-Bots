import pandas as pd
import numpy as np
import pytz
from datetime import datetime, time
from . import BaseStrategy

class NY_ORB_Strategy(BaseStrategy):
    """
    Estrategia NY ORB (Opening Range Breakout) - M5
    Rango Asiático / NY Open (08:00 a 08:15). Breakout con volumen.
    """
    def __init__(self, vol_sma_period=20, name="NY_ORB"):
        super().__init__(name=name)
        self.vol_sma_period = vol_sma_period

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        # Filtro de Sesión Descentralizado (14:30 a 16:30 CET)
        tz = pytz.timezone('Europe/Prague')
        current_time = datetime.now(tz).time()
        
        if not (time(14, 30) <= current_time <= time(16, 30)):
            return None
            
        # Aseguramos formato datetime
        if not pd.api.types.is_datetime64_any_dtype(df['time']):
            df['time'] = pd.to_datetime(df['time'])
            
        df['signal'] = 0
        if len(df) < self.vol_sma_period:
            return df
            
        # 1. Definición del bloque horario (08:00 a 08:15)
        start_time = pd.to_datetime('08:00:00').time()
        end_time = pd.to_datetime('08:15:00').time()
        close_time = pd.to_datetime('11:00:00').time()
        
        # Filtro de tiempo para el rango
        time_mask = (df['time'].dt.time >= start_time) & (df['time'].dt.time <= end_time)
        
        # 2. Cálculo Vectorial del Rango Máximo y Mínimo por Día (Estrictamente Causal)
        df['date'] = df['time'].dt.date
        
        # Guardamos el high/low solo si estamos dentro de la ventana de observación
        df['range_high_accum'] = np.where(time_mask, df['high'], np.nan)
        df['range_low_accum'] = np.where(time_mask, df['low'], np.nan)
        
        # Usamos cummax/cummin por día para acumular el máximo/mínimo hasta la vela actual (0 Look-Ahead)
        df['range_high'] = df.groupby('date')['range_high_accum'].cummax()
        df['range_low'] = df.groupby('date')['range_low_accum'].cummin()
        
        # Propagamos el último valor conocido hacia adelante para usarlo después de las 08:15
        df['range_high'] = df['range_high'].ffill()
        df['range_low'] = df['range_low'].ffill()
        
        # 3. Cálculo de la SMA del Volumen
        # En MT5 se usa 'tick_volume'
        vol_col = 'tick_volume' if 'tick_volume' in df.columns else 'volume'
        df['vol_sma'] = df[vol_col].rolling(window=self.vol_sma_period).mean()
        
        # 4. Lógica de Breakout
        # Solo operamos DESPUÉS de las 08:15 y ANTES de las 11:00
        active_window = (df['time'].dt.time > end_time) & (df['time'].dt.time < close_time)
        
        # Compras
        buy_cond = active_window & (df['close'] > df['range_high']) & (df[vol_col] > df['vol_sma'])
        
        # Ventas
        sell_cond = active_window & (df['close'] < df['range_low']) & (df[vol_col] > df['vol_sma'])
        
        # 5. Generación de Señales (Solo la primera señal válida del día se respeta en la ejecución real)
        df.loc[buy_cond, 'signal'] = 1
        df.loc[sell_cond, 'signal'] = -1
        
        # 6. Cálculo Estructural de Stop Loss y Take Profit
        # SL en el punto medio del rango
        df['midpoint'] = (df['range_high'] + df['range_low']) / 2.0
        df['sl'] = df['midpoint']
        
        risk = np.abs(df['close'] - df['sl'])
        
        # Ratio 1:2
        df['tp'] = np.where(df['signal'] == 1, df['close'] + (risk * 2.0),
                   np.where(df['signal'] == -1, df['close'] - (risk * 2.0), 0.0))
                   
        df['rr_ratio'] = 2.0
        
        return df
