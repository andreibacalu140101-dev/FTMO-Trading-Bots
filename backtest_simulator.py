import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, timedelta

def get_data(symbol, timeframe, days=7):
    tz = pytz.timezone('Europe/Prague')
    utc_to = datetime.now(pytz.timezone('UTC'))
    utc_from = utc_to - timedelta(days=days)
    
    rates = mt5.copy_rates_range(symbol, timeframe, utc_from, utc_to)
    if rates is None or len(rates) == 0:
        print(f"No se pudieron descargar datos para {symbol}")
        return None
        
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df['time'] = df['time'].dt.tz_convert(tz)
    return df

def calculate_atr(df, period=14):
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift(1))
    df['tr2'] = abs(df['low'] - df['close'].shift(1))
    tr = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['atr'] = tr.rolling(period).mean()
    df.drop(['tr0', 'tr1', 'tr2'], axis=1, inplace=True)
    return df

def run_simulation():
    if not mt5.initialize():
        print("❌ Error inicializando MT5")
        return
        
    symbols = ['EURUSD', 'XAUUSD']
    final_report = []
    
    print("="*50)
    print("🧪 INICIANDO BACKTEST SIMULATOR INSTITUCIONAL (7 Días)")
    print("="*50)
    
    for symbol in symbols:
        print(f"\nProcesando {symbol}...")
        df = get_data(symbol, mt5.TIMEFRAME_M5, 7)
        if df is None:
            continue
            
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            print(f"Símbolo {symbol} no encontrado.")
            continue
            
        pip_size = 10 * symbol_info.point if (symbol_info.digits == 5 or symbol_info.digits == 3) else symbol_info.point
        
        df = calculate_atr(df, 14)
        
        # Buffer de Riesgo: (Spread * punto) + (0.5 * ATR)
        df['spread_price'] = df['spread'] * symbol_info.point
        df['buffer'] = df['spread_price'] + (0.5 * df['atr'])
        df['time_str'] = df['time'].dt.strftime('%H:%M')
        
        # Variables de Simulación
        open_trades = []
        daily_pnl = {}
        total_trades = 0
        wins = 0
        saved_by_buffer_count = 0
        trad_sl_hit_count = 0
        
        risk_usd = 50.0 # 0.5% de $10,000
        reward_usd = 100.0 # Ratio 1:2
        base_sl_dist = 10 * pip_size if symbol == 'EURUSD' else 30 * pip_size
        
        # Variables de estado diario
        current_day = ""
        trades_today = 0
        
        # Estado FVG
        active_bull_fvg = None
        active_bear_fvg = None
        
        # Estado ORB
        orb_high = -np.inf
        orb_low = np.inf
        orb_active = False

        for i in range(2, len(df)):
            row = df.iloc[i]
            prev1 = df.iloc[i-1] # Vela 2
            prev2 = df.iloc[i-2] # Vela 1
            
            day_str = row['time'].strftime('%Y-%m-%d')
            h = row['time'].hour
            m = row['time'].minute
            t_str = row['time_str']
            
            # Reset diario
            if day_str != current_day:
                current_day = day_str
                trades_today = 0
                active_bull_fvg = None
                active_bear_fvg = None
                orb_high = -np.inf
                orb_low = np.inf
                orb_active = False
                
            if day_str not in daily_pnl:
                daily_pnl[day_str] = 0.0
                
            # Restricción FTMO (Kill Switch)
            if daily_pnl[day_str] <= -380.0:
                continue
                
            # ---------------------------------------------------------
            # 1. ACTUALIZAR POSICIONES ABIERTAS
            # ---------------------------------------------------------
            for trade in open_trades[:]:
                if not trade['hit_trad_sl']:
                    if trade['type'] == 'BUY' and row['low'] <= trade['sl_trad']:
                        trade['hit_trad_sl'] = True
                    elif trade['type'] == 'SELL' and row['high'] >= trade['sl_trad']:
                        trade['hit_trad_sl'] = True

                if trade['type'] == 'BUY':
                    if row['low'] <= trade['sl_inst']:
                        daily_pnl[day_str] -= risk_usd
                        if trade['hit_trad_sl']: trad_sl_hit_count += 1
                        open_trades.remove(trade)
                    elif row['high'] >= trade['tp']:
                        daily_pnl[day_str] += reward_usd
                        wins += 1
                        if trade['hit_trad_sl']: saved_by_buffer_count += 1
                        open_trades.remove(trade)
                else: # SELL
                    if row['high'] >= trade['sl_inst']:
                        daily_pnl[day_str] -= risk_usd
                        if trade['hit_trad_sl']: trad_sl_hit_count += 1
                        open_trades.remove(trade)
                    elif row['low'] <= trade['tp']:
                        daily_pnl[day_str] += reward_usd
                        wins += 1
                        if trade['hit_trad_sl']: saved_by_buffer_count += 1
                        open_trades.remove(trade)

            # Si ya operamos hoy en este activo o hay trades abiertos, no buscar más entradas
            if trades_today >= 1 or len(open_trades) > 0:
                continue

            signal = 0
            
            # ---------------------------------------------------------
            # 2. LÓGICA DE ESTRATEGIAS
            # ---------------------------------------------------------
            if symbol == 'EURUSD':
                # SMC FVG (08:30 - 11:30)
                is_fvg_window = (h == 8 and m >= 30) or (h > 8 and h < 11) or (h == 11 and m <= 30)
                
                if is_fvg_window:
                    # Detectar nuevos FVGs (Vela 1 = prev2, Vela 3 = row)
                    # Bullish FVG: Max Vela 1 < Min Vela 3
                    if prev2['high'] < row['low'] and prev1['close'] > prev1['open']:
                        active_bull_fvg = {'top': row['low'], 'bottom': prev2['high']}
                    
                    # Bearish FVG: Min Vela 1 > Max Vela 3
                    if prev2['low'] > row['high'] and prev1['close'] < prev1['open']:
                        active_bear_fvg = {'top': prev2['low'], 'bottom': row['high']}
                        
                    # Evaluar Mitigación (Entrada) en vela actual
                    if active_bull_fvg and row['low'] <= active_bull_fvg['top']:
                        signal = 1
                        active_bull_fvg = None # Invalida el gap tras usarlo
                    elif active_bear_fvg and row['high'] >= active_bear_fvg['bottom']:
                        signal = -1
                        active_bear_fvg = None
                else:
                    # Fuera de sesión, limpiar FVGs
                    active_bull_fvg = None
                    active_bear_fvg = None

            elif symbol == 'XAUUSD':
                # NY ORB (Observación 15:30 - 16:00, Ejecución 16:00 - 17:00)
                # Observación
                if (h == 15 and m >= 30):
                    if row['high'] > orb_high: orb_high = row['high']
                    if row['low'] < orb_low: orb_low = row['low']
                
                # Ejecución
                if h == 16:
                    orb_active = True
                    if row['close'] > orb_high:
                        signal = 1
                        orb_active = False # Evita múltiples disparos
                    elif row['close'] < orb_low:
                        signal = -1
                        orb_active = False
                else:
                    orb_active = False
            
            # ---------------------------------------------------------
            # 3. EJECUCIÓN DEL TRADE
            # ---------------------------------------------------------
            if signal != 0:
                sl_trad = row['close'] - base_sl_dist if signal == 1 else row['close'] + base_sl_dist
                sl_inst = sl_trad - row['buffer'] if signal == 1 else sl_trad + row['buffer']
                tp = row['close'] + (base_sl_dist * 2.0) if signal == 1 else row['close'] - (base_sl_dist * 2.0)
                
                open_trades.append({
                    'type': 'BUY' if signal == 1 else 'SELL',
                    'entry': row['close'],
                    'sl_trad': sl_trad,
                    'sl_inst': sl_inst,
                    'tp': tp,
                    'hit_trad_sl': False
                })
                total_trades += 1
                trades_today += 1
                
        # Final calculations
        net_pnl = sum(daily_pnl.values())
        max_dd = min(daily_pnl.values()) if daily_pnl else 0.0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        
        final_report.append({
            'symbol': symbol,
            'strategy': 'SMC FVG' if symbol == 'EURUSD' else 'NY ORB',
            'trades': total_trades,
            'win_rate': win_rate,
            'net_pnl': net_pnl,
            'max_dd': max_dd,
            'saved_by_buffer': saved_by_buffer_count,
            'hit_sl': trad_sl_hit_count
        })
        
    print("\n" + "="*50)
    print("📊 REPORTE FINAL DEL SIMULADOR ESTRATÉGICO")
    print("="*50)
    
    total_net = 0.0
    for res in final_report:
        total_net += res['net_pnl']
        print(f"\nEstrategia: {res['strategy']} ({res['symbol']})")
        print(f"  - Operaciones: {res['trades']}")
        print(f"  - Win Rate:    {res['win_rate']:.2f}%")
        print(f"  - PnL Neto:    ${res['net_pnl']:.2f}")
        print(f"  - Max DD Día:  ${res['max_dd']:.2f}")
        print(f"  - Trades Salvados por Buffer: {res['saved_by_buffer']} 🛡️")
        
    print(f"\n💰 PnL Total Consolidado: ${total_net:.2f}")
    print("="*50)

    mt5.shutdown()

if __name__ == "__main__":
    run_simulation()
