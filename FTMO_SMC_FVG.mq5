//+------------------------------------------------------------------+
//|                                     FTMO_SMC_FVG.mq5             |
//|                                     Copyright 2026, Antigravity  |
//|                                      https://www.mql5.com        |
//+------------------------------------------------------------------+
#property copyright "Antigravity (Trader Institucional SMC)"
#property link      ""
#property version   "1.00"
#property description "Expert Advisor FTMO $10k - SMC Fair Value Gaps (M15)"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- Parámetros de entrada
sinput string     Section1 = "=== Gestión de Riesgo ===";
input double      InpRiskAmount = 50.0;       // Riesgo por operación (USD)
input double      InpDailyDrawdown = 400.0;   // Límite Diario de Pérdida (USD)

sinput string     Section2 = "=== Horarios y Filtros (Hora CET) ===";
input int         InpBrokerOffsetCET = 0;     // Desfase del Broker respecto a CET (0 para FTMO, 1 para EET)
input int         InpStartHour = 8;           // Hora de inicio (CET)
input int         InpEndHour = 17;            // Hora de fin (CET)
input double      InpMaxSpreadPips = 1.5;     // Máximo Spread Permitido (Pips)

sinput string     Section3 = "=== Configuración Estrategia SMC ===";
input ulong       InpMagicNumber = 777123;    // Magic Number
input ulong       InpMaxSlippagePoints = 30;  // Slippage Máximo (Puntos)

//--- Variables Globales
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
CAccountInfo   m_account;

double         g_initial_balance = 0.0;
int            g_last_cet_day = -1;
bool           g_trading_stopped_today = false;

//--- Estructura para almacenar el Fair Value Gap en memoria
struct FVG_Zone
  {
   bool   active;
   int    type;             // 1 = Alcista, -1 = Bajista
   double high_price;       // Borde superior del FVG
   double low_price;        // Borde inferior del FVG
   double mid_price;        // 50% de Mitigación
   double sl_base_price;    // Mínimo/Máximo de la Vela 3 para el Stop Loss estructural
   datetime creation_time;
  };
FVG_Zone g_fvg;

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
      Print("⚠️ ADVERTENCIA: La estrategia SMC FVG está optimizada para M15. Temporalidad actual: ", EnumToString(_Period));
     }

   g_fvg.active = false;

   Print("🚀 FTMO_SMC_FVG inicializado con éxito. MagicNumber: ", InpMagicNumber);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
  }

//+------------------------------------------------------------------+
//| Helper: Convierte hora del Broker a hora CET real                |
//+------------------------------------------------------------------+
datetime GetCetTime(datetime broker_time)
  {
   // Restamos el offset. Ejemplo: Si broker es EET (CET+1), offset es 1.
   // broker_time (15:00) - 1 hora = 14:00 CET.
   return broker_time - (InpBrokerOffsetCET * 3600);
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   if(!m_symbol.RefreshRates()) return;

   datetime current_time = TimeCurrent();
   datetime cet_time = GetCetTime(current_time);
   
   MqlDateTime dt_cet;
   TimeToStruct(cet_time, dt_cet);
   
   //================================================================
   // 1. CONTROL DIARIO FTMO: Reset exacto a la Medianoche CET
   //================================================================
   int current_day = dt_cet.day;
   if(current_day != g_last_cet_day)
     {
      g_initial_balance = m_account.Balance();
      g_last_cet_day = current_day;
      g_trading_stopped_today = false;
      Print("📅 Medianoche CET Detectada. Balance inicial del día fijado en: $", DoubleToString(g_initial_balance, 2));
     }

   //================================================================
   // 2. CORTACORRIENTES DIARIO
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
   // 3. GESTIÓN BREAK EVEN (Tick a Tick)
   //================================================================
   if(PositionsTotal() > 0)
     {
      ManageBreakEven();
      return; // Regla estricta: Máximo 1 operación a la vez. No buscamos entradas.
     }

   //================================================================
   // 4. FILTRO DE SPREAD
   //================================================================
   double point = m_symbol.Point();
   double pip_size = (m_symbol.Digits() == 5 || m_symbol.Digits() == 3) ? point * 10 : point;
   double current_spread = (m_symbol.Ask() - m_symbol.Bid()) / pip_size;
   
   if(current_spread > InpMaxSpreadPips) return; 

   //================================================================
   // 5. GATILLO (Filtro por nueva vela M15)
   //================================================================
   static datetime last_bar_time = 0;
   datetime bar_time[1];
   if(CopyTime(_Symbol, _Period, 0, 1, bar_time) <= 0) return;
   
   if(bar_time[0] != last_bar_time)
     {
      last_bar_time = bar_time[0];
      CheckForEntry(dt_cet.hour);
     }
  }

