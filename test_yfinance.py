import yfinance as yf
import pandas as pd

# Test XAUUSD data
ticker = "XAUUSD=X"
print(f"Testing yfinance for {ticker}...")
try:
    data = yf.download(ticker, period="5d", interval="5m", progress=False)
    print(f"Columns: {data.columns.tolist()}")
    print(f"Shape: {data.shape}")
    print(f"Last rows:\n{data.tail(3)}")
except Exception as e:
    print(f"Error: {e}")
    
# Also test GC=F (Gold Futures)
ticker2 = "GC=F"
print(f"\nTesting {ticker2}...")
try:
    data2 = yf.download(ticker2, period="5d", interval="5m", progress=False)
    print(f"Columns: {data2.columns.tolist()}")
    print(f"Shape: {data2.shape}")
    print(f"Last rows:\n{data2.tail(3)}")
except Exception as e:
    print(f"Error: {e}")
