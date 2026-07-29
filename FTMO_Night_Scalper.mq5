//+------------------------------------------------------------------+
//|                                     FTMO_Night_Scalper.mq5       |
//|                                     Copyright 2026, Antigravity  |
//|                                      https://www.mql5.com        |
//+------------------------------------------------------------------+
#property copyright "Antigravity (Trader Institucional)"
#property link      ""
#property version   "1.00"
#property description "Expert Advisor FTMO $10k - Night Scalper (M15)"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- Parámetros de entrada
sinput string     Section1 = "=== Gestión de Riesgo ===";
input double      InpRiskAmount = 50.0;       // Riesgo por operación (USD)
input double      InpDailyDrawdown = 400.0;   // Límite Diario de Pérdida (USD)
input double      InpFixedSlPips = 15.0;      // Stop Loss Fijo (Pips)
input int         InpBrokerOffsetCET = 0;     // Desfase del Broker respecto a CET (0=FTMO, 1=EET)
input double      InpMaxSpreadPips = 3.0;     // Max Spread Permitido (Pips)
input ulong       InpMaxSlippagePoints = 30;  // Deslizamiento Máximo (Puntos)

sinput string     Section2 = "=== Horarios (Hora Servidor Broker) ===";
input int         InpStartHour = 23;          // Hora de inicio operativa
input int         InpStartMinute = 0;         // Minuto de inicio
input int         InpEndHour = 4;             // Hora fin operativa / Cierre forzado
input int         InpEndMinute = 0;           // Minuto fin / Cierre

sinput string     Section3 = "=== Configuración de Estrategia ===";
input ulong       InpMagicNumber = 999123;    // Magic Number
input int         InpBandsPeriod = 20;        // Periodo Bollinger Bands
input double      InpBandsDev = 2.5;          // Desviación Bollinger Bands
input int         InpRsiPeriod = 14;          // Periodo RSI

//--- Variables Globales
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
CAccountInfo   m_account;

double         g_initial_balance = 0.0;
int            g_last_reset_day = -1;
bool           g_trading_stopped_today = false;

// Handles de indicadores
int            handle_bb;
int            handle_rsi;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   m_symbol.Name(_Symbol);
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(InpMaxSlippagePoints);
   
   if(_Period != PERIOD_M15)
     {
      Print("⚠️ ADVERTENCIA: La estrategia Night Scalper está diseñada estrictamente para M15. Temporalidad actual: ", EnumToString(_Period));
     }
     
   // Inicializar Indicadores
   handle_bb = iBands(_Symbol, _Period, InpBandsPeriod, 0, InpBandsDev, PRICE_CLOSE);
   handle_rsi = iRSI(_Symbol, _Period, InpRsiPeriod, PRICE_CLOSE);
   
   if(handle_bb == INVALID_HANDLE || handle_rsi == INVALID_HANDLE)
     {
      Print("❌ Error al inicializar los indicadores en memoria.");
      return INIT_FAILED;
     }

   Print("🚀 FTMO_Night_Scalper inicializado con éxito. MagicNumber: ", InpMagicNumber);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(handle_bb);
   IndicatorRelease(handle_rsi);
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
      Print("📅 Nuevo ciclo diario detectado. Balance inicial fijado en: $", DoubleToString(g_initial_balance, 2));
     }

   //================================================================
   // 2. LÍMITE DIARIO (Cortacorrientes)
   //================================================================
   if(!g_trading_stopped_today)
     {
      double current_loss = g_initial_balance - m_account.Equity();
      if(current_loss >= InpDailyDrawdown)
        {
         Print("🛑 LÍMITE DIARIO ALCANZADO (Drawdown > $", InpDailyDrawdown, "). Liquidando el robot por hoy.");
         CloseAllPositions();
         g_trading_stopped_today = true;
        }
     }
     
   if(g_trading_stopped_today) return;

   //================================================================
   // 3. HORARIO OPERATIVO CRUZADO (Ej: 23:00 a 04:00)
   //================================================================
   int current_mins = GetMinutesFromMidnight(current_time);
   int start_mins = InpStartHour * 60 + InpStartMinute; // Ej. 1380
   int end_mins = InpEndHour * 60 + InpEndMinute;       // Ej. 240
   
   // Determinar si estamos dentro del bloque de operativa
   bool in_session = false;
   if(start_mins > end_mins) 
      in_session = (current_mins >= start_mins || current_mins < end_mins);
   else 
      in_session = (current_mins >= start_mins && current_mins < end_mins);

   // Cierre forzado fuera de horario
   static bool force_closed = false;
   if(!in_session)
     {
      if(!force_closed && PositionsTotal() > 0)
        {
         Print("⏰ Cierre por Tiempo alcanzado (", InpEndHour, ":", StringFormat("%02d", InpEndMinute), "). Liquidando posiciones.");
         CloseAllPositions();
         force_closed = true;
        }
      return; // No hacer nada más si estamos fuera del horario de scalp
     }
   else
     {
      force_closed = false; // Reset de la bandera al entrar de nuevo en sesión
     }

   //================================================================
   // 4. TAKE PROFIT DINÁMICO (Monitoreo Tick a Tick)
   //================================================================
   if(PositionsTotal() > 0)
     {
      ManageDynamicTP();
      return; // Si ya hay una operación abierta, solo la gestionamos (Regla: Solo 1 operación a la vez)
     }

   //================================================================
   // 5. GATILLO (Filtro por nueva vela)
   //================================================================
   
   // Filtro de Spread antes de considerar cualquier señal
   double point = m_symbol.Point();
   double pip_size = (m_symbol.Digits() == 5 || m_symbol.Digits() == 3) ? point * 10 : point;
   double current_spread = (m_symbol.Ask() - m_symbol.Bid()) / pip_size;
   if(current_spread > InpMaxSpreadPips) return; 

   static datetime last_bar_time = 0;
   datetime bar_time[1];
   if(CopyTime(_Symbol, _Period, 0, 1, bar_time) <= 0) return;
   
   if(bar_time[0] != last_bar_time)
     {
      last_bar_time = bar_time[0];
      CheckForEntry();
     }
  }

