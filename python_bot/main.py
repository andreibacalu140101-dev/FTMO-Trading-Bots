import MetaTrader5 as mt5
import time
import pandas as pd
from datetime import datetime
import pytz
from risk_manager import FTMORiskManager
import config

def initialize_mt5():
    """Inicializa la conexión segura con la terminal MetaTrader 5."""
    print("Iniciando conexión con MetaTrader 5...")
    
    if config.MT5_ACCOUNT != 0 and config.MT5_PASSWORD != "":
        authorized = mt5.initialize(login=config.MT5_ACCOUNT, server=config.MT5_SERVER, password=config.MT5_PASSWORD)
    else:
        authorized = mt5.initialize()
        
    if not authorized:
        print(f"❌ Fallo al inicializar MT5, error code = {mt5.last_error()}")
        return False
        
    terminal_info = mt5.terminal_info()
    if terminal_info is None:
        print("❌ No se pudo obtener información de la terminal.")
        return False
        
    if not terminal_info.trade_allowed:
        print("❌ AutoTrading está DESACTIVADO en la terminal MT5. Actívalo para continuar.")
        return False
        
    print(f"✅ Conexión establecida. Terminal Build: {terminal_info.build}")
    return True

def fetch_rates_with_retry(symbol, timeframe, count, max_retries=3):
    """Watchdog: Obtiene velas con backoff exponencial si hay fallo de conexión."""
    for attempt in range(max_retries):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is not None and len(rates) > 0:
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df
        
        # Fallo en la obtención, posible pérdida de conexión
        wait_time = 2 ** attempt  # 1s, 2s, 4s...
        print(f"⚠️ Error obteniendo datos para {symbol}. Reintentando en {wait_time}s... (Intento {attempt+1}/{max_retries})")
        time.sleep(wait_time)
        
        # Intentar reconectar si la conexión se cayó
        if mt5.terminal_info() is None:
            print("🔄 Intento de reconexión a MT5...")
            initialize_mt5()
            
    return None

def is_within_trading_hours():
    """Verifica si la hora actual del broker está dentro de TRADING_HOURS."""
    tz = pytz.timezone(config.BROKER_TIMEZONE)
    now = datetime.now(tz)
    
    start_time = datetime.strptime(config.TRADING_HOURS["start"], "%H:%M").time()
    end_time = datetime.strptime(config.TRADING_HOURS["end"], "%H:%M").time()
    
    current_time = now.time()
    return start_time <= current_time <= end_time

def main():
    if not initialize_mt5():
        mt5.shutdown()
        return

    print("🤖 Bot Algorítmico Cuantitativo Iniciado.")
    risk_manager = FTMORiskManager()
    
    # strategies = [ Strategy1(), Strategy2() ] # Instanciar aquí las clases de estrategias
    strategies = [] 
    
    # Inicializar símbolos en MT5
    for symbol in config.SYMBOLS:
        mt5.symbol_select(symbol, True)

    try:
        while True:
            # 1. Verificar Límites de Riesgo Diarios y Gestionar Break Evens
            is_blocked = risk_manager.update()
            risk_manager.manage_breakeven()
            
            # Si estamos fuera de horario, no evaluamos nuevas entradas
            if not is_blocked and is_within_trading_hours():
                
                # Bucle Symbol-First
                for symbol in config.SYMBOLS:
                    # 2. Filtro de Spread en Vivo
                    tick = mt5.symbol_info_tick(symbol)
                    symbol_info = mt5.symbol_info(symbol)
                    
                    if tick is None or symbol_info is None:
                        continue
                        
                    pip_size = 10 * symbol_info.point if (symbol_info.digits == 5 or symbol_info.digits == 3) else symbol_info.point
                    current_spread_pips = (tick.ask - tick.bid) / pip_size
                    
                    if current_spread_pips > config.MAX_SPREAD_PIPS:
                        continue # Descartar símbolo temporalmente por alto spread
                        
                    # 3. Watchdog: Obtener velas
                    df = fetch_rates_with_retry(symbol, config.TIMEFRAME, count=50)
                    if df is None:
                        continue
                        
                    # 4. Evaluar Estrategias
                    best_signal = None
                    for strategy in strategies:
                        # expected signature: strategy.evaluate(df, symbol)
                        signal = strategy.evaluate(df, symbol)
                        if signal is not None:
                            # Comparar R:R para quedarnos con la mejor señal si hay varias
                            if best_signal is None or signal.get('rr_ratio', 0) > best_signal.get('rr_ratio', 0):
                                best_signal = signal
                                
                    # 5. Control de Correlación y Ejecución
                    if best_signal is not None:
                        if risk_manager.can_open_trade(symbol):
                            # Aquí iría el código de order_send utilizando best_signal
                            # print(f"🚀 Ejecutando {best_signal['signal_type']} en {symbol}")
                            pass
            
            # Pausa para no consumir 100% CPU
            time.sleep(config.TICK_SLEEP)
            
    except KeyboardInterrupt:
        print("\n⏹️ Deteniendo bot por interrupción manual (Ctrl+C).")
    finally:
        mt5.shutdown()
        print("🔌 Conexión con MT5 cerrada de forma segura.")

if __name__ == "__main__":
    main()
