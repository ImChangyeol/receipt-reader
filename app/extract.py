"""Read one receipt image with Gemini and return clean, typed fields."""

import base64
import json
import re
import time as _time
from datetime import date, datetime

import requests

from . import config

CATEGORIES = ["Gas & Fuel", "Meals", "Tools", "Supplies & Materials"]
RECEIPT_FIELDS = ["date", "time", "vendor", "vendor_address", "subtotal", "sales_tax", "total"]
ITEM_FIELDS = ["description", "quantity", "unit_price", "amount", "category"]

PROMPT = """You read receipts for a small business expense ledger. Look at the receipt image and fill in the fields.

Rules
- date: the purchase date as YYYY-MM-DD. Empty if not printed.
- time: 24-hour HH:MM. Empty if not printed.
- vendor: the store or business name.
- vendor_address: the store address as printed, or empty.
- subtotal, sales_tax, total: numbers only, no currency signs or commas. total is the amount actually paid after discounts.
- items: one entry for every product line on the receipt, in the printed order.
  - description: what the line is, in a few words. Do not repeat the quantity here.
  - quantity, unit_price, amount: numbers only, if the receipt shows them. amount is the line total.
  - category: exactly one of "Gas & Fuel", "Meals", "Tools", "Supplies & Materials".
    Gas & Fuel = gasoline, diesel, kerosene, and diesel exhaust fluid (DEF, AdBlue, urea).
    Meals = food and drinks.
    Tools = hand tools that are used again and again, like hammers, wrenches, drills, saws.
    Supplies & Materials = things that get used up or installed, like screws, tape, light bulbs, filters, cleaning supplies.
Keep the text in the language printed on the receipt."""

# Gemini structured output: the model must answer with this JSON shape.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "date": {"type": "STRING"},
        "time": {"type": "STRING"},
        "vendor": {"type": "STRING"},
        "vendor_address": {"type": "STRING"},
        "subtotal": {"type": "STRING"},
        "sales_tax": {"type": "STRING"},
        "total": {"type": "STRING"},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "description": {"type": "STRING"},
                    "quantity": {"type": "STRING"},
                    "unit_price": {"type": "STRING"},
                    "amount": {"type": "STRING"},
                    "category": {"type": "STRING", "enum": CATEGORIES},
                },
                "required": ["description", "category"],
            },
        },
    },
    "required": ["date", "vendor", "items", "total"],
}

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class ExtractionError(Exception):
    pass


# ---------- calling the model ----------

def call_gemini(image_bytes: bytes, mime_type: str) -> dict:
    key = config.api_key()
    if not key:
        raise ExtractionError("No Gemini API key. Add one in Settings or in the .env file.")

    body = {
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode()}},
        ]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "temperature": 0,
        },
    }
    # The key goes in a header, not the URL, so it never shows up in logs.
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    last_error = "Gemini request failed"
    for model in _unique([config.DEFAULT_MODEL, *config.FALLBACK_MODELS]):
        for attempt in range(2):
            try:
                result = requests.post(API_URL.format(model=model), json=body, headers=headers, timeout=60).json()
            except (requests.RequestException, ValueError) as e:
                last_error = f"{model}: {e}"
                break
            err = result.get("error")
            if not err:
                return parse_response(result)
            last_error = f"{model}: {err.get('code')} {err.get('message', '')}"
            if err.get("code") in (429, 503) and attempt == 0:
                _time.sleep(1.5)  # busy or rate limited, try once more
                continue
            break
    raise ExtractionError(last_error)


def parse_response(result: dict) -> dict:
    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise ExtractionError("Gemini returned no text")
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        raw = json.loads(text)
    except ValueError as e:
        raise ExtractionError(f"Gemini did not return valid JSON: {e}")
    return clean(raw)


# ---------- cleaning the model's answer ----------

def clean(raw: dict) -> dict:
    """Turn the model's strings into a receipt with typed values the ledger can trust.

    The result has the receipt-level fields plus an "items" list. Every item gets its
    own category and its share of the sales tax and total, so the rows of one receipt
    always add up to the receipt total.
    """
    out = {f: str(raw.get(f, "") or "").strip() for f in RECEIPT_FIELDS}
    receipt = {
        "date": parse_date(out["date"]) or date.today(),
        "time": parse_time(out["time"]),
        "vendor": _squash(out["vendor"]),
        "vendor_address": _squash(out["vendor_address"]),
        "subtotal": to_number(out["subtotal"]),
        "sales_tax": to_number(out["sales_tax"]),
        "total": to_number(out["total"]),
    }

    raw_items = raw.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        # Older single-line answers: treat the whole receipt as one item.
        raw_items = [{"description": raw.get("description", ""), "quantity": raw.get("quantity", ""),
                      "unit_price": raw.get("unit_price", ""), "amount": raw.get("amount", ""),
                      "category": raw.get("category", "")}]
    items = [_clean_item(it, receipt["vendor"]) for it in raw_items if isinstance(it, dict)]
    items = [it for it in items if it["description"] or it["amount"] is not None] or [_clean_item({}, receipt["vendor"])]

    _fill_receipt_numbers(receipt, items)
    _split_tax_and_total(receipt, items)
    receipt["items"] = items
    return receipt


