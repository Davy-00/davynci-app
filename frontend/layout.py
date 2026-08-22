import dash_bootstrap_components as dbc
from dash import html, dcc
import dash

TRADINGVIEW_COLORS = {
    "bg": "#131722",
    "bg_secondary": "#1e222d",
    "border": "#2a2e39",
    "text": "#d1d4dc",
    "text_secondary": "#787b86",
    "green": "#26a69a",
    "red": "#ef5350",
    "blue": "#2196f3",
    "orange": "#ff9800",
    "purple": "#9c27b0",
}


def create_header():
    return dbc.Navbar(
        dbc.Container(
            [
                html.Div(
                    [
                        html.H3(
                            "XAUUSD Technical Analysis",
                            className="mb-0",
                            style={"color": TRADINGVIEW_COLORS["text"], "fontWeight": "600"},
                        ),
                        html.Small(
                            "Powered by MetaTrader 5",
                            style={"color": TRADINGVIEW_COLORS["text_secondary"]},
                        ),
                    ],
                    className="me-auto",
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Span("BID: ", style={"color": TRADINGVIEW_COLORS["text_secondary"]}),
                                html.Span(
                                    id="live-bid",
                                    style={
                                        "color": TRADINGVIEW_COLORS["green"],
                                        "fontSize": "24px",
                                        "fontWeight": "bold",
                                        "fontFamily": "monospace",
                                    },
                                ),
                            ],
                            className="me-4",
                        ),
                        html.Div(
                            [
                                html.Span("ASK: ", style={"color": TRADINGVIEW_COLORS["text_secondary"]}),
                                html.Span(
                                    id="live-ask",
                                    style={
                                        "color": TRADINGVIEW_COLORS["red"],
                                        "fontSize": "24px",
                                        "fontWeight": "bold",
                                        "fontFamily": "monospace",
                                    },
                                ),
                            ],
                            className="me-4",
                        ),
                        html.Div(
                            [
                                html.Span("SPREAD: ", style={"color": TRADINGVIEW_COLORS["text_secondary"]}),
                                html.Span(
                                    id="live-spread",
                                    style={
                                        "color": TRADINGVIEW_COLORS["text"],
                                        "fontSize": "18px",
                                        "fontFamily": "monospace",
                                    },
                                ),
                            ],
                        ),
                    ],
                    className="d-flex align-items-center",
                ),
            ],
            fluid=True,
        ),
        color="dark",
        dark=True,
        style={
            "backgroundColor": TRADINGVIEW_COLORS["bg_secondary"],
            "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}",
            "padding": "10px 20px",
        },
    )


def create_timeframe_selector():
    return html.Div(
        [
            dbc.ButtonGroup(
                [
                    dbc.Button("M5", id="btn-m5", color="secondary", outline=True, size="sm"),
                    dbc.Button("M15", id="btn-m15", color="secondary", outline=True, size="sm", active=True),
                    dbc.Button("H1", id="btn-h1", color="secondary", outline=True, size="sm"),
                ],
                size="sm",
                className="me-2",
            ),
            html.Span(
                id="session-info",
                style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "12px"},
            ),
        ],
        className="d-flex align-items-center mb-2",
    )


def create_live_analysis_panel():
    return html.Div(
        [
            html.H5(
                "Live Analysis",
                style={
                    "color": TRADINGVIEW_COLORS["text"],
                    "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}",
                    "paddingBottom": "8px",
                    "marginBottom": "10px",
                    "fontSize": "14px",
                },
            ),
            html.Div(id="analysis-content", children=[
                html.P("Waiting for data...", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "12px", "textAlign": "center"}),
            ]),
            html.Hr(style={"borderColor": TRADINGVIEW_COLORS["border"], "margin": "10px 0"}),
            html.H5(
                "Active Signal",
                style={
                    "color": TRADINGVIEW_COLORS["text"],
                    "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}",
                    "paddingBottom": "8px",
                    "marginBottom": "10px",
                    "fontSize": "14px",
                },
            ),
            html.Div(id="signal-content", children=[
                html.P(
                    "No active signal",
                    style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "12px", "textAlign": "center"},
                ),
            ]),
            html.Div(id="signal-status-display"),
            html.Div(
                id="warning-message",
                style={
                    "color": TRADINGVIEW_COLORS["red"],
                    "fontSize": "14px",
                    "fontWeight": "bold",
                    "marginTop": "10px",
                    "display": "none",
                },
            ),
        ],
        style={
            "backgroundColor": TRADINGVIEW_COLORS["bg_secondary"],
            "padding": "15px",
            "borderRadius": "8px",
            "border": f"1px solid {TRADINGVIEW_COLORS['border']}",
            "height": "100%",
        },
    )


