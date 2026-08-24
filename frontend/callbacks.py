import json
import os
import dash
from dash import Input, Output, State, callback, html, dcc, no_update
import dash_bootstrap_components as dbc
import requests
from datetime import datetime
from frontend.layout import TRADINGVIEW_COLORS

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8051")


def format_price(value):
    if value is None:
        return "--"
    return f"{value:,.2f}"


def format_pnl(value):
    if value is None:
        return "$0.00"
    color = TRADINGVIEW_COLORS["green"] if value >= 0 else TRADINGVIEW_COLORS["red"]
    return html.Span(f"${value:,.2f}", style={"color": color})


def create_analysis_display(analysis):
    if not analysis:
        return html.P("No data", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "12px", "textAlign": "center"})

    c = TRADINGVIEW_COLORS
    narrative = analysis.get("narrative", "")
    setup = analysis.get("setup", "")
    conclusion = analysis.get("conclusion", "")
    buy_score = analysis.get("buy_score", 0)
    sell_score = analysis.get("sell_score", 0)

    # Conclusion color
    concl_color = c["green"] if "BULLISH" in conclusion else (c["red"] if "BEARISH" in conclusion else c["text_secondary"])

    rows = []

    # Narrative
    if narrative:
        for line in narrative.split("\n"):
            line = line.strip()
            if not line:
                continue
            color = c["text"]
            if any(w in line for w in ["UP", "up", "longs", "Bullish", "bullish", "support"]):
                color = c["green"]
            elif any(w in line for w in ["DOWN", "down", "shorts", "Bearish", "bearish", "resistance", "Caution", "overbought"]):
                color = c["red"]
            elif any(w in line for w in ["sideways", "neutral", "Outside"]):
                color = c["text_secondary"]
            rows.append(html.Div(line, style={"color": color, "fontSize": "11px", "marginBottom": "4px", "lineHeight": "1.4"}))

    # Divider
    rows.append(html.Hr(style={"borderColor": c["border"], "margin": "8px 0"}))

    # Setup section header
    rows.append(html.Div("Setup Factors:", style={"color": c["text"], "fontSize": "12px", "fontWeight": "bold", "marginBottom": "4px"}))

    if setup:
        for line in setup.split("\n"):
            line = line.strip()
            if not line:
                continue
            color = c["green"] if line.startswith("+") else c["red"]
            rows.append(html.Div(line, style={"color": color, "fontSize": "11px", "marginBottom": "3px", "lineHeight": "1.3"}))

    # Divider
    rows.append(html.Hr(style={"borderColor": c["border"], "margin": "8px 0"}))

    # Conclusion
    rows.append(html.Div([
        html.Span(conclusion, style={"color": concl_color, "fontSize": "13px", "fontWeight": "bold"}),
    ]))

    return html.Div(rows)


STRATEGY_COLORS_CSS = {
    "BOUNCE": "#ff9800",
    "BREAKOUT": "#e040fb",
    "REVERSAL": "#00e5ff",
    "CONTINUATION": "#76ff03",
}


