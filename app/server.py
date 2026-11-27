"""Small local web app: drop receipts in the browser, get one Excel row per item."""

from pathlib import Path

import requests
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import config, extract, ledger
from .pdf import pdf_to_jpegs

app = FastAPI(title="Receipt Reader")
STATIC = Path(__file__).resolve().parent / "static"
MAX_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def process_file(filename: str, content: bytes) -> list[dict]:
    """Read every page of one upload and save each receipt to the ledger."""
    name = Path(filename).name  # drop any folder parts like ../
    suffix = Path(name).suffix.lower()

    if suffix == ".pdf":
        images = [(page, "image/jpeg") for page in pdf_to_jpegs(content)]
    elif suffix in IMAGE_TYPES:
        images = [(content, IMAGE_TYPES[suffix])]
    else:
        raise extract.ExtractionError("Only PDF, JPG, PNG and WEBP files are supported.")

    results = []
    for page_no, (image, mime) in enumerate(images, 1):
        receipt = extract.call_gemini(image, mime)
        path = ledger.save_receipt(receipt, name)
        results.append({
            "page": page_no,
            "categories": list(dict.fromkeys(it["category"] for it in receipt["items"])),
            "workbook": f"data/ledgers/{path.name}",
            "data": _jsonable(receipt),
        })

    (config.processed_dir() / name).write_bytes(content)
    return results


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_BYTES:
        return JSONResponse({"ok": False, "error": "File is larger than 20 MB."})
    try:
        results = process_file(file.filename or "receipt", content)
        return JSONResponse({"ok": True, "results": results})
    except PermissionError:
        return JSONResponse({"ok": False, "error": "The month's Excel file is open. Close it and try again."})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/api/settings")
def get_settings():
    key = config.api_key()
    return {"has_key": bool(key), "key_hint": config.mask_key(key), "model": config.DEFAULT_MODEL,
            "custom_data_dir": bool(config.load_settings().get("data_dir"))}


@app.post("/api/settings")
def post_settings(payload: dict):
    data = config.load_settings()
    if payload.get("gemini_api_key"):
        data["gemini_api_key"] = str(payload["gemini_api_key"]).strip()
    if "data_dir" in payload:
        folder = str(payload.get("data_dir") or "").strip()
        if folder:
            try:
                Path(folder).expanduser().mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return JSONResponse({"ok": False, "error": f"Can't use that folder: {e}"}, status_code=400)
            data["data_dir"] = folder
        else:
            data.pop("data_dir", None)
    config.save_settings(data)
    return {"ok": True}


@app.post("/api/settings/test")
def test_key(payload: dict):
    key = str(payload.get("api_key") or "").strip() or config.api_key()
    if not key:
        return {"ok": False, "error": "No API key yet."}
    try:
        res = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                           headers={"x-goog-api-key": key}, timeout=30)
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}
    if res.status_code == 200:
        return {"ok": True}
    return {"ok": False, "error": f"Gemini answered {res.status_code}. Check the key."}


def _jsonable(receipt: dict) -> dict:
    out = dict(receipt)
    out["date"] = receipt["date"].isoformat()
    out["time"] = receipt["time"].strftime("%H:%M") if receipt["time"] else ""
    return out
