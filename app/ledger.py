"""Write receipts into one Excel workbook per month.

Each workbook has a Summary sheet plus one sheet per category
(Gas & Fuel, Meals, Tools, Supplies & Materials). New receipts are added to the existing
workbook, sorted newest first, and the Summary is rebuilt every time.
Before any change, the current file is copied to backups/.
"""

import shutil
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from . import config
from .extract import CATEGORIES

SUMMARY = "Summary"
COLUMNS = ["Date", "Time", "Vendor", "Description", "Qty", "Unit Price",
           "Subtotal", "Sales Tax", "Total", "Vendor Address", "Receipt File"]
WIDTHS = [12, 8, 24, 30, 7, 11, 12, 11, 12, 34, 22]
MONEY_COLS = [6, 7, 8, 9]  # 1-based
QTY_COL = 5
KEEP_BACKUPS = 30

HEADER_FILL = PatternFill("solid", fgColor="1F2937")
HEADER_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def workbook_path(day: date) -> Path:
    return config.ledgers_dir() / f"{day:%Y-%m}.xlsx"


def save_record(record: dict, source_name: str) -> Path:
    """Add one cleaned receipt to its month's workbook. Returns the file path."""
    path = workbook_path(record["date"])
    backup(path)
    wb = open_workbook(path)
    insert_newest_first(wb[record["category"]], row_values(record, source_name))
    rebuild_summary(wb, f"{record['date']:%Y-%m}")
    wb.save(path)
    return path


def backup(path: Path) -> None:
    """Copy the workbook before changing it, and keep only the newest copies."""
    if not path.exists():
        return
    folder = config.backups_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    shutil.copy2(path, folder / f"{path.stem}_{stamp}.xlsx")
    copies = sorted(folder.glob(f"{path.stem}_*.xlsx"))
    for old in copies[:-KEEP_BACKUPS]:
        old.unlink()


def open_workbook(path: Path):
    if path.exists():
        wb = openpyxl.load_workbook(path)
    else:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
    for name in CATEGORIES:
        if name not in wb.sheetnames:
            setup_sheet(wb.create_sheet(name))
    if SUMMARY not in wb.sheetnames:
        wb.create_sheet(SUMMARY, 0)
    return wb


def setup_sheet(ws) -> None:
    for col, (name, width) in enumerate(zip(COLUMNS, WIDTHS), 1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = width
    ws.freeze_panes = "A2"


def row_values(record: dict, source_name: str) -> list:
    return [record["date"], record["time"], record["vendor"], record["description"],
            record["quantity"], record["unit_price"], record["subtotal"],
            record["sales_tax"], record["total"], record["vendor_address"], source_name]


def insert_newest_first(ws, values: list) -> None:
    new_day = values[0]
    at = ws.max_row + 1
    for r in range(2, ws.max_row + 1):
        if new_day >= _as_date(ws.cell(r, 1).value):
            at = r
            break
    ws.insert_rows(at)
    for col, value in enumerate(values, 1):
        ws.cell(at, col, value)
    ws.cell(at, 1).number_format = "yyyy-mm-dd"
    ws.cell(at, 2).number_format = "hh:mm"
    for col in MONEY_COLS + [QTY_COL]:
        cell = ws.cell(at, col)
        cell.number_format = "#,##0.00" if isinstance(cell.value, float) else "#,##0"


def rebuild_summary(wb, month: str) -> None:
    ws = wb[SUMMARY]
    ws.delete_rows(1, ws.max_row)

    totals = {c: 0 for c in CATEGORIES}
    by_day = {}
    for cat in CATEGORIES:
        for row in wb[cat].iter_rows(min_row=2, values_only=True):
            amount = row[8] or 0
            day = _as_date(row[0])
            totals[cat] = round(totals[cat] + amount, 2)
            day_totals = by_day.setdefault(day, {c: 0 for c in CATEGORIES})
            day_totals[cat] = round(day_totals[cat] + amount, 2)

    ws["A1"] = f"Expense summary, {datetime.strptime(month, '%Y-%m'):%B %Y}"
    ws["A1"].font = Font(bold=True, size=13)

    _header_row(ws, 3, CATEGORIES + ["Total"])
    for i, cat in enumerate(CATEGORIES, 1):
        _money(ws.cell(4, i, totals[cat]))
    _money(ws.cell(4, len(CATEGORIES) + 1, round(sum(totals.values()), 2)))

    _header_row(ws, 6, ["Date"] + CATEGORIES + ["Daily Total"])
    r = 7
    for day in sorted(by_day, reverse=True):
        ws.cell(r, 1, day).number_format = "yyyy-mm-dd"
        ws.cell(r, 1).border = BOX
        for i, cat in enumerate(CATEGORIES, 2):
            _money(ws.cell(r, i, by_day[day][cat]))
        _money(ws.cell(r, len(CATEGORIES) + 2, round(sum(by_day[day].values()), 2)))
        r += 1

    for col in "ABCDEF":
        ws.column_dimensions[col].width = 20


def _header_row(ws, row: int, labels: list) -> None:
    for i, label in enumerate(labels, 1):
        cell = ws.cell(row, i, label)
        cell.font, cell.border = Font(bold=True), BOX
        cell.alignment = Alignment(horizontal="center")


def _money(cell) -> None:
    cell.number_format = "#,##0.00" if isinstance(cell.value, float) and not cell.value.is_integer() else "#,##0"
    cell.border = BOX


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.min
