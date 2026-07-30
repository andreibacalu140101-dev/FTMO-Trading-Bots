import pandas as pd
import numpy as np
from . import BaseStrategy

class VWAP_Pullback_Strategy(BaseStrategy):
    """
    Estrategia VWAP Pullback (M5)
    Operar pullbacks al VWAP intradiario combinados con cruces de sobreventa/sobrecompra del Estocástico.
    """
    def __init__(self, stoch_k=14, stoch_d=3, stoch_slowing=3, start_hour=8, end_hour=17, name="VWAP_Pullback"):
        super().__init__(name=name)
        self.stoch_k = stoch_k
        self.stoch_d = stoch_d
        self.stoch_slowing = stoch_slowing
        self.start_hour = start_hour
        self.end_hour = end_hour

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df['signal'] = 0
        if len(df) < self.stoch_k + self.stoch_d + self.stoch_slowing:
            return df
            
        if not pd.api.types.is_datetime64_any_dtype(df['time']):
            df['time'] = pd.to_datetime(df['time'])
            
        # 1. VWAP Intradiario Vectorizado
        df['date'] = df['time'].dt.date
        vol_col = 'tick_volume' if 'tick_volume' in df.columns else 'volume'
        
        df['typ_price'] = (df['high'] + df['low'] + df['close']) / 3.0
        df['pv'] = df['typ_price'] * df[vol_col]
        
        df['cum_pv'] = df.groupby('date')['pv'].cumsum()
        df['cum_v'] = df.groupby('date')[vol_col].cumsum()
        
        df['vwap'] = df['cum_pv'] / df['cum_v']
        
        # 2. Estocástico (14, 3, 3) Vectorizado
        highest_high = df['high'].rolling(window=self.stoch_k).max()
        lowest_low = df['low'].rolling(window=self.stoch_k).min()
        
        # Estocástico Rápido %K
        k_fast = 100 * (df['close'] - lowest_low) / (highest_high - lowest_low)
        
        # Suavizado (%K Principal)
        df['stoch_main'] = k_fast.rolling(window=self.stoch_slowing).mean()
        
        # Señal (%D)
        df['stoch_sig'] = df['stoch_main'].rolling(window=self.stoch_d).mean()
        
        df['stoch_main_prev'] = df['stoch_main'].shift(1)
        df['stoch_sig_prev'] = df['stoch_sig'].shift(1)
        
        # 3. Lógica de Pullback al VWAP
        # Evaluamos el VWAP con la vela actual (0) y la vela anterior (1)
        df['vwap_prev'] = df['vwap'].shift(1)
        
        # Verificar toque del VWAP en vela actual o anterior
        touched_curr = (df['low'] <= df['vwap']) & (df['high'] >= df['vwap'])
        touched_prev = (df['low'].shift(1) <= df['vwap_prev']) & (df['high'].shift(1) >= df['vwap_prev'])
        touched = touched_curr | touched_prev
        
        # 4. Horario Operativo
        df['hour'] = df['time'].dt.hour
        in_session = (df['hour'] >= self.start_hour) & (df['hour'] < self.end_hour)
        
        # 5. Gatillos
        # Compras
        stoch_cross_up = (df['stoch_main'] > df['stoch_sig']) & (df['stoch_main_prev'] <= df['stoch_sig_prev'])
        oversold = (df['stoch_main'] < 20.0) | (df['stoch_main_prev'] < 20.0)
        
        buy_cond = in_session & touched & (df['close'] > df['vwap']) & (df['close'] > df['open']) & stoch_cross_up & oversold
        
        # Ventas
        stoch_cross_down = (df['stoch_main'] < df['stoch_sig']) & (df['stoch_main_prev'] >= df['stoch_sig_prev'])
        overbought = (df['stoch_main'] > 80.0) | (df['stoch_main_prev'] > 80.0)
        
        sell_cond = in_session & touched & (df['close'] < df['vwap']) & (df['close'] < df['open']) & stoch_cross_down & overbought
        
        df.loc[buy_cond, 'signal'] = 1
        df.loc[sell_cond, 'signal'] = -1
        
        # 6. SL y TP
        pip = 0.0001
        
        # SL por Debajo/Encima del pullback, con forzado mínimo a 10 pips
        # Evaluamos el mínimo/máximo de las dos velas involucradas en el pullback
        min_2_bars = np.minimum(df['low'], df['low'].shift(1))
        max_2_bars = np.maximum(df['high'], df['high'].shift(1))
        
        sl_base = np.where(df['signal'] == 1, min_2_bars,
                  np.where(df['signal'] == -1, max_2_bars, 0.0))
                  
        sl_dist = np.abs(df['close'] - sl_base)
        min_sl = 10 * pip
        sl_dist = np.maximum(sl_dist, min_sl)
        
        df['sl'] = np.where(df['signal'] == 1, df['close'] - sl_dist,
                   np.where(df['signal'] == -1, df['close'] + sl_dist, 0.0))
                   
        # Ratio 1:2
        df['tp'] = np.where(df['signal'] == 1, df['close'] + (sl_dist * 2.0),
                   np.where(df['signal'] == -1, df['close'] - (sl_dist * 2.0), 0.0))
                   
        df['rr_ratio'] = 2.0
        
        return df
