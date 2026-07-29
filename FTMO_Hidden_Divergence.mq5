//+------------------------------------------------------------------+
//|                               FTMO_Hidden_Divergence.mq5         |
//|                                     Copyright 2026, Antigravity  |
//|                                      https://www.mql5.com        |
//+------------------------------------------------------------------+
#property copyright "Antigravity (Trader Institucional)"
#property link      ""
#property version   "1.00"
#property description "Expert Advisor FTMO $10k - Divergencias Ocultas (M15)"

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

sinput string     Section2 = "=== Configuración de Estrategia ===";
input ulong       InpMagicNumber = 333123;    // Magic Number
input int         InpEmaPeriod = 100;         // Periodo EMA
input int         InpRsiPeriod = 14;          // Periodo RSI

//--- Variables Globales
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
CAccountInfo   m_account;

double         g_initial_balance = 0.0;
int            g_last_reset_day = -1;
bool           g_trading_stopped_today = false;

// Prevenir entradas duplicadas en el mismo pullback
datetime       g_last_traded_swing_time = 0; 

// Handles
int            handle_ema;
int            handle_rsi;
int            handle_fractals;

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
      Print("⚠️ ADVERTENCIA: La estrategia Divergencias Ocultas está optimizada para M15. Temporalidad actual: ", EnumToString(_Period));
     }
     
   // Inicializar Indicadores
   handle_ema = iMA(_Symbol, _Period, InpEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   handle_rsi = iRSI(_Symbol, _Period, InpRsiPeriod, PRICE_CLOSE);
   handle_fractals = iFractals(_Symbol, _Period);
   
   if(handle_ema == INVALID_HANDLE || handle_rsi == INVALID_HANDLE || handle_fractals == INVALID_HANDLE)
     {
      Print("❌ Error al inicializar indicadores.");
      return INIT_FAILED;
     }

   Print("🚀 FTMO_Hidden_Divergence inicializado con éxito. MagicNumber: ", InpMagicNumber);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(handle_ema);
   IndicatorRelease(handle_rsi);
   IndicatorRelease(handle_fractals);
  }

//+------------------------------------------------------------------+
//| Helpers para extraer datos (Wrapper seguro)                      |
//+------------------------------------------------------------------+
double GetLow(int shift) { double a[]; if(CopyLow(_Symbol, _Period, shift, 1, a) > 0) return a[0]; return 0; }
double GetHigh(int shift) { double a[]; if(CopyHigh(_Symbol, _Period, shift, 1, a) > 0) return a[0]; return 0; }
double GetClose(int shift) { double a[]; if(CopyClose(_Symbol, _Period, shift, 1, a) > 0) return a[0]; return 0; }
double GetOpen(int shift) { double a[]; if(CopyOpen(_Symbol, _Period, shift, 1, a) > 0) return a[0]; return 0; }
datetime GetTime(int shift) { datetime a[]; if(CopyTime(_Symbol, _Period, shift, 1, a) > 0) return a[0]; return 0; }

double GetRsi(int shift) { double a[]; if(CopyBuffer(handle_rsi, 0, shift, 1, a) > 0) return a[0]; return 0; }
double GetEma(int shift) { double a[]; if(CopyBuffer(handle_ema, 0, shift, 1, a) > 0) return a[0]; return 0; }

//+------------------------------------------------------------------+
//| Helper: Convierte hora del Broker a hora CET real                |
//+------------------------------------------------------------------+
datetime GetCetTime(datetime broker_time)
  {
   return broker_time - (InpBrokerOffsetCET * 3600);
  }

