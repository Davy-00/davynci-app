import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict
from oanda_client import get_oanda_client
from strategy import scan_for_signal, check_h1_trend, check_m15_pullback, check_m5_confirmation, detect_strategy_type
from indicators import calculate_all_indicators, ema_slope, is_price_near_ema
from schemas import (
    SignalDirection, Timeframe, Signal, StrategyType,
    BacktestTrade, BacktestResult, BacktestConfig,
)
from config.settings import TRADING_CONFIG
import uuid

logger = logging.getLogger(__name__)


class Backtester:
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.trades: List[BacktestTrade] = []
        self._active_trade: Optional[dict] = None

    def run(
        self,
        h1_data: pd.DataFrame,
        m15_data: pd.DataFrame,
        m5_data: pd.DataFrame,
    ) -> BacktestResult:
        self.trades = []
        self._active_trade = None

        min_len = min(len(h1_data), len(m15_data), len(m5_data))
        if min_len < 200:
            logger.warning(f"Not enough data for backtest: {min_len} bars")
            return self._build_result()

        # Align data by index
        h1 = h1_data.copy()
        m15 = m15_data.copy()
        m5 = m5_data.copy()

        # Walk through bars on M5
        for i in range(200, len(m5)):
            current_time = m5.index[i]

            # Sync M15 and H1 to current time
            m15_slice = m15.loc[m15.index <= current_time].iloc[-min(len(m15.loc[m15.index <= current_time]), 300):]
            h1_slice = h1.loc[h1.index <= current_time].iloc[-min(len(h1.loc[h1.index <= current_time]), 300):]
            m5_slice = m5.iloc[:i+1].tail(300)

            if len(m15_slice) < 100 or len(h1_slice) < 100:
                continue

            # Check active trade
            if self._active_trade is not None:
                self._check_active_trade(m5_slice, i)
                continue

            # Scan for new signal
            signal, _ = scan_for_signal(h1_slice, m15_slice, m5_slice, at_time=current_time)
            if signal:
                self._open_trade(signal, m5_slice, i)

        return self._build_result()

    def run_multi(
        self,
        h1_data: pd.DataFrame,
        m15_data: pd.DataFrame,
        m5_data: pd.DataFrame,
        param_sets: List[Dict],
    ) -> List[BacktestResult]:
        results = []
        for params in param_sets:
            old_vals = {}
            for key, val in params.items():
                if hasattr(TRADING_CONFIG, key):
                    old_vals[key] = getattr(TRADING_CONFIG, key)
                    setattr(TRADING_CONFIG, key, val)
            try:
                result = self.run(h1_data, m15_data, m5_data)
                result.trades = []  # Don't return all trades for multi runs
                results.append(result)
            finally:
                for key, val in old_vals.items():
                    setattr(TRADING_CONFIG, key, val)
        return results

    def _open_trade(self, signal: Signal, m5_slice: pd.DataFrame, bar_idx: int):
        point_value = 1.0
        entry_price = signal.entry_price
        stop_loss = signal.stop_loss
        tp1 = signal.tp1
        tp2 = signal.tp2

        self._active_trade = {
            'entry_time': signal.entry_time,
            'entry_bar': bar_idx,
            'direction': signal.direction,
            'strategy_type': signal.strategy_type,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'tp1': tp1,
            'tp2': tp2,
            'risk_pips': signal.risk_pips,
            'risk_dollars': signal.risk_dollars,
            'tp1_hit': False,
        }
        logger.info(f"Backtest OPEN: {signal.direction.value} {signal.strategy_type.value} @ {entry_price:.2f}")

    def _check_active_trade(self, m5_slice: pd.DataFrame, bar_idx: int):
        t = self._active_trade
        high = m5_slice['high'].iloc[-1]
        low = m5_slice['low'].iloc[-1]
        close = m5_slice['close'].iloc[-1]

        direction = t['direction']
        entry_price = t['entry_price']
        sl = t['stop_loss']
        tp1 = t['tp1']
        tp2 = t['tp2']

        exit_price = None
        result = None

        if direction == SignalDirection.BUY:
            if high >= tp2:
                exit_price = tp2
                result = "TP2"
            elif not t['tp1_hit'] and high >= tp1:
                t['tp1_hit'] = True
                t['stop_loss'] = entry_price
                logger.debug(f"Backtest TP1 hit @ {tp1:.2f}, SL moved to BE")
                return
            elif low <= sl:
                exit_price = sl
                result = "SL"
        else:
            if low <= tp2:
                exit_price = tp2
                result = "TP2"
            elif not t['tp1_hit'] and low <= tp1:
                t['tp1_hit'] = True
                t['stop_loss'] = entry_price
                logger.debug(f"Backtest TP1 hit @ {tp1:.2f}, SL moved to BE")
                return
            elif high >= sl:
                exit_price = sl
                result = "SL"

        if result and exit_price is not None:
            if direction == SignalDirection.BUY:
                pnl_pips = exit_price - entry_price
            else:
                pnl_pips = entry_price - exit_price

            risk_per_pip = t['risk_dollars'] / t['risk_pips'] if t['risk_pips'] > 0 else 1
            pnl_dollars = pnl_pips * risk_per_pip
            rr = abs(pnl_pips / t['risk_pips']) if t['risk_pips'] > 0 else 0

            trade = BacktestTrade(
                entry_time=t['entry_time'],
                exit_time=m5_slice.index[-1],
                direction=t['direction'],
                strategy_type=t['strategy_type'],
                entry_price=entry_price,
                exit_price=exit_price,
                stop_loss=sl,
                tp1=tp1,
                tp2=tp2,
                result=result,
                pnl_pips=round(pnl_pips, 1),
                pnl_dollars=round(pnl_dollars, 2),
                rr_achieved=round(rr, 2),
            )
            self.trades.append(trade)
            self._active_trade = None
            logger.info(f"Backtest CLOSE: {result} ${pnl_dollars:.2f} (RR {rr:.2f})")

    def _build_result(self) -> BacktestResult:
        total = len(self.trades)
        wins = [t for t in self.trades if t.pnl_dollars > 0]
        losses = [t for t in self.trades if t.pnl_dollars <= 0]
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total * 100) if total > 0 else 0
        total_pnl = sum(t.pnl_dollars for t in self.trades)

        avg_rr = np.mean([t.rr_achieved for t in self.trades]) if total > 0 else 0

        # Max drawdown (% of peak equity, relative to starting balance before first profit)
        initial = self.config.initial_balance if self.config else 5000.0
        equity = 0
        peak = 0
        max_dd = 0
        for t in self.trades:
            equity += t.pnl_dollars
            peak = max(peak, equity)
            dd_base = peak if peak > 0 else initial
            dd = (peak - equity) / dd_base * 100
            max_dd = max(max_dd, dd)

        # Profit factor
        gross_profit = sum(t.pnl_dollars for t in wins)
        gross_loss = abs(sum(t.pnl_dollars for t in losses))
        profit_factor = gross_profit / max(gross_loss, 0.01)

        # Avg bars held
        avg_bars = 0

        # By strategy breakdown
        by_strategy: Dict[str, dict] = {}
        for t in self.trades:
            key = t.strategy_type.value
            if key not in by_strategy:
                by_strategy[key] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
            by_strategy[key]['trades'] += 1
            by_strategy[key]['pnl'] += t.pnl_dollars
            if t.pnl_dollars > 0:
                by_strategy[key]['wins'] += 1

        return BacktestResult(
            total_trades=total,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=round(win_rate, 1),
            total_pnl=round(total_pnl, 2),
            avg_rr=round(avg_rr, 2),
            max_drawdown=round(max_dd, 2),
            profit_factor=round(profit_factor, 2),
            avg_bars_held=round(avg_bars, 1),
            trades=self.trades[:100],
            by_strategy=by_strategy,
        )


