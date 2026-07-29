//+------------------------------------------------------------------+
//|                                     FTMO_Trend_Momentum.mq5      |
//|                                     Copyright 2026, Antigravity  |
//|                                      https://www.mql5.com        |
//+------------------------------------------------------------------+
#property copyright "Antigravity (Trader Institucional)"
#property link      ""
#property version   "1.00"
#property description "Expert Advisor FTMO $10k - Trend & Momentum (M15)"

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
input int         InpStartHour = 8;           // Hora inicio operativa (08:00)
input int         InpStartMinute = 0;         // Minuto inicio operativa
input int         InpEndHour = 16;            // Hora fin operativa (16:30)
input int         InpEndMinute = 30;          // Minuto fin operativa

sinput string     Section3 = "=== Configuración de Estrategia ===";
input ulong       InpMagicNumber = 888123;    // Magic Number
input int         InpEmaFastPeriod = 50;      // Periodo EMA Micro
input int         InpEmaSlowPeriod = 200;     // Periodo EMA Macro
input int         InpMacdFast = 12;           // Periodo MACD Rápido
input int         InpMacdSlow = 26;           // Periodo MACD Lento
input int         InpMacdSignal = 9;          // Periodo MACD Señal

//--- Variables Globales
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
CAccountInfo   m_account;

double         g_initial_balance = 0.0;
int            g_last_reset_day = -1;
bool           g_trading_stopped_today = false;

// Handles de indicadores
int            handle_ema50;
int            handle_ema200;
int            handle_osma; // Usamos OsMA porque en MT5 representa exactamente el Histograma (MACD_Line - Signal_Line)

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
      Print("⚠️ ADVERTENCIA: La estrategia Trend & Momentum está diseñada para operar en M15. Temporalidad actual: ", EnumToString(_Period));
     }
     
   // Inicializar Indicadores
   handle_ema50 = iMA(_Symbol, _Period, InpEmaFastPeriod, 0, MODE_EMA, PRICE_CLOSE);
   handle_ema200 = iMA(_Symbol, _Period, InpEmaSlowPeriod, 0, MODE_EMA, PRICE_CLOSE);
   // En MT5, iOsMA es el equivalente matemático al "MACD Histogram" utilizado en TradingView y sistemas institucionales
   handle_osma = iOsMA(_Symbol, _Period, InpMacdFast, InpMacdSlow, InpMacdSignal, PRICE_CLOSE);
   
   if(handle_ema50 == INVALID_HANDLE || handle_ema200 == INVALID_HANDLE || handle_osma == INVALID_HANDLE)
     {
      Print("❌ Error al inicializar los indicadores en memoria.");
      return INIT_FAILED;
     }

   Print("🚀 FTMO_Trend_Momentum inicializado con éxito. MagicNumber: ", InpMagicNumber);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(handle_ema50);
   IndicatorRelease(handle_ema200);
   IndicatorRelease(handle_osma);
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
      // Si la pérdida diaria supera el límite
      if(current_loss >= InpDailyDrawdown)
        {
         Print("🛑 LÍMITE DIARIO ALCANZADO (Drawdown > $", InpDailyDrawdown, "). Cerrando todo y deteniendo operativa.");
         CloseAllPositions();
         g_trading_stopped_today = true; // Bloquea el EA hasta el día siguiente
        }
     }
     
   if(g_trading_stopped_today) return;

   //================================================================
   // 3. HORARIO OPERATIVO
   //================================================================
   int current_mins = GetMinutesFromMidnight(current_time);
   int start_mins = InpStartHour * 60 + InpStartMinute;
   int end_mins = InpEndHour * 60 + InpEndMinute;

   if(current_mins < start_mins || current_mins >= end_mins) return; // Fuera del horario de gatillo

   // Solo permitir 1 operación abierta a la vez
   if(PositionsTotal() > 0) return;

   //================================================================
   // 4. GATILLO (Filtro por nueva vela)
   //================================================================
   
   // Filtro de Spread
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
//| Función: Lógica principal de Seguimiento de Tendencia            |
//+------------------------------------------------------------------+
void CheckForEntry()
  {
   double close[];
   double ema50[];
   double ema200[];
   double osma[];
   
   // Copiar los datos necesarios de la vela recién cerrada (shift 1) y la anterior (shift 2)
   if(CopyClose(_Symbol, _Period, 1, 1, close) <= 0) return;
   if(CopyBuffer(handle_ema50, 0, 1, 1, ema50) <= 0) return;
   if(CopyBuffer(handle_ema200, 0, 1, 1, ema200) <= 0) return;
   if(CopyBuffer(handle_osma, 0, 1, 2, osma) <= 0) return; // Copiamos 2 valores para detectar el cruce del cero
   
   // Voltear el arreglo del OsMA para facilitar la lectura: 
   // Índice 0 = Vela Recién Cerrada (Shift 1) | Índice 1 = Vela Previa (Shift 2)
   ArraySetAsSeries(osma, true);
   
   double last_close = close[0];
   double last_ema50 = ema50[0];
   double last_ema200 = ema200[0];
   
   double hist_curr = osma[0]; // Histograma en Shift 1
   double hist_prev = osma[1]; // Histograma en Shift 2
   
   //--- 1. Lógica Compradora (Long) ---
   // El precio debe estar por encima de ambas EMA
   if(last_close > last_ema200 && last_close > last_ema50)
     {
      // El histograma de MACD cruza de negativo a positivo
      if(hist_prev < 0 && hist_curr > 0)
        {
         Print("🔥 Gatillo COMPRA: Tendencia Alcista + Momentum Positivo (Cruce MACD)");
         ExecuteTrade(ORDER_TYPE_BUY);
        }
     }
   
   //--- 2. Lógica Vendedora (Short) ---
   // El precio debe estar por debajo de ambas EMA
   else if(last_close < last_ema200 && last_close < last_ema50)
     {
      // El histograma de MACD cruza de positivo a negativo
      if(hist_prev > 0 && hist_curr < 0)
        {
         Print("🔥 Gatillo VENTA: Tendencia Bajista + Momentum Negativo (Cruce MACD)");
         ExecuteTrade(ORDER_TYPE_SELL);
        }
     }
  }

