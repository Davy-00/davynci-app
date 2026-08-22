#!/usr/bin/env python3
"""
Test script for XAUUSD Technical Analysis indicators and strategy.
Uses synthetic data so it can run without MT5.
"""

import sys
import os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_PROJECT_ROOT, "backend"), _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from indicators import (
    ema, rsi, atr, bollinger_bands,
    get_support_resistance, detect_trend_lines,
    detect_engulfing, calculate_all_indicators,
    ema_slope, is_price_near_ema
)
from strategy import (
    check_session_filter, check_h1_trend,
    check_m15_pullback, check_m5_confirmation,
    calculate_signal_levels, scan_for_signal
)
from signal_manager import SignalManager
from schemas import SignalDirection


def generate_synthetic_candles(n=300, trend='up', volatility=2.0, start_price=2000.0):
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    
    prices = [start_price]
    for i in range(1, n):
        if trend == 'up':
            change = np.random.normal(0.5, volatility)
        elif trend == 'down':
            change = np.random.normal(-0.5, volatility)
        else:
            change = np.random.normal(0, volatility)
        prices.append(prices[-1] + change)
    
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    
    for price in prices:
        o = price + np.random.normal(0, volatility * 0.3)
        c = price + np.random.normal(0, volatility * 0.3)
        h = max(o, c) + abs(np.random.normal(0, volatility * 0.2))
        l = min(o, c) - abs(np.random.normal(0, volatility * 0.2))
        v = int(np.random.normal(1000, 300))
        
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(max(v, 100))
    
    times = [datetime.now(timezone.utc) - timedelta(minutes=5*(n-i)) for i in range(n)]
    
    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    }, index=times)
    
    return df


def test_indicators():
    print("Testing Indicators...")
    
    df = generate_synthetic_candles(300, 'up')
    
    # Test EMA
    ema_21 = ema(df['close'], 21)
    assert len(ema_21) == len(df), "EMA length mismatch"
    assert not ema_21.isna().all(), "EMA all NaN"
    print("  EMA: OK")
    
    # Test RSI
    rsi_14 = rsi(df['close'], 14)
    assert len(rsi_14) == len(df), "RSI length mismatch"
    assert not rsi_14.isna().all(), "RSI all NaN"
    assert rsi_14.min() >= 0 and rsi_14.max() <= 100, "RSI out of range"
    print("  RSI: OK")
    
    # Test ATR
    atr_14 = atr(df['high'], df['low'], df['close'], 14)
    assert len(atr_14) == len(df), "ATR length mismatch"
    assert not atr_14.isna().all(), "ATR all NaN"
    assert (atr_14.dropna() >= 0).all(), "ATR negative"
    print("  ATR: OK")
    
    # Test Bollinger Bands
    bb_up, bb_mid, bb_low = bollinger_bands(df['close'], 20, 2.0)
    assert len(bb_up) == len(df), "BB upper length mismatch"
    assert (bb_up.dropna() >= bb_low.dropna()).all(), "BB upper < lower"
    print("  Bollinger Bands: OK")
    
    # Test Support/Resistance
    supports, resistances = get_support_resistance(df['high'], df['low'], df['close'], 20)
    print(f"  Support levels: {len(supports)} found")
    print(f"  Resistance levels: {len(resistances)} found")
    print("  Support/Resistance: OK")
    
    # Test Engulfing
    engulfing = detect_engulfing(df['open'], df['high'], df['low'], df['close'])
    assert len(engulfing) == len(df), "Engulfing length mismatch"
    bullish_count = (engulfing == 1).sum()
    bearish_count = (engulfing == -1).sum()
    print(f"  Bullish engulfing: {bullish_count}")
    print(f"  Bearish engulfing: {bearish_count}")
    print("  Engulfing: OK")
    
    # Test EMA slope
    slope = ema_slope(ema_21, 10)
    print(f"  EMA slope: {slope:.6f}")
    print("  EMA slope: OK")
    
    # Test price near EMA
    near = is_price_near_ema(df['close'].iloc[-1], ema_21.iloc[-1], 0.3)
    print(f"  Price near EMA: {near}")
    print("  Price near EMA: OK")
    
    print("All indicator tests passed!\n")


