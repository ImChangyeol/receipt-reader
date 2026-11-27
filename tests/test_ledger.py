from datetime import date

import openpyxl

from app import config, extract, ledger
from tests.test_extract import HARDWARE


def receipt(day, category, total, description="Item"):
    return extract.clean({"date": day, "vendor": "Shop", "total": str(total),
                          "items": [{"description": description, "category": category}]})


def test_new_month_gets_summary_and_four_category_sheets():
    path = ledger.save_receipt(receipt("2026-04-02", "Meals", 26.75), "lunch.jpg")
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Summary", "Gas & Fuel", "Meals", "Tools", "Supplies & Materials"]
    assert path.name == "2026-04.xlsx"


def test_each_item_is_its_own_row_in_printed_order():
    path = ledger.save_receipt(extract.clean(HARDWARE), "supplies-receipt.jpg")
    ws = openpyxl.load_workbook(path)["Supplies & Materials"]
    assert ws.max_row == 6
    assert [ws.cell(r, 4).value for r in range(2, 7)][0] == "Wood screws 100 pk"
    assert ws.cell(2, 7).value == 8.97
    assert round(sum(ws.cell(r, 9).value for r in range(2, 7)), 2) == 38.43


def test_mixed_receipt_rows_go_to_their_own_sheets():
    rec = extract.clean({"date": "2026-04-18", "vendor": "Riverbend Hardware", "total": "30",
                         "items": [{"description": "Claw hammer", "amount": "18", "category": "Tools"},
                                   {"description": "Duct tape", "amount": "12", "category": "Supplies & Materials"}]})
    wb = openpyxl.load_workbook(ledger.save_receipt(rec, "mixed.jpg"))
    assert wb["Tools"].cell(2, 4).value == "Claw hammer"
    assert wb["Supplies & Materials"].cell(2, 4).value == "Duct tape"


def test_rows_are_added_to_the_same_file_newest_first():
    ledger.save_receipt(receipt("2026-04-02", "Supplies & Materials", 10), "a.jpg")
    ledger.save_receipt(receipt("2026-04-05", "Supplies & Materials", 20), "b.jpg")
    path = ledger.save_receipt(receipt("2026-04-03", "Supplies & Materials", 30), "c.jpg")
    ws = openpyxl.load_workbook(path)["Supplies & Materials"]
    days = [ws.cell(r, 1).value.date() for r in range(2, ws.max_row + 1)]
    assert days == [date(2026, 4, 5), date(2026, 4, 3), date(2026, 4, 2)]
    assert ws.cell(2, 11).value == "b.jpg"


def test_summary_totals_each_category():
    ledger.save_receipt(receipt("2026-04-02", "Gas & Fuel", 92.35), "fuel.jpg")
    ledger.save_receipt(receipt("2026-04-02", "Meals", 26.75), "lunch.jpg")
    path = ledger.save_receipt(receipt("2026-04-03", "Supplies & Materials", 50.83), "hw.jpg")
    ws = openpyxl.load_workbook(path)["Summary"]
    header = [ws.cell(3, c).value for c in range(1, 6)]
    values = [ws.cell(4, c).value for c in range(1, 6)]
    assert header == ["Gas & Fuel", "Meals", "Tools", "Supplies & Materials", "Total"]
    assert values[:4] == [92.35, 26.75, 0, 50.83]
    assert round(values[4], 2) == 169.93


def test_each_save_backs_up_the_previous_file():
    ledger.save_receipt(receipt("2026-04-02", "Meals", 1), "a.jpg")
    ledger.save_receipt(receipt("2026-04-02", "Meals", 2), "b.jpg")
    ledger.save_receipt(receipt("2026-04-02", "Meals", 3), "c.jpg")
    backups = list(config.backups_dir().glob("2026-04_*.xlsx"))
    assert len(backups) == 2  # the first save had nothing to back up


def test_old_backups_are_trimmed(monkeypatch):
    monkeypatch.setattr(ledger, "KEEP_BACKUPS", 2)
    for i in range(5):
        ledger.save_receipt(receipt("2026-04-02", "Meals", i + 1), f"{i}.jpg")
    assert len(list(config.backups_dir().glob("2026-04_*.xlsx"))) == 2


def test_receipts_from_different_months_go_to_different_files():
    a = ledger.save_receipt(receipt("2026-03-31", "Gas & Fuel", 1), "a.jpg")
    b = ledger.save_receipt(receipt("2026-04-01", "Gas & Fuel", 1), "b.jpg")
    assert (a.name, b.name) == ("2026-03.xlsx", "2026-04.xlsx")
