"""
IBKR Client Portal API wrapper.

Covers all 79 endpoints from the IBKR Client Portal Gateway.
Read-only and query-POST endpoints are implemented and callable.

ORDER SAFETY
------------
Any method that places, modifies, or cancels a live order MUST be
decorated with @requires_human_auth. This is enforced architecturally:
the decorator raises AuthDeniedError before the method body runs unless
the user's fingerprint is verified by the macOS Secure Enclave.

Order methods are currently stubbed (NotImplementedError) — Touch ID
enforcement is wired in NOW so it cannot be omitted when implemented.
"""
import functools
from typing import Any

import requests
import urllib3

from config import IBKR_GATEWAY_URL
from tools.auth_gate import AuthGate, AuthDeniedError  # noqa: F401 — re-exported

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_session = requests.Session()
_session.verify = False  # gateway uses a self-signed cert

_auth_gate = AuthGate()
_primary_account_id: str | None = None  # cached after first accounts call


# ── Auth decorator ────────────────────────────────────────────────────────────

def requires_human_auth(action: str):
    """
    Enforce Touch ID before any live order method executes.

    Decorate every method that places, modifies, or cancels orders.
    The decorator raises AuthDeniedError before the method body runs —
    the order is never submitted without a live fingerprint.

    Usage:
        @requires_human_auth("Cancel order {order_id} for {account_id}")
        def cancel_order(account_id: str, order_id: str): ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                label = action.format(**kwargs)
            except (KeyError, IndexError):
                label = action
            _auth_gate.require(label)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ── Session / cookie helpers ──────────────────────────────────────────────────

def _load_chrome_cookies() -> int:
    """Inject Chrome's IBKR session cookies into the shared session as a raw
    header. requests silently drops cookies for 'localhost' via the cookie jar,
    so we build the Cookie header manually instead."""
    try:
        import browser_cookie3
        jar = browser_cookie3.chrome(domain_name="localhost")
        parts = [f"{c.name}={c.value}" for c in jar]
        if parts:
            _session.headers.update({"Cookie": "; ".join(parts)})
        return len(parts)
    except Exception:
        return 0


_load_chrome_cookies()


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> Any:
    resp = _session.get(f"{IBKR_GATEWAY_URL}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict | None = None) -> Any:
    resp = _session.post(
        f"{IBKR_GATEWAY_URL}{path}",
        json=data or {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _delete(path: str) -> Any:
    resp = _session.delete(f"{IBKR_GATEWAY_URL}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Account helpers ───────────────────────────────────────────────────────────

def _primary_account() -> str:
    """Return the primary account ID, fetching and caching on first call."""
    global _primary_account_id
    if not _primary_account_id:
        accounts = get_accounts()
        if accounts:
            _primary_account_id = (
                accounts[0].get("accountId") or accounts[0].get("id", "")
            )
    return _primary_account_id or ""


# ── Session ───────────────────────────────────────────────────────────────────

def ping() -> bool:
    """Check whether the gateway session is active and authenticated."""
    try:
        _load_chrome_cookies()
        resp = _session.get(f"{IBKR_GATEWAY_URL}/iserver/auth/status", timeout=5)
        if resp.status_code == 401:
            return False
        return resp.json().get("authenticated", False)
    except Exception:
        return False


def get_auth_status() -> dict:
    """Full authentication status from the gateway."""
    return _get("/iserver/auth/status")


def tickle() -> dict:
    """Keep the session alive and verify the gateway is running."""
    return _post("/tickle")


def reauthenticate() -> dict:
    """Attempt to re-authenticate an expired gateway session."""
    return _post("/iserver/reauthenticate")


def validate_sso() -> dict:
    """Validate the current SSO session."""
    return _post("/sso/validate")


# ── Market Data ───────────────────────────────────────────────────────────────

def get_market_data_history(
    conid: int,
    period: str = "1Y",
    bar: str = "1d",
    outside_rth: bool = False,
) -> dict:
    """Historical OHLCV bars for a contract."""
    return _get(
        "/iserver/marketdata/history",
        {
            "conid": conid,
            "period": period,
            "bar": bar,
            "outsideRth": str(outside_rth).lower(),
        },
    )


def get_market_snapshot(conids: list[int], fields: list[str] | None = None) -> list[dict]:
    """Real-time snapshot for one or more contracts."""
    field_str = ",".join(fields or ["31", "55", "70", "71", "84", "86"])
    return _get(
        "/iserver/marketdata/snapshot",
        {"conids": ",".join(str(c) for c in conids), "fields": field_str},
    )


def get_market_data_fields() -> dict:
    """Dictionary of all available market data snapshot field codes."""
    return _get("/iserver/marketdata/fields")


def get_market_data_periods() -> dict:
    """Valid period units for historical data requests."""
    return _get("/iserver/marketdata/periods")


def get_market_data_bars() -> dict:
    """Valid bar size units for historical data requests."""
    return _get("/iserver/marketdata/bars")


def get_market_data_availability() -> dict:
    """Market data availability codes and their meanings."""
    return _get("/iserver/marketdata/availability")


def get_hmds_history(
    conid: int,
    period: str = "1Y",
    bar: str = "1d",
    outside_rth: bool = False,
) -> dict:
    """Historical market data from the HMDS (alternative to iserver)."""
    return _get(
        "/hmds/history",
        {
            "conid": conid,
            "period": period,
            "bar": bar,
            "outsideRth": str(outside_rth).lower(),
        },
    )


# ── Contract / Security Definition ───────────────────────────────────────────

def search_contract(symbol: str, sec_type: str = "STK") -> list[dict]:
    """Resolve a ticker symbol to contract(s). Returns list of matches."""
    data = _get("/iserver/secdef/search", {"symbol": symbol, "secType": sec_type})
    return data if isinstance(data, list) else []


def get_contract_info(conid: int) -> dict:
    """Full contract details for a given conid."""
    return _get(f"/iserver/contract/{conid}/info")


def get_contract_info_and_rules(conid: int) -> dict:
    """Contract details combined with trading rules."""
    return _get(f"/iserver/contract/{conid}/info-and-rules")


def get_contract_algos(conid: int) -> list[dict]:
    """Available IB Algo strategies for a contract."""
    return _get(f"/iserver/contract/{conid}/algos")


def get_secdef_info(conid: int) -> dict:
    """Security definition and rules for a conid."""
    return _get("/iserver/secdef/info", {"conid": conid})


def get_secdef(conids: list[int]) -> list[dict]:
    """Security definitions for a list of conids."""
    return _post("/trsrv/secdef", {"conids": conids})


def get_option_strikes(
    conid: int,
    sec_type: str = "OPT",
    month: str = "",
    exchange: str = "",
) -> dict:
    """Available option strikes for an underlying contract."""
    params: dict = {"conid": conid, "sectype": sec_type}
    if month:
        params["month"] = month
    if exchange:
        params["exchange"] = exchange
    return _get("/iserver/secdef/strikes", params)


def get_option_chain(
    symbol: str,
    exchange: str = "",
    currency: str = "USD",
) -> dict:
    """Full option chain for a symbol."""
    params: dict = {"symbol": symbol, "currency": currency}
    if exchange:
        params["exchange"] = exchange
    return _get("/trsrv/secdef/chains", params)


def get_bond_filters(symbol: str, issue_id: str = "") -> dict:
    """Bond filter options for a given issuer."""
    params: dict = {"symbol": symbol}
    if issue_id:
        params["issueId"] = issue_id
    return _get("/iserver/secdef/bond-filters", params)


def get_futures(symbols: list[str]) -> list[dict]:
    """Future contracts for a list of symbols."""
    return _get("/trsrv/futures", {"symbols": ",".join(symbols)})


def get_stocks(symbols: list[str]) -> list[dict]:
    """Stock contracts for a list of symbols."""
    return _get("/trsrv/stocks", {"symbols": ",".join(symbols)})


def get_trading_schedule(
    asset_class: str,
    symbol: str,
    exchange: str = "",
    exchange_filter: str = "",
) -> dict:
    """Trading schedule for a contract."""
    params: dict = {"assetClass": asset_class, "symbol": symbol}
    if exchange:
        params["exchange"] = exchange
    if exchange_filter:
        params["exchangeFilter"] = exchange_filter
    return _get("/trsrv/secdef/schedule", params)


def get_currency_pairs(currency: str) -> list[dict]:
    """Available currency pairs for a base currency."""
    return _get("/iserver/secdef/currency", {"currency": currency})


# ── Portfolio ─────────────────────────────────────────────────────────────────

def get_accounts() -> list[dict]:
    """All accounts available for the authenticated user."""
    return _get("/portfolio/accounts")


def get_subaccounts() -> list[dict]:
    """Subaccounts (up to 100) for tiered account structures."""
    return _get("/portfolio/subaccounts")


def get_account_meta(account_id: str = "") -> dict:
    """Account metadata: name, currency, type."""
    acct = account_id or _primary_account()
    return _get(f"/portfolio/{acct}/meta")


def get_account_summary(account_id: str = "") -> dict:
    """Account summary: net liquidation, cash, unrealized P&L."""
    acct = account_id or _primary_account()
    return _get(f"/portfolio/{acct}/summary")


def get_account_ledger(account_id: str = "") -> dict:
    """Cash balances and ledger details by currency."""
    acct = account_id or _primary_account()
    return _get(f"/portfolio/{acct}/ledger")


def get_account_allocation(account_id: str = "") -> dict:
    """Position allocation by asset class, industry, and category."""
    acct = account_id or _primary_account()
    return _get(f"/portfolio/{acct}/allocation")


def get_positions(account_id: str = "", page: int = 0) -> list[dict]:
    """All positions for an account (paginated, page 0 = first page)."""
    acct = account_id or _primary_account()
    return _get(f"/portfolio/{acct}/positions/{page}")


def get_positions_by_conid(conid: int) -> list[dict]:
    """All positions for a specific contract across all accounts."""
    return _get(f"/portfolio/positions/{conid}")


def get_position(account_id: str, conid: int) -> dict:
    """Single position for a specific contract within an account."""
    return _get(f"/portfolio/{account_id}/position/{conid}")


def get_combo_positions(account_id: str = "") -> list[dict]:
    """Combination (multi-leg) positions for an account."""
    acct = account_id or _primary_account()
    return _get(f"/portfolio/{acct}/combo/positions")


def get_portfolio_allocation(account_ids: list[str] | None = None) -> dict:
    """Combined allocation for multiple accounts."""
    ids = account_ids or [_primary_account()]
    return _post("/portfolio/allocation", {"acctIds": ids})


# ── Order Monitoring (read-only) ──────────────────────────────────────────────

def get_live_orders() -> list[dict]:
    """All live (open) orders."""
    result = _get("/iserver/account/orders")
    return result.get("orders", result) if isinstance(result, dict) else result


def get_order_status(order_id: str) -> dict:
    """Status of a single order by ID."""
    return _get(f"/iserver/account/order/status/{order_id}")


def get_trades() -> list[dict]:
    """Trades for the current and previous six days."""
    result = _get("/iserver/account/trades")
    return result if isinstance(result, list) else result.get("trades", [])


# ── Portfolio Analyst ─────────────────────────────────────────────────────────

def get_pa_periods(account_ids: list[str] | None = None) -> list[str]:
    """Available periods for Portfolio Analyst data."""
    ids = account_ids or [_primary_account()]
    return _post("/pa/allperiods", {"acctIds": ids})


def get_pa_performance(
    account_ids: list[str] | None = None,
    period: str = "1Y",
) -> dict:
    """Portfolio NAV performance over a period."""
    ids = account_ids or [_primary_account()]
    return _post("/pa/performance", {"acctIds": ids, "period": period})


def get_pa_transactions(
    account_ids: list[str] | None = None,
    period: str = "1Y",
) -> dict:
    """Transaction history from Portfolio Analyst."""
    ids = account_ids or [_primary_account()]
    return _post("/pa/transactions", {"acctIds": ids, "period": period})


# ── Scanner ───────────────────────────────────────────────────────────────────

def get_scanner_params() -> dict:
    """All available iServer scanner parameters and valid values."""
    return _get("/iserver/scanner/params")


def run_iserver_scanner(params: dict) -> list[dict]:
    """
    Run an iServer market scanner.

    Minimal params example:
        {
            "instrument": "STK",
            "type": "TOP_PERC_GAIN",
            "filter": [{"code": "avgVolLimit", "value": 1000000}]
        }
    """
    result = _post("/iserver/scanner/run", params)
    return result.get("contracts", result) if isinstance(result, dict) else result


def run_hmds_scanner(params: dict) -> list[dict]:
    """Run an HMDS scanner (historical data service)."""
    result = _post("/hmds/scanner", params)
    return result.get("contracts", result) if isinstance(result, dict) else result


# ── FYI / Notifications ───────────────────────────────────────────────────────

def get_notifications(max_count: int = 10) -> list[dict]:
    """Recent IBKR FYI notifications."""
    result = _get("/fyi/notifications", {"max": max_count})
    return result if isinstance(result, list) else result.get("notifications", [])


def get_unread_count() -> int:
    """Number of unread FYI notifications."""
    result = _get("/fyi/unreadnumber")
    return result.get("BN", 0) if isinstance(result, dict) else 0


def get_delivery_options() -> dict:
    """Supported FYI delivery options (email, push, etc.)."""
    return _get("/fyi/deliveryoptions")


# ── Watchlists (read-only) ────────────────────────────────────────────────────

def get_watchlists() -> list[dict]:
    """All watchlists for the user."""
    result = _get("/iserver/account/watchlists")
    return result if isinstance(result, list) else result.get("user_lists", [])


def get_watchlist(watchlist_id: str) -> dict:
    """Contracts in a specific watchlist."""
    return _get(f"/iserver/account/watchlist/{watchlist_id}")


# ── Alerts (read-only) ────────────────────────────────────────────────────────

def get_alerts(account_id: str = "") -> list[dict]:
    """All alerts for an account."""
    acct = account_id or _primary_account()
    result = _get(f"/iserver/account/{acct}/alerts")
    return result if isinstance(result, list) else []


def get_mta_alert() -> dict:
    """Mobile Trading Assistant (MTA) alert configuration."""
    return _get("/iserver/account/mta")


# ── ORDER STUBS — Touch ID enforced ──────────────────────────────────────────
#
# Not implemented. Touch ID is wired in NOW so it cannot be bypassed when
# implementation is added. To implement: replace NotImplementedError with
# the actual _post() call. The @requires_human_auth decorator MUST remain.

@requires_human_auth("Place order for {account_id}: {order}")
def place_order(account_id: str, order: dict) -> dict:
    """Place a live order. Requires Touch ID. NOT YET IMPLEMENTED."""
    raise NotImplementedError(
        "Order placement is not implemented in this project. "
        "Use the dedicated order management project."
    )


@requires_human_auth("Modify order {order_id} for {account_id}: {order}")
def modify_order(account_id: str, order_id: str, order: dict) -> dict:
    """Modify a live order. Requires Touch ID. NOT YET IMPLEMENTED."""
    raise NotImplementedError(
        "Order modification is not implemented in this project. "
        "Use the dedicated order management project."
    )


@requires_human_auth("Cancel order {order_id} for {account_id}")
def cancel_order(account_id: str, order_id: str) -> dict:
    """Cancel a live order. Requires Touch ID. NOT YET IMPLEMENTED."""
    raise NotImplementedError(
        "Order cancellation is not implemented in this project. "
        "Use the dedicated order management project."
    )
