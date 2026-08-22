from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, List
import pandas as pd
import numpy as np
from indicators import (
    calculate_all_indicators, ema_slope, is_price_near_ema,
    detect_trend_lines, get_support_resistance,
)
from schemas import SignalDirection, Timeframe, Signal, StrategyType
from config.settings import TRADING_CONFIG
import uuid
import logging

logger = logging.getLogger(__name__)


def check_session_filter(at_time: Optional[datetime] = None) -> Tuple[bool, str]:
    now = at_time or datetime.now(timezone.utc)
    hour = now.hour

    for start, end in TRADING_CONFIG.session_windows:
        if start <= hour < end:
            if start == 7:
                return True, "London"
            elif start == 12:
                return True, "New York"

    next_session = ""
    for start, end in sorted(TRADING_CONFIG.session_windows):
        if hour < start:
            next_session = "London" if start == 7 else "New York"
            break
    else:
        next_session = "London"

    return False, next_session


def check_h1_trend(h1_df: pd.DataFrame) -> Tuple[Optional[SignalDirection], dict]:
    indicators = calculate_all_indicators(h1_df, 'H1')

    ema_200_val = indicators['ema_200'].iloc[-1]
    current_price = h1_df['close'].iloc[-1]

    slope = ema_slope(indicators['ema_200'], TRADING_CONFIG.ema_200_slope_lookback)
    near_ema = is_price_near_ema(current_price, ema_200_val, TRADING_CONFIG.price_ema_threshold_pct)

    info = {
        'ema_200': ema_200_val,
        'slope': slope,
        'price': current_price,
        'near_ema': near_ema,
        'bias': 'neutral',
    }

    if near_ema or abs(slope) < 1e-6:
        return None, info

    if current_price > ema_200_val and slope > 0:
        info['bias'] = 'bullish'
        return SignalDirection.BUY, info
    elif current_price < ema_200_val and slope < 0:
        info['bias'] = 'bearish'
        return SignalDirection.SELL, info

    return None, info


def detect_strategy_type(
    m15_df: pd.DataFrame,
    m5_df: pd.DataFrame,
    direction: SignalDirection,
) -> Tuple[StrategyType, dict]:
    m15_indicators = calculate_all_indicators(m15_df, 'M15')
    m5_indicators = calculate_all_indicators(m5_df, 'M5')
    h1_close = m15_indicators.get('close', m15_df['close'])

    ema_21 = m15_indicators['ema_21'].iloc[-1]
    ema_50 = m15_indicators['ema_50'].iloc[-1]
    ema_200 = m15_indicators.get('ema_200', pd.Series([0]))
    ema_200_val = ema_200.iloc[-1] if len(ema_200) > 0 else 0

    current_close = m15_df['close'].iloc[-1]
    current_low = m15_df['low'].iloc[-1]
    current_high = m15_df['high'].iloc[-1]

    m5_close = m5_df['close']
    m5_high = m5_df['high']
    m5_low = m5_df['low']

    supports = m15_indicators.get('support_levels', [])
    resistances = m15_indicators.get('resistance_levels', [])
    trend_lines = m15_indicators.get('trend_lines', [])

    details = {
        'ema_21': ema_21,
        'ema_50': ema_50,
        'ema_200': ema_200_val,
        'supports': supports[:3],
        'resistances': resistances[:3],
        'trend_lines': [tl['type'] for tl in trend_lines[:3]],
    }

    # --- BREAKOUT ---
    if direction == SignalDirection.BUY:
        recent_high = m15_df['high'].rolling(20).max().iloc[-2]
        if recent_high > 0 and current_close > recent_high * 1.001:
            nearest_resistance = None
            for r in resistances:
                if current_close > r:
                    nearest_resistance = r
                    break
            if nearest_resistance is None or current_close > nearest_resistance * 1.002:
                details['breakout_level'] = recent_high
                return StrategyType.BREAKOUT, details

    else:
        recent_low = m15_df['low'].rolling(20).min().iloc[-2]
        if recent_low > 0 and current_close < recent_low * 0.999:
            nearest_support = None
            for s in supports:
                if current_close < s:
                    nearest_support = s
                    break
            if nearest_support is None or current_close < nearest_support * 0.998:
                details['breakout_level'] = recent_low
                return StrategyType.BREAKOUT, details

    # --- BOUNCE ---
    if direction == SignalDirection.BUY and supports:
        for s in supports[:3]:
            if abs(current_low - s) / s < 0.003 and current_close > s:
                details['bounce_level'] = s
                return StrategyType.BOUNCE, details
    if direction == SignalDirection.SELL and resistances:
        for r in resistances[:3]:
            if abs(current_high - r) / r < 0.003 and current_close < r:
                details['bounce_level'] = r
                return StrategyType.BOUNCE, details

    # --- BOUNCE on trendline ---
    for tl in trend_lines[:3]:
        if direction == SignalDirection.BUY and tl['type'] == 'uptrend' and not tl['is_broken']:
            slope = (tl['end_price'] - tl['start_price']) / (tl['end_idx'] - tl['start_idx'] + 1)
            expected = tl['start_price'] + slope * (len(m15_df) - 1 - tl['start_idx'])
            if abs(current_low - expected) / expected < 0.003:
                details['trendline_bounce'] = tl
                details['bounce_level'] = expected
                return StrategyType.BOUNCE, details
        if direction == SignalDirection.SELL and tl['type'] == 'downtrend' and not tl['is_broken']:
            slope = (tl['end_price'] - tl['start_price']) / (tl['end_idx'] - tl['start_idx'] + 1)
            expected = tl['start_price'] + slope * (len(m15_df) - 1 - tl['start_idx'])
            if abs(current_high - expected) / expected < 0.003:
                details['trendline_bounce'] = tl
                details['bounce_level'] = expected
                return StrategyType.BOUNCE, details

    # --- REVERSAL ---
    m5_rsi = m5_indicators['rsi']
    m5_engulfing = m5_indicators['engulfing']
    m5_pin = m5_indicators['pin_bar']

    recent_m5_highs = m5_df['high'].rolling(10).max()
    recent_m5_lows = m5_df['low'].rolling(10).min()

    if direction == SignalDirection.BUY:
        is_oversold = (m5_rsi.iloc[-2:] < 35).any()
        is_pin = m5_pin.iloc[-1] == 1
        is_bull_engulf = m5_engulfing.iloc[-1] == 1
        at_recent_low = current_close <= recent_m5_lows.iloc[-2] * 1.002

        if (is_oversold or is_pin or is_bull_engulf) and at_recent_low:
            details['reversal_signals'] = {
                'oversold': bool(is_oversold),
                'pin_bar': bool(is_pin),
                'engulfing': bool(is_bull_engulf),
                'at_low': bool(at_recent_low),
            }
            return StrategyType.REVERSAL, details

    else:
        is_overbought = (m5_rsi.iloc[-2:] > 65).any()
        is_pin = m5_pin.iloc[-1] == -1
        is_bear_engulf = m5_engulfing.iloc[-1] == -1
        at_recent_high = current_close >= recent_m5_highs.iloc[-2] * 0.998

        if (is_overbought or is_pin or is_bear_engulf) and at_recent_high:
            details['reversal_signals'] = {
                'overbought': bool(is_overbought),
                'pin_bar': bool(is_pin),
                'engulfing': bool(is_bear_engulf),
                'at_high': bool(at_recent_high),
            }
            return StrategyType.REVERSAL, details

    # --- CONTINUATION (default when in trend + pullback) ---
    details['continuation'] = {
        'ema_trend': direction.value,
        'pullback_to_ema': abs(current_close - ema_21) / ema_21,
    }
    return StrategyType.CONTINUATION, details