def _clean_item(raw: dict, vendor: str) -> dict:
    f = {k: str(raw.get(k, "") or "").strip() for k in ITEM_FIELDS}
    item = {
        "description": _squash(f["description"]),
        "quantity": to_number(f["quantity"]),
        "unit_price": to_number(f["unit_price"]),
        "amount": to_number(f["amount"]),
    }
    if item["amount"] is None and item["quantity"] is not None and item["unit_price"] is not None:
        item["amount"] = round(item["quantity"] * item["unit_price"], 2)
    if item["quantity"] is None and item["amount"] is not None:
        # A line with only a price is one of that thing.
        item["quantity"] = 1
        item["unit_price"] = item["unit_price"] if item["unit_price"] is not None else item["amount"]
    item["description"] = strip_repeated_quantity(item["description"], item["quantity"])
    category = f["category"] if f["category"] in CATEGORIES else "Supplies & Materials"
    item["category"] = apply_category_rules(item, vendor, category)
    return item


def _fill_receipt_numbers(receipt: dict, items: list) -> None:
    """Fill a missing subtotal, tax, total, or single item amount from the numbers that are there."""
    amounts = [it["amount"] for it in items]
    if receipt["subtotal"] is None and items and None not in amounts:
        receipt["subtotal"] = round(sum(amounts), 2)
    if receipt["sales_tax"] is None and receipt["subtotal"] is not None and receipt["total"] is not None:
        tax = round(receipt["total"] - receipt["subtotal"], 2)
        receipt["sales_tax"] = tax if tax >= 0 else None
    if receipt["total"] is None and (receipt["subtotal"] or receipt["sales_tax"]):
        receipt["total"] = round((receipt["subtotal"] or 0) + (receipt["sales_tax"] or 0), 2)
    if len(items) == 1 and items[0]["amount"] is None:
        if receipt["subtotal"] is not None:
            items[0]["amount"] = receipt["subtotal"]
        elif receipt["total"] is not None:
            items[0]["amount"] = round(receipt["total"] - (receipt["sales_tax"] or 0), 2)


def _split_tax_and_total(receipt: dict, items: list) -> None:
    """Give each item its share of the receipt's tax and total, in proportion to its amount."""
    amounts = [it["amount"] for it in items]
    base = sum(a for a in amounts if a is not None)
    if None in amounts or base <= 0:
        # Can't split fairly, so the whole receipt goes on the first row.
        for i, it in enumerate(items):
            it["sales_tax"] = receipt["sales_tax"] if i == 0 else None
            it["total"] = receipt["total"] if i == 0 else None
        return
    total = receipt["total"] if receipt["total"] is not None else round(base + (receipt["sales_tax"] or 0), 2)
    for key, whole in (("sales_tax", receipt["sales_tax"] or 0), ("total", total)):
        shares = [round(whole * a / base, 2) for a in amounts]
        shares[-1] = round(whole - sum(shares[:-1]), 2)  # last row takes the rounding cents
        for it, share in zip(items, shares):
            it[key] = _tidy(share)


def _tidy(num):
    return int(num) if float(num).is_integer() else round(num, 2)


def parse_date(value: str):
    text = value.strip().replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%m-%d-%Y", "%y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(value: str):
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).time()
        except ValueError:
            continue
    return None


def to_number(value):
    """'$1,234.50' -> 1234.5, '₩10,000' -> 10000, '' -> None."""
    text = re.sub(r"[^0-9.\-]", "", str(value or ""))
    if text in ("", "-", ".", "-."):
        return None
    try:
        num = float(text)
    except ValueError:
        return None
    return int(num) if num.is_integer() else round(num, 2)


def strip_repeated_quantity(item: str, quantity) -> str:
    """'Hex bolt M10 20' with quantity 20 -> 'Hex bolt M10'."""
    if not item or quantity is None:
        return item
    q = str(quantity)
    for suffix in (q, f"x{q}", f"X{q}", f"x {q}", f"{q}ea", f"{q} pcs"):
        if item.endswith(" " + suffix):
            return item[: -len(suffix)].rstrip()
    return item


FUEL_WORDS = re.compile(r"\b(def|adblue|urea|diesel exhaust fluid)\b", re.I)
TOOL_WORDS = re.compile(r"\b(hammer|wrench|spanner|socket set|screwdriver|pliers|saw|drill|grinder|tape measure)\b", re.I)
SUPPLY_WORDS = re.compile(r"\b(bolt|nut|screw|washer|rivet|filter|hose|gasket|o-ring|tape|bulb|zip tie|sandpaper)s?\b", re.I)


def apply_category_rules(item: dict, vendor: str, category: str) -> str:
    """A few fixed rules that override the model when it is unsure."""
    if FUEL_WORDS.search(f"{vendor} {item['description']}"):
        return "Gas & Fuel"
    if category in ("Tools", "Supplies & Materials"):
        if TOOL_WORDS.search(item["description"]):
            return "Tools"
        if SUPPLY_WORDS.search(item["description"]):
            return "Supplies & Materials"
    return category


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _unique(items):
    seen = set()
    return [x for x in items if x and not (x in seen or seen.add(x))]

