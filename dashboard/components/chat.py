"""
Claude AI chat panel with tool use and streaming.

Tools available to Claude:
  - fetch_market_data       : fetch IBKR history (checks Drive cache first)
  - check_cache             : inspect Drive manifest
  - run_backtest            : execute strategy in sandbox
  - get_portfolio_summary   : account summary (net liq, cash, P&L)
  - get_positions           : all open positions
  - get_account_overview    : summary + ledger + allocation in one call
  - get_trades              : recent trade history (last 6 days)
  - get_live_orders         : open/live orders
  - get_pa_performance      : portfolio NAV performance over a period
  - get_pa_transactions     : transaction history from Portfolio Analyst
  - get_contract_details    : full contract info + trading rules
  - get_option_chain        : options chain for a symbol
  - run_scanner             : IBKR market scanner
  - get_notifications       : IBKR FYI notifications
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
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_positions",
        "description": "Get all open positions for the IBKR account — symbol, quantity, market value, unrealized P&L.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_account_overview",
        "description": "Full account overview: summary (net liq, cash, P&L) + cash ledger by currency + allocation by asset class. Use this for a complete picture of the account.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_trades",
        "description": "Recent trade history from IBKR for the current and previous 6 days — symbol, side, quantity, price, execution time.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_live_orders",
        "description": "All currently open/live orders in the IBKR account — symbol, order type, side, quantity, status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_pa_performance",
        "description": "Portfolio Analyst NAV performance over a period (1D, 1W, 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, ITD).",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "Period code: 1D, 1W, 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, or ITD", "default": "1Y"},
            },
            "required": [],
        },
    },
    {
        "name": "get_pa_transactions",
        "description": "Transaction history from IBKR Portfolio Analyst — deposits, withdrawals, dividends, fees.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "Period code: 1D, 1W, 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, or ITD", "default": "1Y"},
            },
            "required": [],
        },
    },
    {
        "name": "get_contract_details",
        "description": "Full contract details and trading rules for a symbol — exchange, currency, trading hours, margin requirements, available algos.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
                "sec_type": {"type": "string", "description": "Security type: STK, OPT, FUT, CASH, BOND", "default": "STK"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_option_chain",
        "description": "Options chain for a symbol — available expirations and strikes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Underlying ticker symbol, e.g. AAPL"},
                "exchange": {"type": "string", "description": "Exchange, e.g. CBOE (optional)"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "run_scanner",
        "description": "Run an IBKR market scanner to find stocks matching criteria (top gainers, high volume, momentum, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "scan_type": {"type": "string", "description": "Scanner type, e.g. TOP_PERC_GAIN, TOP_PERC_LOSE, MOST_ACTIVE, HIGH_VS_13W_HL, LOW_VS_13W_HL"},
                "instrument": {"type": "string", "description": "Instrument type: STK, ETF, IND", "default": "STK"},
                "location": {"type": "string", "description": "Market location, e.g. STK.US.MAJOR", "default": "STK.US.MAJOR"},
            },
            "required": ["scan_type"],
        },
    },
    {
        "name": "get_notifications",
        "description": "Recent IBKR FYI notifications and system messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_count": {"type": "integer", "description": "Max notifications to return (default 10)", "default": 10},
            },
            "required": [],
        },
    },
]

SYSTEM_PROMPT = """You are a quantitative trading research assistant with full access to Interactive Brokers data and a Python backtesting sandbox.

Your capabilities:
1. Market data — fetch historical OHLCV, real-time snapshots, contract details, options chains
2. Portfolio — positions, account summary, cash ledger, allocation breakdown
3. Trade history — recent executions, open orders, Portfolio Analyst performance and transactions
4. Research — market scanner, FYI notifications, futures and stock contract lookups
5. Backtesting — write and run Python strategies in a sandbox, return equity curves and metrics