def fetch_backtest_data(
    bars_h1: int = 2000,
    bars_m15: int = 2000,
    bars_m5: int = 3000,
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    dc = get_oanda_client()
    if not dc.connected:
        dc.connect()
    if not dc.connected:
        logger.error("OANDA client not connected - cannot fetch backtest data")
        return None, None, None

    h1 = dc.get_candles_df(Timeframe.H1, bars_h1)
    m15 = dc.get_candles_df(Timeframe.M15, bars_m15)
    m5 = dc.get_candles_df(Timeframe.M5, bars_m5)

    return h1, m15, m5


def run_backtest(config: Optional[BacktestConfig] = None) -> BacktestResult:
    h1, m15, m5 = fetch_backtest_data()
    if h1 is None:
        return BacktestResult(
            total_trades=0, win_count=0, loss_count=0, win_rate=0,
            total_pnl=0, avg_rr=0, max_drawdown=0, profit_factor=0,
            avg_bars_held=0, trades=[], by_strategy={},
        )
    bt = Backtester(config)
    return bt.run(h1, m15, m5)


def run_multi_backtest(param_sets: List[Dict]) -> List[BacktestResult]:
    h1, m15, m5 = fetch_backtest_data()
    if h1 is None:
        return []
    bt = Backtester()
    return bt.run_multi(h1, m15, m5, param_sets)


# ---------------------------------------------------------------------------
# Fast vectorized engine: same rules as Backtester + scan_for_signal, but
# indicators are computed once on full series (higher timeframes shifted to
# completed bars) and entries are boolean masks. Trade management replicates
# the original per-bar logic: entry at signal-bar close, TP1 moves SL to BE,
# optimistic same-bar ordering TP2 > TP1 > SL, one trade at a time.
# ---------------------------------------------------------------------------

def _rolling_slope(series: pd.Series, lookback: int) -> pd.Series:
    values = series.values.astype(float)
    n = len(values)
    out = np.full(n, np.nan)
    if n < lookback:
        return pd.Series(out, index=series.index)
    x = np.arange(lookback, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    win = np.lib.stride_tricks.sliding_window_view(values, lookback)
    slopes = ((win - win.mean(axis=1, keepdims=True)) * (x - x_mean)).sum(axis=1) / denom
    out[lookback - 1:] = slopes
    return pd.Series(out, index=series.index)


def run_vector_backtest(
    h1: pd.DataFrame,
    m15: pd.DataFrame,
    m5: pd.DataFrame,
    sl_mult: float,
    tp1_rr: float,
    tp2_rr: float,
    rsi_cross_bars: int = 1,
    require_engulfing: bool = True,
    session_windows: Optional[List[tuple]] = None,
    warmup: int = 200,
    risk_dollars: float = None,
    fixed_units: Optional[float] = None,
    entry_start: Optional[datetime] = None,
    account_balance: float = None,
) -> Dict:
    from indicators import ema as _ema, rsi as _rsi, atr as _atr, detect_engulfing

    cfg = TRADING_CONFIG
    if risk_dollars is None:
        risk_dollars = cfg.account_balance * cfg.risk_per_trade_pct / 100.0
    if session_windows is None:
        session_windows = cfg.session_windows

    idx = m5.index
    hours = idx.hour.values

    def to_m5_completed(s: pd.Series) -> pd.Series:
        # last COMPLETED higher-TF bar value as of each M5 bar
        return s.shift(1).reindex(idx, method="ffill")

    # H1 trend (completed bars)
    h1_ema200 = _ema(h1["close"], 200)
    slope_tol = 1e-6
    trend_bull_h1 = (h1["close"] > h1_ema200) & (_rolling_slope(h1_ema200, cfg.ema_200_slope_lookback) > slope_tol)
    trend_bear_h1 = (h1["close"] < h1_ema200) & (_rolling_slope(h1_ema200, cfg.ema_200_slope_lookback) < -slope_tol)
    near_ema_h1 = ((h1["close"] - h1_ema200).abs() / h1_ema200 * 100) <= cfg.price_ema_threshold_pct
    trend_bull = to_m5_completed(trend_bull_h1 & ~near_ema_h1).fillna(False).values
    trend_bear = to_m5_completed(trend_bear_h1 & ~near_ema_h1).fillna(False).values

    # M15 pullback (completed bar)
    m15_ema50 = _ema(m15["close"], 50)
    pull_buy = to_m5_completed(m15["low"] <= m15_ema50).fillna(False).values
    pull_sell = to_m5_completed(m15["high"] >= m15_ema50).fillna(False).values

    # M5 features (signal bar itself)
    m5_close = m5["close"]
    engulfing = detect_engulfing(m5["open"], m5["high"], m5["low"], m5_close)
    rsi_s = _rsi(m5_close, cfg.rsi_period)
    ema21 = _ema(m5_close, 21)
    atr_s = _atr(m5["high"], m5["low"], m5_close, cfg.atr_period)

    cross_up = (rsi_s.shift(1) <= 50) & (rsi_s > 50)
    w = max(1, rsi_cross_bars)
    cross_up_recent = cross_up.rolling(w, min_periods=1).max().fillna(0).astype(bool).values
    cross_dn = (rsi_s.shift(1) >= 50) & (rsi_s < 50)
    cross_dn_recent = cross_dn.rolling(w, min_periods=1).max().fillna(0).astype(bool).values

    body_dir = (m5_close > m5["open"]).values

    in_session = np.zeros(len(idx), dtype=bool)
    for start, end in session_windows:
        in_session |= (hours >= start) & (hours < end)

    eng_ok_buy = (engulfing == 1).values if require_engulfing else body_dir
    eng_ok_sell = (engulfing == -1).values if require_engulfing else ~body_dir

    buy_mask = (
        trend_bull & pull_buy & eng_ok_buy & cross_up_recent
        & (m5_close > ema21).values & in_session
    )
    sell_mask = (
        trend_bear & pull_sell & eng_ok_sell & cross_dn_recent
        & (m5_close < ema21).values & in_session
    )

    close_a = m5_close.values
    high_a = m5["high"].values
    low_a = m5["low"].values
    atr_a = atr_s.values
    times = idx

    trades = []
    i = warmup
    n = len(idx)
    entry_start_ts = pd.Timestamp(entry_start)
    if entry_start_ts.tzinfo is None:
        entry_start_ts = entry_start_ts.tz_localize("UTC")
    else:
        entry_start_ts = entry_start_ts.tz_convert("UTC")
    while i < n:
        if buy_mask[i]:
            direction = 1
        elif sell_mask[i]:
            direction = -1
        else:
            i += 1
            continue

        if entry_start_ts is not None and times[i] < entry_start_ts:
            i += 1
            continue

        dist = sl_mult * atr_a[i]
        if not np.isfinite(dist) or dist <= 0 or not np.isfinite(close_a[i]):
            i += 1
            continue

        entry = close_a[i]
        sl = entry - direction * dist
        tp1 = entry + direction * dist * tp1_rr
        tp2 = entry + direction * dist * tp2_rr
        tp1_hit = False
        exit_price = None
        result = None

        j = i + 1
        while j < n:
            hi, lo = high_a[j], low_a[j]
            if direction == 1:
                if hi >= tp2:
                    exit_price, result = tp2, "TP2"
                    break
                if not tp1_hit and hi >= tp1:
                    tp1_hit = True
                    sl = entry
                    j += 1
                    continue
                if lo <= sl:
                    exit_price, result = sl, "SL"
                    break
            else:
                if lo <= tp2:
                    exit_price, result = tp2, "TP2"
                    break
                if not tp1_hit and lo <= tp1:
                    tp1_hit = True
                    sl = entry
                    j += 1
                    continue
                if hi >= sl:
                    exit_price, result = sl, "SL"
                    break
            j += 1

        if exit_price is None:
            break  # ran off end of data with open trade

        if fixed_units is not None:
            pnl_dollars = direction * (exit_price - entry) * fixed_units
            trade_risk = dist * fixed_units
        else:
            pnl_r = tp2_rr if result == "TP2" else (0.0 if tp1_hit else -1.0)
            pnl_dollars = pnl_r * risk_dollars
            trade_risk = risk_dollars
        rr = abs(pnl_dollars) / trade_risk if trade_risk > 0 else 0.0
        trades.append({
            "entry_time": times[i],
            "exit_time": times[j],
            "direction": "BUY" if direction == 1 else "SELL",
            "entry": round(float(entry), 2),
            "result": result,
            "pnl_dollars": round(pnl_dollars, 2),
            "rr": round(rr, 2),
        })
        i = j + 1

    # Stats
    total = len(trades)
    wins = sum(1 for t in trades if t["pnl_dollars"] > 0)
    total_pnl = sum(t["pnl_dollars"] for t in trades)
    gross_profit = sum(t["pnl_dollars"] for t in trades if t["pnl_dollars"] > 0)
    gross_loss = abs(sum(t["pnl_dollars"] for t in trades if t["pnl_dollars"] <= 0))

    equity, peak, max_dd = 0.0, 0.0, 0.0
    dd_base = account_balance or cfg.account_balance or 5000.0
    for t in trades:
        equity += t["pnl_dollars"]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / dd_base * 100)

    return {
        "total_trades": total,
        "win_count": wins,
        "win_rate": round(wins / total * 100, 1) if total else 0.0,
        "total_pnl": round(total_pnl, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_drawdown": round(max_dd, 2),
        "avg_rr": round(sum(t["rr"] for t in trades) / total, 2) if total else 0.0,
        "trades": trades,
    }
