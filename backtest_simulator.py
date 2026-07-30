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
    print("🧪 INICIANDO BACKTEST SIMULATOR (7 Días - M5)")
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
        
        # Simulación de Franjas Horarias
        df['time_str'] = df['time'].dt.strftime('%H:%M')
        
        def is_valid_window(t_str):
            h, m = map(int, t_str.split(':'))
            # Night Scalper: 23:00-02:00
            if h >= 23 or h < 2: return True
            # SMC FVG: 08:30-11:30
            if (h == 8 and m >= 30) or (h > 8 and h < 11) or (h == 11 and m <= 30): return True
            # NY ORB: 14:30-16:30
            if (h == 14 and m >= 30) or (h == 15) or (h == 16 and m <= 30): return True
            return False
            
        df['valid_window'] = df['time_str'].apply(is_valid_window)
        
        # Generar Señales Dummy (Cruce de EMAs) solo en ventanas válidas
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['signal'] = 0
        
        buy_cross = (df['ema9'].shift(1) < df['ema21'].shift(1)) & (df['ema9'] > df['ema21'])
        sell_cross = (df['ema9'].shift(1) > df['ema21'].shift(1)) & (df['ema9'] < df['ema21'])
        
        df.loc[buy_cross & df['valid_window'], 'signal'] = 1
        df.loc[sell_cross & df['valid_window'], 'signal'] = -1
        
        # Motor de Evaluación y Límite FTMO
        open_trades = []
        daily_pnl = {}
        total_trades = 0
        wins = 0
        saved_by_buffer_count = 0
        trad_sl_hit_count = 0
        
        risk_usd = 50.0 # 0.5% de $10,000
        reward_usd = 100.0 # Ratio 1:2
        
        # SL Tradicional simulado: 10 pips para EURUSD, 30 pips para XAUUSD
        base_sl_dist = 10 * pip_size if symbol == 'EURUSD' else 30 * pip_size
        
        for i in range(len(df)):
            row = df.iloc[i]
            day_str = row['time'].strftime('%Y-%m-%d')
            
            if day_str not in daily_pnl:
                daily_pnl[day_str] = 0.0
                
            # Restricción FTMO (Kill Switch Diario)
            if daily_pnl[day_str] <= -380.0:
                continue
                
            # Procesar trades abiertos
            for trade in open_trades[:]:
                # Verificar si habría tocado el SL Tradicional
                if not trade['hit_trad_sl']:
                    if trade['type'] == 'BUY' and row['low'] <= trade['sl_trad']:
                        trade['hit_trad_sl'] = True
                    elif trade['type'] == 'SELL' and row['high'] >= trade['sl_trad']:
                        trade['hit_trad_sl'] = True

                # Verificar SL Institucional y TP
                if trade['type'] == 'BUY':
                    if row['low'] <= trade['sl_inst']:
                        daily_pnl[day_str] -= risk_usd
                        if trade['hit_trad_sl']:
                            trad_sl_hit_count += 1
                        open_trades.remove(trade)
                    elif row['high'] >= trade['tp']:
                        daily_pnl[day_str] += reward_usd
                        wins += 1
                        if trade['hit_trad_sl']:
                            saved_by_buffer_count += 1
                        open_trades.remove(trade)
                else: # SELL
                    if row['high'] >= trade['sl_inst']:
                        daily_pnl[day_str] -= risk_usd
                        if trade['hit_trad_sl']:
                            trad_sl_hit_count += 1
                        open_trades.remove(trade)
                    elif row['low'] <= trade['tp']:
                        daily_pnl[day_str] += reward_usd
                        wins += 1
                        if trade['hit_trad_sl']:
                            saved_by_buffer_count += 1
                        open_trades.remove(trade)
                        
            # Abrir nuevos trades si no hay trades activos (para simplificar)
            if row['signal'] != 0 and len(open_trades) == 0:
                # Verificar si el SL tradicional cruza o toca el buffer (cálculo de entrada)
                sl_trad = row['close'] - base_sl_dist if row['signal'] == 1 else row['close'] + base_sl_dist
                sl_inst = sl_trad - row['buffer'] if row['signal'] == 1 else sl_trad + row['buffer']
                
                # Para forzar TP a ratio 1:2 usamos la distancia técnica base
                tp = row['close'] + (base_sl_dist * 2.0) if row['signal'] == 1 else row['close'] - (base_sl_dist * 2.0)
                
                open_trades.append({
                    'type': 'BUY' if row['signal'] == 1 else 'SELL',
                    'entry': row['close'],
                    'sl_trad': sl_trad,
                    'sl_inst': sl_inst,
                    'tp': tp,
                    'hit_trad_sl': False
                })
                total_trades += 1
                
        # Final calculations
        net_pnl = sum(daily_pnl.values())
        max_dd = min(daily_pnl.values()) if daily_pnl else 0.0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        
        final_report.append({
            'symbol': symbol,
            'trades': total_trades,
            'win_rate': win_rate,
            'net_pnl': net_pnl,
            'max_dd': max_dd,
            'saved_by_buffer': saved_by_buffer_count,
            'hit_sl': trad_sl_hit_count
        })
        
    print("\n" + "="*50)
    print("📊 REPORTE FINAL DEL SIMULADOR")
    print("="*50)
    
    total_net = 0.0
    for res in final_report:
        total_net += res['net_pnl']
        print(f"\nActivo: {res['symbol']}")
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
