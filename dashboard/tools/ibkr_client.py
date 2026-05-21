import requests
import urllib3
from config import IBKR_GATEWAY_URL

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_session = requests.Session()
_session.verify = False  # gateway uses self-signed cert


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
    """
    Fetch OHLCV history for a contract.

    period: e.g. '1Y', '6M', '3M', '1W'
    bar:    e.g. '1d', '1h', '30min', '5min', '1min'
    """
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
        resp = _session.post(f"{IBKR_GATEWAY_URL}/tickle", timeout=5)
        if resp.status_code != 200:
            return False
        data = resp.json()
        # iserver.authStatus.authenticated == True means session is live
        return data.get("iserver", {}).get("authStatus", {}).get("authenticated", False)
    except Exception:
        return False


def get_accounts() -> list[dict]:
    return _get("/portfolio/accounts")


def get_account_summary(account_id: str) -> dict:
    return _get(f"/portfolio/{account_id}/summary")
