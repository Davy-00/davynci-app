import pandas as pd
import numpy as np
from typing import List, Tuple, Optional, Dict
from scipy.signal import argrelextrema
from dataclasses import dataclass
from config.settings import TRADING_CONFIG


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def find_swing_points(high: pd.Series, low: pd.Series, lookback: int = 10) -> Tuple[List[int], List[int]]:
    high_idx = argrelextrema(high.values, np.greater_equal, order=lookback)[0]
    low_idx = argrelextrema(low.values, np.less_equal, order=lookback)[0]
    return high_idx.tolist(), low_idx.tolist()


@dataclass
class TrendLine:
    type: str  # 'uptrend' or 'downtrend'
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    touches: int
    strength: float
    angle: float
    is_broken: bool


def detect_trend_lines(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lookback: int = 15,
    min_touches: int = 2,
) -> List[TrendLine]:
    high_idx, low_idx = find_swing_points(high, low, lookback)
    result: List[TrendLine] = []
    n = len(close)

    # Detect uptrend lines (connecting higher lows)
    if len(low_idx) >= 3:
        for i in range(len(low_idx) - 2):
            idx1 = low_idx[i]
            for j in range(i + 1, len(low_idx) - 1):
                idx2 = low_idx[j]
                p1, p2 = low.iloc[idx1], low.iloc[idx2]
                if p2 <= p1:
                    continue
                slope = (p2 - p1) / (idx2 - idx1)
                angle = float(np.degrees(np.arctan(slope)))
                if angle < 5 or angle > 70:
                    continue
                touches = 2
                for k in range(j + 1, len(low_idx)):
                    idx3 = low_idx[k]
                    expected = p1 + slope * (idx3 - idx1)
                    if abs(low.iloc[idx3] - expected) < 2.0:
                        touches += 1
                        idx2 = idx3
                        p2 = low.iloc[idx3]
                is_broken = bool(close.iloc[-1] < p1 + slope * (n - 1 - idx1) - 1.0)
                strength = touches / max(n - idx1, 1) * 100
                if touches >= min_touches:
                    result.append(TrendLine(
                        type='uptrend',
                        start_idx=idx1, end_idx=idx2,
                        start_price=float(p1), end_price=float(p2),
                        touches=touches, strength=round(strength, 2),
                        angle=round(angle, 1), is_broken=bool(is_broken),
                    ))

    # Detect downtrend lines (connecting lower highs)
    if len(high_idx) >= 3:
        for i in range(len(high_idx) - 2):
            idx1 = high_idx[i]
            for j in range(i + 1, len(high_idx) - 1):
                idx2 = high_idx[j]
                p1, p2 = high.iloc[idx1], high.iloc[idx2]
                if p2 >= p1:
                    continue
                slope = (p2 - p1) / (idx2 - idx1)
                angle = float(np.degrees(np.arctan(abs(slope))))
                if angle < 5 or angle > 70:
                    continue
                touches = 2
                for k in range(j + 1, len(high_idx)):
                    idx3 = high_idx[k]
                    expected = p1 + slope * (idx3 - idx1)
                    if abs(high.iloc[idx3] - expected) < 2.0:
                        touches += 1
                        idx2 = idx3
                        p2 = high.iloc[idx3]
                is_broken = bool(close.iloc[-1] > p1 + slope * (n - 1 - idx1) + 1.0)
                strength = touches / max(n - idx1, 1) * 100
                if touches >= min_touches:
                    result.append(TrendLine(
                        type='downtrend',
                        start_idx=idx1, end_idx=idx2,
                        start_price=float(p1), end_price=float(p2),
                        touches=touches, strength=round(strength, 2),
                        angle=round(angle, 1), is_broken=bool(is_broken),
                    ))

    result.sort(key=lambda x: x.strength, reverse=True)
    return result[:6]


def get_support_resistance(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lookback: int = 20,
    cluster_distance: float = 5.0,
) -> Tuple[List[float], List[float]]:
    high_idx, low_idx = find_swing_points(high, low, lookback)

    swing_highs = high.iloc[high_idx].values if high_idx else np.array([])
    swing_lows = low.iloc[low_idx].values if low_idx else np.array([])

    current_price = close.iloc[-1]

    def cluster_levels(levels: np.ndarray, dist: float) -> List[float]:
        if len(levels) == 0:
            return []
        levels = np.sort(levels)
        clusters = []
        current_cluster = [levels[0]]
        for l in levels[1:]:
            if abs(l - current_cluster[-1]) <= dist:
                current_cluster.append(l)
            else:
                clusters.append(np.mean(current_cluster))
                current_cluster = [l]
        clusters.append(np.mean(current_cluster))
        return clusters

    res = [h for h in swing_highs if h > current_price]
    sup = [l for l in swing_lows if l < current_price]

    resistances = [float(x) for x in cluster_levels(np.array(sorted(res, reverse=True)), cluster_distance)[:8]]
    supports = [float(x) for x in cluster_levels(np.array(sorted(sup)), cluster_distance)[:8]]

    return supports, resistances


