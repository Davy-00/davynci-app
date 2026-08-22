# XAUUSD Technical Analysis & Signal Generator

A professional dark-mode Python web application for real-time gold (XAUUSD) technical analysis connected to MetaTrader 5. Features TradingView-like UI with real-time candlestick charts, multi-timeframe analysis, and automated signal generation.

## Features

- **Real-time Data**: Connects to MetaTrader 5 for live XAUUSD price data on M5, M15, and H1 timeframes
- **Professional Charts**: Dark mode TradingView-style candlestick charts with Plotly
- **Technical Indicators**: EMA 21/50/200, Bollinger Bands, RSI 14, ATR 14, Support/Resistance levels, Trend lines
- **Multi-timeframe Strategy**: EMA pullback strategy with H1 trend filter, M15 pullback detection, M5 entry confirmation
- **Signal Management**: Automatic signal generation with TP/SL tracking, daily limits, consecutive loss protection
- **Trade History**: Complete trade log with statistics (win rate, average R:R, total P&L)
- **WebSocket Updates**: Real-time price and indicator updates without page refresh

## Architecture

- **Backend**: FastAPI with WebSocket support (port 8051)
- **Frontend**: Plotly Dash with dark theme (port 8050)
- **Data**: MetaTrader 5 via `MetaTrader5` Python package
- **Calculations**: pandas/numpy for all technical indicators

## Installation

### Prerequisites
- Python 3.9+
- MetaTrader 5 installed and running on your local machine
- XAUUSD (Gold) symbol available in your MT5 broker

### Install Dependencies
```bash
pip install -r requirements.txt
```

Note: `MetaTrader5` package requires Windows. For macOS/Linux, you may need to use Wine or run in a Windows VM.

## Usage

### 1. Start MetaTrader 5
Ensure MT5 is running and you are logged into your broker account.

### 2. Start the Application
```bash
python start.py
```

This will start:
- Backend API: http://127.0.0.1:8051
- Frontend Dashboard: http://127.0.0.1:8050
- API Documentation: http://127.0.0.1:8051/docs

### 3. Access the Dashboard
Open your browser and navigate to http://127.0.0.1:8050

## Trading Strategy

### Step 1: Trend Direction Filter (H1)
- Price above 200 EMA with upward slope → BULLISH bias (only BUY signals)
- Price below 200 EMA with downward slope → BEARISH bias (only SELL signals)
- Price within 0.3% of 200 EMA or flat slope → NO signals

### Step 2: Pullback Detection (M15)
- Buy: Price pulls back and touches/wicks below 50 EMA
- Sell: Price pulls back and touches/wicks above 50 EMA

### Step 3: Entry Confirmation (M5) - BOTH must be true
- Buy: Bullish engulfing closes above 21 EMA AND RSI crosses above 50
- Sell: Bearish engulfing closes below 21 EMA AND RSI crosses below 50

### Step 4: Session Filter (GMT)
- London: 07:00-10:00 GMT
- New York: 12:00-16:00 GMT

### Signal Levels
- Stop Loss: 1.5 × ATR(14)
- TP1: 2× risk distance (1:2 R:R)
- TP2: 3× risk distance (1:3 R:R)
- Risk: $50 per trade (1% of $5000 account)

### Risk Management
- Maximum 3 signals per day
- 2 consecutive SL hits → Daily loss limit warning, pause scanning
- TP1 hit → Move SL to breakeven, continue to TP2
- Signal closes on TP2 or SL hit

## File Structure

```
davynci/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + WebSocket
│   ├── mt5_client.py        # MT5 connection
│   ├── indicators.py        # Technical indicators
│   ├── strategy.py          # Signal generation logic
│   ├── signal_manager.py    # Signal state management
│   ├── trade_history.py     # History & statistics
│   └── schemas.py           # Pydantic models
├── frontend/
│   ├── __init__.py
│   ├── app.py               # Dash app entry
│   ├── layout.py            # UI layout
│   ├── callbacks.py         # Dash callbacks
│   ├── charts.py            # Chart creation
│   └── assets/
│       └── style.css        # Custom dark theme
├── config/
│   ├── __init__.py
│   └── settings.py          # Configuration
├── data/                    # Trade history storage
├── requirements.txt
├── start.py                 # Startup script
└── README.md
```

## Configuration

Edit `config/settings.py` to customize:
- Account balance and risk percentage
- EMA periods
- Bollinger Bands settings
- Session windows
- Daily signal limits
- Consecutive loss limits

## API Endpoints

- `GET /` - API status
- `GET /api/chart/{timeframe}` - Chart data (M5, M15, H1)
- `GET /api/price` - Current live price
- `GET /api/signals` - Active and today's signals
- `GET /api/history` - Trade history and statistics
- `POST /api/signals/reset` - Reset signal manager
- `WS /ws` - WebSocket for real-time updates

## Troubleshooting

### MT5 Connection Issues
- Ensure MT5 is running before starting the app
- Check that XAUUSD symbol is available in your MT5 Market Watch
- Verify MT5 terminal is not blocked by firewall

### Package Installation Issues
- `MetaTrader5` requires Windows. On macOS, use CrossOver or Parallels.
- For `ta-lib`, you may need to install the C library first.

### Port Conflicts
- Backend uses port 8051
- Frontend uses port 8050
- Change ports in `config/settings.py` if needed

## License

MIT License

## Disclaimer

This application is for educational and analytical purposes only. Trading financial instruments carries significant risk. Past performance does not guarantee future results. Always use proper risk management and never trade with money you cannot afford to lose.