def create_signal_card(signal):
    if not signal:
        return html.P(
            "No active signal",
            style={"color": TRADINGVIEW_COLORS["text_secondary"], "textAlign": "center"},
        )

    direction = signal.get("direction", "")
    strategy_type = signal.get("strategy_type", "CONTINUATION")
    direction_color = TRADINGVIEW_COLORS["green"] if direction == "BUY" else TRADINGVIEW_COLORS["red"]
    strat_color = STRATEGY_COLORS_CSS.get(strategy_type, TRADINGVIEW_COLORS["text"])

    pnl = signal.get("current_pnl", 0)
    pnl_color = TRADINGVIEW_COLORS["green"] if pnl >= 0 else TRADINGVIEW_COLORS["red"]

    status_badge = None
    if signal.get("tp1_hit"):
        status_badge = dbc.Badge("TP1 HIT - BE Active", color="warning", className="mb-2")

    return html.Div(
        [
            status_badge,
            html.Div(
                [
                    html.Span(
                        direction,
                        style={"color": direction_color, "fontSize": "24px", "fontWeight": "bold"},
                    ),
                    html.Span(
                        f" #{signal.get('id', '')}",
                        style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "12px"},
                    ),
                ],
                className="mb-2",
            ),
            dbc.Badge(strategy_type, color="dark", textColor=strat_color,
                      style={"border": f"1px solid {strat_color}", "marginBottom": "8px"}),
            html.Div(
                [
                    html.Div("Entry", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                    html.Div(format_price(signal.get("entry_price")), style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "16px", "fontWeight": "bold"}),
                ],
                className="mb-2",
            ),
            html.Div(
                [
                    html.Div("Stop Loss", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                    html.Div(format_price(signal.get("stop_loss")), style={"color": TRADINGVIEW_COLORS["red"], "fontSize": "16px", "fontWeight": "bold"}),
                ],
                className="mb-2",
            ),
            html.Div(
                [
                    html.Div("TP1", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                    html.Div(format_price(signal.get("tp1")), style={"color": TRADINGVIEW_COLORS["green"], "fontSize": "16px", "fontWeight": "bold"}),
                ],
                className="mb-2",
            ),
            html.Div(
                [
                    html.Div("TP2", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                    html.Div(format_price(signal.get("tp2")), style={"color": TRADINGVIEW_COLORS["green"], "fontSize": "16px", "fontWeight": "bold"}),
                ],
                className="mb-2",
            ),
            html.Hr(style={"borderColor": TRADINGVIEW_COLORS["border"]}),
            html.Div(
                [
                    html.Div("Risk", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                    html.Div(f"${signal.get('risk_dollars', 0):.2f} ({signal.get('risk_pips', 0)} pips)", style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "12px"}),
                ],
                className="mb-2",
            ),
            html.Div(
                [
                    html.Div("Lot Size", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                    html.Div(f"{signal.get('lot_size', 0):.2f}", style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "12px"}),
                ],
                className="mb-2",
            ),
            html.Hr(style={"borderColor": TRADINGVIEW_COLORS["border"]}),
            html.Div(
                [
                    html.Div("Live P&L", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                    html.Div(
                        f"${pnl:,.2f} ({signal.get('current_pnl_pips', 0):.1f} pips)",
                        style={"color": pnl_color, "fontSize": "20px", "fontWeight": "bold"},
                    ),
                ],
            ),
        ]
    )


def create_history_table(trades):
    if not trades:
        return html.P(
            "No trades yet",
            style={"color": TRADINGVIEW_COLORS["text_secondary"], "textAlign": "center"},
        )
    
    rows = []
    for trade in trades[-20:]:
        pnl = trade.get("pnl_dollars", 0)
        pnl_color = TRADINGVIEW_COLORS["green"] if pnl >= 0 else TRADINGVIEW_COLORS["red"]
        direction_color = TRADINGVIEW_COLORS["green"] if trade.get("direction") == "BUY" else TRADINGVIEW_COLORS["red"]
        strategy_type = trade.get("strategy_type", "")

        rows.append(
            html.Tr(
                [
                    html.Td(trade.get("date", ""), style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px", "padding": "3px"}),
                    html.Td(trade.get("time", ""), style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px", "padding": "3px"}),
                    html.Td(
                        trade.get("direction", ""),
                        style={"color": direction_color, "fontSize": "10px", "fontWeight": "bold", "padding": "3px"},
                    ),
                    html.Td(
                        strategy_type[:4],
                        style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "9px", "padding": "3px"},
                    ),
                    html.Td(f"${pnl:,.2f}", style={"color": pnl_color, "fontSize": "10px", "padding": "3px"}),
                    html.Td(trade.get("result", ""), style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "10px", "padding": "3px"}),
                ]
            )
        )
    
    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Date", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px", "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}"}),
                        html.Th("Time", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px", "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}"}),
                        html.Th("Dir", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px", "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}"}),
                        html.Th("Typ", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px", "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}"}),
                        html.Th("P&L", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px", "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}"}),
                        html.Th("Res", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px", "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}"}),
                    ]
                )
            ),
            html.Tbody(rows),
        ],
        className="w-100",
        style={"borderCollapse": "collapse"},
    )


def _fetch_chart(timeframe: str):
    """Fast path when backend awake; long-retry covers cold start."""
    try:
        return requests.get(f"{API_BASE_URL}/api/chart/{timeframe}", timeout=8).json()
    except Exception:
        return requests.get(f"{API_BASE_URL}/api/chart/{timeframe}", timeout=45).json()


