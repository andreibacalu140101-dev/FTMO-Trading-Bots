import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime
import pytz
import traceback

import config
from risk_manager import FTMORiskManager

# Importar solo las estrategias validadas para Forward Testing
from strategies import (
    NY_ORB_Strategy,
    SMC_FVG_Strategy
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
        return 0.01 
        
    account_info = mt5.account_info()
    if account_info is None:
        return 0.01
        
    risk_percent = getattr(config, 'RISK_PER_TRADE_PERCENT', 0.5)
    risk_usd = account_info.balance * (risk_percent / 100.0)
    
    risk_dist = abs(entry_price - sl_price)
    
    if risk_dist == 0:
        return symbol_info.volume_min
        
    tick_value = symbol_info.trade_tick_value
    tick_size = symbol_info.trade_tick_size
    
    if tick_size == 0 or tick_value == 0:
        return symbol_info.volume_min
        
    loss_for_one_lot = (risk_dist / tick_size) * tick_value
    if loss_for_one_lot == 0:
        return symbol_info.volume_min
        
    volume = risk_usd / loss_for_one_lot
    
    step = symbol_info.volume_step
    volume = round(volume / step) * step
    volume = max(symbol_info.volume_min, min(volume, symbol_info.volume_max))
    
    return volume

def execute_trade(symbol, signal_dict):
    """Ejecuta la orden en MT5 a mercado usando bloque try-except."""
    try:
        order_type = mt5.ORDER_TYPE_BUY if signal_dict['signal_type'] == "BUY" else mt5.ORDER_TYPE_SELL
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            log(f"❌ Error al obtener precio actual para {symbol}")
            return False
            
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        
        # Actualizamos TP para forzar R:R de 1:2 basado en el nuevo SL final (con buffer)
        final_sl = signal_dict['sl']
        risk_dist = abs(price - final_sl)
        
        if order_type == mt5.ORDER_TYPE_BUY:
            final_tp = price + (risk_dist * 2.0)
        else:
            final_tp = price - (risk_dist * 2.0)
            
        volume = calculate_volume(symbol, final_sl, price)
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": final_sl,
            "tp": final_tp,
            "deviation": 20,
            "magic": getattr(config, 'MAGIC_NUMBER', 777000),
            "comment": signal_dict['strategy_name'][:15],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            log(f"❌ Rechazo de orden {symbol} ({signal_dict['strategy_name']}): {result.comment} (Code: {result.retcode})")
            return False
            
        log(f"🚀 ¡Orden EXITOSA! {signal_dict['signal_type']} en {symbol}. Vol: {volume}, Ticket: {result.order}")
        return True
        
    except Exception as e:
        log(f"🔥 Excepción crítica al ejecutar trade: {str(e)}")
        log(traceback.format_exc())
        return False

def main():
    if not initialize_mt5():
        return

    log("🤖 Orquestador Principal (Cerebro) Iniciado. Forward Testing FTMO.")
    
    risk_manager = FTMORiskManager()
    
    # 5 estrategias desactivadas temporalmente, conservamos las 2 validadas
    strategies = {
        "NY_ORB": NY_ORB_Strategy(),
        "SMC_FVG": SMC_FVG_Strategy()
    }
    
    log(f"🧠 {len(strategies)} Estrategias cargadas (SMC_FVG y NY_ORB) y listas.")
    
    symbols_to_trade = getattr(config, 'SYMBOLS', ["EURUSD", "XAUUSD"])
    for symbol in symbols_to_trade:
        mt5.symbol_select(symbol, True)
        
    # Variables de Estado Global
    state_current_day = ""
    state_trades_today = {
        "SMC_FVG": 0,
        "NY_ORB": 0
    }
        
    try:
        while True:
            try:
                # Actualizar reloj de estado (Medianoche reset)
                current_day_str = risk_manager._get_cet_time().strftime('%Y-%m-%d')
                if current_day_str != state_current_day:
                    state_current_day = current_day_str
                    state_trades_today["SMC_FVG"] = 0
                    state_trades_today["NY_ORB"] = 0
                    log(f"📅 Nuevo Día Detectado ({current_day_str}). Contadores de estrategia reiniciados.")
                    
                # PASO 1: Riesgo Global (Kill Switch)
                trading_allowed = risk_manager.update()
                if not trading_allowed:
                    time.sleep(10)
                    continue
                    
                # PASO 2: Protección Flotante
                risk_manager.manage_breakeven()
                
                # PASO 3: Evaluación Símbolo a Símbolo
                for symbol in symbols_to_trade:
                    tick = mt5.symbol_info_tick(symbol)
                    symbol_info = mt5.symbol_info(symbol)
                    
                    if tick is None or symbol_info is None:
                        continue
                        
                    pip_size = 10 * symbol_info.point if (symbol_info.digits == 5 or symbol_info.digits == 3) else symbol_info.point
                    current_spread_pips = (tick.ask - tick.bid) / pip_size
                    
                    if current_spread_pips > getattr(config, 'MAX_SPREAD_PIPS', 1.5):
                        continue
                        
                    # M5 Timeframe recomendado para estas estrategias institucionales
                    df = fetch_rates_with_retry(symbol, getattr(config, 'TIMEFRAME', mt5.TIMEFRAME_M5), 300)
                    if df is None or len(df) < 15:
                        continue
                        
                    # Filtro MACRO de Volatilidad (ATR de 14 periodos)
                    df['tr0'] = abs(df['high'] - df['low'])
                    df['tr1'] = abs(df['high'] - df['close'].shift())
                    df['tr2'] = abs(df['low'] - df['close'].shift())
                    tr = df[['tr0', 'tr1', 'tr2']].max(axis=1)
                    atr_14 = tr.rolling(14).mean().iloc[-1] / pip_size
                    
                    if atr_14 < getattr(config, 'MIN_ATR_PIPS', 3.0):
                        continue
                        
                    best_signal = None
                    
                    for name, strategy in strategies.items():
                        # Si ya agotamos la bala diaria de esta estrategia, la ignoramos.
                        if state_trades_today.get(name, 0) >= 1:
                            continue
                            
                        signal = strategy.evaluate(df, symbol)
                        if signal is not None:
                            if best_signal is None or signal.get('rr_ratio', 0) > best_signal.get('rr_ratio', 0):
                                best_signal = signal
                                
                    # PASO 4: Ejecución de Órdenes
                    if best_signal is not None:
                        strategy_name = best_signal['strategy_name']
                        
                        if risk_manager.can_open_trade(symbol, best_signal):
                            # ==========================================
                            # 🛡️ BUFFER INSTITUCIONAL DE STOP LOSS
                            # ==========================================
                            symbol_info_local = mt5.symbol_info(symbol)
                            tick_local = mt5.symbol_info_tick(symbol)
                            if symbol_info_local and tick_local:
                                p_size = 10 * symbol_info_local.point if (symbol_info_local.digits == 5 or symbol_info_local.digits == 3) else symbol_info_local.point
                                
                                spread_buffer = tick_local.ask - tick_local.bid
                                atr_buffer = (atr_14 * p_size) * 0.5
                                total_buffer = spread_buffer + atr_buffer
                                
                                if best_signal['signal_type'] == "BUY":
                                    best_signal['sl'] -= total_buffer
                                else:
                                    best_signal['sl'] += total_buffer
                                    
                            log(f"🎯 Señal detectada: {best_signal['signal_type']} en {symbol} vía {strategy_name}")
                            
                            success = execute_trade(symbol, best_signal)
                            if success:
                                # Consumir la bala diaria de esta estrategia
                                state_trades_today[strategy_name] += 1
                                log(f"🔒 Estrategia {strategy_name} bloqueada por el resto del día ({state_current_day}).")
                            
            except Exception as e:
                log(f"🔥 Error en el Bucle Principal: {str(e)}")
                log(traceback.format_exc())
                time.sleep(5)
                
            time.sleep(getattr(config, 'TICK_SLEEP', 1.0))
            
    except KeyboardInterrupt:
        log("⏹️ Deteniendo bot por interrupción manual de usuario (Ctrl+C).")
    finally:
        mt5.shutdown()
        log("🔌 Conexión con MT5 finalizada de forma segura.")

if __name__ == "__main__":
    main()