Guidelines:
- Always check the Drive cache before fetching new data (use check_cache first)
- For account questions, use get_account_overview for a complete picture
- When writing strategy code, always set df['signal'] = 1 (long), 0 (flat), or -1 (short)
- Present results clearly with key metrics in markdown tables where appropriate
- When you mention a ticker symbol, the TradingView chart on the left auto-switches to it
- Order placement is NOT available — this is a read-only research environment"""


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

    if name == "get_positions":
        try:
            positions = ibkr_client.get_positions()
            if not positions:
                return "No open positions found.", None
            return json.dumps(positions, indent=2), None
        except Exception as e:
            return f"Could not fetch positions: {e}", None

    if name == "get_account_overview":
        try:
            summary = ibkr_client.get_account_summary()
            ledger = ibkr_client.get_account_ledger()
            allocation = ibkr_client.get_account_allocation()
            overview = {
                "summary": summary,
                "ledger": ledger,
                "allocation": allocation,
            }
            return json.dumps(overview, indent=2), None
        except Exception as e:
            return f"Could not fetch account overview: {e}", None

    if name == "get_trades":
        try:
            trades = ibkr_client.get_trades()
            if not trades:
                return "No trades found for the last 6 days.", None
            return json.dumps(trades, indent=2), None
        except Exception as e:
            return f"Could not fetch trades: {e}", None

    if name == "get_live_orders":
        try:
            orders = ibkr_client.get_live_orders()
            if not orders:
                return "No open orders.", None
            return json.dumps(orders, indent=2), None
        except Exception as e:
            return f"Could not fetch live orders: {e}", None

    if name == "get_pa_performance":
        try:
            period = inputs.get("period", "1Y")
            perf = ibkr_client.get_pa_performance(period=period)
            return json.dumps(perf, indent=2), None
        except Exception as e:
            return f"Could not fetch PA performance: {e}", None

    if name == "get_pa_transactions":
        try:
            period = inputs.get("period", "1Y")
            txns = ibkr_client.get_pa_transactions(period=period)
            return json.dumps(txns, indent=2), None
        except Exception as e:
            return f"Could not fetch PA transactions: {e}", None

    if name == "get_contract_details":
        try:
            symbol = inputs["symbol"].upper()
            sec_type = inputs.get("sec_type", "STK")
            contracts = ibkr_client.search_contract(symbol, sec_type)
            if not contracts:
                return f"No contract found for {symbol}.", None
            conid = contracts[0].get("conid") or contracts[0].get("con_id")
            if not conid:
                return f"Contract found for {symbol} but conid missing.", None
            info = ibkr_client.get_contract_info_and_rules(conid)
            return json.dumps(info, indent=2), None
        except Exception as e:
            return f"Could not fetch contract details for {inputs.get('symbol', '?')}: {e}", None

    if name == "get_option_chain":
        try:
            symbol = inputs["symbol"].upper()
            exchange = inputs.get("exchange", "")
            chain = ibkr_client.get_option_chain(symbol, exchange=exchange)
            return json.dumps(chain, indent=2), None
        except Exception as e:
            return f"Could not fetch option chain for {inputs.get('symbol', '?')}: {e}", None

    if name == "run_scanner":
        try:
            params = {
                "instrument": inputs.get("instrument", "STK"),
                "type": inputs["scan_type"],
                "filter": [],
                "location": inputs.get("location", "STK.US.MAJOR"),
                "size": "25",
            }
            results = ibkr_client.run_iserver_scanner(params)
            if not results:
                return "Scanner returned no results.", None
            return json.dumps(results[:25], indent=2), None
        except Exception as e:
            return f"Scanner error: {e}", None

    if name == "get_notifications":
        try:
            max_count = inputs.get("max_count", 10)
            notifications = ibkr_client.get_notifications(max_count=max_count)
            unread = ibkr_client.get_unread_count()
            result = {"unread_count": unread, "notifications": notifications}
            return json.dumps(result, indent=2), None
        except Exception as e:
            return f"Could not fetch notifications: {e}", None

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

            except Exception as e:
                import traceback, sys
                print(f"[chat] exception in stream loop: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                err = f"Error: {e}. Please try again."
                if not full_response:
                    full_response = err

            finally:
                placeholder.markdown(full_response)
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                st.session_state.pending_figs = figs
                st.rerun()
