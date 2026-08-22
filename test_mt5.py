import MetaTrader5 as mt5
import sys

# Try simple initialize first
r = mt5.initialize()
print(f"simple init: {r}")
if r:
    acct = mt5.account_info()
    if acct:
        print(f"Account: {acct.login} on {acct.server}")
    else:
        print("No account info")
    mt5.shutdown()
    sys.exit(0)

mt5.shutdown()

# Try with login
r = mt5.initialize(
    path=r"C:\Program Files\MetaTrader 5\terminal64.exe",
    login=336239416,
    password="#IMeagle2005",
    server="XMGlobal-mt5"
)
print(f"full init: {r}")
if r:
    acct = mt5.account_info()
    if acct:
        print(f"Account: {acct.login} on {acct.server}")
    else:
        print("No account info")
    mt5.shutdown()
    sys.exit(0)
else:
    print(f"Error: {mt5.last_error()}")

mt5.shutdown()
