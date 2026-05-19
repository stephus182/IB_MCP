import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_DRIVE_FOLDER_ID = os.environ["GOOGLE_DRIVE_FOLDER_ID"]

MCP_BASE_URL = (
    f"https://localhost:{os.getenv('MCP_SERVER_PORT', '5002')}"
)
ANTHROPIC_MODEL = "claude-sonnet-4-6"

GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
GDRIVE_CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"
GDRIVE_TOKEN_FILE = Path(__file__).parent / "token.json"
