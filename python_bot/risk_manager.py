import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import pytz
import config

class FTMORiskManager:
    def __init__(self):
        self.initial_balance = 0.0
        self.last_reset_day = -1
        self.trading_stopped_today = False
        self.tz = pytz.timezone(config.BROKER_TIMEZONE)
        
    def _get_cet_time(self):
        """Retorna la hora actual en la zona horaria CET (Broker FTMO)."""
        return datetime.now(self.tz)

    def _close_all_positions(self):
        """Cierra todas las posiciones abiertas nativamente (Panic Button)."""
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
                "deviation": 20,
                "magic": config.MAGIC_NUMBER,
                "comment": "Panic Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"❌ Error al cerrar posición {pos.ticket}: {result.comment}")
            else:
                print(f"✅ Posición {pos.ticket} cerrada por riesgo diario.")

    def update(self):
        """Verifica límites de riesgo diario. Devuelve True si la operativa está bloqueada."""
        account_info = mt5.account_info()
        if account_info is None:
            return True # Bloquear si no hay info
            
        cet_time = self._get_cet_time()
        
        # 1. Reset Diario
        if cet_time.day != self.last_reset_day:
            self.initial_balance = account_info.balance
            self.last_reset_day = cet_time.day
            self.trading_stopped_today = False
            print(f"📅 Reset Diario. Balance Inicial fijado en: ${self.initial_balance:.2f} (CET Time: {cet_time.strftime('%Y-%m-%d %H:%M:%S')})")
            
        # 2. Cortacorrientes (HARD_STOP_LIMIT = 380)
        if not self.trading_stopped_today:
            current_loss = self.initial_balance - account_info.equity
            if current_loss >= config.HARD_STOP_LIMIT:
                print(f"🛑 PANIC BUTTON ALCANZADO (Pérdida > ${config.HARD_STOP_LIMIT}). Cerrando todo el mercado.")
                self._close_all_positions()
                self.trading_stopped_today = True
                
        return self.trading_stopped_today

    def can_open_trade(self, symbol):
        """Verifica la matriz de correlación para prevenir exposición excesiva."""
        positions = mt5.positions_get()
        if positions is None:
            return True
        
        # Encontrar divisas base y quote del símbolo a operar
        target_currencies = []
        for currency, symbols_list in config.CURRENCY_EXPOSURE_GROUPS.items():
            if symbol in symbols_list:
                target_currencies.append(currency)
                
        # Contar cuántas posiciones abiertas involucran estas monedas
        exposure_count = {curr: 0 for curr in target_currencies}
        
        for pos in positions:
            for currency in target_currencies:
                if pos.symbol in config.CURRENCY_EXPOSURE_GROUPS.get(currency, []):
                    exposure_count[currency] += 1
                    
        # Si alguna de las divisas ya tiene 2 operaciones o más, bloquear
        for currency, count in exposure_count.items():
            if count >= 2:
                print(f"⚠️ Operación en {symbol} bloqueada por exposición a {currency} (Ya hay {count} trades activos).")
                return False
                
        return True

    def manage_breakeven(self):
        """Mueve SL a Break Even si R:R es 1:1."""
        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            return
            
        for pos in positions:
            # Solo gestionar posiciones de nuestro bot
            if pos.magic != config.MAGIC_NUMBER:
                continue
                
            open_price = pos.price_open
            sl = pos.sl
            tp = pos.tp
            
            # Si no tiene SL, no podemos calcular distancia
            if sl == 0.0:
                continue
                
            risk_dist = abs(open_price - sl)
            if risk_dist == 0:
                continue
                
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                continue
                
            # Calcular profit actual en distancia
            if pos.type == mt5.POSITION_TYPE_BUY:
                current_profit_dist = tick.bid - open_price
                if current_profit_dist >= risk_dist and sl < open_price:
                    # Modificar SL a Break Even
                    self._modify_sl(pos, open_price, tp)
            elif pos.type == mt5.POSITION_TYPE_SELL:
                current_profit_dist = open_price - tick.ask
                if current_profit_dist >= risk_dist and sl > open_price:
                    # Modificar SL a Break Even
                    self._modify_sl(pos, open_price, tp)

    def _modify_sl(self, pos, new_sl, tp):
        """Helper para enviar la orden de modificación de SL."""
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": pos.ticket,
            "sl": new_sl,
            "tp": tp,
            "magic": config.MAGIC_NUMBER
        }
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"❌ Error al mover SL a Break Even (Ticket {pos.ticket}): {result.comment}")
        else:
            print(f"🛡️ SL movido a Break Even para posición {pos.ticket} en {pos.symbol}.")
