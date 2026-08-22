#!/usr/bin/env python3
"""Grid-search strategy parameters over historical OANDA XAU_USD data."""

import sys
import os
import itertools
import logging

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_PROJECT_ROOT, "backend"), _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.ERROR)

from oanda_client import get_oanda_client
from backtester import run_vector_backtest
from schemas import Timeframe

SESSIONS = {
    "london+ny": [(7, 10), (12, 16)],
    "london": [(7, 10)],
    "ny": [(12, 16)],
    "allday": [(7, 16)],
}

BASELINE = dict(sl_mult=1.5, tp1_rr=2.0, tp2_rr=3.0, rsi_cross_bars=1,
                require_engulfing=True, session_windows=SESSIONS["london+ny"])


def main(days: int = 90, top: int = 12):
    client = get_oanda_client()
    if not client.connect():
        sys.exit("OANDA connection failed")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    print(f"Fetching {client.instrument} {start.date()} -> {end.date()}...")

    data = {}
    for tf in (Timeframe.H1, Timeframe.M15, Timeframe.M5):
        df = client.get_candles_range(tf, start, end)
        if df is None or len(df) < 200:
            sys.exit(f"Not enough {tf.value} data")
        data[tf] = df
        print(f"  {tf.value}: {len(df)} bars")

    h1, m15, m5 = data[Timeframe.H1], data[Timeframe.M15], data[Timeframe.M5]

    def run(**params):
        return run_vector_backtest(h1, m15, m5, **params)

    print("\nBaseline:", end=" ")
    base = run(**BASELINE)
    print(f"{base['total_trades']} trades, WR {base['win_rate']}%, "
          f"P&L ${base['total_pnl']}, PF {base['profit_factor']}, DD {base['max_drawdown']}%")

    grid = []
    for sl_mult, (tp1, tp2), rsi_bars, eng, sess in itertools.product(
        [1.0, 1.5, 2.0],
        [(1.5, 2.5), (2.0, 3.0), (3.0, 4.0)],
        [1, 2, 3],
        [True, False],
        list(SESSIONS.items()),
    ):
        grid.append(dict(sl_mult=sl_mult, tp1_rr=tp1, tp2_rr=tp2,
                         rsi_cross_bars=rsi_bars, require_engulfing=eng,
                         session_windows=sess[1]))

    print(f"Running {len(grid)} combinations...")
    results = []
    for params in grid:
        r = run(**params)
        results.append((params, r))

    results.sort(key=lambda x: x[1]["total_pnl"], reverse=True)

    print(f"\n{'rank':>4} {'sl':>4} {'tp1':>4} {'tp2':>4} {'rsiB':>4} {'engf':>5} "
          f"{'session':>10} {'trd':>4} {'WR%':>6} {'P&L$':>9} {'PF':>6} {'DD%':>6}")
    print("-" * 80)
    print(f"{'base':>4} {BASELINE['sl_mult']:>4} {BASELINE['tp1_rr']:>4} {BASELINE['tp2_rr']:>4} "
          f"{BASELINE['rsi_cross_bars']:>4} {str(BASELINE['require_engulfing']):>5} "
          f"{'lon+ny':>10} {base['total_trades']:>4} {base['win_rate']:>6} "
          f"{base['total_pnl']:>9} {base['profit_factor']:>6} {base['max_drawdown']:>6}")

    shown = 0
    for rank, (params, r) in enumerate(results, 1):
        if r["total_trades"] < 10:
            continue
        sess_name = next(k for k, v in SESSIONS.items() if v == params["session_windows"])
        print(f"{rank:>4} {params['sl_mult']:>4} {params['tp1_rr']:>4} {params['tp2_rr']:>4} "
              f"{params['rsi_cross_bars']:>4} {str(params['require_engulfing']):>5} "
              f"{sess_name:>10} {r['total_trades']:>4} {r['win_rate']:>6} "
              f"{r['total_pnl']:>9} {r['profit_factor']:>6} {r['max_drawdown']:>6}")
        shown += 1
        if shown >= top:
            break

    # Monthly stability for the best qualifying result
    best_params, best = results[0]
    if best["trades"]:
        sess_name = next(k for k, v in SESSIONS.items() if v == best_params["session_windows"])
        print(f"\nBest: SL={best_params['sl_mult']}xATR TP={best_params['tp1_rr']}/"
              f"{best_params['tp2_rr']} RSIbars={best_params['rsi_cross_bars']} "
              f"engulf={best_params['require_engulfing']} session={sess_name}")
        monthly = {}
        for t in best["trades"]:
            key = t["entry_time"].strftime("%Y-%m")
            m = monthly.setdefault(key, {"n": 0, "pnl": 0.0})
            m["n"] += 1
            m["pnl"] += t["pnl_dollars"]
        print("Monthly P&L:")
        for key in sorted(monthly):
            m = monthly[key]
            print(f"  {key}: {m['n']:>3} trades  ${m['pnl']:>9.2f}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 90)
