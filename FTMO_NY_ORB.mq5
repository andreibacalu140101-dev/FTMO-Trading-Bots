//+------------------------------------------------------------------+
//|                                                FTMO_NY_ORB.mq5   |
//|                                     Copyright 2026, Antigravity  |
//|                                      https://www.mql5.com        |
//+------------------------------------------------------------------+
#property copyright "Antigravity (Trader Institucional)"
#property link      ""
#property version   "1.00"
#property description "Expert Advisor para FTMO $10k - Estrategia NY ORB"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- Parámetros de entrada
sinput string     Section1 = "=== Gestión de Riesgo ===";
input double      InpRiskAmount = 50.0;       // Riesgo por operación (USD)
input double      InpDailyDrawdown = 400.0;   // Límite Diario de Pérdida (USD)
input int         InpBrokerOffsetCET = 0;     // Desfase del Broker respecto a CET (0=FTMO, 1=EET)
input double      InpMaxSpreadPips = 1.5;     // Max Spread Permitido (Pips)
input ulong       InpMaxSlippagePoints = 30;  // Deslizamiento Máximo (Puntos)

sinput string     Section2 = "=== Horarios (Hora Servidor Broker) ===";
input int         InpStartHour = 8;           // Hora inicio observación (08:00)
input int         InpStartMinute = 0;         // Minuto inicio observación
input int         InpEndObsHour = 8;          // Hora fin observación / Gatillo (08:15)
input int         InpEndObsMinute = 15;       // Minuto fin observación
input int         InpCloseHour = 11;          // Hora cierre forzado (11:00)
input int         InpCloseMinute = 0;         // Minuto cierre forzado

sinput string     Section3 = "=== Configuración de EA ===";
input ulong       InpMagicNumber = 777123;    // Magic Number
input int         InpVolumeSmaPeriod = 20;    // Periodo SMA de Volumen

//--- Variables Globales (Instancias)
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
CAccountInfo   m_account;

//--- Variables de la Estrategia
double         g_range_high = 0.0;
double         g_range_low = 0.0;
bool           g_range_calculated = false;

double         g_initial_balance = 0.0;
int            g_last_reset_day = -1;
bool           g_trading_stopped_today = false;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   m_symbol.Name(_Symbol);
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(InpMaxSlippagePoints);
   
   // Validar temporalidad
   if(_Period != PERIOD_M5)
     {
      Print("⚠️ ADVERTENCIA: La estrategia ORB está diseñada estrictamente para M5. Temporalidad actual: ", EnumToString(_Period));
     }
     
   Print("🚀 FTMO_NY_ORB inicializado con éxito. MagicNumber: ", InpMagicNumber);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Helper: Retorna los minutos transcurridos desde medianoche       |
//+------------------------------------------------------------------+
int GetMinutesFromMidnight(datetime time)
  {
   MqlDateTime dt;
   TimeToStruct(time, dt);
   return dt.hour * 60 + dt.min;
  }

//+------------------------------------------------------------------+
//| Helper: Convierte hora del Broker a hora CET real                |
//+------------------------------------------------------------------+
datetime GetCetTime(datetime broker_time)
  {
   return broker_time - (InpBrokerOffsetCET * 3600);
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   if(!m_symbol.RefreshRates()) return;

   datetime current_time = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(current_time, dt);
   
   //================================================================
   // 1. CONTROL DIARIO: Reset de límite diario a la medianoche CET
   //================================================================
   datetime cet_time = GetCetTime(current_time);
   MqlDateTime dt_cet;
   TimeToStruct(cet_time, dt_cet);
   
   int current_day = dt_cet.day;
   if(current_day != g_last_reset_day)
     {
      g_initial_balance = m_account.Balance();
      g_last_reset_day = current_day;
      g_trading_stopped_today = false;
      
      // Reiniciar rango
      g_range_calculated = false;
      g_range_high = 0.0;
      g_range_low = 0.0;
      
      Print("📅 Nuevo ciclo diario detectado. Balance inicial fijado en: $", DoubleToString(g_initial_balance, 2));
     }

   //================================================================
   // 2. LÍMITE DIARIO (Cortacorrientes)
   //================================================================
   if(!g_trading_stopped_today)
     {
      double current_loss = g_initial_balance - m_account.Equity();
      // Si la pérdida flotante/cerrada supera el límite de -$400
      if(current_loss >= InpDailyDrawdown)
        {
         Print("🛑 LÍMITE DIARIO ALCANZADO (Drawdown > $", InpDailyDrawdown, "). Cerrando todo...");
         CloseAllPositions();
         g_trading_stopped_today = true; // Se detiene por el resto del día
        }
     }
     
   // Si saltó el cortacorrientes, bloqueamos operativa.
   if(g_trading_stopped_today) return;

   //================================================================
   // 3. GESTIÓN BREAK EVEN
   //================================================================
   ManageBreakEven();

   //--- Tiempos
   int current_mins = GetMinutesFromMidnight(current_time);
   int obs_start_mins = InpStartHour * 60 + InpStartMinute;
   int obs_end_mins = InpEndObsHour * 60 + InpEndObsMinute;
   int close_mins = InpCloseHour * 60 + InpCloseMinute;

   //================================================================
   // 4. CIERRE POR TIEMPO (11:00 Server Time)
   //================================================================
   if(current_mins >= close_mins)
     {
      if(PositionsTotal() > 0)
        {
         Print("⏰ Cierre por Tiempo alcanzado (", InpCloseHour, ":", StringFormat("%02d", InpCloseMinute), "). Cerrando posiciones.");
         CloseAllPositions();
        }
      return; // No hay más lógica de gatillo después de esta hora
     }

   // No buscar setup si aún no termina la observación
   if(current_mins < obs_end_mins) return;

   //================================================================
   // 5. CÁLCULO DEL RANGO (Fase de Observación 08:00 a 08:15)
   //================================================================
   if(!g_range_calculated && current_mins >= obs_end_mins)
     {
      CalculateRange(obs_start_mins, obs_end_mins);
     }

   if(!g_range_calculated) return;

   //================================================================
   // 5. GATILLO ORB (Lógica de Breakout en sesión)
   //================================================================
   
   // Filtro de Spread
   double point = m_symbol.Point();
   double pip_size = (m_symbol.Digits() == 5 || m_symbol.Digits() == 3) ? point * 10 : point;
   double current_spread = (m_symbol.Ask() - m_symbol.Bid()) / pip_size;
   if(current_spread > InpMaxSpreadPips) return; 

   // Asegurar que solo disparamos a una nueva vela de M5
   static datetime last_bar_time = 0;
   datetime bar_time[1];
   if(CopyTime(_Symbol, _Period, 0, 1, bar_time) <= 0) return;
   
   // Si hay una vela nueva
   if(bar_time[0] != last_bar_time)
     {
      last_bar_time = bar_time[0];
      CheckForEntry();
     }
  }

