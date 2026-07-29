# python_bot/config.py
import MetaTrader5 as mt5

# Credenciales de MT5 (Opcional, dejar vacío si ya está logueado en la terminal local)
MT5_ACCOUNT = 0
MT5_PASSWORD = ""
MT5_SERVER = ""

# Gestión de Riesgo Global
MAGIC_NUMBER = 777000
DAILY_DRAWDOWN_LIMIT = 400.0  # Regla dura de FTMO
HARD_STOP_LIMIT = 380.0       # Panic Button Limit para evitar slippage
RISK_PER_TRADE_USD = 50.0
MAX_SPREAD_PIPS = 1.5         # Máximo spread permitido para entrar

# Zona Horaria (Broker) - FTMO usa huso horario CET/CEST
BROKER_TIMEZONE = "Europe/Prague"

# Horarios de Trading Estrictos (CET)
TRADING_HOURS = {
    "start": "08:00",
    "end": "17:00"
}

# Matriz de Exposición y Correlación
# Máximo 2 trades activos por moneda en toda la cuenta.
CURRENCY_EXPOSURE_GROUPS = {
    "USD": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"],
    "EUR": ["EURUSD", "EURGBP", "EURJPY", "EURAUD", "EURCAD", "EURCHF"],
    "GBP": ["GBPUSD", "EURGBP", "GBPJPY", "GBPAUD", "GBPCAD", "GBPCHF"],
    "JPY": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY"],
    "AUD": ["AUDUSD", "EURAUD", "GBPAUD", "AUDJPY", "AUDCAD", "AUDCHF"],
    "CAD": ["USDCAD", "EURCAD", "GBPCAD", "CADJPY", "AUDCAD", "CADCHF"],
    "CHF": ["USDCHF", "EURCHF", "GBPCHF", "CHFJPY", "AUDCHF", "CADCHF"],
    "NZD": ["NZDUSD", "EURNZD", "GBPNZD", "NZDJPY", "AUDNZD", "NZDCAD", "NZDCHF"]
}

# Símbolos a operar
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"]

# Temporizadores y Concurrencia
TIMEFRAME = mt5.TIMEFRAME_M5
TICK_SLEEP = 1.0 # Segundos de espera en el bucle principal