//+------------------------------------------------------------------+
//| Lógica Principal: Detección y Mitigación de FVG                  |
//+------------------------------------------------------------------+
void CheckForEntry(int cet_hour)
  {
   MqlRates rates[];
   // Copiamos las últimas 3 velas cerradas (shift 1, 2 y 3)
   if(CopyRates(_Symbol, _Period, 1, 3, rates) <= 0) return;
   
   // En MqlRates (sin ArraySetAsSeries):
   // rates[0] = Vela 3 (La más antigua del patrón)
   // rates[1] = Vela 2 (La del medio, donde se forma el desequilibrio)
   // rates[2] = Vela 1 (La más reciente, que cerró el gap)
   
   double high3 = rates[0].high;
   double low3  = rates[0].low;
   
   double high1 = rates[2].high;
   double low1  = rates[2].low;
   double close1 = rates[2].close;
   double open1 = rates[2].open;
   
   //================================================================
   // A. DETECCIÓN DE NUEVOS PATRONES FVG
   //================================================================
   if(high3 < low1)
     {
      // FVG Alcista (Bullish Imbalance)
      g_fvg.active = true;
      g_fvg.type = 1;
      g_fvg.high_price = low1;
      g_fvg.low_price = high3;
      g_fvg.mid_price = high3 + ((low1 - high3) * 0.5);
      g_fvg.sl_base_price = low3; // Mínimo de la vela 3
      g_fvg.creation_time = rates[2].time;
     }
   else if(low3 > high1)
     {
      // FVG Bajista (Bearish Imbalance)
      g_fvg.active = true;
      g_fvg.type = -1;
      g_fvg.high_price = low3;
      g_fvg.low_price = high1;
      g_fvg.mid_price = high1 + ((low3 - high1) * 0.5);
      g_fvg.sl_base_price = high3; // Máximo de la vela 3
      g_fvg.creation_time = rates[2].time;
     }
     
   //================================================================
   // B. FILTRO DE HORARIO (Solo evaluamos mitigaciones en sesión)
   //================================================================
   if(cet_hour < InpStartHour || cet_hour >= InpEndHour) return;

   //================================================================
   // C. EVALUACIÓN DE MITIGACIÓN Y RECHAZO
   //================================================================
   if(g_fvg.active)
     {
      // 1. Invalidación Estructural (El precio cruzó todo el gap con el cuerpo)
      if(g_fvg.type == 1 && close1 < g_fvg.low_price) g_fvg.active = false;
      if(g_fvg.type == -1 && close1 > g_fvg.high_price) g_fvg.active = false;
      
      if(!g_fvg.active) return;
      
      // 2. Mitigación FVG Alcista
      if(g_fvg.type == 1)
        {
         // El precio retrocedió hasta el 50% y la vela cerró alcista demostrando inyección de liquidez
         if(low1 <= g_fvg.mid_price && close1 > open1)
           {
            Print("⚡ Gatillo COMPRA: FVG Alcista Mitigado (>50%) y Rechazado (Cierre Alcista).");
            ExecuteTrade(ORDER_TYPE_BUY);
            g_fvg.active = false; // El gap ya fue capitalizado
           }
        }
      // 3. Mitigación FVG Bajista
      else if(g_fvg.type == -1)
        {
         // El precio subió hasta el 50% y la vela cerró bajista
         if(high1 >= g_fvg.mid_price && close1 < open1)
           {
            Print("⚡ Gatillo VENTA: FVG Bajista Mitigado (>50%) y Rechazado (Cierre Bajista).");
            ExecuteTrade(ORDER_TYPE_SELL);
            g_fvg.active = false; // El gap ya fue capitalizado
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Ejecución Dinámica, Control de SL Mínimo y Take Profit Asimétrico|
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ORDER_TYPE type)
  {
   double entry_price = (type == ORDER_TYPE_BUY) ? m_symbol.Ask() : m_symbol.Bid();
   
   double point = m_symbol.Point();
   int digits = m_symbol.Digits();
   double pip_size = (digits == 5 || digits == 3) ? point * 10 : point;
   
   double sl_price = 0.0;
   
   //================================================================
   // ESTRUCTURACIÓN DE STOP LOSS (Con Forzado Mínimo de 5 Pips)
   //================================================================
   if(type == ORDER_TYPE_BUY)
     {
      sl_price = g_fvg.sl_base_price - (1.0 * pip_size); // 1 pip por debajo del origen (Low 3)
      if(entry_price - sl_price < 5.0 * pip_size) 
         sl_price = entry_price - (5.0 * pip_size);
     }
   else
     {
      sl_price = g_fvg.sl_base_price + (1.0 * pip_size); // 1 pip por encima del origen (High 3)
      if(sl_price - entry_price < 5.0 * pip_size) 
         sl_price = entry_price + (5.0 * pip_size);
     }
     
   double risk_dist_price = MathAbs(entry_price - sl_price);
   if(risk_dist_price == 0) return;
   
   //================================================================
   // TAKE PROFIT FIJO (Ratio 1:3)
   //================================================================
   double tp_dist_price = risk_dist_price * 3.0;
   double tp_price = (type == ORDER_TYPE_BUY) ? entry_price + tp_dist_price : entry_price - tp_dist_price;
      
   //================================================================
   // CÁLCULO MATEMÁTICO DE LOTAJE ($50 de Riesgo exactos)
   //================================================================
   double tick_size = m_symbol.TickSize();
   double tick_value = m_symbol.TickValue();
   if(tick_size == 0 || tick_value == 0) return;
   
   double sl_ticks = risk_dist_price / tick_size;
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
   
   sl_price = NormalizeDouble(sl_price, digits);
   tp_price = NormalizeDouble(tp_price, digits);
   
   if(type == ORDER_TYPE_BUY)
      m_trade.Buy(lots, _Symbol, 0.0, sl_price, tp_price, "SMC_FVG_Long");
   else
      m_trade.Sell(lots, _Symbol, 0.0, sl_price, tp_price, "SMC_FVG_Short");
      
   Print("✅ ORDEN SMC ENVIADA. Lotes: ", DoubleToString(lots, 2), " | Ratio: 1:3");
  }

//+------------------------------------------------------------------+
//| Gestión Break Even (Mover SL a Entrada al tocar Ratio 1:1)       |
//+------------------------------------------------------------------+
void ManageBreakEven()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(m_position.SelectByIndex(i))
        {
         if(m_position.Symbol() == _Symbol && m_position.Magic() == InpMagicNumber)
           {
            double entry = m_position.PriceOpen();
            double sl = m_position.StopLoss();
            double tp = m_position.TakeProfit();
            
            if(sl == entry || sl == 0) continue; // Ya está protegido o sin SL
            
            double risk_dist = MathAbs(entry - sl);
            if(risk_dist == 0) continue;
            
            bool move_be = false;
            
            // Si es Compra y el precio Bid subió un 100% de la distancia del riesgo original
            if(m_position.PositionType() == POSITION_TYPE_BUY)
              {
               if(sl < entry && m_symbol.Bid() >= entry + risk_dist) move_be = true;
              }
            // Si es Venta y el precio Ask bajó un 100% de la distancia del riesgo original
            else if(m_position.PositionType() == POSITION_TYPE_SELL)
              {
               if(sl > entry && m_symbol.Ask() <= entry - risk_dist) move_be = true;
              }
              
            if(move_be)
              {
               // Movemos SL al precio de entrada exacto
               m_trade.PositionModify(m_position.Ticket(), entry, tp);
               Print("🛡️ Break Even Activado: Ratio 1:1 superado. Riesgo $0 asegurado.");
              }
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Cerrar Todas las Posiciones (Emergencia / Límite Diario)         |
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
