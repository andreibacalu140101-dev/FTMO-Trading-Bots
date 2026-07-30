import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import pytz
import config

class FTMORiskManager:
    """
    Gestor de Riesgo Institucional para pruebas FTMO ($10,000).
    Implementa el Kill Switch diario estricto y gestión de exposición.
    """
    def __init__(self):
        self.initial_balance = 0.0
        self.last_reset_day = -1
        self.trading_allowed = True
        
        # FTMO opera en horario CET/CEST (Praga/Berlín)
        self.tz = pytz.timezone('Europe/Prague')
        
        # Límite de Pérdida Diaria FTMO ($400 max, fijamos Hard Limit en $380)
        self.hard_stop_limit = 380.0 
        
    def _get_cet_time(self):
        """Retorna la hora actual del servidor en CET/CEST."""
        return datetime.now(self.tz)

    def _cancel_pending_orders(self):
        """Cancela todas las órdenes pendientes (Limit/Stop)."""
        orders = mt5.orders_get()
        if orders is None or len(orders) == 0:
            return
            
        for order in orders:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
                "magic": config.MAGIC_NUMBER if hasattr(config, 'MAGIC_NUMBER') else 0
            }
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"❌ Error al cancelar orden pendiente {order.ticket}: {result.comment}")
            else:
                print(f"✅ Orden pendiente {order.ticket} cancelada (Kill Switch).")

    def _close_all_positions(self):
        """Cierra todas las posiciones abiertas a precio de mercado."""
        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            return
            
        for pos in positions:
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                continue
                
            type_dict = {
                mt5.POSITION_TYPE_BUY: mt5.ORDER_TYPE_SELL,
                mt5.POSITION_TYPE_SELL: mt5.ORDER_TYPE_BUY
            }
            price_dict = {
                mt5.ORDER_TYPE_SELL: tick.bid,
                mt5.ORDER_TYPE_BUY: tick.ask
            }
            
            close_type = type_dict.get(pos.type)
            if close_type is None:
                continue
                
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": close_type,
                "position": pos.ticket,
                "price": price_dict[close_type],
                "deviation": 20, # Slippage permitido
                "magic": config.MAGIC_NUMBER if hasattr(config, 'MAGIC_NUMBER') else 0,
                "comment": "FTMO Kill Switch",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"❌ Error al cerrar posición {pos.ticket}: {result.comment}")
            else:
                print(f"🚨 Posición {pos.ticket} cerrada a mercado (Kill Switch).")

    def execute_kill_switch(self, current_pnl):
        """Ejecuta el protocolo de emergencia cuando se viola el límite diario."""
        print(f"🛑 [KILL SWITCH ACTIVADO] PnL Diario: ${current_pnl:.2f} (Límite: -${self.hard_stop_limit})")
        self._close_all_positions()
        self._cancel_pending_orders()
        self.trading_allowed = False
        print("🔒 Trading bloqueado por el resto del día.")

    def update(self) -> bool:
        """
        Verifica límites de riesgo diario actualizados. 
        Devuelve True si el trading está permitido, False si está bloqueado.
        """
        account_info = mt5.account_info()
        if account_info is None:
            print("⚠️ No se pudo obtener información de la cuenta.")
            return False # Bloquear por seguridad si no hay conexión
            
        cet_time = self._get_cet_time()
        
        # 1. Reset Automático a la Medianoche (CET/CEST)
        if cet_time.day != self.last_reset_day:
            self.initial_balance = account_info.balance
            self.last_reset_day = cet_time.day
            self.trading_allowed = True
            print(f"📅 [FTMO RESET] Medianoche CET cruzada. Balance Inicial fijado: ${self.initial_balance:.2f}. Trading Permitido.")
            
        # 2. Evaluación de Pérdida Diaria (Cerradas + Flotante)
        if self.trading_allowed:
            # PnL Diario = Equity Actual - Balance Inicial del Día
            # (Si equity bajó, el daily_pnl es negativo)
            daily_pnl = account_info.equity - self.initial_balance
            
            if daily_pnl <= -self.hard_stop_limit:
                self.execute_kill_switch(daily_pnl)
                
        return self.trading_allowed

    def can_open_trade(self, symbol, signal_dict) -> bool:
        """
        Verifica el horario operativo, el Kill Switch y la matriz de correlación antes de autorizar un trade.
        """
        # 1. Filtro Global de Horario Operativo (CET/CEST) con Excepciones de Alta Calidad
        current_hour = self._get_cet_time().hour
        if hasattr(config, 'TRADING_START_HOUR') and hasattr(config, 'TRADING_END_HOUR'):
            in_session = (config.TRADING_START_HOUR <= current_hour < config.TRADING_END_HOUR)
            
            if not in_session:
                # 🌟 Excepciones Seguras Fuera de Horario
                strategy_name = signal_dict.get('strategy_name', '')
                rr_ratio = signal_dict.get('rr_ratio', 0)
                
                # Criterio de QA Quant: Solo permitir NightScalper o trades con R:R >= 2.0
                is_night_scalper = (strategy_name == "NightScalper")
                is_high_probability = (rr_ratio >= 2.0)
                
                if not (is_night_scalper or is_high_probability):
                    print(f"⏳ Fuera de horario ({config.TRADING_START_HOUR}:00-{config.TRADING_END_HOUR}:00 CET). Trade denegado en {symbol} ({strategy_name} R:R={rr_ratio:.2f}).")
                    return False
                else:
                    print(f"🌟 Excepción Nocturna Aprobada en {symbol}: Estrategia {strategy_name} (R:R={rr_ratio:.2f}) superó el filtro cuantitativo.")

        # 2. Si el Kill Switch está activo, se rechaza cualquier trade
        if not self.trading_allowed:
            return False
            
        # Matriz de Correlación
        positions = mt5.positions_get()
        if positions is None:
            return True
            
        if not hasattr(config, 'CURRENCY_EXPOSURE_GROUPS'):
            return True
        
        # Extraer divisas base y cotizadas del símbolo a operar
        target_currencies = []
        for currency, symbols_list in config.CURRENCY_EXPOSURE_GROUPS.items():
            if symbol in symbols_list:
                target_currencies.append(currency)
                
        exposure_count = {curr: 0 for curr in target_currencies}
        
        for pos in positions:
            for currency in target_currencies:
                if pos.symbol in config.CURRENCY_EXPOSURE_GROUPS.get(currency, []):
                    exposure_count[currency] += 1
                    
        for currency, count in exposure_count.items():
            if count >= 2:
                print(f"⚠️ Trade en {symbol} denegado. Sobreexposición a {currency} (Operaciones activas: {count}).")
                return False
                
        return True

    def manage_breakeven(self):
        """Mueve SL a Break Even si el profit flotante iguala el riesgo inicial."""
        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            return
            
        for pos in positions:
            if hasattr(config, 'MAGIC_NUMBER') and pos.magic != config.MAGIC_NUMBER:
                continue
                
            open_price = pos.price_open
            sl = pos.sl
            tp = pos.tp
            
            if sl == 0.0:
                continue
                
            risk_dist = abs(open_price - sl)
            if risk_dist == 0:
                continue
                
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                continue
                
            if pos.type == mt5.POSITION_TYPE_BUY:
                current_profit_dist = tick.bid - open_price
                if current_profit_dist >= risk_dist and sl < open_price:
                    self._modify_sl(pos, open_price, tp)
            elif pos.type == mt5.POSITION_TYPE_SELL:
                current_profit_dist = open_price - tick.ask
                if current_profit_dist >= risk_dist and sl > open_price:
                    self._modify_sl(pos, open_price, tp)

    def _modify_sl(self, pos, new_sl, tp):
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": pos.ticket,
            "sl": new_sl,
            "tp": tp,
            "magic": config.MAGIC_NUMBER if hasattr(config, 'MAGIC_NUMBER') else 0
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"🛡️ SL ajustado a Break Even (Ticket {pos.ticket}, {pos.symbol}).")