//+------------------------------------------------------------------+
//| Función: Cierre dinámico al tocar la Banda Media (SMA 20)        |
//+------------------------------------------------------------------+
void ManageDynamicTP()
  {
   double bb_base[]; // Buffer 0 (Middle band)
   // Tomamos el valor de la banda media en la vela actual (shift 0)
   if(CopyBuffer(handle_bb, 0, 0, 1, bb_base) <= 0) return;
   
   double middle_band = bb_base[0];
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(m_position.SelectByIndex(i))
        {
         if(m_position.Symbol() == _Symbol && m_position.Magic() == InpMagicNumber)
           {
            bool close_it = false;
            
            // Compras: Cierra si el precio de venta (Bid) iguala o supera la banda media
            if(m_position.PositionType() == POSITION_TYPE_BUY)
              {
               if(m_symbol.Bid() >= middle_band) close_it = true;
              }
            // Ventas: Cierra si el precio de compra (Ask) iguala o cae bajo la banda media
            else if(m_position.PositionType() == POSITION_TYPE_SELL)
              {
               if(m_symbol.Ask() <= middle_band) close_it = true;
              }
              
            if(close_it)
              {
               m_trade.PositionClose(m_position.Ticket());
               Print("🎯 TP Dinámico Alcanzado: Posición cerrada en línea central de Bollinger (", DoubleToString(middle_band, 5), ").");
              }
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Función: Lógica de Entrada de Reversión Nocturna                 |
//+------------------------------------------------------------------+
void CheckForEntry()
  {
   double close[];
   double rsi[];
   double bb_upper[];
   double bb_lower[];
   
   // Leer vela recién cerrada (shift 1)
   if(CopyClose(_Symbol, _Period, 1, 1, close) <= 0) return;
   if(CopyBuffer(handle_rsi, 0, 1, 1, rsi) <= 0) return;
   if(CopyBuffer(handle_bb, 1, 1, 1, bb_upper) <= 0) return; // Buffer 1 = Upper Band
   if(CopyBuffer(handle_bb, 2, 1, 1, bb_lower) <= 0) return; // Buffer 2 = Lower Band
   
   double last_close = close[0];
   double last_rsi = rsi[0];
   double last_upper = bb_upper[0];
   double last_lower = bb_lower[0];
   
   //--- 1. Lógica Compradora (Long) ---
   if(last_close < last_lower && last_rsi < 30.0)
     {
      Print("⚡ Gatillo COMPRA: Cierre (", last_close, ") bajo la BB Inferior (", last_lower, ") con RSI Sobreventa (", last_rsi, ")");
      ExecuteTrade(ORDER_TYPE_BUY);
     }
   
   //--- 2. Lógica Vendedora (Short) ---
   else if(last_close > last_upper && last_rsi > 70.0)
     {
      Print("⚡ Gatillo VENTA: Cierre (", last_close, ") sobre la BB Superior (", last_upper, ") con RSI Sobrecompra (", last_rsi, ")");
      ExecuteTrade(ORDER_TYPE_SELL);
     }
  }

//+------------------------------------------------------------------+
//| Función: Ejecución de Orden y Cálculo de Lotaje Matemático       |
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ORDER_TYPE type)
  {
   double entry_price = (type == ORDER_TYPE_BUY) ? m_symbol.Ask() : m_symbol.Bid();
   
   // Cálculo de distancia en precio para el SL Fijo
   double point = m_symbol.Point();
   int digits = m_symbol.Digits();
   double pip_size = (digits == 5 || digits == 3) ? point * 10 : point;
   
   double sl_dist_points = InpFixedSlPips * pip_size;
   
   double sl_price = 0.0;
   if(type == ORDER_TYPE_BUY)
      sl_price = entry_price - sl_dist_points;
   else
      sl_price = entry_price + sl_dist_points;
      
   //================================================================
   // CÁLCULO DINÁMICO DE LOTAJE ($50 de Riesgo a los 15 Pips)
   //================================================================
   double tick_size = m_symbol.TickSize();
   double tick_value = m_symbol.TickValue();
   if(tick_size == 0 || tick_value == 0) return;
   
   double loss_per_lot = (sl_dist_points / tick_size) * tick_value;
   if(loss_per_lot <= 0) return;
   
   double lots = InpRiskAmount / loss_per_lot;
   
   // Ajuste del bróker
   double step = m_symbol.LotsStep();
   lots = MathFloor(lots / step) * step;
   
   if(lots < m_symbol.LotsMin())
     {
      Print("🚫 CANCELADO: El Stop Loss es tan amplio que usar el lote mínimo superaría el riesgo estricto de $", InpRiskAmount);
      return;
     }
   if(lots > m_symbol.LotsMax()) lots = m_symbol.LotsMax();
   
   sl_price = NormalizeDouble(sl_price, digits);
   // El Take Profit es dinámico, por tanto se envía en 0.0 (vacío en servidor)
   double tp_price = 0.0; 
   
   if(type == ORDER_TYPE_BUY)
      m_trade.Buy(lots, _Symbol, 0.0, sl_price, tp_price, "NightScalp_Long");
   else
      m_trade.Sell(lots, _Symbol, 0.0, sl_price, tp_price, "NightScalp_Short");
      
   Print("✅ ORDEN ENVIADA. Lotes: ", DoubleToString(lots, 2), " | Riesgo Aprox: $", InpRiskAmount, " | SL: 15 Pips");
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
