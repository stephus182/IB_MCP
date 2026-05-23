import requests
import urllib3
from config import IBKR_GATEWAY_URL

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_session = requests.Session()
_session.verify = False  # gateway uses self-signed cert


def _load_chrome_cookies():
    """Inject Chrome's IBKR session cookies into the shared session as a raw header.

    requests silently drops cookies set for 'localhost' via the cookie jar,
    so we build the Cookie header manually instead.
    """
    try:
        import browser_cookie3
        jar = browser_cookie3.chrome(domain_name="localhost")
        # Collect all cookies — let the gateway decide what it needs
        parts = [f"{c.name}={c.value}" for c in jar]
        if parts:
            _session.headers.update({"Cookie": "; ".join(parts)})
        return len(parts)
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