@callback(
    Output("live-bid", "children"),
    Output("live-ask", "children"),
    Output("live-spread", "children"),
    Output("analysis-content", "children"),
    Output("signal-content", "children"),
    Output("signal-status-display", "children"),
    Output("warning-message", "children"),
    Output("warning-message", "style"),
    Output("stat-total", "children"),
    Output("stat-winrate", "children"),
    Output("stat-avg-rr", "children"),
    Output("stat-total-pnl", "children"),
    Output("stat-daily-pnl", "children"),
    Output("trade-history-table", "children"),
    Output("session-info", "children"),
    Input("interval-component", "n_intervals"),
    State("current-timeframe", "data"),
)
def update_dashboard(n, timeframe):
    try:
        data = _fetch_chart(timeframe)
    except Exception as e:
        return (
            "--", "--", "--",
            create_analysis_display({}),
            html.P("⏳ Backend waking up — first load takes ~40s on free hosting, charts appear automatically.",
                   style={"color": "#f0b90b", "fontSize": "13px"}),
            html.P("Waking…", style={"color": "#f0b90b"}),
            "",
            {"display": "none"},
            "0", "0%", "0", "$0", "$0",
            html.P("Waiting for backend…", style={"color": "#f0b90b"}),
            f"Waking backend ({type(e).__name__})",
        )
    
    if "error" in data:
        return (
            "--", "--", "--",
            create_analysis_display({}),
            html.P(data["error"], style={"color": "red"}),
            html.P("Error", style={"color": "red"}),
            "",
            {"display": "none"},
            "0", "0%", "0", "$0", "$0",
            html.P("Error", style={"color": "red"}),
            data.get("error", "Unknown error"),
        )
    
    price_data = data.get("current_price", {})
    bid = format_price(price_data.get("bid"))
    ask = format_price(price_data.get("ask"))
    spread = format_price(price_data.get("spread"))
    
    signals = data.get("signals", [])
    active_signal = signals[0] if signals else None
    signal_card = create_signal_card(active_signal)
    
    signal_status = data.get("signal_status", {})
    status_items = []
    if signal_status.get("has_active_signal"):
        status_items.append(html.Div("Active signal running", style={"color": TRADINGVIEW_COLORS["green"], "fontSize": "12px"}))
    status_items.append(html.Div(f"Signals today: {signal_status.get('signals_today_count', 0)}/{signal_status.get('max_daily_signals', 3)}", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "12px"}))
    
    if signal_status.get("daily_limit_reached"):
        status_items.append(html.Div("Daily limit reached", style={"color": TRADINGVIEW_COLORS["orange"], "fontSize": "12px"}))
    
    warning = ""
    warning_style = {"display": "none"}
    if signal_status.get("daily_loss_limit_reached"):
        warning = "DAILY LOSS LIMIT REACHED - Scanning paused"
        warning_style = {"display": "block", "color": TRADINGVIEW_COLORS["red"], "fontSize": "14px", "fontWeight": "bold", "marginTop": "10px"}
    
    stats = data.get("statistics", {})
    total = str(stats.get("total_signals", 0))
    winrate = f"{stats.get('win_rate', 0)}%"
    avg_rr = f"{stats.get('avg_rr', 0):.2f}"
    total_pnl = format_pnl(stats.get("total_pnl_dollars", 0))
    daily_pnl = format_pnl(stats.get("daily_pnl_dollars", 0))
    
    history_data = data.get("trade_history", [])
    history_table = create_history_table(history_data)
    
    analysis = data.get("analysis", {})
    analysis_display = create_analysis_display(analysis)

    session_info = data.get("session_info", {})
    session_text = f"Session: {session_info.get('current_session', 'None')}"
    if not session_info.get("is_active"):
        session_text += f" | Next: {session_info.get('next_session', '')}"
    
    return (
        bid, ask, spread,
        analysis_display,
        signal_card,
        html.Div(status_items),
        warning,
        warning_style,
        total, winrate, avg_rr,
        total_pnl,
        daily_pnl,
        history_table,
        session_text,
    )


def format_backtest_result(data):
    if not data or data.get("total_trades", 0) == 0:
        return html.P("No trades generated", style={"color": TRADINGVIEW_COLORS["text_secondary"]})

    colors = TRADINGVIEW_COLORS
    return html.Div([
        html.Div(f"Trades: {data['total_trades']}  Win: {data['win_rate']}%",
                 style={"color": colors["text"], "fontSize": "12px"}),
        html.Div(f"P&L: ${data['total_pnl']:.2f}  RR: {data['avg_rr']}",
                 style={"color": colors["green"] if data['total_pnl'] >= 0 else colors["red"], "fontSize": "12px"}),
        html.Div(f"PF: {data['profit_factor']}  DD: {data['max_drawdown']}%",
                 style={"color": colors["text_secondary"], "fontSize": "11px"}),
        html.Hr(style={"borderColor": colors["border"], "margin": "4px 0"}),
        html.Div("By Strategy:", style={"color": colors["text_secondary"], "fontSize": "11px", "fontWeight": "bold"}),
        html.Div([
            html.Div(f"{k}: {v['trades']}t {v['wins']}w ${v['pnl']:.0f}",
                     style={"color": colors["text"], "fontSize": "11px"})
            for k, v in data.get("by_strategy", {}).items()
        ]),
    ])


