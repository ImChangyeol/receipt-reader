"""Paths and settings.

The API key is read from (1) the settings file saved by the web UI, or
(2) the GEMINI_API_KEY environment variable / .env file.
Neither is ever committed to git.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

SETTINGS_PATH = Path(os.getenv("RECEIPT_READER_SETTINGS", PROJECT_DIR / "settings.json"))

DEFAULT_MODEL = os.getenv("GEMINI_MODEL") or "gemini-3.1-flash-lite"
FALLBACK_MODELS = ["gemini-2.5-flash"]


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def api_key() -> str:
    key = str(load_settings().get("gemini_api_key", "")).strip()
    return key or (os.getenv("GEMINI_API_KEY") or "").strip()


def mask_key(key: str) -> str:
    return "" if not key else key[:4] + "****"


def data_dir() -> Path:
    """Root folder for ledgers, processed receipts and backups."""
    custom = str(load_settings().get("data_dir", "")).strip() or os.getenv("RECEIPT_READER_DATA_DIR", "")
    path = Path(custom).expanduser().resolve() if custom else PROJECT_DIR / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ledgers_dir() -> Path:
    return _sub("ledgers")


def processed_dir() -> Path:
    return _sub("processed")


def backups_dir() -> Path:
    return _sub("backups")


def _sub(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path