def create_statistics_panel():
    return html.Div(
        [
            html.H5(
                "Statistics",
                style={
                    "color": TRADINGVIEW_COLORS["text"],
                    "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}",
                    "paddingBottom": "10px",
                    "marginBottom": "15px",
                },
            ),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Div("Total Signals", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                            html.Div(id="stat-total", style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "20px", "fontWeight": "bold"}),
                        ],
                        width=6,
                        className="mb-2",
                    ),
                    dbc.Col(
                        [
                            html.Div("Win Rate", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                            html.Div(id="stat-winrate", style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "20px", "fontWeight": "bold"}),
                        ],
                        width=6,
                        className="mb-2",
                    ),
                    dbc.Col(
                        [
                            html.Div("Avg R:R", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                            html.Div(id="stat-avg-rr", style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "20px", "fontWeight": "bold"}),
                        ],
                        width=6,
                        className="mb-2",
                    ),
                    dbc.Col(
                        [
                            html.Div("Total P&L", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                            html.Div(id="stat-total-pnl", style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "20px", "fontWeight": "bold"}),
                        ],
                        width=6,
                        className="mb-2",
                    ),
                    dbc.Col(
                        [
                            html.Div("Daily P&L", style={"color": TRADINGVIEW_COLORS["text_secondary"], "fontSize": "11px"}),
                            html.Div(id="stat-daily-pnl", style={"color": TRADINGVIEW_COLORS["text"], "fontSize": "20px", "fontWeight": "bold"}),
                        ],
                        width=12,
                        className="mb-2",
                    ),
                ],
            ),
        ],
        style={
            "backgroundColor": TRADINGVIEW_COLORS["bg_secondary"],
            "padding": "15px",
            "borderRadius": "8px",
            "border": f"1px solid {TRADINGVIEW_COLORS['border']}",
            "marginTop": "15px",
        },
    )


def create_trade_history():
    return html.Div(
        [
            html.H5(
                "Trade History",
                style={
                    "color": TRADINGVIEW_COLORS["text"],
                    "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}",
                    "paddingBottom": "10px",
                    "marginBottom": "15px",
                },
            ),
            html.Div(
                id="trade-history-table",
                style={
                    "maxHeight": "300px",
                    "overflowY": "auto",
                },
            ),
        ],
        style={
            "backgroundColor": TRADINGVIEW_COLORS["bg_secondary"],
            "padding": "15px",
            "borderRadius": "8px",
            "border": f"1px solid {TRADINGVIEW_COLORS['border']}",
            "marginTop": "15px",
        },
    )


def create_backtest_panel():
    return html.Div(
        [
            html.H5(
                "Backtest",
                style={
                    "color": TRADINGVIEW_COLORS["text"],
                    "borderBottom": f"1px solid {TRADINGVIEW_COLORS['border']}",
                    "paddingBottom": "10px",
                    "marginBottom": "15px",
                },
            ),
            dbc.Button(
                "Run Backtest",
                id="btn-backtest",
                color="primary",
                size="sm",
                className="w-100 mb-2",
            ),
            dbc.Button(
                "Run Multi (6 params)",
                id="btn-backtest-multi",
                color="secondary",
                size="sm",
                className="w-100 mb-2",
            ),
            html.Div(
                id="backtest-results",
                style={
                    "maxHeight": "200px",
                    "overflowY": "auto",
                    "fontSize": "12px",
                },
                children=[
                    html.P("Click 'Run Backtest' to start", style={"color": TRADINGVIEW_COLORS["text_secondary"], "textAlign": "center"})
                ],
            ),
        ],
        style={
            "backgroundColor": TRADINGVIEW_COLORS["bg_secondary"],
            "padding": "15px",
            "borderRadius": "8px",
            "border": f"1px solid {TRADINGVIEW_COLORS['border']}",
            "marginTop": "15px",
        },
    )


def create_layout():
    return dbc.Container(
        [
            create_header(),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            create_timeframe_selector(),
                            html.Iframe(
                                id="tv-chart",
                                src="http://127.0.0.1:8051/chart",
                                style={
                                    "width": "100%",
                                    "height": "75vh",
                                    "border": "none",
                                    "backgroundColor": TRADINGVIEW_COLORS["bg"],
                                },
                            ),
                        ],
                        width=9,
                    ),
                    dbc.Col(
                        [
                            create_live_analysis_panel(),
                            create_statistics_panel(),
                            create_trade_history(),
                            create_backtest_panel(),
                        ],
                        width=3,
                    ),
                ],
                className="mt-3",
            ),
            dcc.Interval(
                id="interval-component",
                interval=5000,
                n_intervals=0,
            ),
            dcc.Store(id="current-timeframe", data="M15"),
            dcc.Store(id="ws-connected", data=False),
            html.Div(id="ws-output"),
        ],
        fluid=True,
        style={
            "backgroundColor": TRADINGVIEW_COLORS["bg"],
            "minHeight": "100vh",
            "padding": "0",
        },
    )
