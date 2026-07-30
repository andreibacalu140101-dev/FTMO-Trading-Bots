import pandas as pd
import numpy as np
from datetime import datetime, time
from . import BaseStrategy

class SMC_FVG_Strategy(BaseStrategy):
    """
    Estrategia SMC FVG (Fair Value Gap) - M5
    Detección y mitigación de FVG en la ventana 08:30 - 11:30 CET.
    """
    def __init__(self, name="SMC_FVG"):
        super().__init__(name=name)

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df['signal'] = 0
        if len(df) < 5:
            return df
            
        df['time'] = pd.to_datetime(df['time'])
        df['hour'] = df['time'].dt.hour
        df['minute'] = df['time'].dt.minute
        
        # 1. Filtro de Sesión (08:30 a 11:30)
        is_fvg_window = ((df['hour'] == 8) & (df['minute'] >= 30)) | \
                        ((df['hour'] > 8) & (df['hour'] < 11)) | \
                        ((df['hour'] == 11) & (df['minute'] <= 30))
                        
        # 2. Detección FVG (Vela 1 = shift(3), Vela 3 = shift(1), actual = 0)
        bull_fvg_formed = (df['high'].shift(3) < df['low'].shift(1)) & (df['close'].shift(2) > df['open'].shift(2))
        bear_fvg_formed = (df['low'].shift(3) > df['high'].shift(1)) & (df['close'].shift(2) < df['open'].shift(2))
        
        # Marcar los límites del FVG en el instante que se forman
        df['bull_top'] = np.where(bull_fvg_formed & is_fvg_window, df['low'].shift(1), np.nan)
        df['bull_bot'] = np.where(bull_fvg_formed & is_fvg_window, df['high'].shift(3), np.nan)
        
        df['bear_top'] = np.where(bear_fvg_formed & is_fvg_window, df['low'].shift(3), np.nan)
        df['bear_bot'] = np.where(bear_fvg_formed & is_fvg_window, df['high'].shift(1), np.nan)
        
        # Propagar valores temporalmente (solo dentro de la sesión)
        df['bull_top'] = df['bull_top'].ffill()
        df['bull_bot'] = df['bull_bot'].ffill()
        df['bear_top'] = df['bear_top'].ffill()
        df['bear_bot'] = df['bear_bot'].ffill()
        
        df['bull_top'] = np.where(is_fvg_window, df['bull_top'], np.nan)
        df['bull_bot'] = np.where(is_fvg_window, df['bull_bot'], np.nan)
        df['bear_top'] = np.where(is_fvg_window, df['bear_top'], np.nan)
        df['bear_bot'] = np.where(is_fvg_window, df['bear_bot'], np.nan)
        
        # 3. Mitigación (Entrada) cuando el precio retrocede y toca la zona
        buy_cond = is_fvg_window & (df['low'] <= df['bull_top']) & (df['low'].shift(1) > df['bull_top'])
        sell_cond = is_fvg_window & (df['high'] >= df['bear_bot']) & (df['high'].shift(1) < df['bear_bot'])
        
        df.loc[buy_cond, 'signal'] = 1
        df.loc[sell_cond, 'signal'] = -1
        
        # SL base en el extremo opuesto del FVG. Main.py sumará el Buffer de ATR + Spread
        df['sl'] = 0.0
        df.loc[buy_cond, 'sl'] = df['bull_bot']
        df.loc[sell_cond, 'sl'] = df['bear_top']
        
        return df
