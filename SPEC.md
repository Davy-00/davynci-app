# XAUUSD Technical Analysis & Signal Generator - Specification

## Overview
A professional dark-mode Python web application for real-time gold (XAUUSD) technical analysis connected to MetaTrader 5. TradingView-like UI with real-time candlestick charts, multi-timeframe analysis, and automated signal generation based on a specific EMA pullback strategy.

## Architecture
- **Backend**: FastAPI with WebSocket support for real-time data push
- **Data Source**: MetaTrader 5 via `MetaTrader5` Python package
- **Indicators**: pandas/numpy calculations on backend
- **Frontend**: Plotly Dash with dark mode TradingView-style theme
- **Real-time**: WebSocket for live price/indicator updates

## MT5 Connection
- Connect to local MT5 terminal using `MetaTrader5` library
- Pull real-time OHLCV for XAUUSD on M5, M15, H1 timeframes
- Update data with each new candle
- Display live price updating every second at top of screen

## Chart Display (Main Chart - M15 default, switchable M5/M15/H1)
**Interactive**: zoomable, scrollable, resizable

**Overlays on Candlesticks:**
- EMA 21 (blue)
- EMA 50 (orange)
- EMA 200 (white)
- Bollinger Bands (20, 2) - purple with shaded fill
- Support/Resistance: horizontal lines from last 20 significant swing highs/lows on H1
  - Support: green
  - Resistance: red
- Dynamic trend lines: connecting recent higher lows (uptrend) or lower highs (downtrend)
- Signal markers:
  - Buy: green upward arrow on trigger candle
  - Sell: red downward arrow on trigger candle
  - Active signal: red dashed line at SL, green dashed lines at TP1/TP2 (labeled)

**Sub-panels (below main chart):**
- RSI 14: lines at 70/50/30
- ATR 14: volatility display

## Trading Strategy (Multi-timeframe EMA Pullback)

### Step 1: Trend Direction Filter (H1)
- 200 EMA on H1
- Bullish: price > 200 EMA AND 200 EMA sloping up → only BUY signals
- Bearish: price < 200 EMA AND 200 EMA sloping down → only SELL signals
- Neutral: price within 0.3% of 200 EMA OR flat slope → NO signals

### Step 2: Pullback Detection (M15)
- Price pulls back to zone between EMA 21 and EMA 50
- Buy: price touches/wicks below 50 EMA
- Sell: price touches/wicks above 50 EMA

### Step 3: Entry Confirmation (M5) - BOTH must be true on SAME candle
- Buy: bullish engulfing closes > 21 EMA AND RSI 14 crosses above 50
- Sell: bearish engulfing closes < 21 EMA AND RSI 14 crosses below 50

### Step 4: Session Filter (GMT)
- London: 07:00-10:00 GMT
- New York: 12:00-16:00 GMT
- No signals outside these windows

## Signal Generation & Display

**Signal Details:**
- Direction: BUY/SELL
- Entry: close of confirmation M5 candle
- SL: 1.5 × ATR(14) from entry
- TP1: 2× risk distance (1:2 R:R)
- TP2: 3× risk distance (1:3 R:R)
- Risk: $50 max (1% of $5000)
- Lot size: calculated from $50 risk / SL distance

**Signal Panel (right side):**
- All signal details
- Live floating P&L updating in real-time

**Signal Lock Rules:**
- One active signal at a time
- Signal resolves when price hits TP2 or SL → auto-close, remove lines, reset scanner
- TP1 hit: log it, move SL to breakeven, continue to TP2
- Max 3 signals/day
- 2 consecutive SL hits in same day → "Daily loss limit reached" warning, pause scanning

## Trade History & Statistics Panel

**History Log (each closed signal):**
- Date, Time, Direction, Entry, SL, TP/SL hit, P&L (pips), P&L ($), R:R achieved

**Running Statistics:**
- Total signals taken
- Win rate %
- Average R:R
- Total P&L ($)
- Current daily P&L ($)

## Technical Stack
- **Backend**: FastAPI, WebSockets, MetaTrader5, pandas, numpy
- **Frontend**: Plotly Dash, plotly.graph_objects
- **Theme**: Dark mode (#131722 bg), white/red candles, modern font
- **Deployment**: Localhost only

## File Structure
```
davynci/
├── backend/
│   ├── main.py              # FastAPI app + WebSocket
│   ├── mt5_client.py        # MT5 connection & data fetching
│   ├── indicators.py        # All indicator calculations
│   ├── strategy.py          # Signal generation logic
│   ├── signal_manager.py    # Signal state, locks, daily limits
│   ├── trade_history.py     # History & statistics
│   └── schemas.py           # Pydantic models
├── frontend/
│   ├── app.py               # Dash app
│   ├── layout.py            # UI layout
│   ├── callbacks.py         # Dash callbacks
│   ├── charts.py            # Chart creation functions
│   └── assets/
│       └── style.css        # Custom dark theme
├── config/
│   └── settings.py          # Configuration
├── tests/
│   └── test_indicators.py
├── requirements.txt
└── SPEC.md
```