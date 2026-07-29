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
        """Cierra todas las posiciones abiertas nativamente."""
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
                "comment": "Cierre Riesgo Diario",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"❌ Error al cerrar posición {pos.ticket}: {result.comment}")
            else:
                print(f"✅ Posición {pos.ticket} cerrada por riesgo diario.")

    def update(self):
        """Método llamado en cada tick para verificar límites de riesgo."""
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
            
        # 2. Cortacorrientes
        if not self.trading_stopped_today:
            current_loss = self.initial_balance - account_info.equity
            if current_loss >= config.DAILY_DRAWDOWN_LIMIT:
                print(f"🛑 LÍMITE DIARIO ALCANZADO (Pérdida > ${config.DAILY_DRAWDOWN_LIMIT}). Deteniendo operativa.")
                self._close_all_positions()
                self.trading_stopped_today = True
                
        return self.trading_stopped_today
