import asyncio
import json
import logging
import os
import sys
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (_BACKEND_DIR, os.path.dirname(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from oanda_client import OandaClient
from oanda_stream import get_price_stream
from strategy import scan_for_signal, check_session_filter
from signal_manager import SignalManager
from trade_history import trade_history
from telegram_notifier import send_telegram, format_new_signal, format_signal_closed
from session_notifier import session_watch_loop, announce_if_session_active, send_alert
from ai_analyst import ai_configured, analyze_chart, GEMINI_MODEL
from schemas import Timeframe, LivePrice, Signal, StrategyType, BacktestConfig
from indicators import calculate_all_indicators, ema_slope, is_price_near_ema, detect_trend_lines
from backtester import run_backtest, run_multi_backtest, run_vector_backtest
from config.settings import APP_CONFIG, TRADING_CONFIG, TELEGRAM_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="XAUUSD Technical Analysis")

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

@app.get("/chart")
async def serve_chart_widget():
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(_STATIC_DIR, "chart.html"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

signal_manager = SignalManager()
active_connections: list[WebSocket] = []


def serialize_for_json(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    return str(obj)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        return serialize_for_json(obj)


def signal_to_dict(signal: Optional[Signal]) -> Optional[dict]:
    if signal is None:
        return None
    return signal.model_dump()


def compute_simple_analysis(h1_df: pd.DataFrame, m15_df: pd.DataFrame, m5_df: pd.DataFrame) -> dict:
    try:
        h1_close = h1_df['close']
        m15_close = m15_df['close']
        m5_close = m5_df['close']

        h1_indicators = calculate_all_indicators(h1_df, 'H1')
        m15_indicators = calculate_all_indicators(m15_df, 'M15')
        m5_indicators = calculate_all_indicators(m5_df, 'M5')

        # -- H1 Trend --
        h1_ema200 = float(h1_indicators['ema_200'].iloc[-1])
        h1_ema50 = float(h1_indicators['ema_50'].iloc[-1])
        h1_last = float(h1_close.iloc[-1])
        price_vs_ema200 = "above" if h1_last > h1_ema200 else "below"
        slope = float(ema_slope(h1_indicators['ema_200'], 10))
        if slope > 0.5:
            h1_trend = "UPTREND"
        elif slope < -0.5:
            h1_trend = "DOWNTREND"
        else:
            h1_trend = "SIDEWAYS"

        # -- M15 --
        m15_ema21 = float(m15_indicators['ema_21'].iloc[-1])
        m15_ema50 = float(m15_indicators['ema_50'].iloc[-1])
        m15_price = float(m15_close.iloc[-1])
        near_ema21 = bool(is_price_near_ema(m15_price, m15_ema21, 0.5))
        near_ema50 = bool(is_price_near_ema(m15_price, m15_ema50, 0.5))
        m15_slope = float(ema_slope(m15_indicators['ema_21'], 5))

        # -- M5 --
        m5_rsi = float(m5_indicators['rsi'].iloc[-1])
        m5_ema21 = float(m5_indicators['ema_21'].iloc[-1])
        m5_price = float(m5_close.iloc[-1])
        m5_trend = "BULL" if m5_price > m5_ema21 else "BEAR"

        # -- RSI --
        rsi_val = float(m15_indicators['rsi'].iloc[-1])
        if rsi_val > 70:
            rsi_status = "OVBOUGHT"
        elif rsi_val < 30:
            rsi_status = "OVSOLD"
        elif rsi_val > 60:
            rsi_status = "BULLISH"
        elif rsi_val < 40:
            rsi_status = "BEARISH"
        else:
            rsi_status = "NEUTRAL"

        # -- Volatility --
        atr_val = float(m15_indicators['atr'].iloc[-1])
        atr_pct = atr_val / m15_price * 100 if m15_price else 0
        if atr_pct > 0.5:
            vol = "HIGH"
        elif atr_pct > 0.2:
            vol = "MEDIUM"
        else:
            vol = "LOW"

        # -- Patterns --
        m5_engulf = int(m5_indicators['engulfing'].iloc[-1])
        m5_pin = int(m5_indicators['pin_bar'].iloc[-1])
        pattern = "NONE"
        if m5_engulf == 1:
            pattern = "BULL_ENGULF"
        elif m5_engulf == -1:
            pattern = "BEAR_ENGULF"
        elif m5_pin == 1:
            pattern = "BULL_PIN"
        elif m5_pin == -1:
            pattern = "BEAR_PIN"

        # -- Support/Resistance proximity --
        supports = h1_indicators.get('support_levels', [])
        resistances = h1_indicators.get('resistance_levels', [])
        nearest_support = min(supports, key=lambda x: abs(x - m15_price)) if supports else None
        nearest_resistance = min(resistances, key=lambda x: abs(x - m15_price)) if resistances else None
        dist_to_support = abs(m15_price - nearest_support) / m15_price * 100 if nearest_support else None
        dist_to_resistance = abs(m15_price - nearest_resistance) / m15_price * 100 if nearest_resistance else None

        # -- Build narrative --
        lines = []

        # Price action summary
        ema_position = "above" if m15_price > m15_ema50 else "below"
        lines.append(f"Price is {ema_position} the M15 EMA50, trading at ${m15_price:.2f}.")

        # Trend description
        if h1_trend == "UPTREND":
            lines.append(f"H1 trend is UP (EMA200 slope: {slope:.1f}). Higher timeframe favors longs.")
        elif h1_trend == "DOWNTREND":
            lines.append(f"H1 trend is DOWN (EMA200 slope: {slope:.1f}). Higher timeframe favors shorts.")
        else:
            lines.append(f"H1 is sideways (EMA200 slope: {slope:.1f}). No clear directional bias on higher TF.")

        # Pullback / EMA touch
        if near_ema21:
            lines.append(f"Price is at M15 EMA21 — potential pullback completion point.")
        if near_ema50:
            lines.append(f"Price is near M15 EMA50 — key support/resistance zone.")

        # RSI
        if rsi_status == "OVBOUGHT":
            lines.append(f"M15 RSI is {rsi_val:.0f} (overbought). Caution on longs.")
        elif rsi_status == "OVSOLD":
            lines.append(f"M15 RSI is {rsi_val:.0f} (oversold). Caution on shorts.")
        else:
            lines.append(f"M15 RSI is {rsi_val:.0f} ({rsi_status}).")

        # Pattern
        pattern_desc = {
            "BULL_ENGULF": "Bullish engulfing pattern detected on M5",
            "BEAR_ENGULF": "Bearish engulfing pattern detected on M5",
            "BULL_PIN": "Bullish pin bar detected on M5",
            "BEAR_PIN": "Bearish pin bar detected on M5",
        }
        if pattern != "NONE":
            lines.append(f"{pattern_desc[pattern]} — confirms momentum.")

        # Volatility
        lines.append(f"Volatility: {vol} (ATR {atr_val:.2f}, {atr_pct:.1f}% of price).")

        # Session
        session_active, session_name = check_session_filter()
        if session_active:
            lines.append(f"{session_name} session active — good liquidity conditions.")
        else:
            lines.append("Outside major session — spreads may be wider.")

        # -- Setup evaluation --
        setup_lines = []
        buy_score = 0
        sell_score = 0

        if h1_trend == "UPTREND":
            buy_score += 2
            setup_lines.append("+ H1 trend is up")
        elif h1_trend == "DOWNTREND":
            sell_score += 2
            setup_lines.append("+ H1 trend is down")

        if near_ema21 and h1_trend == "UPTREND":
            buy_score += 2
            setup_lines.append("+ Pullback to M15 EMA21 in uptrend (continuation setup)")
        elif near_ema21 and h1_trend == "DOWNTREND":
            sell_score += 2
            setup_lines.append("+ Retrace to M15 EMA21 in downtrend (continuation setup)")

        if rsi_status == "BULLISH":
            buy_score += 1
        elif rsi_status == "BEARISH":
            sell_score += 1

        if pattern == "BULL_ENGULF" or pattern == "BULL_PIN":
            buy_score += 1
        elif pattern == "BEAR_ENGULF" or pattern == "BEAR_PIN":
            sell_score += 1

        if nearest_support and dist_to_support and dist_to_support < 0.5:
            setup_lines.append(f"+ Price near support ${nearest_support:.2f} ({dist_to_support:.2f}% away)")
            buy_score += 1
        if nearest_resistance and dist_to_resistance and dist_to_resistance < 0.5:
            setup_lines.append(f"+ Price near resistance ${nearest_resistance:.2f} ({dist_to_resistance:.2f}% away)")
            sell_score += 1

        vol_warning = ""
        if atr_pct < 0.1:
            setup_lines.append("- Very low volatility — breakout may be imminent but no confirmation yet")
        elif atr_pct > 1.0:
            setup_lines.append("- High volatility — wider stops required")

        if m5_trend == "BEAR" and buy_score > sell_score:
            setup_lines.append("- M5 is bearish (below EMA21) — conflicting with bullish bias")
        elif m5_trend == "BULL" and sell_score > buy_score:
            setup_lines.append("- M5 is bullish (above EMA21) — conflicting with bearish bias")

        if rsi_status == "OVBOUGHT" and buy_score > sell_score:
            setup_lines.append("- RSI overbought — limited upside potential")
        elif rsi_status == "OVSOLD" and sell_score > buy_score:
            setup_lines.append("- RSI oversold — limited downside potential")

        conclusion = ""
        if buy_score >= 3 and buy_score > sell_score:
            conclusion = f"BULLISH SETUP (score {buy_score}-{sell_score})"
        elif sell_score >= 3 and sell_score > buy_score:
            conclusion = f"BEARISH SETUP (score {sell_score}-{buy_score})"
        elif buy_score == sell_score:
            conclusion = f"NEUTRAL — no clear edge ({buy_score}-{sell_score})"
        else:
            conclusion = f"WAIT — score too low (buy {buy_score}, sell {sell_score})"

        narrative = "\n".join(lines)
        setup_text = "\n".join(setup_lines) if setup_lines else "No clear setup factors."

        return {
            "narrative": narrative,
            "setup": setup_text,
            "conclusion": conclusion,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "h1": {"trend": h1_trend, "price_vs_ema200": price_vs_ema200, "ema200_slope": round(slope, 2)},
            "m15": {"near_ema21": near_ema21, "ema21_slope": round(m15_slope, 2), "rsi": round(rsi_val, 1), "rsi_status": rsi_status},
            "m5": {"trend": m5_trend, "rsi": round(m5_rsi, 1), "pattern": pattern},
            "volatility": vol,
        }
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        return {}


def generate_trade_suggestion(analysis: dict, tf_df: pd.DataFrame, live_price: Optional[LivePrice]) -> Optional[dict]:
    conclusion = analysis.get("conclusion", "")
    buy_score = analysis.get("buy_score", 0)
    sell_score = analysis.get("sell_score", 0)
    
    if "BULLISH" in conclusion and buy_score >= 3:
        direction = "BUY"
        side = "Long"
    elif "BEARISH" in conclusion and sell_score >= 3:
        direction = "SELL"
        side = "Short"
    else:
        return None
    
    entry = live_price.bid if live_price else (tf_df['close'].iloc[-1] if tf_df is not None and not tf_df.empty else None)
    if entry is None:
        return None
    
    atr_series = calculate_all_indicators(tf_df, 'M15').get('atr', pd.Series([0]))
    atr_val = float(atr_series.iloc[-1]) if len(atr_series) > 0 else 0
    if atr_val == 0:
        atr_val = entry * 0.005  # fallback: 0.5% of price
    
    sl_dist = atr_val * 1.5
    
    if direction == "BUY":
        sl = entry - sl_dist
        tp1 = entry + sl_dist * 2.0
        tp2 = entry + sl_dist * 3.0
    else:
        sl = entry + sl_dist
        tp1 = entry - sl_dist * 2.0
        tp2 = entry - sl_dist * 3.0
    
    risk = abs(entry - sl)
    rr1 = abs(tp1 - entry) / risk if risk > 0 else 0
    rr2 = abs(tp2 - entry) / risk if risk > 0 else 0
    
    return {
        "direction": direction,
        "side": side,
        "entry": round(entry, 2),
        "stop_loss": round(sl, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "risk": round(risk, 2),
        "rr1": round(rr1, 2),
        "rr2": round(rr2, 2),
        "bias_score": f"{buy_score}-{sell_score}",
        "reasoning": analysis.get("narrative", "").split("\n")[:3],
    }


def calculate_chart_data(timeframe: Timeframe = Timeframe.M15) -> dict:
    dc = get_data_client()
    
    try:
        h1_df = dc.get_candles_df(Timeframe.H1, APP_CONFIG.candle_history_bars)
        m15_df = dc.get_candles_df(Timeframe.M15, APP_CONFIG.candle_history_bars)
        m5_df = dc.get_candles_df(Timeframe.M5, APP_CONFIG.candle_history_bars)

        def _normalize(df):
            if df is not None and not df.empty:
                df.columns = df.columns.str.lower()
            return df

        h1_df = _normalize(h1_df)
        m15_df = _normalize(m15_df)
        m5_df = _normalize(m5_df)

        if any(d is None or d.empty or 'close' not in d.columns for d in (h1_df, m15_df, m5_df)):
            return {
                "error": "No data available",
                "offline": True,
                "candles": [],
                "indicators": {},
                "analysis": {"conclusion": "Waiting for OANDA data...", "narrative": ""},
                "suggested_trade": None,
            }
        
        current_tf_df = dc.get_candles_df(timeframe, APP_CONFIG.candle_history_bars)
        if current_tf_df is None or current_tf_df.empty:
            return {"error": "Failed to fetch current timeframe data"}

        current_tf_df = _normalize(current_tf_df)
        if 'close' not in current_tf_df.columns:
            return {"error": "No data available"}

        current_tf_indicators = calculate_all_indicators(current_tf_df, timeframe.value)
        
        current_tf_indicators = calculate_all_indicators(current_tf_df, timeframe.value)
        
        candles = []
        for idx, row in current_tf_df.tail(200).iterrows():
            candles.append({
                "time": idx.isoformat(),
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "volume": int(row['volume']),
            })
        
        indicators_dict = {}
        for key, value in current_tf_indicators.items():
            if isinstance(value, dict):
                if 'points' in value:
                    indicators_dict[key] = value
                else:
                    indicators_dict[key] = value
            elif isinstance(value, pd.Series):
                indicators_dict[key] = value.tail(200).tolist()
            elif isinstance(value, list):
                indicators_dict[key] = value
            else:
                indicators_dict[key] = value
        
        h1_indicators = calculate_all_indicators(h1_df, 'H1')
        if 'support_levels' in h1_indicators:
            indicators_dict['support_levels'] = h1_indicators['support_levels']
        if 'resistance_levels' in h1_indicators:
            indicators_dict['resistance_levels'] = h1_indicators['resistance_levels']

        # Trend lines drawn on the DISPLAYED timeframe, indices rebased to the
        # tail(200) window the frontend receives (partial lines clipped).
        offset = max(0, len(current_tf_df) - 200)
        raw_lines = detect_trend_lines(
            current_tf_df["high"], current_tf_df["low"], current_tf_df["close"],
            lookback=15,
        )
        draw_lines = []
        for tl in raw_lines:
            s_i, e_i = int(tl.start_idx), int(tl.end_idx)
            span = max(1, e_i - s_i)
            slope = (tl.end_price - tl.start_price) / span

            def _price_at(local_i):
                return tl.start_price + slope * local_i

            cs, ce = max(s_i - offset, 0), min(e_i - offset, 199)
            if ce <= cs:
                continue
            draw_lines.append({
                "type": tl.type,
                "start_idx": cs,
                "end_idx": ce,
                "start_price": round(float(_price_at(cs)), 2),
                "end_price": round(float(_price_at(ce)), 2),
                "touches": tl.touches,
                "strength": tl.strength,
                "angle": tl.angle,
                "is_broken": tl.is_broken,
            })
        indicators_dict['trend_lines'] = draw_lines
        if 'breakout' in h1_indicators:
            indicators_dict['breakout'] = h1_indicators['breakout'].tail(200).tolist()
        if 'bounce' in h1_indicators:
            indicators_dict['bounce'] = h1_indicators['bounce'].tail(200).tolist()
        
        live_price = dc.get_live_price()
        price_dict = None
        if live_price:
            price_dict = {
                "symbol": live_price.symbol,
                "bid": live_price.bid,
                "ask": live_price.ask,
                "spread": round(live_price.spread, 2),
                "time": live_price.time.isoformat(),
            }
        
        session_active, session_name = check_session_filter()
        session_info = {
            "is_active": session_active,
            "current_session": session_name if session_active else "None",
            "next_session": session_name if not session_active else "",
        }
        
        active_signal = signal_manager.get_active_signal()
        if active_signal and live_price:
            signal_manager.update_signal_pnl(live_price.bid)
            hit = signal_manager.check_tp_sl(live_price.bid)
        
        stats = trade_history.get_statistics()
        history_trades = trade_history.get_all_trades()
        analysis = compute_simple_analysis(h1_df, m15_df, m5_df)
        
        # Generate trade suggestion from analysis
        suggested_trade = generate_trade_suggestion(analysis, current_tf_df, live_price)
        
        source = dc.get_data_source_label() if hasattr(dc, 'get_data_source_label') else type(dc).__name__
        instrument = "XAUUSD"
        return {
            "candles": candles,
            "indicators": indicators_dict,
            "signals": [signal_to_dict(active_signal)] if active_signal else [],
            "current_price": price_dict,
            "timeframe": timeframe.value,
            "session_info": session_info,
            "signal_status": signal_manager.get_status(),
            "statistics": stats.model_dump(),
            "trade_history": [t.model_dump() for t in history_trades],
            "analysis": analysis,
            "suggested_trade": suggested_trade,
            "data_source": source,
            "instrument": instrument,
        }
    except Exception as e:
        logger.error(f"Error calculating chart data: {e}")
        return {"error": str(e)}


async def scan_and_generate_signals():
    if not signal_manager.can_generate_signal():
        return
    
    dc = get_data_client()
    
    try:
        h1_df = dc.get_candles_df(Timeframe.H1, 200)
        m15_df = dc.get_candles_df(Timeframe.M15, 200)
        m5_df = dc.get_candles_df(Timeframe.M5, 200)
        
        if h1_df is None or m15_df is None or m5_df is None:
            return
        
        signal, debug_info = scan_for_signal(h1_df, m15_df, m5_df)
        
        if signal:
            signal_manager.add_signal(signal)
            logger.info(f"New signal generated: {signal.direction} @ {signal.entry_price:.2f}")
            await broadcast_message({
                "type": "NEW_SIGNAL",
                "signal": signal_to_dict(signal),
            })
            await send_telegram(format_new_signal(signal))
    except Exception as e:
        logger.error(f"Error scanning for signals: {e}")


async def broadcast_message(message: dict):
    disconnected = []
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception:
            disconnected.append(connection)
    
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)


async def data_updater():
    while True:
        try:
            await scan_and_generate_signals()
            
            data = calculate_chart_data(Timeframe.M15)
            await broadcast_message({
                "type": "UPDATE",
                "data": data,
            })
            
            await asyncio.sleep(APP_CONFIG.chart_update_interval_ms / 1000)
        except Exception as e:
            logger.error(f"Error in data updater: {e}")
            await asyncio.sleep(5)


_data_client = None

def get_data_client():
    global _data_client
    if _data_client is not None:
        return _data_client
    client = OandaClient()
    if client.connect():
        logger.info(f"Data source: {client.get_data_source_label()}")
        _data_client = client
        return _data_client
    logger.error("OANDA connection failed. Check OANDA_API_TOKEN / OANDA_ACCOUNT_ID in .env.")
    _data_client = client  # connected=False
    return _data_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    dc = get_data_client()
    logger.info(f"Data source: {dc.get_data_source_label() if hasattr(dc, 'get_data_source_label') else type(dc).__name__}")

    stream = get_price_stream()
    stream.start()

    asyncio.create_task(data_updater())
    startup_alert = announce_if_session_active(TRADING_CONFIG.session_windows)
    if startup_alert:
        asyncio.create_task(send_alert(startup_alert))
        logger.info("Startup session alert queued")
    session_task = asyncio.create_task(
        session_watch_loop(TRADING_CONFIG.session_windows)
    )

    yield
    session_task.cancel()
    stream.stop()
    if dc.connected:
        dc.disconnect()
        logger.info("Data source disconnected")

app.router.lifespan_context = lifespan


@app.get("/")
async def root():
    dc = get_data_client()
    return {"status": "XAUUSD Technical Analysis API", "data_connected": dc.connected}


@app.get("/api/chart/{timeframe}")
async def get_chart(timeframe: str):
    try:
        tf = Timeframe(timeframe.upper())
    except ValueError:
        return {"error": "Invalid timeframe. Use M5, M15, or H1"}
    
    return calculate_chart_data(tf)


@app.get("/api/price")
async def get_price():
    dc = get_data_client()
    price = dc.get_live_price()
    if price:
        return price.model_dump()
    return {"error": "Failed to get price"}


@app.get("/api/stream/status")
async def stream_status():
    return get_price_stream().get_status()


@app.get("/api/signals")
async def get_signals():
    active = signal_manager.get_active_signal()
    today = signal_manager.get_signals_today()
    return {
        "active": signal_to_dict(active),
        "today": [signal_to_dict(s) for s in today],
        "status": signal_manager.get_status(),
    }


@app.get("/api/history")
async def get_history():
    trades = trade_history.get_all_trades()
    stats = trade_history.get_statistics()
    return {
        "trades": [t.model_dump() for t in trades],
        "statistics": stats.model_dump(),
    }


@app.post("/api/signals/reset")
async def reset_signals():
    signal_manager.reset()
    return {"status": "Signals reset"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"WebSocket client connected. Total: {len(active_connections)}")
    
    try:
        data = calculate_chart_data(Timeframe.M15)
        await websocket.send_json({
            "type": "INIT",
            "data": data,
        })
        
        while True:
            message = await websocket.receive_text()
            try:
                msg = json.loads(message)
                msg_type = msg.get("type", "")
                
                if msg_type == "SUBSCRIBE":
                    tf = msg.get("timeframe", "M15")
                    try:
                        timeframe = Timeframe(tf.upper())
                        data = calculate_chart_data(timeframe)
                        await websocket.send_json({
                            "type": "UPDATE",
                            "data": data,
                        })
                    except ValueError:
                        await websocket.send_json({"type": "ERROR", "message": "Invalid timeframe"})
                
                elif msg_type == "PING":
                    await websocket.send_json({"type": "PONG"})
            
            except json.JSONDecodeError:
                await websocket.send_json({"type": "ERROR", "message": "Invalid JSON"})
    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)


def on_signal_closed(signal: Signal):
    trade_history.add_trade(signal)
    asyncio.create_task(broadcast_message({
        "type": "SIGNAL_CLOSED",
        "signal": signal_to_dict(signal),
    }))
    asyncio.create_task(send_telegram(format_signal_closed(signal)))


signal_manager.on_signal_closed(on_signal_closed)


@app.post("/api/telegram/test")
async def telegram_test():
    if not TELEGRAM_CONFIG.enabled:
        raise HTTPException(status_code=503, detail="Telegram not configured")
    await send_telegram("\U00002705 DAvynci backend online \u2014 signal alerts active.")
    return {"sent": True}


class AIAnalyzeRequest(BaseModel):
    timeframe: str = Field(default="M15", pattern="^(M5|M15|H1)$")
    question: Optional[str] = Field(default=None, max_length=500)


@app.get("/api/ai/status")
async def ai_status():
    return {"configured": ai_configured(), "model": GEMINI_MODEL}


@app.post("/api/ai/analyze")
async def ai_analyze(request: AIAnalyzeRequest):
    if not ai_configured():
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured")
    chart_data = calculate_chart_data(Timeframe(request.timeframe))
    if "error" in chart_data:
        raise HTTPException(status_code=502, detail=f"Market data unavailable: {chart_data['error']}")
    result = analyze_chart(chart_data, request.question)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


class BacktestRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    account_balance: Optional[float] = Field(default=None, gt=0)
    fixed_units: Optional[float] = Field(default=None, gt=0)


def _fetch_backtest_frames(days: int):
    """Fetch H1/M15/M5 frames covering `days` + indicator warmup."""
    dc = get_data_client()
    if not dc.connected:
        return None, None, None
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days + 15)  # 15d warmup for H1 EMA200/slope
    h1 = dc.get_candles_range(Timeframe.H1, start, now)
    m15 = dc.get_candles_range(Timeframe.M15, start, now)
    m5 = dc.get_candles_range(Timeframe.M5, start, now)
    if h1 is None or m15 is None or m5 is None:
        return None, None, None
    return h1, m15, m5


def _vector_result_to_response(res: dict, by_strategy: bool = True) -> dict:
    pf = res.get("profit_factor", 0.0)
    wins = res.get("win_count", 0)
    losses = res.get("total_trades", 0) - wins
    out = {
        "total_trades": res.get("total_trades", 0),
        "win_count": wins,
        "loss_count": losses,
        "win_rate": res.get("win_rate", 0.0),
        "total_pnl": res.get("total_pnl", 0.0),
        "avg_rr": res.get("avg_rr", 0.0),
        "max_drawdown": res.get("max_drawdown", 0.0),
        "profit_factor": min(pf, 999.99) if pf == float("inf") else pf,
        "avg_bars_held": 0.0,
        "trades": [
            {
                "entry_time": str(t["entry_time"]),
                "exit_time": str(t.get("exit_time")),
                "direction": t["direction"],
                "entry": t["entry"],
                "result": t["result"],
                "pnl_dollars": t["pnl_dollars"],
                "rr_achieved": t["rr"],
            }
            for t in res.get("trades", [])
        ],
        "by_strategy": {},
    }
    if by_strategy and out["total_trades"]:
        out["by_strategy"] = {
            "ema_pullback": {
                "trades": out["total_trades"],
                "wins": wins,
                "pnl": out["total_pnl"],
            }
        }
    return out


@app.post("/api/backtest")
async def backtest(request: Optional[BacktestRequest] = None):
    req = request or BacktestRequest()
    cfg = TRADING_CONFIG
    balance = req.account_balance or cfg.account_balance
    risk_dollars = (
        balance * cfg.risk_per_trade_pct / 100.0
        if req.fixed_units is None
        else None
    )
    h1, m15, m5 = _fetch_backtest_frames(req.days)
    if h1 is None:
        raise HTTPException(status_code=503, detail="Data source unavailable")
    entry_start = datetime.now(timezone.utc) - timedelta(days=req.days)
    res = run_vector_backtest(
        h1, m15, m5,
        sl_mult=cfg.sl_atr_multiplier,
        tp1_rr=cfg.tp1_rr,
        tp2_rr=cfg.tp2_rr,
        rsi_cross_bars=cfg.rsi_cross_bars,
        require_engulfing=cfg.require_engulfing,
        session_windows=cfg.session_windows,
        risk_dollars=risk_dollars,
        fixed_units=req.fixed_units,
        entry_start=entry_start,
        account_balance=balance,
    )
    return _vector_result_to_response(res)


@app.post("/api/backtest/multi")
async def backtest_multi(request: Optional[BacktestRequest] = None):
    req = request or BacktestRequest()
    cfg = TRADING_CONFIG
    balance = req.account_balance or cfg.account_balance
    risk_dollars = (
        balance * cfg.risk_per_trade_pct / 100.0
        if req.fixed_units is None
        else None
    )
    h1, m15, m5 = _fetch_backtest_frames(req.days)
    if h1 is None:
        raise HTTPException(status_code=503, detail="Data source unavailable")
    param_sets = [
        {},
        {"sl_mult": 1.0},
        {"sl_mult": 2.0},
        {"tp1_rr": cfg.tp1_rr * 0.75, "tp2_rr": cfg.tp2_rr * 0.75},
        {"tp1_rr": cfg.tp1_rr * 1.25, "tp2_rr": cfg.tp2_rr * 1.25},
        {"rsi_cross_bars": 1},
    ]
    results = []
    entry_start = datetime.now(timezone.utc) - timedelta(days=req.days)
    for overrides in param_sets:
        res = run_vector_backtest(
            h1, m15, m5,
            sl_mult=overrides.get("sl_mult", cfg.sl_atr_multiplier),
            tp1_rr=overrides.get("tp1_rr", cfg.tp1_rr),
            tp2_rr=overrides.get("tp2_rr", cfg.tp2_rr),
            rsi_cross_bars=overrides.get("rsi_cross_bars", cfg.rsi_cross_bars),
            require_engulfing=cfg.require_engulfing,
            session_windows=cfg.session_windows,
            risk_dollars=risk_dollars,
            fixed_units=req.fixed_units,
            entry_start=entry_start,
            account_balance=balance,
        )
        results.append(_vector_result_to_response(res, by_strategy=False))
    return results


@app.get("/api/backtest/status")
async def backtest_status():
    dc = get_data_client()
    bars_available = 0
    if dc.connected:
        df = dc.get_candles_df(Timeframe.M5, 1)
        if df is not None:
            bars_available = 500
    return {
        "data_connected": dc.connected,
        "bars_available": bars_available,
        "min_bars_required": 200,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=APP_CONFIG.host, port=APP_CONFIG.ws_port)
