//+------------------------------------------------------------------+
//|                               FTMO_Volatility_Breakout.mq5       |
//|                                     Copyright 2026, Antigravity  |
//|                                      https://www.mql5.com        |
//+------------------------------------------------------------------+
#property copyright "Antigravity (Trader Institucional)"
#property link      ""
#property version   "1.00"
#property description "Expert Advisor FTMO $10k - Volatility Breakout (H1)"

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
input ulong       InpMagicNumber = 222123;    // Magic Number
input int         InpDonchianPeriod = 20;     // Periodo Donchian Channel
input int         InpAtrPeriod = 14;          // Periodo ATR
input int         InpAtrSmaPeriod = 14;       // Periodo SMA del ATR
input double      InpAtrMultiplierSl = 1.5;   // Multiplicador ATR para Stop Loss
input double      InpAtrMultiplierTp = 3.0;   // Multiplicador ATR para Take Profit (1:2 RR)

//--- Variables Globales
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
CAccountInfo   m_account;

double         g_initial_balance = 0.0;
int            g_last_reset_day = -1;
bool           g_trading_stopped_today = false;

// Handles
int            handle_atr;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   m_symbol.Name(_Symbol);
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(InpMaxSlippagePoints);
   
   if(_Period != PERIOD_H1)
     {
      Print("⚠️ ADVERTENCIA: La estrategia Breakout de Volatilidad está diseñada estrictamente para H1. Temporalidad actual: ", EnumToString(_Period));
     }
     
   // Inicializar Indicador
   handle_atr = iATR(_Symbol, _Period, InpAtrPeriod);
   
   if(handle_atr == INVALID_HANDLE)
     {
      Print("❌ Error al inicializar el ATR.");
      return INIT_FAILED;
     }

   Print("🚀 FTMO_Volatility_Breakout inicializado con éxito. MagicNumber: ", InpMagicNumber);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(handle_atr);
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
//| Función: Lógica de Breakout de Volatilidad (Donchian + ATR)      |
//+------------------------------------------------------------------+
void CheckForEntry()
  {
   // 1. Obtener Cierre de la Vela Gatillo (Shift 1)
   double close[];
   if(CopyClose(_Symbol, _Period, 1, 1, close) <= 0) return;
   double last_close = close[0];
   
   // 2. Calcular Bandas de Donchian de los N periodos ANTERIORES al gatillo (Shift 2 a 21)
   double high[];
   if(CopyHigh(_Symbol, _Period, 2, InpDonchianPeriod, high) <= 0) return;
   double upper_band = high[ArrayMaximum(high)];
   
   double low[];
   if(CopyLow(_Symbol, _Period, 2, InpDonchianPeriod, low) <= 0) return;
   double lower_band = low[ArrayMinimum(low)];
   
   // 3. Calcular ATR y SMA del ATR
   double atr_values[];
   // Copiamos datos suficientes para la SMA (terminando en la vela 1)
   if(CopyBuffer(handle_atr, 0, 1, InpAtrSmaPeriod, atr_values) <= 0) return;
   
   ArraySetAsSeries(atr_values, true); // Índice 0 es el ATR de la vela recién cerrada (Shift 1)
   double current_atr = atr_values[0];
   
   double atr_sum = 0;
   for(int i=0; i<InpAtrSmaPeriod; i++) 
     {
      atr_sum += atr_values[i];
     }
   double atr_sma = atr_sum / InpAtrSmaPeriod;
   
   //--- 4. Lógica Compradora (Long) ---
   // El cierre rompe el techo previo Y la volatilidad está en expansión
   if(last_close > upper_band && current_atr > atr_sma)
     {
      Print("⚡ Gatillo COMPRA: Breakout Alcista Donchian completado. Volatilidad (ATR) en Expansión.");
      ExecuteTrade(ORDER_TYPE_BUY, current_atr);
     }
     
   //--- 5. Lógica Vendedora (Short) ---
   // El cierre rompe el suelo previo Y la volatilidad está en expansión
   else if(last_close < lower_band && current_atr > atr_sma)
     {
      Print("⚡ Gatillo VENTA: Breakout Bajista Donchian completado. Volatilidad (ATR) en Expansión.");
      ExecuteTrade(ORDER_TYPE_SELL, current_atr);
     }
  }

//+------------------------------------------------------------------+
//| Función: Ejecución Dinámica por ATR y Riesgo en USD              |
//+------------------------------------------------------------------+
void ExecuteTrade(ENUM_ORDER_TYPE type, double atr_value)
  {
   double entry_price = (type == ORDER_TYPE_BUY) ? m_symbol.Ask() : m_symbol.Bid();
   
   // 1. Distancias en precios absolutos (El ATR ya devuelve unidades de precio)
   double sl_dist_price = InpAtrMultiplierSl * atr_value;
   double tp_dist_price = InpAtrMultiplierTp * atr_value;
   
   double sl_price = (type == ORDER_TYPE_BUY) ? entry_price - sl_dist_price : entry_price + sl_dist_price;
   double tp_price = (type == ORDER_TYPE_BUY) ? entry_price + tp_dist_price : entry_price - tp_dist_price;
      
   //================================================================
   // 2. CÁLCULO DINÁMICO DE LOTAJE ($50 de Riesgo exactos)
   //================================================================
   double tick_size = m_symbol.TickSize();
   double tick_value = m_symbol.TickValue();
   if(tick_size == 0 || tick_value == 0) return;
   
   // Conversión: Distancia de Stop Loss / Tamaño del Tick = Cantidad de Ticks
   double sl_ticks = sl_dist_price / tick_size;
   
   // ¿Cuánto pierdo en USD si me tocan el Stop Loss moviendo 1 Lote entero?
   double loss_per_lot = sl_ticks * tick_value;
   if(loss_per_lot <= 0) return;
   
   // Lotes requeridos = Dinero Riesgo / Dinero por Lote
   double lots = InpRiskAmount / loss_per_lot;
   
   // 3. Ajuste y Normalización
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
   
   // 4. Envío de Orden
   if(type == ORDER_TYPE_BUY)
      m_trade.Buy(lots, _Symbol, 0.0, sl_price, tp_price, "Breakout_Long");
   else
      m_trade.Sell(lots, _Symbol, 0.0, sl_price, tp_price, "Breakout_Short");
      
   Print("✅ ORDEN ENVIADA. Lotes: ", DoubleToString(lots, 2), " | Riesgo Aprox: $", InpRiskAmount, " | SL Distancia (Ticks): ", sl_ticks);
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
