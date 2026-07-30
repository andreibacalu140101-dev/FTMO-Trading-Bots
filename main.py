import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime
import pytz
import traceback

import config
from risk_manager import FTMORiskManager

# Importar las 7 estrategias
from strategies import (
    HiddenDivergenceStrategy,
    NY_ORB_Strategy,
    NightScalperStrategy,
    SMC_FVG_Strategy,
    TrendMomentumStrategy,
    VWAP_Pullback_Strategy,
    VolatilityBreakoutStrategy
)

def log(msg):
    """Función de logging con timestamp para consola."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")

def initialize_mt5():
    """Conecta a la terminal MetaTrader 5."""
    log("Iniciando conexión con MetaTrader 5...")
    
    if hasattr(config, 'MT5_ACCOUNT') and config.MT5_ACCOUNT != 0 and config.MT5_PASSWORD != "":
        authorized = mt5.initialize(login=config.MT5_ACCOUNT, server=config.MT5_SERVER, password=config.MT5_PASSWORD)
    else:
        authorized = mt5.initialize()
        
    if not authorized:
        log(f"❌ Error CRÍTICO: No se pudo conectar a MT5. Código: {mt5.last_error()}")
        return False
        
    terminal_info = mt5.terminal_info()
    if terminal_info is None:
        log("❌ Error CRÍTICO: No se obtuvo info de la terminal.")
        return False
        
    if not terminal_info.trade_allowed:
        log("❌ AutoTrading está DESACTIVADO en la terminal MT5.")
        return False
        
    log(f"✅ Conectado exitosamente. Terminal Build: {terminal_info.build}")
    return True

def fetch_rates_with_retry(symbol, timeframe, count, max_retries=3):
    """Descarga de velas segura con backoff en caso de fallos."""
    for attempt in range(max_retries):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is not None and len(rates) > 0:
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df
        
        wait_time = 2 ** attempt
        log(f"⚠️ Aviso: Fallo obteniendo velas de {symbol}. Reintentando en {wait_time}s...")
        time.sleep(wait_time)
        
        # Reconexión de emergencia
        if mt5.terminal_info() is None:
            log("🔄 Terminal desconectada. Intentando reconectar...")
            initialize_mt5()
            
    return None

def calculate_volume(symbol, sl_price, entry_price):
    """Calcula el lotaje dinámico basado en el porcentaje de riesgo del balance."""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return 0.01 # Fallback
        
    account_info = mt5.account_info()
    if account_info is None:
        return 0.01
        
    # Cálculo dinámico basado en el balance actual de la cuenta
    risk_percent = getattr(config, 'RISK_PER_TRADE_PERCENT', 0.5)
    risk_usd = account_info.balance * (risk_percent / 100.0)
    
    risk_dist = abs(entry_price - sl_price)
    
    if risk_dist == 0:
        return symbol_info.volume_min
        
    tick_value = symbol_info.trade_tick_value
    tick_size = symbol_info.trade_tick_size
    
    # Pérdida de 1 lote = (risk_dist / tick_size) * tick_value
    if tick_size == 0 or tick_value == 0:
        return symbol_info.volume_min
        
    loss_for_one_lot = (risk_dist / tick_size) * tick_value
    if loss_for_one_lot == 0:
        return symbol_info.volume_min
        
    volume = risk_usd / loss_for_one_lot
    
    # Normalizar volumen
    step = symbol_info.volume_step
    volume = round(volume / step) * step
    volume = max(symbol_info.volume_min, min(volume, symbol_info.volume_max))
    
    return volume

def execute_trade(symbol, signal_dict):
    """Ejecuta la orden en MT5 a mercado usando los datos de la señal."""
    order_type = mt5.ORDER_TYPE_BUY if signal_dict['signal_type'] == "BUY" else mt5.ORDER_TYPE_SELL
    
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log(f"❌ Error al obtener precio actual para {symbol}")
        return
        
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    volume = calculate_volume(symbol, signal_dict['sl'], price)
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": signal_dict['sl'],
        "tp": signal_dict['tp'],
        "deviation": 20,
        "magic": getattr(config, 'MAGIC_NUMBER', 777000),
        "comment": signal_dict['strategy_name'][:15],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log(f"❌ Rechazo de orden {symbol} ({signal_dict['strategy_name']}): {result.comment}")
    else:
        log(f"🚀 ¡Orden EXITOSA! {signal_dict['signal_type']} en {symbol}. Vol: {volume}, Ticket: {result.order}")

def main():
    if not initialize_mt5():
        return

    log("🤖 Orquestador Principal (Cerebro) Iniciado. Cuenta fondeo FTMO $10,000.")
    
    # Instanciar Gestor de Riesgos
    risk_manager = FTMORiskManager()
    
    # Instanciar el arsenal de 7 estrategias
    strategies = {
        "HiddenDivergence": HiddenDivergenceStrategy(),
        "NY_ORB": NY_ORB_Strategy(),
        "NightScalper": NightScalperStrategy(),
        "SMC_FVG": SMC_FVG_Strategy(),
        "TrendMomentum": TrendMomentumStrategy(),
        "VWAP_Pullback": VWAP_Pullback_Strategy(),
        "VolatilityBreakout": VolatilityBreakoutStrategy()
    }
    
    log(f"🧠 {len(strategies)} Estrategias cargadas y listas.")
    
    # Activar símbolos en Market Watch
    symbols_to_trade = getattr(config, 'SYMBOLS', ["EURUSD"])
    for symbol in symbols_to_trade:
        mt5.symbol_select(symbol, True)
        
    last_trade_time = {} # Diccionario Anti-Spam de señales
        
    # Bucle Principal de Alta Frecuencia Segura
    try:
        while True:
            try:
                # PASO 1: Riesgo Global (Kill Switch)
                trading_allowed = risk_manager.update()
                if not trading_allowed:
                    # El Kill Switch se activó por superar la pérdida límite de -$380.
                    # Saltamos el ciclo (no evaluamos estrategias).
                    time.sleep(10)
                    continue
                    
                # PASO 2: Protección Flotante
                risk_manager.manage_breakeven()
                
                # PASO 3: Evaluación Símbolo a Símbolo
                for symbol in symbols_to_trade:
                    # Obtener 100 velas (Suficiente para EMAs grandes como la de 200 en H1)
                    # Usamos M15 por defecto, aunque cada estrategia podría requerir su propio timeframe
                    # Aquí estandarizamos a la obtención de velas solicitada.
                    df = fetch_rates_with_retry(symbol, getattr(config, 'TIMEFRAME', mt5.TIMEFRAME_M15), 300)
                    if df is None:
                        continue
                        
                    best_signal = None
                    
                    for name, strategy in strategies.items():
                        # Usamos evaluate() que procesa generate_signals(df) internamente y aplica Anti-Repaint
                        signal = strategy.evaluate(df, symbol)
                        
                        if signal is not None:
                            # Filtro: Nos quedamos con la señal que ofrezca mejor R:R
                            if best_signal is None or signal.get('rr_ratio', 0) > best_signal.get('rr_ratio', 0):
                                best_signal = signal
                                
                    # PASO 4: Ejecución de Órdenes
                    if best_signal is not None:
                        # Mecanismo Anti-Spam: Prevenir disparar 100 veces en la misma vela si la orden falla o ya se abrió
                        signal_time = df.iloc[-1]['time']
                        if symbol in last_trade_time and last_trade_time[symbol] == signal_time:
                            continue # Ya intentamos disparar en esta misma vela, ignorar hasta la siguiente
                            
                        # Preguntar al Gestor de Riesgo si la matriz de exposición y el filtro de horario permiten el trade
                        if risk_manager.can_open_trade(symbol, best_signal):
                            log(f"🎯 Señal detectada: {best_signal['signal_type']} en {symbol} vía {best_signal['strategy_name']} (R:R {best_signal.get('rr_ratio',0):.2f})")
                            execute_trade(symbol, best_signal)
                            last_trade_time[symbol] = signal_time # Registrar disparo para no repetir en esta vela
                            
            except Exception as e:
                # Catch-all para que el bot nunca crashee por excepciones en tiempo de ejecución
                log(f"🔥 Error en el Bucle Principal: {str(e)}")
                log(traceback.format_exc())
                time.sleep(5) # Pausa por si es un error repetitivo
                
            # Sleep final del ciclo para descargar la CPU (Heartbeat)
            time.sleep(getattr(config, 'TICK_SLEEP', 1.0))
            
    except KeyboardInterrupt:
        log("⏹️ Deteniendo bot por interrupción manual de usuario (Ctrl+C).")
    finally:
        mt5.shutdown()
        log("🔌 Conexión con MT5 finalizada de forma segura.")

if __name__ == "__main__":
    main()
