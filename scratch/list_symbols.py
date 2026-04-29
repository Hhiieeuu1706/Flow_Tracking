import MetaTrader5 as mt5
import os

def list_ust10y_symbols():
    if not mt5.initialize():
        print("initialize() failed")
        return

    symbols = mt5.symbols_get()
    if symbols is None:
        print("No symbols found")
        return

    matching = [s.name for s in symbols if "UST10Y" in s.name]
    print(f"Found {len(matching)} UST10Y symbols:")
    for name in matching:
        print(f" - {name}")

    mt5.shutdown()

if __name__ == "__main__":
    list_ust10y_symbols()
