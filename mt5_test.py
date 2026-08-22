import MetaTrader5 as mt5

path = r"C:\Program Files\MetaTrader 5\terminal64.exe"

print("Initialize...")
r = mt5.initialize(path=path, timeout=15)
print(f"  result={r}")
if r:
    print(f"  terminal info: {mt5.terminal_info()}")
    print(f"  account info: {mt5.account_info()}")
    mt5.shutdown()
else:
    print(f"  error: {mt5.last_error()}")
    
    # Try with login credentials
    print("\nTrying with login credentials...")
    mt5.shutdown()
    r2 = mt5.initialize(
        path=path,
        login=336239416,
        password="#IMeagle2005",
        server="XMGlobal-mt5",
        timeout=15
    )
    print(f"  result={r2}")
    if r2:
        acct = mt5.account_info()
        print(f"  account: {acct.login} {acct.server}")
        print(f"  balance: {acct.balance}")
        mt5.shutdown()
    else:
        print(f"  error: {mt5.last_error()}")
        mt5.shutdown()