def check_m15_pullback(m15_df: pd.DataFrame, direction: SignalDirection) -> Tuple[bool, dict]:
    indicators = calculate_all_indicators(m15_df, 'M15')

    ema_21 = indicators['ema_21'].iloc[-1]
    ema_50 = indicators['ema_50'].iloc[-1]
    current_price = m15_df['close'].iloc[-1]
    low = m15_df['low'].iloc[-1]
    high = m15_df['high'].iloc[-1]

    info = {'ema_21': ema_21, 'ema_50': ema_50, 'price': current_price}

    if direction == SignalDirection.BUY:
        pulled_back = low <= ema_50
        info['pulled_back'] = pulled_back
        info['condition'] = f"Low ({low:.2f}) <= EMA50 ({ema_50:.2f})"
        return pulled_back, info
    else:
        pulled_back = high >= ema_50
        info['pulled_back'] = pulled_back
        info['condition'] = f"High ({high:.2f}) >= EMA50 ({ema_50:.2f})"
        return pulled_back, info


def check_m5_confirmation(m5_df: pd.DataFrame, direction: SignalDirection) -> Tuple[bool, dict]:
    indicators = calculate_all_indicators(m5_df, 'M5')

    engulfing = indicators['engulfing'].iloc[-1]
    pin_bar = indicators['pin_bar'].iloc[-1]
    rsi_series = indicators['rsi']
    rsi = float(rsi_series.iloc[-1])
    rsi_prev = float(rsi_series.iloc[-2])
    ema_21 = indicators['ema_21'].iloc[-1]
    close = m5_df['close'].iloc[-1]
    atr_val = indicators['atr'].iloc[-1]

    bars = max(1, TRADING_CONFIG.rsi_cross_bars)
    recent_rsi = rsi_series.iloc[-(bars + 1):].reset_index(drop=True)

    info = {
        'engulfing': int(engulfing),
        'pin_bar': int(pin_bar),
        'rsi': rsi,
        'rsi_prev': rsi_prev,
        'ema_21': ema_21,
        'close': close,
        'atr': atr_val,
    }

    if direction == SignalDirection.BUY:
        pattern_ok = (
            engulfing == 1 if TRADING_CONFIG.require_engulfing
            else (close > m5_df['open'].iloc[-1])
        )
        rsi_cross_up = any(
            recent_rsi.iloc[k] <= 50 and recent_rsi.iloc[k + 1] > 50
            for k in range(len(recent_rsi) - 1)
        )
        close_above_ema = close > ema_21

        info['pattern_ok'] = bool(pattern_ok)
        info['rsi_cross_up'] = bool(rsi_cross_up)
        info['close_above_ema'] = bool(close_above_ema)

        return pattern_ok and rsi_cross_up and close_above_ema, info
    else:
        pattern_ok = (
            engulfing == -1 if TRADING_CONFIG.require_engulfing
            else (close < m5_df['open'].iloc[-1])
        )
        rsi_cross_down = any(
            recent_rsi.iloc[k] >= 50 and recent_rsi.iloc[k + 1] < 50
            for k in range(len(recent_rsi) - 1)
        )
        close_below_ema = close < ema_21

        info['pattern_ok'] = bool(pattern_ok)
        info['rsi_cross_down'] = bool(rsi_cross_down)
        info['close_below_ema'] = bool(close_below_ema)

        return pattern_ok and rsi_cross_down and close_below_ema, info