def format_multi_backtest_results(results):
    if not results:
        return html.P("No results", style={"color": TRADINGVIEW_COLORS["text_secondary"]})

    colors = TRADINGVIEW_COLORS
    rows = []
    for i, r in enumerate(results):
        best = r.get("total_pnl", 0)
        rows.append(html.Div(
            f"#{i+1}: Trades={r['total_trades']} WR={r['win_rate']}% P&L=${best:.0f} PF={r['profit_factor']}",
            style={"color": colors["green"] if best >= 0 else colors["red"], "fontSize": "11px",
                   "borderBottom": f"1px solid {colors['border']}", "padding": "2px 0"},
        ))

    return html.Div([
        html.Div("Multi-Run Results:", style={"color": colors["text"], "fontSize": "12px", "fontWeight": "bold"}),
        *rows,
    ])


@callback(
    Output("ai-insight", "children"),
    Input("btn-ai-analyze", "n_clicks"),
    State("ai-question", "value"),
    State("current-timeframe", "data"),
    prevent_initial_call=True,
)
def get_ai_insight(n, question, timeframe):
    if not n:
        return no_update
    try:
        payload = {"timeframe": timeframe}
        if question:
            payload["question"] = question
        response = requests.post(f"{API_BASE_URL}/api/ai/analyze", json=payload, timeout=50)
        data = response.json()
        if "detail" in data or "error" in data:
            msg = data.get("detail") or data.get("error")
            return html.P(f"⚠ {msg}", style={"color": TRADINGVIEW_COLORS["orange"], "fontSize": "12px"})
        insight = data.get("insight", "")
        paras = []
        for block in insight.split("\n"):
            b = block.strip()
            if not b:
                continue
            color = TRADINGVIEW_COLORS.get("text", "#d1d4dc")
            paras.append(html.P(b, style={"color": color, "fontSize": "12px", "marginBottom": "6px"}))
        model = data.get("model", "")
        footer = html.P(f"— {model}", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "10px"})
        return [*paras, footer]
    except Exception as e:
        return html.P("⏳ Timed out (backend may have been waking up). Click 'Get AI Insight' again — second try is fast.",
                      style={"color": TRADINGVIEW_COLORS["orange"], "fontSize": "12px"})


@callback(
    Output("current-timeframe", "data"),
    Output("btn-m5", "active"),
    Output("btn-m15", "active"),
    Output("btn-h1", "active"),
    Input("btn-m5", "n_clicks"),
    Input("btn-m15", "n_clicks"),
    Input("btn-h1", "n_clicks"),
    prevent_initial_call=True,
)
def switch_timeframe(n5, n15, n1):
    ctx = dash.callback_context
    if not ctx.triggered:
        return "M15", False, True, False

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    tf = "M15"
    m5_a = m15_a = h1_a = False

    if button_id == "btn-m5":
        tf = "M5"; m5_a = True
    elif button_id == "btn-m15":
        tf = "M15"; m15_a = True
    elif button_id == "btn-h1":
        tf = "H1"; h1_a = True
    else:
        tf = "M15"; m15_a = True

    return tf, m5_a, m15_a, h1_a


@callback(
    Output("tv-chart", "src"),
    Input("current-timeframe", "data"),
)
def update_chart_timeframe(tf):
    return f"{API_BASE_URL}/chart?tf={tf}"


@callback(
    Output("backtest-results", "children"),
    Input("btn-backtest", "n_clicks"),
    prevent_initial_call=True,
)
def run_single_backtest(n):
    try:
        response = requests.post(f"{API_BASE_URL}/api/backtest", timeout=120)
        data = response.json()
        return format_backtest_result(data)
    except Exception as e:
        return html.P(f"Error: {e}", style={"color": TRADINGVIEW_COLORS["red"], "fontSize": "11px"})


@callback(
    Output("backtest-results", "children", allow_duplicate=True),
    Input("btn-backtest-multi", "n_clicks"),
    prevent_initial_call=True,
)
def run_multi_backtest(n):
    try:
        response = requests.post(f"{API_BASE_URL}/api/backtest/multi", timeout=300)
        results = response.json()
        return format_multi_backtest_results(results)
    except Exception as e:
        return html.P(f"Error: {e}", style={"color": TRADINGVIEW_COLORS["red"], "fontSize": "11px"})