//+------------------------------------------------------------------+
//| Helper: Busca el último Fractal (Swing High o Low)               |
//| direction = 0 (UPPER/Swing High), 1 (LOWER/Swing Low)            |
//+------------------------------------------------------------------+
int FindLastFractal(int direction, int start_shift, int limit=100)
  {
   double fractals[];
   if(CopyBuffer(handle_fractals, direction, start_shift, limit, fractals) <= 0) return -1;
   
   ArraySetAsSeries(fractals, true);
   for(int i = 0; i < limit; i++)
     {
      // El fractal es válido si su valor no es el de vacío por defecto de MT5
      if(fractals[i] != EMPTY_VALUE && fractals[i] != 0.0 && fractals[i] != DBL_MAX)
        {
         return start_shift + i;
        }
     }
   return -1;
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

   // Regla estricta: Solo 1 operación abierta a la vez
   if(PositionsTotal() > 0) return;

   //================================================================
   // 3. GATILLO (Filtro por nueva vela)
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
//| Función: Mapeo de Estructura Institucional y Divergencia Oculta  |
//+------------------------------------------------------------------+
void CheckForEntry()
  {
   double point = m_symbol.Point();
   int digits = m_symbol.Digits();
   double pip_size = (digits == 5 || digits == 3) ? point * 10 : point;
   
   double ema100 = GetEma(1);
   double close1 = GetClose(1);
   double open1 = GetOpen(1);
   
   //================================================================
   // LÓGICA COMPRADORA (Divergencia Oculta Alcista)
   //================================================================
   if(close1 > ema100 && close1 > open1) // Tendencia y Rechazo (Vela Cierra Alcista)
     {
      // 1. Encontrar el último pico (Swing High local)
      int last_swing_high_idx = FindLastFractal(0, 3, 100);
      if(last_swing_high_idx != -1)
        {
         // 2. Encontrar el Swing Low previo (más antiguo que el Swing High)
         int prev_swing_low_idx = FindLastFractal(1, last_swing_high_idx + 1, 100);
         if(prev_swing_low_idx != -1)
           {
            // 3. Identificar el mínimo actual del pullback (Swing Low en formación)
            int count_curr = last_swing_high_idx - 1;
            if(count_curr > 0)
              {
               double lows[];
               if(CopyLow(_Symbol, _Period, 1, count_curr, lows) > 0)
                 {
                  ArraySetAsSeries(lows, true);
                  int min_offset = ArrayMinimum(lows);
                  int curr_low_idx = 1 + min_offset;
                  double curr_low_price = lows[min_offset];
                  
                  double prev_low_price = GetLow(prev_swing_low_idx);
                  
                  // 4. Evaluar estructura y divergencia
                  if(curr_low_price > prev_low_price) // Higher Low estructural
                    {
                     double rsi_curr = GetRsi(curr_low_idx);
                     double rsi_prev = GetRsi(prev_swing_low_idx);
                     
                     if(rsi_curr < rsi_prev) // Lower Low en RSI (Divergencia Oculta)
                       {
                        datetime swing_time = GetTime(curr_low_idx);
                        if(swing_time != g_last_traded_swing_time)
                          {
                           Print("⚡ Gatillo COMPRA: Divergencia Oculta Alcista Detectada. Higher Low en Precio, Lower Low en RSI.");
                           
                           double sl_price = curr_low_price - (2.0 * pip_size); // 2 pips por debajo
                           double tp_price = GetHigh(last_swing_high_idx); // Último Swing High
                           
                           ExecuteTrade(ORDER_TYPE_BUY, sl_price, tp_price, swing_time);
                           return; // Evita evaluar cortos si ya operó
                          }
                       }
                    }
                 }
              }
           }
        }
     }
     
   //================================================================
   // LÓGICA VENDEDORA (Divergencia Oculta Bajista)
   //================================================================
   if(close1 < ema100 && close1 < open1) // Tendencia y Rechazo (Vela Cierra Bajista)
     {
      // 1. Encontrar el último valle (Swing Low local)
      int last_swing_low_idx = FindLastFractal(1, 3, 100);
      if(last_swing_low_idx != -1)
        {
         // 2. Encontrar el Swing High previo (más antiguo que el Swing Low)
         int prev_swing_high_idx = FindLastFractal(0, last_swing_low_idx + 1, 100);
         if(prev_swing_high_idx != -1)
           {
            // 3. Identificar el máximo actual del pullback (Swing High en formación)
            int count_curr = last_swing_low_idx - 1;
            if(count_curr > 0)
              {
               double highs[];
               if(CopyHigh(_Symbol, _Period, 1, count_curr, highs) > 0)
                 {
                  ArraySetAsSeries(highs, true);
                  int max_offset = ArrayMaximum(highs);
                  int curr_high_idx = 1 + max_offset;
                  double curr_high_price = highs[max_offset];
                  
                  double prev_high_price = GetHigh(prev_swing_high_idx);
                  
                  // 4. Evaluar estructura y divergencia
                  if(curr_high_price < prev_high_price) // Lower High estructural
                    {
                     double rsi_curr = GetRsi(curr_high_idx);
                     double rsi_prev = GetRsi(prev_swing_high_idx);
                     
                     if(rsi_curr > rsi_prev) // Higher High en RSI (Divergencia Oculta)
                       {
                        datetime swing_time = GetTime(curr_high_idx);
                        if(swing_time != g_last_traded_swing_time)
                          {
                           Print("⚡ Gatillo VENTA: Divergencia Oculta Bajista Detectada. Lower High en Precio, Higher High en RSI.");
                           
                           double sl_price = curr_high_price + (2.0 * pip_size); // 2 pips por encima
                           double tp_price = GetLow(last_swing_low_idx); // Último Swing Low
                           
                           ExecuteTrade(ORDER_TYPE_SELL, sl_price, tp_price, swing_time);
                           return;
                          }
                       }
                    }
                 }
              }
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Función: Ejecución Dinámica, Control RR y Riesgo en USD          |
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ORDER_TYPE type, double sl_price, double tp_price, datetime swing_time)
  {
   double entry_price = (type == ORDER_TYPE_BUY) ? m_symbol.Ask() : m_symbol.Bid();
   
   double sl_dist_price = MathAbs(entry_price - sl_price);
   if(sl_dist_price == 0) return;
   
   double tp_dist_price = MathAbs(tp_price - entry_price);
   
   //================================================================
   // FORZAR RATIO RIESGO/BENEFICIO MÍNIMO (1:1.5)
   //================================================================
   double min_tp_dist = sl_dist_price * 1.5;
   if(tp_dist_price < min_tp_dist)
     {
      tp_dist_price = min_tp_dist;
      tp_price = (type == ORDER_TYPE_BUY) ? entry_price + tp_dist_price : entry_price - tp_dist_price;
     }
      
   //================================================================
   // CÁLCULO DINÁMICO DE LOTAJE ($50 de Riesgo exactos)
   //================================================================
   double tick_size = m_symbol.TickSize();
   double tick_value = m_symbol.TickValue();
   if(tick_size == 0 || tick_value == 0) return;
   
   double sl_ticks = sl_dist_price / tick_size;
   double loss_per_lot = sl_ticks * tick_value;
   if(loss_per_lot <= 0) return;
   
   double lots = InpRiskAmount / loss_per_lot;
   
   double step = m_symbol.LotsStep();
   lots = MathFloor(lots / step) * step;
   
   if(lots < m_symbol.LotsMin())
     {
      Print("🚫 CANCELADO: El Stop Loss es tan amplio que usar el lote mínimo superaría el riesgo estricto de $", InpRiskAmount);
      return;
     }
   if(lots > m_symbol.LotsMax()) lots = m_symbol.LotsMax();
   
   int digits = m_symbol.Digits();
   sl_price = NormalizeDouble(sl_price, digits);
   tp_price = NormalizeDouble(tp_price, digits);
   
   if(type == ORDER_TYPE_BUY)
      m_trade.Buy(lots, _Symbol, 0.0, sl_price, tp_price, "HiddenDiv_Long");
   else
      m_trade.Sell(lots, _Symbol, 0.0, sl_price, tp_price, "HiddenDiv_Short");
      
   Print("✅ ORDEN ENVIADA. Lotes: ", DoubleToString(lots, 2), " | Riesgo Aprox: $", InpRiskAmount);
   
   // Prevenir re-entrada en el mismo swing exacto
   g_last_traded_swing_time = swing_time;
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
