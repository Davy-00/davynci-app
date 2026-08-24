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
    lookback: int = 10,
    min_touches: int = 3,
) -> List[TrendLine]:
    """Pivot-anchored trend lines with ATR-scaled touch tolerance.

    - Anchors are swing points (argrelextrema, order=lookback).
    - The segment between the two anchor pivots must NOT be violated
      beyond an ATR-scaled band (otherwise the "line" cuts through candles).
    - Touches after the second anchor are counted as distinct clusters
      (consecutive bars near the line count once).
    - A line needs at least `min_touches` total contacts to be reported.
    - Unbroken lines are projected to the most recent bar so the drawn
      level reflects where support/resistance sits NOW.
    """
    n = len(close)
    if n < lookback * 3:
        return []

    atr14 = atr(high, low, close, 14)
    tol = atr14.bfill().fillna(1.0) * 0.30
    atr_med = float(atr14.dropna().median()) if not atr14.dropna().empty else 1.0

    high_idx, low_idx = find_swing_points(high, low, lookback)

    def _clustered_touches(idx_start: int, idx_end: int, line_fn, series: pd.Series, kind: str) -> int:
        touches = 0
        in_cluster = False
        for t in range(idx_start, idx_end):
            expected = line_fn(t - idx_start)
            band = float(tol.iloc[t])
            v = float(series.iloc[t])
            near = abs(v - expected) <= band
            if near and not in_cluster:
                touches += 1
                in_cluster = True
            elif not near:
                in_cluster = False
        return touches

    def build(pivots: List[int], series: pd.Series, kind: str) -> List[TrendLine]:
        out: List[TrendLine] = []
        fallback: List[TrendLine] = []
        for a in range(len(pivots) - 1):
            for b in range(a + 1, len(pivots)):
                i1, i2 = pivots[a], pivots[b]
                if i2 - i1 < lookback:
                    continue
                p1, p2 = float(series.iloc[i1]), float(series.iloc[i2])
                slope = (p2 - p1) / (i2 - i1)
                if kind == 'uptrend' and slope <= 0:
                    continue
                if kind == 'downtrend' and slope >= 0:
                    continue

                # No violation between anchors (band-scaled)
                viol = False
                for t in range(i1, i2 + 1):
                    expected = p1 + slope * (t - i1)
                    band = float(tol.iloc[t])
                    v = float(series.iloc[t])
                    if kind == 'uptrend' and v < expected - band:
                        viol = True
                        break
                    if kind == 'downtrend' and v > expected + band:
                        viol = True
                        break
                if viol:
                    continue

                touches = 2 + _clustered_touches(i2 + 1, n, lambda k: p1 + slope * (i2 - i1 + k), series, kind)

                # A close beyond the line by >1.25*ATR at ANY point after
                # formation means the line was broken (not just churn/wicks).
                close_arr = close.values[i2:]
                proj_arr = p1 + slope * (np.arange(i2, n) - i1)
                bands = tol.values[i2:] * 4.17  # 0.30*ATR * 4.17 = 1.25*ATR
                pierced = (close_arr < proj_arr - bands) if kind == 'uptrend' else (close_arr > proj_arr + bands)

                proj_last = p1 + slope * (n - 1 - i1)
                band_last = float(tol.iloc[-1])
                if kind == 'uptrend':
                    is_broken = bool(pierced.any() or float(close.iloc[-1]) < proj_last - band_last)
                else:
                    is_broken = bool(pierced.any() or float(close.iloc[-1]) > proj_last + band_last)

                # Drop lines broken long ago (stale structure); keep only
                # recently broken ones so the break level stays visible.
                if is_broken:
                    if pierced.any():
                        first_pierce = i2 + int(np.argmax(pierced))
                    else:
                        first_pierce = n - 1
                    recent_window = max(30, n // 10)
                    if n - first_pierce > recent_window:
                        continue

                # Drop stale lines whose projected level is nowhere near
                # current price (>20 ATR away) — pure chart clutter.
                if abs(proj_last - float(close.iloc[-1])) > 20 * atr_med:
                    continue

                if touches < min_touches:
                    # Clean 2-point line: keep as fallback candidate only.
                    if not is_broken:
                        span_frac = (i2 - i1) / max(n - 1, 1)
                        recency = i2 / max(n - 1, 1)
                        fallback.append(TrendLine(
                            type=kind,
                            start_idx=i1,
                            end_idx=n - 1,
                            start_price=round(p1, 4),
                            end_price=round(proj_last, 4),
                            touches=touches,
                            strength=round(24 + span_frac * 30 + recency * 20, 2),
                            angle=round(float(np.degrees(np.arctan(slope))), 2),
                            is_broken=False,
                        ))
                    continue

                span_frac = (i2 - i1) / max(n - 1, 1)
                recency = i2 / max(n - 1, 1)
                strength = round(touches * 12 + span_frac * 30 + recency * 20, 2)

                out.append(TrendLine(
                    type=kind,
                    start_idx=i1,
                    end_idx=n - 1,
                    start_price=round(p1, 4),
                    end_price=round(proj_last, 4),
                    touches=touches,
                    strength=strength,
                    angle=round(float(np.degrees(np.arctan(slope))), 2),
                    is_broken=is_broken,
                ))
        return out, fallback

    up, up_fallback = build(low_idx, low, 'uptrend')
    down, down_fallback = build(high_idx, high, 'downtrend')

    def _dedup(cands: List[TrendLine]) -> List[TrendLine]:
        # Different anchor pairs on the same structure produce overlapping
        # lines. Greedily keep best (unbroken preferred, then strongest);
        # reject lines whose current level and slope closely match an
        # already-accepted one.
        kept: List[TrendLine] = []
        for tl in sorted(cands, key=lambda x: (x.is_broken, -x.strength)):
            slope_tl = (tl.end_price - tl.start_price) / max(tl.end_idx - tl.start_idx, 1)
            dup = False
            for k in kept:
                slope_k = (k.end_price - k.start_price) / max(k.end_idx - k.start_idx, 1)
                if abs(tl.end_price - k.end_price) < atr_med and \
                   abs(slope_tl - slope_k) < atr_med / 50:
                    dup = True
                    break
            if not dup:
                kept.append(tl)
        return kept

    result = _dedup(up + down)
    # If strict multi-touch detection found little structure, top up with
    # clean 2-point fallback lines so the chart isn't empty.
    if len(result) < 3:
        result = _dedup(result + up_fallback + down_fallback)

    result.sort(key=lambda x: (x.is_broken, -x.strength))
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

        trend_lines = detect_trend_lines(high, low, close, lookback=8)
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
