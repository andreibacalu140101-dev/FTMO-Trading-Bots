//+------------------------------------------------------------------+
//|                                     FTMO_VWAP_Pullback.mq5       |
//|                                     Copyright 2026, Antigravity  |
//|                                      https://www.mql5.com        |
//+------------------------------------------------------------------+
#property copyright "Antigravity (Trader Institucional)"
#property link      ""
#property version   "1.00"
#property description "Expert Advisor FTMO $10k - VWAP Pullback (M5)"

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
input int         InpStartHour = 8;           // Hora inicio operativa
input int         InpStartMinute = 0;         // Minuto inicio
input int         InpEndHour = 17;            // Hora fin operativa / Cierre
input int         InpEndMinute = 0;           // Minuto fin

sinput string     Section3 = "=== Configuración de Estrategia ===";
input ulong       InpMagicNumber = 111123;    // Magic Number
input int         InpStochK = 14;             // Estocástico %K
input int         InpStochD = 3;              // Estocástico %D
input int         InpStochSlowing = 3;        // Estocástico Slowing

//--- Variables Globales
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
CAccountInfo   m_account;

double         g_initial_balance = 0.0;
int            g_last_reset_day = -1;
bool           g_trading_stopped_today = false;

// Handles
int            handle_stoch;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   m_symbol.Name(_Symbol);
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(InpMaxSlippagePoints);
   
   if(_Period != PERIOD_M5)
     {
      Print("⚠️ ADVERTENCIA: La estrategia VWAP Pullback está optimizada para M5. Temporalidad actual: ", EnumToString(_Period));
     }
     
   // Estocástico
   handle_stoch = iStochastic(_Symbol, _Period, InpStochK, InpStochD, InpStochSlowing, MODE_SMA, STO_LOWHIGH);
   
   if(handle_stoch == INVALID_HANDLE)
     {
      Print("❌ Error al inicializar el Estocástico.");
      return INIT_FAILED;
     }

   Print("🚀 FTMO_VWAP_Pullback inicializado con éxito. MagicNumber: ", InpMagicNumber);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(handle_stoch);
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
//| Helper: Calcula el VWAP Diario de manera dinámica y nativa       |
//+------------------------------------------------------------------+
double GetVWAP(int target_shift)
  {
   static double daily_sum_pv = 0;
   static long daily_sum_v = 0;
   static datetime current_vwap_day = 0;
   static datetime last_processed_bar = 0;
   
   static double cached_vwap_1 = 0;
   static double cached_vwap_2 = 0;
   
   datetime time[];
   if(CopyTime(_Symbol, _Period, 1, 1, time) <= 0) return 0;
   
   // Cache O(1)
   if(time[0] == last_processed_bar)
     {
      if(target_shift == 1) return cached_vwap_1;
      if(target_shift == 2) return cached_vwap_2;
      return 0;
     }
     
   MqlDateTime dt;
   TimeToStruct(time[0], dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   datetime start_of_day = StructToTime(dt);
   
   if(start_of_day != current_vwap_day)
     {
      daily_sum_pv = 0;
      daily_sum_v = 0;
      current_vwap_day = start_of_day;
      
      // Backfill inicial si arranca a mitad del día
      int start_shift = iBarShift(_Symbol, _Period, start_of_day, false);
      if(start_shift > 1)
        {
         int count = start_shift - 2 + 1; // Hasta shift 2
         MqlRates rates[];
         if(count > 0 && CopyRates(_Symbol, _Period, 2, count, rates) > 0)
           {
            for(int i=0; i<ArraySize(rates); i++)
              {
               double tp = (rates[i].high + rates[i].low + rates[i].close) / 3.0;
               daily_sum_pv += tp * rates[i].tick_volume;
               daily_sum_v += rates[i].tick_volume;
              }
           }
        }
      cached_vwap_2 = (daily_sum_v > 0) ? (daily_sum_pv / daily_sum_v) : 0;
      last_processed_bar = time[0] - PeriodSeconds(_Period); 
     }
     
   int missing_bars = iBarShift(_Symbol, _Period, last_processed_bar, false) - 1;
   
   if(missing_bars > 0)
     {
      MqlRates rates[];
      if(CopyRates(_Symbol, _Period, 1, missing_bars, rates) > 0)
        {
         for(int i=0; i<ArraySize(rates); i++)
           {
            if(i == ArraySize(rates) - 1) 
               cached_vwap_2 = (daily_sum_v > 0) ? (daily_sum_pv / daily_sum_v) : 0;
               
            double tp = (rates[i].high + rates[i].low + rates[i].close) / 3.0;
            daily_sum_pv += tp * rates[i].tick_volume;
            daily_sum_v += rates[i].tick_volume;
           }
         cached_vwap_1 = (daily_sum_v > 0) ? (daily_sum_pv / daily_sum_v) : 0;
        }
     }
     
   last_processed_bar = time[0];
   
   if(target_shift == 1) return cached_vwap_1;
   if(target_shift == 2) return cached_vwap_2;
   return 0;
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
         Print("🛑 LÍMITE DIARIO ALCANZADO (Drawdown > $", InpDailyDrawdown, "). Liquidando posiciones.");
         CloseAllPositions();
         g_trading_stopped_today = true;
        }
     }
     
   if(g_trading_stopped_today) return;

   //================================================================
   // 3. HORARIO OPERATIVO
   //================================================================
   int current_mins = GetMinutesFromMidnight(current_time);
   int start_mins = InpStartHour * 60 + InpStartMinute; 
   int end_mins = InpEndHour * 60 + InpEndMinute;       
   
   // Solo buscar operaciones en este bloque
   if(current_mins < start_mins || current_mins >= end_mins) return;

   // Regla estricta: Solo 1 operación abierta a la vez
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
//| Función: Lógica de VWAP Pullback                                 |
//+------------------------------------------------------------------+
void CheckForEntry()
  {
   MqlRates rates[];
   if(CopyRates(_Symbol, _Period, 1, 2, rates) <= 0) return;
   
   // rates[0] = shift 2 (penúltima), rates[1] = shift 1 (vela recién cerrada)
   double open1 = rates[1].open;
   double close1 = rates[1].close;
   double high1 = rates[1].high;
   double low1 = rates[1].low;
   
   double high2 = rates[0].high;
   double low2 = rates[0].low;
   
   // Calcular VWAP para ambas velas
   double vwap1 = GetVWAP(1);
   double vwap2 = GetVWAP(2);
   
   if(vwap1 == 0 || vwap2 == 0) return;
   
   // Evaluar si alguna de las dos velas tocó el VWAP
   bool touched1 = (low1 <= vwap1 && high1 >= vwap1);
   bool touched2 = (low2 <= vwap2 && high2 >= vwap2);
   
   if(!touched1 && !touched2) return; // No hay Pullback tocando la media
   
   // Estocástico
   double stoch_main[];
   double stoch_sig[];
   if(CopyBuffer(handle_stoch, 0, 1, 2, stoch_main) <= 0) return; // Main
   if(CopyBuffer(handle_stoch, 1, 1, 2, stoch_sig) <= 0) return;  // Signal
   
   ArraySetAsSeries(stoch_main, true); // [0]=shift 1, [1]=shift 2
   ArraySetAsSeries(stoch_sig, true);
   
   double main1 = stoch_main[0];
   double main2 = stoch_main[1];
   double sig1 = stoch_sig[0];
   double sig2 = stoch_sig[1];
   
   //--- 1. Lógica Compradora (Long) ---
   // Tendencia alcista y vela de gatillo cierra alcista (C > O)
   if(close1 > vwap1 && close1 > open1)
     {
      // Filtros: Estocástico cruzó hacia arriba y está sobrevendido
      bool stoch_cross_up = (main1 > sig1 && main2 <= sig2);
      bool oversold = (main1 < 20.0 || main2 < 20.0);
      
      if(stoch_cross_up && oversold)
        {
         double sl_price = (touched1) ? low1 : low2;
         if(touched1 && touched2) sl_price = MathMin(low1, low2);
         
         Print("⚡ Gatillo COMPRA: Pullback al VWAP completado. Cruce de Estocástico desde Sobreventa.");
         ExecuteTrade(ORDER_TYPE_BUY, sl_price);
        }
     }
     
   //--- 2. Lógica Vendedora (Short) ---
   // Tendencia bajista y vela de gatillo cierra bajista (C < O)
   else if(close1 < vwap1 && close1 < open1)
     {
      // Filtros: Estocástico cruzó hacia abajo y está sobrecomprado
      bool stoch_cross_down = (main1 < sig1 && main2 >= sig2);
      bool overbought = (main1 > 80.0 || main2 > 80.0);
      
      if(stoch_cross_down && overbought)
        {
         double sl_price = (touched1) ? high1 : high2;
         if(touched1 && touched2) sl_price = MathMax(high1, high2);
         
         Print("⚡ Gatillo VENTA: Pullback al VWAP completado. Cruce de Estocástico desde Sobrecompra.");
         ExecuteTrade(ORDER_TYPE_SELL, sl_price);
        }
     }
  }