def test_calculate_all_indicators():
    print("Testing calculate_all_indicators...")
    
    df = generate_synthetic_candles(300, 'up')
    indicators = calculate_all_indicators(df, 'M15')
    
    required_keys = ['ema_21', 'ema_50', 'ema_200', 'bb_upper', 'bb_middle', 
                     'bb_lower', 'rsi', 'atr', 'engulfing']
    for key in required_keys:
        assert key in indicators, f"Missing key: {key}"
    print(f"  Keys: {list(indicators.keys())}")
    print("  calculate_all_indicators: OK\n")


def test_strategy_logic():
    print("Testing Strategy Logic...")
    
    # Generate data with clear uptrend for bullish signal test
    h1_df = generate_synthetic_candles(200, 'up', volatility=3.0, start_price=1950.0)
    m15_df = generate_synthetic_candles(200, 'up', volatility=2.0, start_price=1980.0)
    m5_df = generate_synthetic_candles(200, 'up', volatility=1.0, start_price=1990.0)
    
    # Test H1 trend
    direction, h1_info = check_h1_trend(h1_df)
    print(f"  H1 Trend: {direction}")
    print(f"  H1 Info: {h1_info}")
    
    # Test session filter
    session_ok, session_name = check_session_filter()
    print(f"  Session active: {session_ok}, Name: {session_name}")
    
    # Test M15 pullback (may or may not trigger depending on data)
    if direction:
        pullback_ok, m15_info = check_m15_pullback(m15_df, direction)
        print(f"  M15 Pullback: {pullback_ok}")
        print(f"  M15 Info: {m15_info}")
    
    # Test M5 confirmation
    if direction:
        confirm_ok, m5_info = check_m5_confirmation(m5_df, direction)
        print(f"  M5 Confirmation: {confirm_ok}")
        print(f"  M5 Info keys: {list(m5_info.keys())}")
    
    # Test signal levels calculation
    atr_val = calculate_all_indicators(m5_df, 'M5')['atr'].iloc[-1]
    levels = calculate_signal_levels(
        m5_df['close'].iloc[-1],
        atr_val,
        SignalDirection.BUY,
        5000.0,
        1.0
    )
    print(f"  Signal levels: {levels}")
    
    print("Strategy logic tests completed!\n")


def test_signal_manager():
    print("Testing Signal Manager...")
    
    manager = SignalManager()
    assert manager.can_generate_signal(), "Should be able to generate signal initially"
    print("  Initial state: OK")
    
    # Simulate adding a signal
    from backend.schemas import Signal
    signal = Signal(
        id="TEST001",
        direction=SignalDirection.BUY,
        entry_price=2000.0,
        stop_loss=1995.0,
        tp1=2010.0,
        tp2=2015.0,
        risk_pips=50.0,
        risk_dollars=50.0,
        lot_size=0.1,
        entry_time=datetime.now(timezone.utc),
    )
    
    manager.add_signal(signal)
    assert not manager.can_generate_signal(), "Should not generate while active signal exists"
    print("  Signal lock: OK")
    
    # Simulate TP hit
    manager.check_tp_sl(2015.0)
    assert manager.get_active_signal() is None, "Signal should be closed"
    assert manager.can_generate_signal(), "Should be able to generate after close"
    print("  TP close: OK")
    
    print("Signal manager tests passed!\n")


def test_full_scan():
    print("Testing Full Signal Scan...")
    
    # This may or may not generate a signal depending on synthetic data
    h1_df = generate_synthetic_candles(300, 'up', volatility=3.0, start_price=1950.0)
    m15_df = generate_synthetic_candles(300, 'up', volatility=2.0, start_price=1980.0)
    m5_df = generate_synthetic_candles(300, 'up', volatility=1.0, start_price=1990.0)
    
    signal, debug_info = scan_for_signal(h1_df, m15_df, m5_df)
    
    if signal:
        print(f"  Signal generated: {signal.direction} @ {signal.entry_price:.2f}")
        print(f"  SL: {signal.stop_loss:.2f}, TP1: {signal.tp1:.2f}, TP2: {signal.tp2:.2f}")
        print(f"  Risk: ${signal.risk_dollars:.2f}, Lot: {signal.lot_size:.2f}")
    else:
        print("  No signal generated (expected with random data)")
        print(f"  Debug: {list(debug_info.keys())}")
    
    print("Full scan test completed!\n")


def main():
    print("=" * 60)
    print("XAUUSD Technical Analysis - Unit Tests")
    print("=" * 60)
    print()
    
    try:
        test_indicators()
        test_calculate_all_indicators()
        test_strategy_logic()
        test_signal_manager()
        test_full_scan()
        
        print("=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())