def calculate_signal_levels(
    entry_price: float,
    atr_value: float,
    direction: SignalDirection,
    account_balance: float,
    risk_pct: float,
) -> dict:
    risk_dollars = account_balance * (risk_pct / 100)
    sl_distance = atr_value * TRADING_CONFIG.sl_atr_multiplier

    if direction == SignalDirection.BUY:
        stop_loss = entry_price - sl_distance
        tp1 = entry_price + (sl_distance * TRADING_CONFIG.tp1_rr)
        tp2 = entry_price + (sl_distance * TRADING_CONFIG.tp2_rr)
    else:
        stop_loss = entry_price + sl_distance
        tp1 = entry_price - (sl_distance * TRADING_CONFIG.tp1_rr)
        tp2 = entry_price - (sl_distance * TRADING_CONFIG.tp2_rr)

    point_value = 1.0
    sl_pips = sl_distance / point_value
    lot_size = risk_dollars / (sl_pips * 10) if sl_pips > 0 else 0.01

    return {
        'stop_loss': round(stop_loss, 2),
        'tp1': round(tp1, 2),
        'tp2': round(tp2, 2),
        'risk_pips': round(sl_pips, 1),
        'risk_dollars': round(risk_dollars, 2),
        'lot_size': round(max(0.01, min(lot_size, 10.0)), 2),
        'sl_distance': sl_distance,
    }


def scan_for_signal(
    h1_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    m5_df: pd.DataFrame,
    at_time: Optional[datetime] = None,
) -> Tuple[Optional[Signal], dict]:
    debug_info = {}

    session_active, session_info = check_session_filter(at_time)
    debug_info['session'] = {'active': session_active, 'info': session_info}

    if not session_active:
        return None, debug_info

    direction, h1_info = check_h1_trend(h1_df)
    debug_info['h1'] = h1_info

    if direction is None:
        return None, debug_info

    # Detect strategy type BEFORE pullback/confirmation
    strategy_type, type_details = detect_strategy_type(m15_df, m5_df, direction)
    debug_info['strategy_type'] = {'type': strategy_type.value, 'details': type_details}

    # For BREAKOUT, we don't need pullback - just confirmation
    if strategy_type == StrategyType.BREAKOUT:
        confirm_ok, m5_info = check_m5_confirmation(m5_df, direction)
        debug_info['m5'] = m5_info
        if not confirm_ok:
            return None, debug_info
    else:
        # Standard: pullback + confirmation
        pullback_ok, m15_info = check_m15_pullback(m15_df, direction)
        debug_info['m15'] = m15_info

        if not pullback_ok:
            return None, debug_info

        confirm_ok, m5_info = check_m5_confirmation(m5_df, direction)
        debug_info['m5'] = m5_info

        if not confirm_ok:
            return None, debug_info

    entry_price = m5_df['close'].iloc[-1]
    atr_value = m5_info.get('atr', 0)

    if atr_value == 0:
        atr_indicators = calculate_all_indicators(m5_df, 'M5')
        atr_value = atr_indicators['atr'].iloc[-1]

    levels = calculate_signal_levels(
        entry_price, atr_value, direction,
        TRADING_CONFIG.account_balance, TRADING_CONFIG.risk_per_trade_pct,
    )

    signal = Signal(
        id=str(uuid.uuid4())[:8],
        direction=direction,
        strategy_type=strategy_type,
        entry_price=entry_price,
        stop_loss=levels['stop_loss'],
        tp1=levels['tp1'],
        tp2=levels['tp2'],
        risk_pips=levels['risk_pips'],
        risk_dollars=levels['risk_dollars'],
        lot_size=levels['lot_size'],
        entry_time=(at_time or datetime.now(timezone.utc)),
        strategy_details=type_details,
    )

    debug_info['signal'] = signal.model_dump()
    return signal, debug_info
