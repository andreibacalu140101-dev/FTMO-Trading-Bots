import pandas as pd
import numpy as np
from . import BaseStrategy

class SMC_FVG_Strategy(BaseStrategy):
    """
    Estrategia SMC FVG (Fair Value Gap) - M15
    Vectorización de Máquina de Estados para Gaps no mitigados.
    """
    def __init__(self, start_hour=8, end_hour=17, name="SMC_FVG"):
        super().__init__(name=name)
        self.start_hour = start_hour
        self.end_hour = end_hour

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df['signal'] = 0
        if len(df) < 3:
            return df
            
        # Aseguramos formato datetime
        if not pd.api.types.is_datetime64_any_dtype(df['time']):
            df['time'] = pd.to_datetime(df['time'])
            
        # 1. Identificación Vectorizada de FVGs (Patrón de 3 velas)
        # Shift(2) equivale a la Vela 3 (La más antigua del patrón)
        # Shift(1) equivale a la Vela 2 (Donde está el inbalance)
        # Shift(0) equivale a la Vela 1 (La vela actual que confirma el gap)
        df['high_shift_2'] = df['high'].shift(2)
        df['low_shift_2'] = df['low'].shift(2)
        
        # Bullish FVG: Máximo de vela 3 es menor al mínimo de vela 1
        df['is_bull_fvg'] = df['high_shift_2'] < df['low']
        # Bearish FVG: Mínimo de vela 3 es mayor al máximo de vela 1
        df['is_bear_fvg'] = df['low_shift_2'] > df['high']
        
        # 2. Extracción de propiedades del gap
        df['fvg_type'] = np.where(df['is_bull_fvg'], 1, np.where(df['is_bear_fvg'], -1, np.nan))
        df['fvg_high'] = np.where(df['is_bull_fvg'], df['low'], np.where(df['is_bear_fvg'], df['low_shift_2'], np.nan))
        df['fvg_low'] = np.where(df['is_bull_fvg'], df['high_shift_2'], np.where(df['is_bear_fvg'], df['high'], np.nan))
        df['fvg_mid'] = (df['fvg_high'] + df['fvg_low']) / 2.0
        df['fvg_sl_base'] = np.where(df['is_bull_fvg'], df['low_shift_2'], np.where(df['is_bear_fvg'], df['high_shift_2'], np.nan))
        
        # 3. Tracking del Ciclo de Vida del FVG (Máquina de Estados)
        # Asignar un ID único a cada gap
        df['fvg_id'] = (df['is_bull_fvg'] | df['is_bear_fvg']).cumsum()
        df['fvg_id'] = df['fvg_id'].replace(0, np.nan)
        
        # Forward fill properties
        df['fvg_type'] = df['fvg_type'].ffill()
        df['fvg_high'] = df['fvg_high'].ffill()
        df['fvg_low'] = df['fvg_low'].ffill()
        df['fvg_mid'] = df['fvg_mid'].ffill()
        df['fvg_sl_base'] = df['fvg_sl_base'].ffill()
        df['fvg_id'] = df['fvg_id'].ffill()
        
        # 4. Evaluación de Invalidación
        df['invalidation'] = False
        df.loc[(df['fvg_type'] == 1) & (df['close'] < df['fvg_low']), 'invalidation'] = True
        df.loc[(df['fvg_type'] == -1) & (df['close'] > df['fvg_high']), 'invalidation'] = True
        
        # 5. Evaluación de Mitigación (Gatillo)
        df['mitigation'] = False
        bull_mitigation = (df['fvg_type'] == 1) & (df['low'] <= df['fvg_mid']) & (df['close'] > df['open'])
        bear_mitigation = (df['fvg_type'] == -1) & (df['high'] >= df['fvg_mid']) & (df['close'] < df['open'])
        
        df.loc[bull_mitigation | bear_mitigation, 'mitigation'] = True
        
        # 6. Filtrar gaps ya consumidos (para evitar múltiples señales del mismo FVG)
        df['consumed_event'] = df['invalidation'] | df['mitigation']
        # Usamos shift(1) para saber si AL EMPEZAR LA VELA ACTUAL el gap ya estaba consumido
        df['already_consumed'] = df.groupby('fvg_id')['consumed_event'].cumsum().shift(1).fillna(0) > 0
        
        # 7. Filtro Horario
        df['hour'] = df['time'].dt.hour
        in_session = (df['hour'] >= self.start_hour) & (df['hour'] < self.end_hour)
        
        # 8. Señal Final
        df['valid_buy_trigger'] = bull_mitigation & ~df['already_consumed'] & in_session
        df['valid_sell_trigger'] = bear_mitigation & ~df['already_consumed'] & in_session
        
        df.loc[df['valid_buy_trigger'], 'signal'] = 1
        df.loc[df['valid_sell_trigger'], 'signal'] = -1
        
        # 9. Cálculo Estructural de SL y TP
        pip = 0.0001
        
        # SL forzado mínimo a 5 pips desde la base
        df['sl_buy'] = np.minimum(df['fvg_sl_base'] - pip, df['close'] - (5 * pip))
        df['sl_sell'] = np.maximum(df['fvg_sl_base'] + pip, df['close'] + (5 * pip))
        
        df['sl'] = np.where(df['signal'] == 1, df['sl_buy'], 
                   np.where(df['signal'] == -1, df['sl_sell'], 0.0))
                   
        risk = np.abs(df['close'] - df['sl'])
        
        # TP Asimétrico Fijo a 1:3
        df['tp'] = np.where(df['signal'] == 1, df['close'] + (risk * 3.0),
                   np.where(df['signal'] == -1, df['close'] - (risk * 3.0), 0.0))
                   
        df['rr_ratio'] = 3.0
        
        return df