//+------------------------------------------------------------------+
//| Función: Ejecutar Orden calculando SL dinámico y Lote            |
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ORDER_TYPE type)
  {
   double entry_price = (type == ORDER_TYPE_BUY) ? m_symbol.Ask() : m_symbol.Bid();
   double sl_price = 0.0;
   
   // Variables para cálculo de Pips
   double point = m_symbol.Point();
   int digits = m_symbol.Digits();
   double pip_size = (digits == 5 || digits == 3) ? point * 10 : point; // Normalizador estándar de pips
   
   //================================================================
   // 1. CÁLCULO DEL STOP LOSS BÁSICO (Últimas 15 velas)
   //================================================================
   if(type == ORDER_TYPE_BUY)
     {
      double low[];
      if(CopyLow(_Symbol, _Period, 1, 15, low) <= 0) return;
      sl_price = low[ArrayMinimum(low)]; // El mínimo más bajo
      
      double sl_dist_pips = (entry_price - sl_price) / pip_size;
      
      // Control de Límites
      if(sl_dist_pips < 10.0)
        {
         sl_dist_pips = 10.0;
         sl_price = entry_price - (sl_dist_pips * pip_size);
        }
      else if(sl_dist_pips > 25.0)
        {
         Print("🚫 Señal de COMPRA cancelada: SL técnico superior a 25 pips (", DoubleToString(sl_dist_pips, 1), ").");
         return;
        }
     }
   else // VENTA
     {
      double high[];
      if(CopyHigh(_Symbol, _Period, 1, 15, high) <= 0) return;
      sl_price = high[ArrayMaximum(high)]; // El máximo más alto
      
      double sl_dist_pips = (sl_price - entry_price) / pip_size;
      
      // Control de Límites
      if(sl_dist_pips < 10.0)
        {
         sl_dist_pips = 10.0;
         sl_price = entry_price + (sl_dist_pips * pip_size);
        }
      else if(sl_dist_pips > 25.0)
        {
         Print("🚫 Señal de VENTA cancelada: SL técnico superior a 25 pips (", DoubleToString(sl_dist_pips, 1), ").");
         return;
        }
     }
     
   //================================================================
   // 2. CÁLCULO DE TAKE PROFIT
   //================================================================
   double sl_dist_points = MathAbs(entry_price - sl_price);
   if(sl_dist_points == 0) return;
   
   double tp_price = 0;
   // Ratio 1:2 Exacto
   if(type == ORDER_TYPE_BUY)
      tp_price = entry_price + (sl_dist_points * 2.0);
   else
      tp_price = entry_price - (sl_dist_points * 2.0);
      
   //================================================================
   // 3. CÁLCULO DINÁMICO DE LOTAJE ($50 de Riesgo)
   //================================================================
   double tick_size = m_symbol.TickSize();
   double tick_value = m_symbol.TickValue();
   if(tick_size == 0 || tick_value == 0) return;
   
   // Cuánto dinero pierdo al mover el StopLoss usando 1 Lote exacto
   double loss_per_lot = (sl_dist_points / tick_size) * tick_value;
   if(loss_per_lot <= 0) return;
   
   // Fórmula: Lotes = Riesgo Total / Pérdida por Lote
   double lots = InpRiskAmount / loss_per_lot;
   
   // Ajuste y Normalización de Lotes a lo soportado por el Broker
   double step = m_symbol.LotsStep();
   lots = MathFloor(lots / step) * step;
   
   if(lots < m_symbol.LotsMin())
     {
      Print("🚫 CANCELADO: El Stop Loss es tan amplio que usar el lote mínimo superaría el riesgo estricto de $", InpRiskAmount);
      return;
     }
   if(lots > m_symbol.LotsMax()) lots = m_symbol.LotsMax();
   
   // Normalización de Precios (Importante para evitar Error 130 o 4756)
   sl_price = NormalizeDouble(sl_price, digits);
   tp_price = NormalizeDouble(tp_price, digits);
   
   //================================================================
   // 4. EJECUCIÓN EN MERCADO
   //================================================================
   if(type == ORDER_TYPE_BUY)
      m_trade.Buy(lots, _Symbol, 0.0, sl_price, tp_price, "TrendMom_Long");
   else
      m_trade.Sell(lots, _Symbol, 0.0, sl_price, tp_price, "TrendMom_Short");
      
   Print("✅ ORDEN ENVIADA. Lotes: ", DoubleToString(lots, 2), " | Riesgo Aprox: $", InpRiskAmount, " | SL (Pips): ", DoubleToString(sl_dist_points/pip_size, 1));
  }

//+------------------------------------------------------------------+
//| Función: Cerrar todas las operaciones abiertas                   |
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
