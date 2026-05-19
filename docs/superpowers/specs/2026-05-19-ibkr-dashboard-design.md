# IBKR MCP Research Dashboard — Design Spec & Implementation Plan

## Context

Setting up a personal trading research environment centred on Interactive Brokers data access, strategy backtesting, and market analysis — with Claude as the AI layer. The project forks an existing open-source IBKR MCP server (rcontesti/IB_MCP) into the user's personal GitHub, extends it with a Streamlit dashboard, and wires in Google Drive for cross-machine data caching and TradingView Pro for charting.

**Priorities (in order):** market data access → data analysis → backtesting. Live position/P&L widgets are explicitly out of scope for this phase.

---

## Approved Design

### Layout
Hybrid split dashboard:
- **Left panel**: TradingView Advanced Chart Widget (Pro account iframe, auto-follows symbol Claude is discussing)
- **Right panel**: Claude AI chat (tool use, streaming, inline Plotly charts)
- Either panel independently expandable to full-screen (⤢ button or `F` key), `Esc` to return to split

### Tech stack
- **UI**: Streamlit (Python) — `dashboard/app.py`
- **AI**: Anthropic SDK with tool use — `claude-sonnet-4-6`
- **Data source**: IBKR MCP server (Docker) via HTTP
- **Cache**: Google Drive folder `IBKR_cache/` — parquet files, shared across machines
- **Charts in chat**: Plotly rendered inline in Streamlit
- **Backtests**: sandboxed Python executor (no network, no file writes)
- **Platform**: local-only (Mac and PC compatible, Docker + WSL2 on Windows)

---

## Architecture

```
Browser (localhost:8501)
├── Left:  TradingView Advanced Chart Widget (Pro auth iframe)
└── Right: Claude AI Chat Panel (Anthropic SDK streaming)

Streamlit Backend (Python)
├── ibkr_client.py     → HTTP calls to MCP server
├── gdrive_cache.py    → Google Drive API read/write parquet
├── backtest.py        → sandboxed strategy executor
└── config.py          → API keys, MCP URL, model settings

Docker Compose (forked IB_MCP repo)
├── IB Client Portal Gateway  (Java, browser-authenticated)
├── Auto-tickler              (session keepalive)
└── FastMCP Server            (Python/FastAPI, 9 ready endpoints)
```

**Constraint:** IBKR gateway must run on the same machine as the browser auth. Local-only stack, no cloud deployment.

---

## Project Structure

```
IBKR_mcp/                          ← forked from rcontesti/IB_MCP
├── api_gateway/                   # existing — unchanged
├── mcp_server/                    # existing — unchanged
│   └── routers/
├── dashboard/                     # NEW
│   ├── app.py                     # entry point: hybrid layout + panel toggle
│   ├── components/
│   │   ├── tradingview.py         # TV Advanced Chart Widget HTML component
│   │   └── chat.py                # Claude API chat panel + streaming
│   ├── tools/
│   │   ├── ibkr_client.py         # wraps MCP server endpoints
│   │   ├── gdrive_cache.py        # Google Drive parquet cache
│   │   └── backtest.py            # sandboxed Python executor
│   ├── requirements.txt
│   └── config.py
├── docs/
│   └── superpowers/specs/
│       └── 2026-05-19-ibkr-dashboard-design.md
├── CLAUDE.md                      # NEW
├── docker-compose.yml             # existing — unchanged
└── .env                           # extended: + ANTHROPIC_API_KEY + GOOGLE_DRIVE_FOLDER_ID
```

---

## Component Details

### `dashboard/components/tradingview.py`
- Renders the official TradingView Advanced Chart Widget via `st.components.v1.html()`
- iframe allows Pro account login to persist (user stays logged in, saved layouts + indicators work)
- Accepts a `symbol` prop — updated from the chat panel whenever Claude mentions a ticker
- Full-screen toggle via CSS class swap + custom JS injected into the component

### `dashboard/components/chat.py`
- Streamlit chat interface using `st.chat_input` / `st.chat_message`
- Anthropic SDK with streaming (`stream=True`)
- Tool use definitions exposed to Claude:
  - `fetch_market_data(symbol, period, bar)` → calls IBKR MCP, caches to Drive
  - `check_cache(symbol, period)` → checks Drive manifest before fetching
  - `run_backtest(code, data_key)` → executes strategy in sandbox
  - `get_portfolio_summary()` → IBKR portfolio endpoint (background context only)
- Conversation history held in `st.session_state`
- Plotly figures returned by tools rendered inline via `st.plotly_chart()`

### `dashboard/tools/gdrive_cache.py`
- Google Drive API (google-api-python-client) authenticated via **OAuth2** (google-auth-oauthlib) — uses your existing Google account, one-time browser consent on first run, token saved locally
- Drive folder: `IBKR_cache/` (folder ID stored in `.env`)
- File naming: `{SYMBOL}_{TIMEFRAME}_{START}_{END}.parquet`
- `manifest.json` in the folder: index of cached files with date ranges
- Cache check: if end date < today − 1 day, re-fetches tail and appends
- Same folder shared across Mac and PC — no machine-specific paths

### `dashboard/tools/backtest.py`
- Receives Claude-generated Python code as a string
- Executes in a `RestrictedPython` sandbox (no network, no `open()`, no `os` module)
- Allowed imports: `pandas`, `numpy`, `plotly`
- Returns: `{ total_return, sharpe, max_drawdown, num_trades, equity_curve (DataFrame) }`
- Equity curve passed back to chat panel as a Plotly figure

### `CLAUDE.md`
Documents for future Claude Code sessions:
- How to start Docker (`docker compose up --build`)
- Browser auth URL for IBKR gateway
- MCP server base URL and available endpoints (with status)
- How to start the Streamlit app
- `.env` keys required
- Google Drive folder structure
- Backtest sandbox constraints
- Known IBKR API quirks (351 OpenAPI spec errors, same-machine auth constraint)

