#!/usr/bin/env python3
"""Backtest the EMA pullback strategy over the past N days of OANDA XAU_USD data."""

import sys
import os
import logging

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_PROJECT_ROOT, "backend"), _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.WARNING)

from oanda_client import get_oanda_client
from backtester import Backtester
from schemas import Timeframe


def main(days: int = 90):
    client = get_oanda_client()
    if not client.connect():
        sys.exit("OANDA connection failed")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    print(f"Backtesting {client.instrument} {start.date()} -> {end.date()} ({days} days)\n")

    data = {}
    for tf in (Timeframe.H1, Timeframe.M15, Timeframe.M5):
        df = client.get_candles_range(tf, start, end)
        if df is None or len(df) < 200:
            sys.exit(f"Not enough {tf.value} data: {0 if df is None else len(df)} bars")
        data[tf] = df
        print(f"{tf.value}: {len(df)} bars [{df.index[0]} .. {df.index[-1]}]")

    print("\nRunning backtest...")
    result = Backtester().run(data[Timeframe.H1], data[Timeframe.M15], data[Timeframe.M5])

    print("\n=== RESULTS ===")
    print(f"Total trades:   {result.total_trades}")
    print(f"Wins / Losses:  {result.win_count} / {result.loss_count}")
    print(f"Win rate:       {result.win_rate}%")
    print(f"Total P&L:      ${result.total_pnl}")
    print(f"Avg R:R:        {result.avg_rr}")
    print(f"Max drawdown:   {result.max_drawdown}%")
    print(f"Profit factor:  {result.profit_factor}")

    if result.by_strategy:
        print("\nBy strategy:")
        for name, s in result.by_strategy.items():
            wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
            print(f"  {name}: {s['trades']} trades, {wr:.0f}% win, P&L ${s['pnl']:.2f}")

    if result.trades:
        print("\nLast 10 trades:")
        for t in result.trades[-10:]:
            print(f"  {t.entry_time:%Y-%m-%d %H:%M} {t.direction.value} "
                  f"{t.strategy_type.value} @ {t.entry_price:.2f} -> {t.result} "
                  f"P&L ${t.pnl_dollars:.2f} (RR {t.rr_achieved})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 90)
