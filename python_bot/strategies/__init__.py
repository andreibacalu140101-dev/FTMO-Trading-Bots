# python_bot/strategies/__init__.py
from abc import ABC, abstractmethod
import pandas as pd

class BaseStrategy(ABC):
    """
    Clase base para todas las estrategias cuantitativas.
    Implementa reglas Anti-Repaint y un formato estándar de señal.
    """
    
    def __init__(self, name="Base"):
        self.name = name
        self.last_signal_time = None
        
    @abstractmethod
    def generate_signal(self, df, symbol):
        """
        Lógica interna de la estrategia. 
        Debe devolver un diccionario con la señal o None.
        Ejemplo de retorno:
        {
            "signal_type": "BUY", # o "SELL"
            "entry": 1.0500,
            "sl": 1.0480,
            "tp": 1.0540,
            "rr_ratio": 2.0
        }
        """
        pass
        
    def evaluate(self, df: pd.DataFrame, symbol: str):
        """
        Evalúa el DataFrame aplicando estrictamente reglas Anti-Repaint.
        Solo evalúa sobre velas cerradas y evita generar señales múltiples en la misma vela.
        """
        if df is None or len(df) < 2:
            return None
            
        # 1. Regla Anti-Repaint: Extraemos la vela recién cerrada (índice -2)
        # La vela en curso (índice -1) todavía se está formando y su cierre no es definitivo.
        closed_candle_time = df.iloc[-2]['time']
        
        # 2. Control de Frecuencia: No emitir señal dos veces para la misma vela
        if self.last_signal_time == closed_candle_time:
            return None
            
        # 3. Delegar a la lógica específica de la estrategia
        signal = self.generate_signal(df, symbol)
        
        # 4. Registrar timestamp si hay señal para evitar repintado/spam
        if signal is not None:
            self.last_signal_time = closed_candle_time
            signal['strategy_name'] = self.name
            
        return signal
