"""Turn each page of a PDF into a JPEG so the model can read it.

Uses pypdfium2, which installs with pip. No separate PDF tool is needed.
"""

import io

import pypdfium2 as pdfium


def pdf_to_jpegs(pdf_bytes: bytes, scale: float = 2.0) -> list[bytes]:
    pages = []
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        for page in pdf:
            image = page.render(scale=scale).to_pil().convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=90)
            pages.append(buf.getvalue())
    finally:
        pdf.close()
    return pages