def detect_engulfing(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_open = open_.shift(1)
    prev_close = close.shift(1)

    bullish = (prev_close < prev_open) & (close > open_) & (close > prev_open) & (open_ < prev_close)
    bearish = (prev_close > prev_open) & (close < open_) & (close < prev_open) & (open_ > prev_close)

    result = pd.Series(0, index=close.index)
    result[bullish] = 1
    result[bearish] = -1
    return result


def detect_pin_bar(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    body = abs(close - open_)
    upper_wick = high - np.maximum(open_, close)
    lower_wick = np.minimum(open_, close) - low
    total = high - low

    bullish_pin = (lower_wick > body * 2) & (lower_wick > upper_wick * 2) & (close > open_)
    bearish_pin = (upper_wick > body * 2) & (upper_wick > lower_wick * 2) & (close < open_)

    result = pd.Series(0, index=close.index)
    result[bullish_pin] = 1
    result[bearish_pin] = -1
    return result


def detect_breakout(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    levels: List[float],
) -> pd.Series:
    result = pd.Series(0, index=close.index)
    if not levels:
        return result
    for lvl in levels:
        bullish_break = (close > lvl) & (close.shift(1) <= lvl)
        bearish_break = (close < lvl) & (close.shift(1) >= lvl)
        result[bullish_break] = 1
        result[bearish_break] = -1
    return result


def detect_bounce(
    close: pd.Series,
    low: pd.Series,
    high: pd.Series,
    levels: List[float],
    lookback: int = 3,
) -> pd.Series:
    result = pd.Series(0, index=close.index)
    if not levels:
        return result
    for lvl in levels:
        near_support = (low <= lvl * 1.001) & (close > lvl)
        near_resistance = (high >= lvl * 0.999) & (close < lvl)
        result[near_support] = 1
        result[near_resistance] = -1
    return result


def calculate_all_indicators(df: pd.DataFrame, timeframe: str) -> dict:
    close = df['close']
    high = df['high']
    low = df['low']
    open_ = df['open']

    result = {}

    for period in TRADING_CONFIG.ema_periods:
        result[f'ema_{period}'] = ema(close, period)

    bb_upper, bb_middle, bb_lower = bollinger_bands(
        close, TRADING_CONFIG.bb_period, TRADING_CONFIG.bb_std
    )
    result['bb_upper'] = bb_upper
    result['bb_middle'] = bb_middle
    result['bb_lower'] = bb_lower

    result['rsi'] = rsi(close, TRADING_CONFIG.rsi_period)
    result['atr'] = atr(high, low, close, TRADING_CONFIG.atr_period)
    result['engulfing'] = detect_engulfing(open_, high, low, close)
    result['pin_bar'] = detect_pin_bar(open_, high, low, close)

    if timeframe == 'H1':
        supports, resistances = get_support_resistance(
            high, low, close, TRADING_CONFIG.swing_lookback
        )
        result['support_levels'] = supports
        result['resistance_levels'] = resistances

        all_lines = high.rolling(center=False, window=1).max()
        trend_lines = detect_trend_lines(high, low, close, lookback=15)
        result['trend_lines'] = [
            {
                'type': tl.type,
                'start_idx': tl.start_idx,
                'end_idx': tl.end_idx,
                'start_price': round(tl.start_price, 2),
                'end_price': round(tl.end_price, 2),
                'touches': tl.touches,
                'strength': tl.strength,
                'angle': tl.angle,
                'is_broken': tl.is_broken,
            }
            for tl in trend_lines
        ]

        result['breakout'] = detect_breakout(close, high, low, supports + resistances)
        result['bounce'] = detect_bounce(close, low, high, supports + resistances)

    return result


def ema_slope(ema_series: pd.Series, lookback: int = 10) -> float:
    if len(ema_series) < lookback:
        return 0.0
    recent = ema_series.iloc[-lookback:]
    x = np.arange(len(recent))
    y = recent.values
    slope = np.polyfit(x, y, 1)[0]
    return slope


def is_price_near_ema(price: float, ema_value: float, threshold_pct: float = 0.3) -> bool:
    if ema_value == 0:
        return False
    diff_pct = abs(price - ema_value) / ema_value * 100
    return diff_pct <= threshold_pct
