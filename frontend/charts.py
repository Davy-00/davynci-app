import plotly.graph_objects as go
from typing import Dict, Any
from datetime import datetime


TV = {
    "bg": "#131722",
    "bg2": "#1e222d",
    "border": "#2a2e39",
    "text": "#d1d4dc",
    "text2": "#787b86",
    "green": "#26a69a",
    "red": "#ef5350",
    "ema21": "#2196f3",
    "ema50": "#ff9800",
    "ema200": "#ffffff",
    "grid": "#2a2e39",
}


def create_main_chart(data: Dict[str, Any], timeframe: str = "M15") -> go.Figure:
    candles = data.get("candles", [])
    indicators = data.get("indicators", {})

    if not candles:
        fig = go.Figure()
        fig.update_layout(template="plotly_dark", paper_bgcolor=TV["bg"], plot_bgcolor=TV["bg"])
        return fig

    times = [datetime.fromisoformat(c["time"]) for c in candles]
    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    fig = go.Figure()

    # Candlesticks
    fig.add_trace(
        go.Candlestick(
            x=times, open=opens, high=highs, low=lows, close=closes,
            name="XAUUSD",
            increasing_line_color=TV["green"],
            decreasing_line_color=TV["red"],
            increasing_fillcolor=TV["green"],
            decreasing_fillcolor=TV["red"],
            line=dict(width=1),
        ),
    )

    # EMAs
    for ema_name, color in [("ema_21", TV["ema21"]), ("ema_50", TV["ema50"]), ("ema_200", TV["ema200"])]:
        vals = indicators.get(ema_name, [])
        if vals and len(vals) == len(times):
            fig.add_trace(
                go.Scatter(
                    x=times, y=vals,
                    name=ema_name.upper().replace("_", " "),
                    line=dict(color=color, width=1),
                    mode="lines",
                ),
            )

    # Current price line
    price = data.get("current_price", {})
    bid = price.get("bid")
    if bid and times:
        fig.add_hline(
            y=bid,
            line=dict(color=TV["text2"], width=1, dash="dot"),
            annotation_text=f"{bid:.2f}",
            annotation_position="right",
            annotation_font=dict(color=TV["text2"], size=10),
        )

    # Signal markers
    signals = data.get("signals", [])
    for signal in signals:
        if not signal:
            continue
        direction = signal.get("direction", "")
        entry_time = datetime.fromisoformat(signal["entry_time"]) if signal.get("entry_time") else None
        entry_price = signal.get("entry_price", 0)
        sl = signal.get("stop_loss", 0)
        tp1 = signal.get("tp1", 0)
        tp2 = signal.get("tp2", 0)

        arrow_color = TV["green"] if direction == "BUY" else TV["red"]
        arrow_sym = "arrow-up" if direction == "BUY" else "arrow-down"

        if entry_time and entry_price:
            fig.add_trace(
                go.Scatter(
                    x=[entry_time], y=[entry_price],
                    mode="markers",
                    marker=dict(symbol=arrow_sym, size=20, color=arrow_color, line=dict(width=2, color="white")),
                    name=f"{direction}",
                ),
            )

        for label, val, color in [("SL", sl, TV["red"]), ("TP1", tp1, TV["green"]), ("TP2", tp2, TV["green"])]:
            if val:
                fig.add_hline(
                    y=val,
                    line=dict(color=color, width=1, dash="dash"),
                    annotation_text=label,
                    annotation_position="left",
                    annotation_font=dict(color=color, size=9),
                )

    # Layout
    fig.update_layout(
        title=dict(text=f"XAUUSD / {timeframe}", font=dict(size=14, color=TV["text"]), x=0, xanchor="left"),
        paper_bgcolor=TV["bg"],
        plot_bgcolor=TV["bg"],
        font=dict(color=TV["text"], size=11),
        dragmode="pan",
        hovermode="x unified",
        autosize=True,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
            bgcolor="rgba(30,34,45,0.8)", font=dict(size=9), borderwidth=1, bordercolor=TV["border"],
        ),
        margin=dict(l=10, r=40, t=50, b=10),
        hoverlabel=dict(bgcolor=TV["bg2"], font=dict(color=TV["text"], size=11), bordercolor=TV["border"]),
        modebar=dict(bgcolor="rgba(30,34,45,0.9)", color=TV["text2"], activecolor=TV["text"]),
        xaxis_rangeslider_visible=False,
    )

    fig.update_xaxes(
        showgrid=True, gridwidth=1, gridcolor=TV["grid"],
        tickfont=dict(size=9, color=TV["text2"]),
        rangeslider=dict(visible=False),
        spikemode="across", spikesnap="cursor", showspikes=True,
        spikecolor=TV["text2"], spikethickness=1,
    )

    fig.update_yaxes(
        showgrid=True, gridwidth=1, gridcolor=TV["grid"],
        tickfont=dict(size=9, color=TV["text2"]),
        side="right",
        spikemode="across", spikesnap="cursor", showspikes=True,
        spikecolor=TV["text2"], spikethickness=1,
    )

    return fig
