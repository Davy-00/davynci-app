import dash
import dash_bootstrap_components as dbc
from frontend.layout import create_layout
from frontend.callbacks import *

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
    title="XAUUSD Technical Analysis",
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
    ],
)

app.layout = create_layout()

server = app.server

if __name__ == "__main__":
    app.run_server(debug=True, host="127.0.0.1", port=8050)
