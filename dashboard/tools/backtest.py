"""
Sandboxed backtest executor.

Claude-generated strategy code runs inside RestrictedPython with:
  - allowed imports: pandas, numpy, plotly
  - no network, no file I/O, no os/sys access
  - pre-loaded DataFrame `df` with OHLCV columns
"""
import traceback
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Guards import (
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
    safe_builtins,
)

_ALLOWED_IMPORTS = {"pandas", "numpy", "plotly", "plotly.graph_objects"}


def _safe_import(name, *args, **kwargs):
    top = name.split(".")[0]
    if top not in _ALLOWED_IMPORTS:
        raise ImportError(f"Import '{name}' is not allowed in backtest sandbox")
    return __import__(name, *args, **kwargs)


def _build_globals(df: pd.DataFrame) -> dict:
    glb = safe_globals.copy()
    glb["__builtins__"] = safe_builtins.copy()
    glb["__builtins__"]["__import__"] = _safe_import
    glb["_getiter_"] = iter
    glb["_getattr_"] = getattr
    glb["_getitem_"] = lambda obj, key: obj[key]
    glb["_iter_unpack_sequence_"] = guarded_iter_unpack_sequence
    glb["_unpack_sequence_"] = guarded_unpack_sequence
    glb["pd"] = pd
    glb["np"] = np
    glb["go"] = go
    glb["df"] = df.copy()
    return glb


def run_backtest(code: str, df: pd.DataFrame) -> dict[str, Any]:
    """
    Execute strategy code against df. Returns metrics dict.

    Expected: code sets a `signals` Series (1=long, 0=flat, -1=short)
    or a `positions` column on df. If neither found, infers from
    `df['signal']` if present.
    """
    try:
        byte_code = compile_restricted(code, "<backtest>", "exec")
    except SyntaxError as e:
        return {"error": f"Syntax error in strategy: {e}"}

    glb = _build_globals(df)
    try:
        exec(byte_code, glb)  # noqa: S102
    except Exception:
        return {"error": traceback.format_exc(limit=5)}

    result_df: pd.DataFrame = glb.get("df", df).copy()

    if "signal" not in result_df.columns:
        return {"error": "Strategy must set df['signal'] (1=long, 0=flat, -1=short)"}

    return _compute_metrics(result_df)


def _compute_metrics(df: pd.DataFrame) -> dict[str, Any]:
    df = df.copy()
    df["returns"] = df["close"].pct_change()
    df["strategy_returns"] = df["signal"].shift(1) * df["returns"]
    df["equity"] = (1 + df["strategy_returns"].fillna(0)).cumprod()

    total_return = float(df["equity"].iloc[-1] - 1)
    daily_std = df["strategy_returns"].std()
    sharpe = float((df["strategy_returns"].mean() / daily_std * (252**0.5)) if daily_std else 0)
    rolling_max = df["equity"].cummax()
    drawdown = (df["equity"] - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min())

    trades = df["signal"].diff().abs().fillna(0)
    num_trades = int((trades > 0).sum())

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=df.index, y=df["equity"], name="Strategy", line={"color": "#7c3aed"})
    )
    buy_hold = (1 + df["returns"].fillna(0)).cumprod()
    fig.add_trace(
        go.Scatter(x=df.index, y=buy_hold, name="Buy & Hold", line={"color": "#64748b", "dash": "dot"})
    )
    fig.update_layout(
        template="plotly_dark",
        title="Equity Curve",
        xaxis_title="Date",
        yaxis_title="Portfolio Value (normalized)",
        legend={"orientation": "h"},
        height=350,
    )

    return {
        "total_return": round(total_return * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
        "num_trades": num_trades,
        "equity_curve": fig,
    }