//+------------------------------------------------------------------+
//| Función: Calcula el Rango Asiático / NY Open                     |
//+------------------------------------------------------------------+
void CalculateRange(int start_mins, int end_mins)
  {
   datetime time_arr[];
   double high_arr[];
   double low_arr[];
   
   // Copiamos las últimas 30 velas (sobra, pero asegura cubrir M5)
   int copied = CopyTime(_Symbol, _Period, 0, 30, time_arr);
   if(copied < 0) return;
   
   ArraySetAsSeries(time_arr, true); // Índice 0 = actual (sin cerrar)
   
   int start_index = -1;
   int end_index = -1;
   
   for(int i=0; i<copied; i++)
     {
      int mins = GetMinutesFromMidnight(time_arr[i]);
      if(mins >= start_mins && mins < end_mins)
        {
         if(end_index == -1) end_index = i;  // El primer hallazgo es la vela más reciente dentro del rango
         start_index = i;                    // El último hallazgo será la vela más antigua dentro del rango
        }
     }
     
   if(start_index != -1 && end_index != -1)
     {
      int count = start_index - end_index + 1; // Número de velas en la observación
      
      // CopyHigh/Low cuentan hacia atrás desde start_pos (end_index)
      if(CopyHigh(_Symbol, _Period, end_index, count, high_arr) <= 0) return;
      if(CopyLow(_Symbol, _Period, end_index, count, low_arr) <= 0) return;
      
      g_range_high = high_arr[ArrayMaximum(high_arr)];
      g_range_low = low_arr[ArrayMinimum(low_arr)];
      g_range_calculated = true;
      
      Print("📊 Rango ORB Definido | Máximo: ", DoubleToString(g_range_high, 5), " | Mínimo: ", DoubleToString(g_range_low, 5));
     }
  }

//+------------------------------------------------------------------+
//| Función: Gatillo de la estrategia (Cierre y Volumen)             |
//+------------------------------------------------------------------+
void CheckForEntry()
  {
   // Máximo 1 operación abierta al mismo tiempo
   if(PositionsTotal() > 0) return;
   
   double close[];
   long volume[];
   
   // Copiamos datos de velas pasadas
   if(CopyClose(_Symbol, _Period, 1, 1, close) <= 0) return;
   if(CopyTickVolume(_Symbol, _Period, 1, InpVolumeSmaPeriod, volume) <= 0) return;
   
   ArraySetAsSeries(close, true);
   ArraySetAsSeries(volume, true); // 0 = vela anterior, 1 = 2 velas atrás, etc.
   
   // 1. Filtrar por SMA 20 del volumen
   long sum_vol = 0;
   for(int i=0; i<InpVolumeSmaPeriod; i++)
     {
      sum_vol += volume[i];
     }
   double sma_vol = (double)sum_vol / InpVolumeSmaPeriod;
   
   double last_close = close[0];
   long last_vol = volume[0];
   
   // 2. Lógica Compradora (Long)
   if(last_close > g_range_high && last_vol > sma_vol)
     {
      Print("🔥 Gatillo COMPRA: Cierre arriba (", last_close, ") y Vol (", last_vol, " > SMA ", sma_vol, ")");
      ExecuteTrade(ORDER_TYPE_BUY);
     }
   // 3. Lógica Vendedora (Short)
   else if(last_close < g_range_low && last_vol > sma_vol)
     {
      Print("🔥 Gatillo VENTA: Cierre abajo (", last_close, ") y Vol (", last_vol, " > SMA ", sma_vol, ")");
      ExecuteTrade(ORDER_TYPE_SELL);
     }
  }

