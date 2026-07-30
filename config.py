import MetaTrader5 as mt5
from typing import List, Dict

# ==========================================
# ⚙️ CONFIGURACIÓN DEL ENTORNO METATRADER 5
# ==========================================
# (Opcional: Dejar vacío si la terminal ya está abierta y logueada)
MT5_ACCOUNT: int = 0
MT5_PASSWORD: str = ""
MT5_SERVER: str = ""

# ==========================================
# 🤖 IDENTIFICADORES DEL BOT
# ==========================================
# Número mágico para aislar las operaciones de este bot de la operativa manual
MAGIC_NUMBER: int = 777777

# ==========================================
# 📈 UNIVERSO DE ACTIVOS (SÍMBOLOS)
# ==========================================
# Lista principal de activos donde operarán las 7 estrategias
SYMBOLS: List[str] = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "XAUUSD",
    "US30.cash"
]

# Timeframe por defecto a evaluar
TIMEFRAME = mt5.TIMEFRAME_M15

# Temporizador del main loop (en segundos)
TICK_SLEEP: float = 1.0

# ==========================================
# 🛡️ GESTIÓN DE RIESGO Y FTMO ($10,000)
# ==========================================
# Porcentaje de la cuenta a arriesgar por trade (0.5% = $50 en cuenta de 10k)
RISK_PER_TRADE_PERCENT: float = 0.5 

# Límite duro diario en USD para proteger el límite de $400 de FTMO
MAX_DAILY_LOSS_USD: float = 380.0

# ==========================================
# 🌐 HORARIOS DE OPERACIÓN (SESIONES)
# ==========================================
# FTMO utiliza los servidores de Praga/Berlín para sus cortes diarios
BROKER_TIMEZONE: str = "Europe/Prague"

# Restricción de operativa (Ej: Solo Sesión de NY o Londres cruzada)
TRADING_START_HOUR: int = 8
TRADING_END_HOUR: int = 17

# ==========================================
# ⚖️ MATRIZ DE EXPOSICIÓN (CORRELACIÓN)
# ==========================================
# Define la correlación sectorial. El Risk Manager (risk_manager.py) bloqueará 
# nuevas posiciones si una divisa base/cotizada específica alcanza 2 operaciones simultáneas.
CURRENCY_EXPOSURE_GROUPS: Dict[str, List[str]] = {
    "USD": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "USDCAD", "USDCHF"],
    "EUR": ["EURUSD", "EURGBP", "EURJPY", "EURAUD", "EURCAD", "EURCHF"],
    "GBP": ["GBPUSD", "EURGBP", "GBPJPY", "GBPAUD", "GBPCAD", "GBPCHF"],
    "JPY": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY"],
    "AUD": ["AUDUSD", "EURAUD", "GBPAUD", "AUDJPY", "AUDCAD", "AUDCHF"],
    "CAD": ["USDCAD", "EURCAD", "GBPCAD", "CADJPY", "AUDCAD", "CADCHF"],
    "CHF": ["USDCHF", "EURCHF", "GBPCHF", "CHFJPY", "AUDCHF", "CADCHF"],
    "NZD": ["NZDUSD", "EURNZD", "GBPNZD", "NZDJPY", "AUDNZD", "NZDCAD", "NZDCHF"],
    "METALS": ["XAUUSD", "XAGUSD"],
    "INDICES": ["US30", "NAS100", "GER40"]
}
