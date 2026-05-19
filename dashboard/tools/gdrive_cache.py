"""
Google Drive parquet cache for IBKR historical data.

Files are stored in IBKR_cache/ folder on Drive.
Naming: {SYMBOL}_{TIMEFRAME}_{START}_{END}.parquet
Index:  manifest.json in the same folder.
"""
import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from config import (
    GDRIVE_CREDENTIALS_FILE,
    GDRIVE_SCOPES,
    GDRIVE_TOKEN_FILE,
    GOOGLE_DRIVE_FOLDER_ID,
)

_service = None
_manifest: dict = {}
_MANIFEST_NAME = "manifest.json"


def _get_service():
    global _service
    if _service:
        return _service

    creds = None
    if GDRIVE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GDRIVE_TOKEN_FILE), GDRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GDRIVE_CREDENTIALS_FILE), GDRIVE_SCOPES
            )
            creds = flow.run_local_server(port=0)
        GDRIVE_TOKEN_FILE.write_text(creds.to_json())

    _service = build("drive", "v3", credentials=creds)
    return _service


def _load_manifest() -> dict:
    global _manifest
    svc = _get_service()
    results = (
        svc.files()
        .list(
            q=f"name='{_MANIFEST_NAME}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        )
        .execute()
    )
    files = results.get("files", [])
    if not files:
        _manifest = {}
        return _manifest

    file_id = files[0]["id"]
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    _manifest = json.loads(buf.getvalue())
    return _manifest


def _save_manifest():
    svc = _get_service()
    data = json.dumps(_manifest, indent=2).encode()
    buf = io.BytesIO(data)
    media = MediaIoBaseUpload(buf, mimetype="application/json")

    results = (
        svc.files()
        .list(
            q=f"name='{_MANIFEST_NAME}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        )
        .execute()
    )
    files = results.get("files", [])
    if files:
        svc.files().update(fileId=files[0]["id"], media_body=media).execute()
    else:
        metadata = {"name": _MANIFEST_NAME, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
        svc.files().create(body=metadata, media_body=media, fields="id").execute()


def _cache_key(symbol: str, timeframe: str, start: str, end: str) -> str:
    return f"{symbol.upper()}_{timeframe.upper()}_{start}_{end}"


def _filename(key: str) -> str:
    return f"{key}.parquet"


def check_cache(symbol: str, timeframe: str, start: str, end: str) -> bool:
    """Return True if a fresh cached file exists for this symbol/timeframe/range."""
    _load_manifest()
    key = _cache_key(symbol, timeframe, start, end)
    entry = _manifest.get(key)
    if not entry:
        return False
    cached_end = datetime.strptime(entry["end"], "%Y-%m-%d").date()
    if end == "today":
        stale = cached_end < date.today() - timedelta(days=1)
    else:
        stale = False
    return not stale


def load_cache(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    """Download and return cached parquet as DataFrame."""
    key = _cache_key(symbol, timeframe, start, end)
    fname = _filename(key)
    svc = _get_service()

    results = (
        svc.files()
        .list(
            q=f"name='{fname}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        )
        .execute()
    )
    files = results.get("files", [])
    if not files:
        raise FileNotFoundError(f"Cache miss for {fname}")

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=files[0]["id"]))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return pd.read_parquet(buf)


def save_cache(df: pd.DataFrame, symbol: str, timeframe: str, start: str, end: str):
    """Upload DataFrame as parquet to Drive and update manifest."""
    key = _cache_key(symbol, timeframe, start, end)
    fname = _filename(key)
    svc = _get_service()

    buf = io.BytesIO()
    df.to_parquet(buf, index=True)
    buf.seek(0)
    media = MediaIoBaseUpload(buf, mimetype="application/octet-stream")

    results = (
        svc.files()
        .list(
            q=f"name='{fname}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id)",
        )
        .execute()
    )
    existing = results.get("files", [])
    if existing:
        svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        metadata = {"name": fname, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
        svc.files().create(body=metadata, media_body=media, fields="id").execute()

    _load_manifest()
    _manifest[key] = {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "start": start,
        "end": end if end != "today" else str(date.today()),
        "rows": len(df),
        "cached_at": datetime.utcnow().isoformat(),
    }
    _save_manifest()