---

## Google Drive Cache Flow

```
User asks Claude about AAPL 2022–2024
  → check_cache("AAPL", "1D", "2022", "2024")
      HIT  → load AAPL_1D_2022-2024.parquet from Drive
      MISS → fetch_market_data from IBKR MCP
               → save AAPL_1D_2022-2024.parquet to Drive
               → update manifest.json
  → Claude writes Python strategy
  → run_backtest(code, "AAPL_1D_2022-2024")
  → return metrics + equity curve
  → TradingView panel switches to AAPL
```

---

## Additional IBKR MCP Uses (beyond user's original three)

These can be added incrementally as the platform matures:
- **Options chain analysis** — Greeks, expiry scanning (endpoint exists, untested)
- **Scanner/screener automation** — find stocks matching criteria
- **FYI/notification triage** — Claude filters IBKR noise into summaries
- **Risk dashboard** — position sizing, drawdown tracking (low-priority per user)
- **Multi-account aggregation** — subaccounts endpoint available
- **Tax-loss harvesting** — wash-sale candidate detection from trade history

---

## Implementation Steps

### Phase 1 — Repository Setup
1. Fork `rcontesti/IB_MCP` to `github.com/stephus182` (personal GitHub) — repo will be at `https://github.com/stephus182/IB_MCP`
2. Clone locally to `/Users/steph/Claude_Projects/IBKR_mcp`
3. Create `dashboard/` directory structure
4. Create `CLAUDE.md` with project context
5. Extend `.env.example` with `ANTHROPIC_API_KEY` and `GOOGLE_DRIVE_FOLDER_ID`
6. Add `.superpowers/` to `.gitignore`
7. Write spec doc to `docs/superpowers/specs/2026-05-19-ibkr-dashboard-design.md`
8. Initial commit and push to personal GitHub

### Phase 2 — Google Drive Cache Layer
9. Enable Google Drive API in Google Cloud Console, create OAuth2 credentials (Desktop app type), download `credentials.json`
10. Implement `gdrive_cache.py`: OAuth2 flow on first run → saves `token.json` locally; upload, download, manifest read/write
11. Unit test: cache miss → IBKR fetch → Drive write → cache hit on second call

### Phase 3 — IBKR MCP Client
12. Implement `ibkr_client.py` wrapping the 9 production-ready endpoints
13. Focus on: `marketdata/history`, `marketdata/snapshot`, `secdef/search`
14. Test against live Docker stack

### Phase 4 — Backtest Runner
15. Implement sandboxed executor in `backtest.py` using `RestrictedPython`
16. Define allowed builtins and imports
17. Test with a simple SMA crossover strategy on cached AAPL data

### Phase 5 — Streamlit Dashboard
18. Build `app.py` hybrid layout: two-column split with custom CSS
19. Implement full-screen toggle (CSS + JS injected via `st.components`)
20. Implement `tradingview.py` HTML component with symbol prop
21. Implement `chat.py` Claude chat panel with tool use and streaming
22. Wire tool results (charts, metrics) back to UI
23. Wire TradingView symbol to Claude's current focus ticker

### Phase 6 — Integration & Polish
24. End-to-end test: Docker up → auth → Streamlit → ask Claude to backtest → verify Drive cache populated → verify chart and results render
25. Test full-screen toggle on both panels
26. Test from a second machine (verify Drive cache is shared)
27. Push final code to personal GitHub

---

## Critical Files to Create/Modify

| File | Action | Notes |
|---|---|---|
| `CLAUDE.md` | Create | Project context for Claude Code sessions |
| `dashboard/app.py` | Create | Streamlit entry point, hybrid layout |
| `dashboard/components/tradingview.py` | Create | TV Advanced Chart Widget embed |
| `dashboard/components/chat.py` | Create | Claude API chat + tool use |
| `dashboard/tools/ibkr_client.py` | Create | MCP HTTP client wrapper |
| `dashboard/tools/gdrive_cache.py` | Create | Google Drive parquet cache |
| `dashboard/tools/backtest.py` | Create | RestrictedPython sandbox executor |
| `dashboard/config.py` | Create | Config, env var loading |
| `dashboard/requirements.txt` | Create | streamlit, anthropic, google-api-python-client, pandas, numpy, plotly, RestrictedPython, pyarrow |
| `.env.example` | Modify | Add ANTHROPIC_API_KEY, GOOGLE_DRIVE_FOLDER_ID |
| `.gitignore` | Modify | Add .superpowers/, .env, *.parquet |
| `docker-compose.yml` | No change | Existing setup unchanged |

---

## Verification

End-to-end test sequence:
1. `docker compose up --build` — containers start, authenticate in browser at gateway URL
2. `cd dashboard && pip install -r requirements.txt && streamlit run app.py`
3. Open `localhost:8501` — hybrid layout loads, TradingView chart visible on left
4. Type: *"Fetch AAPL daily data for 2023"* → Claude calls `fetch_market_data` → parquet saved to Google Drive → confirm file appears in `IBKR_cache/` folder
5. Repeat same request → Claude calls `check_cache` → Drive HIT → no IBKR call made
6. Type: *"Backtest a 20/50 EMA crossover on that data"* → Claude writes code → `run_backtest` executes → equity curve renders inline in chat
7. Verify TradingView panel auto-switched to AAPL
8. Click ⤢ on chart panel → full-screen TradingView → press Esc → split view returns
9. Click ⤢ on AI panel → full-screen Claude chat → press Esc → split view returns
10. Open Drive folder from a second machine → confirm parquet files accessible
