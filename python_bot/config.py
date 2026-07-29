# python_bot/config.py

# Credenciales de MT5 (Opcional, dejar vacío si ya está logueado en la terminal local)
MT5_ACCOUNT = 0
MT5_PASSWORD = ""
MT5_SERVER = ""

# Gestión de Riesgo Global
MAGIC_NUMBER = 777000
DAILY_DRAWDOWN_LIMIT = 400.0  # Regla dura de FTMO
RISK_PER_TRADE_USD = 50.0

# Zona Horaria (Broker) - FTMO usa huso horario CET/CEST
BROKER_TIMEZONE = "Europe/Prague"

# Temporizadores
TICK_SLEEP = 1.0 # Segundos de espera en el bucle principal
