"""Read one receipt image with Gemini and return clean, typed fields."""

import base64
import json
import re
import time as _time
from datetime import date, datetime

import requests

from . import config

CATEGORIES = ["Gas & Fuel", "Meals", "Tools", "Supplies & Materials"]
FIELDS = ["date", "time", "vendor", "description", "quantity", "unit_price",
          "subtotal", "sales_tax", "total", "vendor_address", "category"]

PROMPT = """You read receipts for a small business expense ledger. Look at the receipt image and fill in the fields.

Rules
- date: the purchase date as YYYY-MM-DD. Empty if not printed.
- time: 24-hour HH:MM. Empty if not printed.
- vendor: the store or business name.
- description: what was bought, in a few words. Do not repeat the quantity here.
- quantity, unit_price: numbers only, if the receipt shows them.
- subtotal, sales_tax, total: numbers only, no currency signs or commas. total is the amount actually paid after discounts.
- vendor_address: the store address as printed, or empty.
- category: exactly one of "Gas & Fuel", "Meals", "Tools", "Supplies & Materials".
  Gas & Fuel = gasoline, diesel, kerosene, and diesel exhaust fluid (DEF, AdBlue, urea).
  Meals = food and drinks.
  Tools = hand tools that are used again and again, like hammers, wrenches, drills, saws.
  Supplies & Materials = things that get used up or installed, like bolts, nuts, filters, hoses, tape, cleaning supplies.
Keep the text in the language printed on the receipt."""

# Gemini structured output: the model must answer with this JSON shape.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "date": {"type": "STRING"},
        "time": {"type": "STRING"},
        "vendor": {"type": "STRING"},
        "description": {"type": "STRING"},
        "quantity": {"type": "STRING"},
        "unit_price": {"type": "STRING"},
        "subtotal": {"type": "STRING"},
        "sales_tax": {"type": "STRING"},
        "total": {"type": "STRING"},
        "vendor_address": {"type": "STRING"},
        "category": {"type": "STRING", "enum": CATEGORIES},
    },
    "required": ["date", "vendor", "description", "total", "category"],
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
    """Turn the model's strings into typed values the ledger can trust."""
    out = {f: str(raw.get(f, "") or "").strip() for f in FIELDS}

    record = {
        "date": parse_date(out["date"]) or date.today(),
        "time": parse_time(out["time"]),
        "vendor": _squash(out["vendor"]),
        "description": _squash(out["description"]),
        "quantity": to_number(out["quantity"]),
        "unit_price": to_number(out["unit_price"]),
        "subtotal": to_number(out["subtotal"]),
        "sales_tax": to_number(out["sales_tax"]),
        "total": to_number(out["total"]),
        "vendor_address": _squash(out["vendor_address"]),
    }

    # If the total is missing but its parts are there, add them up.
    if record["total"] is None and (record["subtotal"] or record["sales_tax"]):
        record["total"] = round((record["subtotal"] or 0) + (record["sales_tax"] or 0), 2)

    record["description"] = strip_repeated_quantity(record["description"], record["quantity"])
    category = out["category"] if out["category"] in CATEGORIES else "Supplies & Materials"
    record["category"] = apply_category_rules(record, category)
    return record


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
SUPPLY_WORDS = re.compile(r"\b(bolt|nut|screw|washer|rivet|filter|hose|gasket|o-ring|tape)s?\b", re.I)


def apply_category_rules(record: dict, category: str) -> str:
    """A few fixed rules that override the model when it is unsure."""
    text = f"{record['vendor']} {record['description']}"
    if FUEL_WORDS.search(text):
        return "Gas & Fuel"
    if category in ("Tools", "Supplies & Materials"):
        if TOOL_WORDS.search(record["description"]):
            return "Tools"
        if SUPPLY_WORDS.search(record["description"]):
            return "Supplies & Materials"
    return category


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _unique(items):
    seen = set()
    return [x for x in items if x and not (x in seen or seen.add(x))]

