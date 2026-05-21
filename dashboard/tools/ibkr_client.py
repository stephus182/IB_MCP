import requests
import urllib3
from config import IBKR_GATEWAY_URL

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_session = requests.Session()
_session.verify = False  # gateway uses self-signed cert


def _load_chrome_cookies():
    """Inject Chrome's authenticated IBKR session cookies into the shared session."""
    try:
        import browser_cookie3
        jar = browser_cookie3.chrome(domain_name="localhost")
        loaded = 0
        for c in jar:
            # Only use cookies that were set for the API path (not static assets)
            if c.path.startswith("/v1/api") or c.path == "/":
                _session.cookies.set(c.name, c.value, domain="localhost")
                loaded += 1
        return loaded
    except Exception:
        return 0


# Load cookies on module import
_load_chrome_cookies()


def _get(path: str, params: dict = None) -> dict:
    resp = _session.get(f"{IBKR_GATEWAY_URL}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def search_contract(symbol: str, sec_type: str = "STK") -> list[dict]:
    """Resolve ticker symbol to contract(s). Returns list of matches."""
    data = _get("/iserver/secdef/search", {"symbol": symbol, "secType": sec_type})
    return data if isinstance(data, list) else []


def get_market_data_history(
    conid: int,
    period: str = "1Y",
    bar: str = "1d",
    outside_rth: bool = False,
) -> dict:
    return _get(
        "/iserver/marketdata/history",
        {
            "conid": conid,
            "period": period,
            "bar": bar,
            "outsideRth": str(outside_rth).lower(),
        },
    )


def get_market_snapshot(conids: list[int], fields: list[str] = None) -> list[dict]:
    """Real-time snapshot for one or more contracts."""
    field_str = ",".join(fields or ["31", "55", "70", "71", "84", "86"])
    return _get(
        "/iserver/marketdata/snapshot",
        {"conids": ",".join(str(c) for c in conids), "fields": field_str},
    )


def ping() -> bool:
    """Check: is the IBKR gateway reachable and session active?"""
    try:
        _load_chrome_cookies()
        resp = _session.get(f"{IBKR_GATEWAY_URL}/iserver/auth/status", timeout=5)
        if resp.status_code == 401:
            return False
        data = resp.json()
        return data.get("authenticated", False)
    except Exception:
        return False


def get_accounts() -> list[dict]:
    return _get("/portfolio/accounts")


def get_account_summary(account_id: str) -> dict:
    return _get(f"/portfolio/{account_id}/summary")
