import MetaTrader5 as mt5
import time
from risk_manager import FTMORiskManager
import config

def initialize_mt5():
    """Inicializa la conexión segura con la terminal MetaTrader 5."""
    print("Iniciando conexión con MetaTrader 5...")
    
    # Intentar inicializar (con credenciales si se proveen)
    if config.MT5_ACCOUNT != 0 and config.MT5_PASSWORD != "":
        authorized = mt5.initialize(login=config.MT5_ACCOUNT, server=config.MT5_SERVER, password=config.MT5_PASSWORD)
    else:
        authorized = mt5.initialize()
        
    if not authorized:
        print(f"❌ Fallo al inicializar MT5, error code = {mt5.last_error()}")
        return False
        
    # Verificar AutoTrading
    terminal_info = mt5.terminal_info()
    if terminal_info is None:
        print("❌ No se pudo obtener información de la terminal.")
        return False
        
    if not terminal_info.trade_allowed:
        print("❌ AutoTrading está DESACTIVADO en la terminal MT5. Actívalo para continuar.")
        return False
        
    print(f"✅ Conexión establecida. Terminal Build: {terminal_info.build}")
    return True

def main():
    if not initialize_mt5():
        mt5.shutdown()
        return

    print("🤖 Bot Algorítmico Cuantitativo Iniciado.")
    risk_manager = FTMORiskManager()
    
    # Aquí puedes instanciar y almacenar tus estrategias desde config.py o de forma dinámica
    # strategies = [ Strategy1(), Strategy2() ]

    try:
        while True:
            # 1. Verificar Límites de FTMO antes de hacer nada
            is_blocked = risk_manager.update()
            
            if not is_blocked:
                # 2. Ejecutar Lógica de Estrategias
                # for strategy in strategies:
                #    strategy.evaluate()
                pass
            
            # Pausa para no consumir 100% CPU
            time.sleep(config.TICK_SLEEP)
            
    except KeyboardInterrupt:
        print("\n⏹️ Deteniendo bot por interrupción manual (Ctrl+C).")
    finally:
        mt5.shutdown()
        print("🔌 Conexión con MT5 cerrada de forma segura.")

if __name__ == "__main__":
    main()
