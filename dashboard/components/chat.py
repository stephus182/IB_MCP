"""
Claude AI chat panel with tool use and streaming.

Tools available to Claude:
  - fetch_market_data   : fetch IBKR history (checks Drive cache first)
  - check_cache         : inspect Drive manifest
  - run_backtest        : execute strategy in sandbox
  - get_portfolio_summary: account overview
"""
import json
from datetime import date

import anthropic
import pandas as pd
import streamlit as st

from config import ANTHROPIC_MODEL, ANTHROPIC_API_KEY
from tools import backtest, gdrive_cache, ibkr_client

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

TOOLS = [
    {
        "name": "fetch_market_data",
        "description": (
            "Fetch OHLCV historical data for a symbol from IBKR. "
            "Checks Google Drive cache first; only calls IBKR on a cache miss. "
            "Returns a summary of the data retrieved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
                "period": {"type": "string", "description": "History period, e.g. '1Y', '6M', '2Y'"},
                "bar": {"type": "string", "description": "Bar size, e.g. '1d', '1h', '30min'", "default": "1d"},
                "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (optional)"},
                "end_date": {"type": "string", "description": "End date YYYY-MM-DD, defaults to today"},
            },
            "required": ["symbol", "period"],
        },
    },
    {
        "name": "check_cache",
        "description": "Check whether data for a symbol/timeframe is already cached in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "description": "e.g. '1D', '1H'"},
                "period": {"type": "string", "description": "e.g. '1Y', '6M' — must match what was used in fetch_market_data"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD, defaults to today"},
            },
            "required": ["symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "run_backtest",
        "description": (
            "Execute a Python trading strategy in a sandboxed environment. "
            "The code receives a pandas DataFrame `df` with columns: open, high, low, close, volume. "
            "The code must set df['signal'] = 1 (long), 0 (flat), or -1 (short). "
            "Returns performance metrics and an equity curve chart."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python strategy code"},
                "symbol": {"type": "string", "description": "Symbol the data was fetched for"},
                "timeframe": {"type": "string", "description": "e.g. '1D' — must match what was used in fetch_market_data"},
                "period": {"type": "string", "description": "e.g. '1Y', '6M' — must match what was used in fetch_market_data"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD used in fetch_market_data"},
            },
            "required": ["code", "symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "get_portfolio_summary",
        "description": "Retrieve account summary from IBKR (net liquidation, cash, unrealized P&L).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

SYSTEM_PROMPT = """You are a quantitative trading research assistant with direct access to Interactive Brokers market data and a Python backtesting sandbox.

Your primary tasks:
1. Fetch and analyse historical market data via IBKR
2. Write and run trading strategy backtests in Python using pandas/numpy
3. Interpret results: equity curves, Sharpe ratios, drawdowns, trade statistics
4. Suggest strategy improvements based on results

Always check the Drive cache before fetching new data. When writing strategy code, always set df['signal'] column (1=long, 0=flat, -1=short). Present results clearly with key metrics.

When you mention a specific ticker symbol (e.g. AAPL, TSLA), the TradingView chart on the left will automatically switch to that symbol."""


def _execute_tool(name: str, inputs: dict) -> tuple[str, object]:
    """Execute a tool call and return (text_result, optional_plotly_fig)."""
    if name == "check_cache":
        try:
            hit = gdrive_cache.check_cache(
                inputs["symbol"], inputs["timeframe"], inputs["period"], inputs["end"]
            )
            return f"Cache {'HIT' if hit else 'MISS'} for {inputs['symbol']} {inputs['timeframe']} {inputs['period']}–{inputs['end']}", None
        except Exception as e:
            return f"Cache check error: {e}", None

    if name == "fetch_market_data":
        symbol = inputs["symbol"].upper()
        period = inputs["period"]
        bar = inputs.get("bar", "1d")
        end = inputs.get("end_date", str(date.today()))
        timeframe = bar.upper()

        try:
            if gdrive_cache.check_cache(symbol, timeframe, period, end):
                df = gdrive_cache.load_cache(symbol, timeframe, period, end)
                return (
                    f"Loaded {symbol} {timeframe} ({period}) from Drive cache. "
                    f"{len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}.",
                    None,
                )
        except Exception as e:
            return f"Cache error for {symbol}: {e}", None

        try:
            contracts = ibkr_client.search_contract(symbol)
        except Exception as e:
            return f"IBKR contract search failed for {symbol}: {e}", None

        if not contracts:
            return f"No contract found for {symbol} — is IBKR connected and authenticated?", None

        conid = contracts[0].get("conid") or contracts[0].get("con_id")
        if not conid:
            return f"Contract found for {symbol} but conid missing: {contracts[0]}", None

        try:
            raw = ibkr_client.get_market_data_history(conid, period=period, bar=bar)
        except Exception as e:
            return f"IBKR history fetch failed for {symbol} (conid={conid}): {e}", None

        data = raw.get("data", [])
        if not data:
            return (
                f"IBKR returned no data for {symbol} (conid={conid}, period={period}, bar={bar}). "
                f"Raw response: {raw}",
                None,
            )

        try:
            df = pd.DataFrame(data)
            df["t"] = pd.to_datetime(df["t"], unit="ms")
            df = df.rename(columns={"t": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
            df = df.set_index("date").sort_index()

            gdrive_cache.save_cache(df, symbol, timeframe, period, end)
            return (
                f"Fetched {symbol} {timeframe} ({period}) from IBKR: "
                f"{len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}. "
                f"Saved to Drive cache.",
                None,
            )
        except Exception as e:
            return f"Error processing/caching {symbol} data: {e}", None

    if name == "run_backtest":
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]

        try:
            df = gdrive_cache.load_cache(symbol, timeframe, period, end)
        except FileNotFoundError:
            return f"No cached data for {symbol} {timeframe} {period}–{end}. Fetch the data first.", None
        except Exception as e:
            return f"Error loading cached data for {symbol}: {e}", None

        try:
            result = backtest.run_backtest(inputs["code"], df)
        except Exception as e:
            return f"Backtest execution error: {e}", None

        if "error" in result:
            return f"Backtest error: {result['error']}", None

        fig = result.pop("equity_curve")
        summary = (
            f"**{symbol} Backtest Results**\n"
            f"- Total return: {result['total_return']:+.2f}%\n"
            f"- Sharpe ratio: {result['sharpe']:.2f}\n"
            f"- Max drawdown: {result['max_drawdown']:.2f}%\n"
            f"- Trades: {result['num_trades']}"
        )
        return summary, fig

    if name == "get_portfolio_summary":
        try:
            accounts = ibkr_client.get_accounts()
            if not accounts:
                return "No accounts found.", None
            account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
            summary = ibkr_client.get_account_summary(account_id)
            return json.dumps(summary, indent=2), None
        except Exception as e:
            return f"Could not fetch portfolio summary: {e}", None

    return f"Unknown tool: {name}", None


def render_chat(on_symbol_change=None):
    """
    Render the Claude chat panel.
    on_symbol_change: optional callback(symbol: str) to sync TradingView chart.
    """
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_figs" not in st.session_state:
        st.session_state.pending_figs = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    for fig in st.session_state.pending_figs:
        st.plotly_chart(fig, use_container_width=True)
    st.session_state.pending_figs = []

    if prompt := st.chat_input("Ask Claude about market data, analysis, or backtesting..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
        figs = []
        full_response = ""

        with st.chat_message("assistant"):
            placeholder = st.empty()

            try:
                while True:
                    with _client.messages.stream(
                        model=ANTHROPIC_MODEL,
                        max_tokens=4096,
                        system=SYSTEM_PROMPT,
                        tools=TOOLS,
                        messages=api_messages,
                    ) as stream:
                        tool_calls = []
                        for event in stream:
                            if hasattr(event, "type"):
                                if event.type == "content_block_start":
                                    if getattr(event.content_block, "type", "") == "tool_use":
                                        tool_calls.append({
                                            "id": event.content_block.id,
                                            "name": event.content_block.name,
                                        })
                                elif event.type == "content_block_delta":
                                    delta = event.delta
                                    if hasattr(delta, "text") and delta.text:
                                        full_response += delta.text
                                        placeholder.markdown(full_response + "▌")

                        final = stream.get_final_message()

                    if not tool_calls:
                        break

                    tool_results = []
                    for tc in final.content:
                        if tc.type != "tool_use":
                            continue
                        text, fig = _execute_tool(tc.name, tc.input)
                        if fig:
                            figs.append(fig)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": text,
                        })

                        if on_symbol_change and tc.name == "fetch_market_data":
                            on_symbol_change(tc.input.get("symbol", "").upper())

                    api_messages.append({"role": "assistant", "content": final.content})
                    api_messages.append({"role": "user", "content": tool_results})

                    if final.stop_reason != "tool_use":
                        break

            except anthropic.APIError as e:
                err = f"Anthropic API error: {e}. Please try again."
                placeholder.markdown(err)
                full_response = err

        placeholder.markdown(full_response)
        st.session_state.messages.append({"role": "assistant", "content": full_response})
        st.session_state.pending_figs = figs
        st.rerun()
