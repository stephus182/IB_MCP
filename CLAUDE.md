# IBKR MCP Research Dashboard

Personal trading research environment: market data access, strategy backtesting, and analysis via Claude AI. Built on top of the [IB_MCP](https://github.com/rcontesti/IB_MCP) open-source IBKR MCP server.

## Conventions

- **Package manager**: Always use Homebrew (`brew install`) for macOS tooling — Python, Docker, CLI tools, etc. Use `pip install -r requirements.txt` only for project-scoped Python dependencies.
- **Python**: Install via `brew install python` (targets Python 3.12+). Do not use the system Python 3.9.

## Quick Start

### 1. Start the IBKR Docker stack
```bash
docker compose up --build
```
Then open **https://localhost:5055** in your browser and authenticate with your IBKR credentials. Do this once per session (the auto-tickler keeps the session alive).

### 2. Start the dashboard
```bash
# From repo root — must be run from here, not from inside dashboard/
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```
Open **http://localhost:8501**.

### 3. First-run Google Drive auth
On first launch, a browser window opens for Google OAuth2 consent. Approve it — `token.json` is saved locally and reused on future runs.

## Environment Variables

Copy `.env.example` to `.env` and fill in:

| Key | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GOOGLE_DRIVE_FOLDER_ID` | ID of the `IBKR_cache/` folder in Google Drive |
| `GATEWAY_PORT` | IBKR gateway port (default: 5055) |
| `MCP_SERVER_PORT` | MCP server port (default: 5002) |

To get `GOOGLE_DRIVE_FOLDER_ID`: open the `IBKR_cache/` folder in Google Drive → the ID is the last segment of the URL.

## MCP Server Endpoints

Base URL: `https://localhost:5002`

### Production-ready (9 endpoints)
| Endpoint | Description |
|---|---|
| `GET /iserver/marketdata/history` | Historical OHLCV bars — primary data source for backtests |
| `GET /iserver/marketdata/snapshot` | Real-time price snapshot |
| `GET /iserver/secdef/search` | Search contracts by symbol |
| `GET /iserver/secdef/bond-filters` | Bond filter options |
| `GET /portfolio/accounts` | Account list |
| `GET /portfolio/subaccounts` | Subaccount list |
| `GET /portfolio/{accountId}/summary` | Account summary |
| `GET /portfolio/positions/{conid}` | Positions for contract |
| `GET /portfolio/{acctId}/position/{conid}` | Single position detail |

### Untested (70 endpoints)
Orders, alerts, options chains, scanner, watchlists — present but not validated. See `ENDPOINTS.md` for full list.

## Dashboard Architecture

```
Browser (localhost:8501)
├── Left panel:  TradingView Advanced Chart Widget (Pro account iframe)
└── Right panel: Claude AI Chat (Anthropic SDK, tool use, streaming)

dashboard/
├── app.py                    ← entry point, hybrid layout, panel toggle
├── components/
│   ├── tradingview.py        ← TradingView HTML component
│   └── chat.py               ← Claude chat panel + tool use
├── tools/
│   ├── ibkr_client.py        ← HTTP wrapper for MCP endpoints
│   ├── gdrive_cache.py       ← Google Drive parquet cache
│   └── backtest.py           ← RestrictedPython sandbox executor
└── config.py                 ← env var loading
```

## Claude Tools (available in chat)

| Tool | Description |
|---|---|
| `fetch_market_data(symbol, period, bar)` | Fetch IBKR history, cache to Drive |
| `check_cache(symbol, period)` | Check Drive manifest before fetching |
| `run_backtest(code, data_key)` | Execute strategy in sandbox, return metrics |
| `get_portfolio_summary()` | Account summary (background context) |

## Google Drive Cache

Cache folder: `IBKR_cache/` in your Google Drive.

File naming: `{SYMBOL}_{TIMEFRAME}_{START}_{END}.parquet`  
e.g. `AAPL_1D_2022-01-01_2024-12-31.parquet`

`manifest.json` in the folder indexes all cached files. The cache is shared across machines — same Drive folder, any machine.

## Backtest Sandbox Constraints

The `RestrictedPython` sandbox allows only:
- `pandas`, `numpy`, `plotly`
- No network access, no file I/O, no `os` module

Claude-generated strategy code must work within these constraints. Data is pre-loaded as a pandas DataFrame named `df` with columns: `open`, `high`, `low`, `close`, `volume`.

## Known IBKR API Quirks

- **Same-machine constraint**: The IBKR gateway must run on the same machine where browser authentication was performed. No cloud deployment possible.
- **OpenAPI spec errors**: The upstream spec has 351 validation errors — endpoints are implemented manually, not auto-generated.
- **Session timeout**: The auto-tickler calls `/tickle` every 60s. If Docker is stopped and restarted, re-authenticate in the browser.
- **conid vs symbol**: Most endpoints require a contract ID (`conid`), not a ticker symbol. Use `secdef/search` to resolve symbol → conid first.

## Model

Claude chat panel uses `claude-sonnet-4-6` with streaming enabled.
