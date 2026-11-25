from datetime import date, time

import pytest

from app import extract
from tests.conftest import gemini_reply


def test_money_and_dates_become_real_numbers():
    rec = extract.clean({"date": "2026/04/03", "time": "15:05", "vendor": "  Corner  Hardware ",
                         "description": "Hex bolt M10", "subtotal": "$1,234.50", "sales_tax": "86.42",
                         "total": "1,320.92", "category": "Supplies & Materials"})
    assert rec["date"] == date(2026, 4, 3)
    assert rec["time"] == time(15, 5)
    assert rec["vendor"] == "Corner Hardware"
    assert rec["subtotal"] == 1234.5
    assert rec["total"] == 1320.92


def test_whole_amounts_stay_integers():
    assert extract.to_number("₩10,000") == 10000
    assert extract.to_number("") is None


def test_missing_total_is_added_up():
    rec = extract.clean({"date": "2026-04-02", "subtotal": "25", "sales_tax": "1.75", "category": "Meals"})
    assert rec["total"] == 26.75


def test_quantity_is_not_repeated_in_item():
    rec = extract.clean({"date": "2026-04-03", "description": "Hex bolt M10 x20", "quantity": "20",
                         "total": "9", "category": "Supplies & Materials"})
    assert rec["description"] == "Hex bolt M10"


@pytest.mark.parametrize("description, model_says, expected", [
    ("DEF fluid 2.5 gal", "Supplies & Materials", "Gas & Fuel"),
    ("Socket wrench set", "Supplies & Materials", "Tools"),
    ("Hydraulic hose", "Tools", "Supplies & Materials"),
    ("Turkey sandwich", "Meals", "Meals"),
])
def test_category_rules_override_the_model(description, model_says, expected):
    rec = extract.clean({"date": "2026-04-01", "description": description, "total": "1", "category": model_says})
    assert rec["category"] == expected


def test_unknown_category_falls_back_to_supplies():
    rec = extract.clean({"date": "2026-04-01", "description": "Mystery", "total": "1", "category": "Snacks"})
    assert rec["category"] == "Supplies & Materials"


def test_reply_wrapped_in_code_fence_still_parses():
    reply = gemini_reply({"date": "2026-04-02", "vendor": "Deli", "description": "Lunch",
                          "total": "26.75", "category": "Meals"}, fenced=True).json()
    assert extract.parse_response(reply)["total"] == 26.75


def test_key_is_sent_in_header_not_url(fake_gemini):
    fake_gemini.replies = [{"date": "2026-04-02", "vendor": "Deli", "description": "Lunch",
                            "total": "26.75", "category": "Meals"}]
    extract.call_gemini(b"image", "image/jpeg")
    call = fake_gemini.calls[0]
    assert "key=" not in call["url"]
    assert call["headers"]["x-goog-api-key"] == "test-key"


def test_missing_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(extract.ExtractionError, match="API key"):
        extract.call_gemini(b"image", "image/jpeg")