//+------------------------------------------------------------------+
//| Función: Ejecutar Operación Calculando Lotaje                    |
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ORDER_TYPE type)
  {
   double midpoint = (g_range_high + g_range_low) / 2.0;
   double entry_price = (type == ORDER_TYPE_BUY) ? m_symbol.Ask() : m_symbol.Bid();
   
   // SL en el midpoint exacto
   double sl = midpoint; 
   double sl_dist = MathAbs(entry_price - sl);
   if(sl_dist == 0) return;
   
   // TP ratio 1:2
   double tp = (type == ORDER_TYPE_BUY) ? (entry_price + sl_dist * 2.0) : (entry_price - sl_dist * 2.0);
      
   // Cálculo matemático del lote
   double tick_size = m_symbol.TickSize();
   double tick_value = m_symbol.TickValue();
   if(tick_size == 0 || tick_value == 0) 
     {
      Print("❌ Error obteniendo Tick Size o Tick Value");
      return;
     }
   
   // Dinero arriesgado por 1 lote entero
   double loss_per_lot = (sl_dist / tick_size) * tick_value;
   if(loss_per_lot <= 0) return;
   
   // Lotes = Riesgo $ / Pérdida por Lote $
   double lots = InpRiskAmount / loss_per_lot;
   
   // Normalizar a los límites del Broker
   double step = m_symbol.LotsStep();
   lots = MathFloor(lots / step) * step;
   
   if(lots < m_symbol.LotsMin())
     {
      Print("🚫 CANCELADO: El Stop Loss es tan amplio que usar el lote mínimo superaría el riesgo estricto de $", InpRiskAmount);
      return;
     }
   if(lots > m_symbol.LotsMax()) lots = m_symbol.LotsMax();
   
   // Normalizar precios
   sl = NormalizeDouble(sl, m_symbol.Digits());
   tp = NormalizeDouble(tp, m_symbol.Digits());
   
   // Apertura
   if(type == ORDER_TYPE_BUY)
      m_trade.Buy(lots, _Symbol, 0.0, sl, tp, "ORB_Long");
   else
      m_trade.Sell(lots, _Symbol, 0.0, sl, tp, "ORB_Short");
      
   Print("✅ Posición enviada. Lotes: ", DoubleToString(lots, 2), " | Riesgo Aprox: $", InpRiskAmount);
  }

//+------------------------------------------------------------------+
//| Función: Modificar a Break Even (Ratio 1:1)                      |
//+------------------------------------------------------------------+
void ManageBreakEven()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(m_position.SelectByIndex(i))
        {
         if(m_position.Symbol() == _Symbol && m_position.Magic() == InpMagicNumber)
           {
            double open_price = m_position.PriceOpen();
            double sl = m_position.StopLoss();
            double tp = m_position.TakeProfit();
            
            // Distancia original al Stop (se calcula con el midpoint del rango)
            double midpoint = (g_range_high + g_range_low) / 2.0;
            double sl_dist = MathAbs(open_price - midpoint);
            
            if(m_position.PositionType() == POSITION_TYPE_BUY)
              {
               // Si el precio actual ya subió un 1:1 respecto a nuestro riesgo
               if(m_symbol.Bid() - open_price >= sl_dist) 
                 {
                  if(sl < open_price) // Si el SL sigue estando por debajo (en pérdida)
                    {
                     m_trade.PositionModify(m_position.Ticket(), open_price, tp);
                     Print("🛡️ SL movido a Break Even (BUY). Precio Protegido: ", open_price);
                    }
                 }
              }
            else if(m_position.PositionType() == POSITION_TYPE_SELL)
              {
               // Si el precio bajó un 1:1
               if(open_price - m_symbol.Ask() >= sl_dist) 
                 {
                  if(sl > open_price || sl == 0) // Si el SL sigue estando arriba
                    {
                     m_trade.PositionModify(m_position.Ticket(), open_price, tp);
                     Print("🛡️ SL movido a Break Even (SELL). Precio Protegido: ", open_price);
                    }
                 }
              }
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Función: Cerrar Todo                                             |
//+------------------------------------------------------------------+
void CloseAllPositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(m_position.SelectByIndex(i))
        {
         if(m_position.Symbol() == _Symbol && m_position.Magic() == InpMagicNumber)
           {
            m_trade.PositionClose(m_position.Ticket());
           }
        }
     }
  }
