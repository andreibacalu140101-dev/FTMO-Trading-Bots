# python_bot/strategies/__init__.py
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np

class BaseStrategy(ABC):
    """
    Clase base para todas las estrategias cuantitativas vectorizadas.
    """
    
    def __init__(self, name="Base"):
        self.name = name
        
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Lógica vectorial pura (sin bucles for).
        Debe devolver el mismo DataFrame añadiendo las columnas:
        - 'signal' (1 = Compra, -1 = Venta, 0 = Neutral)
        - 'sl' (Stop Loss price)
        - 'tp' (Take Profit price)
        - 'rr_ratio' (Risk:Reward Ratio esperado)
        """
        pass
        
    def evaluate(self, df: pd.DataFrame, symbol: str):
        """
        Puente hacia el orquestador main.py. Ejecuta la vectorización 
        y extrae únicamente la vela cerrada válida (índice -2).
        """
        if df is None or len(df) < 2:
            return None
            
        # Ejecutar la lógica vectorial completa
        df = self.generate_signals(df.copy())
        
        # Extraer la fila de la última vela cerrada (-2) para Anti-Repaint
        closed_candle = df.iloc[-2]
        
        # Si la señal no es 0 (Neutral) y las columnas requeridas existen
        if closed_candle.get('signal', 0) != 0:
            signal_type = "BUY" if closed_candle['signal'] == 1 else "SELL"
            
            # Generar el diccionario esperado por main.py
            return {
                "signal_type": signal_type,
                "entry": closed_candle['close'],
                "sl": closed_candle.get('sl', 0.0),
                "tp": closed_candle.get('tp', 0.0),
                "rr_ratio": closed_candle.get('rr_ratio', 2.0),
                "strategy_name": self.name
            }
            
        return None

from .hidden_divergence import HiddenDivergenceStrategy
from .ny_orb import NY_ORB_Strategy
from .night_scalper import NightScalperStrategy
from .smc_fvg import SMC_FVG_Strategy
from .trend_momentum import TrendMomentumStrategy
from .vwap_pullback import VWAP_Pullback_Strategy
from .volatility_breakout import VolatilityBreakoutStrategy

