from datetime import date, time

import pytest

from app import extract
from tests.conftest import gemini_reply

HARDWARE = {
    "date": "2026-04-22", "time": "14:15", "vendor": "Riverbend Hardware",
    "subtotal": "35.92", "sales_tax": "2.51", "total": "38.43",
    "items": [
        {"description": "Wood screws 100 pk", "quantity": "1", "unit_price": "8.97", "amount": "8.97", "category": "Supplies & Materials"},
        {"description": "Duct tape 2 in", "amount": "6.99", "category": "Supplies & Materials"},
        {"description": "LED light bulbs 4 pk", "amount": "9.98", "category": "Supplies & Materials"},
        {"description": "Sandpaper 5 pk", "amount": "4.49", "category": "Supplies & Materials"},
        {"description": "Zip ties 100 pk", "amount": "5.49", "category": "Supplies & Materials"},
    ],
}


def test_money_and_dates_become_real_numbers():
    rec = extract.clean({"date": "2026/04/03", "time": "15:05", "vendor": "  Corner  Hardware ",
                         "subtotal": "$1,234.50", "sales_tax": "86.42", "total": "1,320.92",
                         "items": [{"description": "Hex bolt M10", "amount": "1,234.50", "category": "Supplies & Materials"}]})
    assert rec["date"] == date(2026, 4, 3)
    assert rec["time"] == time(15, 5)
    assert rec["vendor"] == "Corner Hardware"
    assert rec["subtotal"] == 1234.5
    assert rec["total"] == 1320.92


def test_every_item_becomes_its_own_line():
    rec = extract.clean(HARDWARE)
    assert [it["description"] for it in rec["items"]] == [
        "Wood screws 100 pk", "Duct tape 2 in", "LED light bulbs 4 pk", "Sandpaper 5 pk", "Zip ties 100 pk"]
    assert rec["items"][0]["quantity"] == 1
    assert rec["items"][0]["unit_price"] == 8.97


def test_item_totals_add_up_to_the_receipt_total():
    rec = extract.clean(HARDWARE)
    assert round(sum(it["total"] for it in rec["items"]), 2) == 38.43
    assert round(sum(it["sales_tax"] for it in rec["items"]), 2) == 2.51


def test_missing_tax_is_worked_out_from_subtotal_and_total():
    reply = dict(HARDWARE, sales_tax="")
    rec = extract.clean(reply)
    assert rec["sales_tax"] == 2.51


def test_missing_total_is_added_up():
    rec = extract.clean({"date": "2026-04-02", "subtotal": "25", "sales_tax": "1.75",
                         "items": [{"description": "Lunch", "category": "Meals"}]})
    assert rec["total"] == 26.75
    assert rec["items"][0]["amount"] == 25


def test_amount_comes_from_quantity_times_price():
    rec = extract.clean({"date": "2026-04-03", "total": "9",
                         "items": [{"description": "Hex bolt M10", "quantity": "20", "unit_price": "0.45",
                                    "category": "Supplies & Materials"}]})
    assert rec["items"][0]["amount"] == 9


def test_quantity_is_not_repeated_in_item():
    rec = extract.clean({"date": "2026-04-03", "total": "9",
                         "items": [{"description": "Hex bolt M10 x20", "quantity": "20", "category": "Supplies & Materials"}]})
    assert rec["items"][0]["description"] == "Hex bolt M10"


def test_tools_and_supplies_on_one_receipt_get_split():
    rec = extract.clean({"date": "2026-04-18", "vendor": "Riverbend Hardware", "total": "30",
                         "items": [{"description": "Claw hammer 16 oz", "amount": "18", "category": "Supplies & Materials"},
                                   {"description": "Duct tape", "amount": "12", "category": "Tools"}]})
    assert [it["category"] for it in rec["items"]] == ["Tools", "Supplies & Materials"]


@pytest.mark.parametrize("description, model_says, expected", [
    ("DEF fluid 2.5 gal", "Supplies & Materials", "Gas & Fuel"),
    ("Socket wrench set", "Supplies & Materials", "Tools"),
    ("Hydraulic hose", "Tools", "Supplies & Materials"),
    ("Turkey sandwich", "Meals", "Meals"),
])
def test_category_rules_override_the_model(description, model_says, expected):
    rec = extract.clean({"date": "2026-04-01", "total": "1",
                         "items": [{"description": description, "category": model_says}]})
    assert rec["items"][0]["category"] == expected


def test_unknown_category_falls_back_to_supplies():
    rec = extract.clean({"date": "2026-04-01", "total": "1", "items": [{"description": "Mystery", "category": "Snacks"}]})
    assert rec["items"][0]["category"] == "Supplies & Materials"


def test_answer_without_items_still_becomes_one_line():
    rec = extract.clean({"date": "2026-04-02", "vendor": "Deli", "description": "Lunch",
                         "total": "26.75", "category": "Meals"})
    assert len(rec["items"]) == 1
    assert rec["items"][0]["total"] == 26.75


def test_reply_wrapped_in_code_fence_still_parses():
    reply = gemini_reply({"date": "2026-04-02", "vendor": "Deli", "total": "26.75",
                          "items": [{"description": "Lunch", "category": "Meals"}]}, fenced=True).json()
    assert extract.parse_response(reply)["total"] == 26.75


def test_key_is_sent_in_header_not_url(fake_gemini):
    fake_gemini.replies = [{"date": "2026-04-02", "vendor": "Deli", "total": "26.75",
                            "items": [{"description": "Lunch", "category": "Meals"}]}]
    extract.call_gemini(b"image", "image/jpeg")
    call = fake_gemini.calls[0]
    assert "key=" not in call["url"]
    assert call["headers"]["x-goog-api-key"] == "test-key"


def test_missing_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(extract.ExtractionError, match="API key"):
        extract.call_gemini(b"image", "image/jpeg")
