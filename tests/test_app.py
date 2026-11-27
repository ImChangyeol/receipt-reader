import pytest

pytest.importorskip("fastapi")

from app import config  # noqa: E402
from app.server import process_file  # noqa: E402
from tests.conftest import SAMPLES  # noqa: E402

LUNCH = {"date": "2026-04-02", "time": "12:31", "vendor": "Maple Street Deli",
         "subtotal": "25.00", "sales_tax": "1.75", "total": "26.75",
         "items": [{"description": "Turkey sandwich", "quantity": "2", "unit_price": "9.50", "amount": "19.00", "category": "Meals"},
                   {"description": "Iced tea", "quantity": "2", "unit_price": "3.00", "amount": "6.00", "category": "Meals"}]}
TOOL = {"date": "2026-04-05", "time": "10:12", "vendor": "Corner Hardware Co.",
        "subtotal": "64.00", "sales_tax": "4.48", "total": "68.48",
        "items": [{"description": "Socket wrench set", "amount": "64.00", "category": "Tools"}]}


def test_image_upload_lands_in_the_ledger(fake_gemini):
    fake_gemini.replies = [LUNCH]
    results = process_file("lunch-receipt.jpg", (SAMPLES / "lunch-receipt.jpg").read_bytes())
    assert results[0]["categories"] == ["Meals"]
    assert len(results[0]["data"]["items"]) == 2
    assert results[0]["workbook"] == "data/ledgers/2026-04.xlsx"
    assert (config.processed_dir() / "lunch-receipt.jpg").exists()


def test_each_pdf_page_is_its_own_receipt(fake_gemini):
    fake_gemini.replies = [LUNCH, TOOL]
    results = process_file("two-receipts.pdf", (SAMPLES / "two-receipts.pdf").read_bytes())
    assert [r["categories"] for r in results] == [["Meals"], ["Tools"]]
    assert len(fake_gemini.calls) == 2


def test_file_name_cannot_escape_the_data_folder(fake_gemini, tmp_path):
    fake_gemini.replies = [LUNCH]
    process_file("../../evil.jpg", (SAMPLES / "lunch-receipt.jpg").read_bytes())
    assert (config.processed_dir() / "evil.jpg").exists()
    assert not (tmp_path.parent / "evil.jpg").exists()


def test_unsupported_file_type_is_rejected(fake_gemini):
    with pytest.raises(Exception, match="supported"):
        process_file("notes.txt", b"hello")
