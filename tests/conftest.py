import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SAMPLES = ROOT / "samples"


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test writes to its own temp folder and never touches a real key."""
    from app import config
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setenv("RECEIPT_READER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return tmp_path


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def gemini_reply(fields: dict, fenced: bool = False) -> FakeResponse:
    text = json.dumps(fields)
    if fenced:
        text = f"```json\n{text}\n```"
    return FakeResponse({"candidates": [{"content": {"parts": [{"text": text}]}}]})


@pytest.fixture
def fake_gemini(monkeypatch):
    """Replace the network call. Append dicts to .replies to script the answers."""
    from app import extract

    class Script:
        replies = []
        calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        Script.calls.append({"url": url, "headers": headers})
        return gemini_reply(Script.replies.pop(0))

    monkeypatch.setattr(extract.requests, "post", fake_post)
    return Script