//+------------------------------------------------------------------+
//| Función: Ejecución de Orden y Cálculo de Lotaje Matemático       |
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ORDER_TYPE type, double sl_price)
  {
   double entry_price = (type == ORDER_TYPE_BUY) ? m_symbol.Ask() : m_symbol.Bid();
   
   double point = m_symbol.Point();
   int digits = m_symbol.Digits();
   double pip_size = (digits == 5 || digits == 3) ? point * 10 : point;
   
   //================================================================
   // FORZAR SL MINIMO (10 pips)
   //================================================================
   double sl_dist_pips = MathAbs(entry_price - sl_price) / pip_size;
   
   if(sl_dist_pips < 10.0)
     {
      sl_dist_pips = 10.0;
      if(type == ORDER_TYPE_BUY) sl_price = entry_price - (10.0 * pip_size);
      else sl_price = entry_price + (10.0 * pip_size);
     }
     
   double sl_dist_points = MathAbs(entry_price - sl_price);
   if(sl_dist_points == 0) return;
   
   // Ratio Riesgo/Beneficio Fijo 1:2
   double tp_price = 0.0;
   if(type == ORDER_TYPE_BUY)
      tp_price = entry_price + (sl_dist_points * 2.0);
   else
      tp_price = entry_price - (sl_dist_points * 2.0);
      
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
   tp_price = NormalizeDouble(tp_price, digits);
   
   if(type == ORDER_TYPE_BUY)
      m_trade.Buy(lots, _Symbol, 0.0, sl_price, tp_price, "VWAP_Long");
   else
      m_trade.Sell(lots, _Symbol, 0.0, sl_price, tp_price, "VWAP_Short");
      
   Print("✅ ORDEN ENVIADA. Lotes: ", DoubleToString(lots, 2), " | Riesgo: $", InpRiskAmount, " | SL (Pips): ", DoubleToString(sl_dist_pips, 1));
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
