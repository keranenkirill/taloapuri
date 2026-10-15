"""PDF-tekstin poiminta sivuittain (pöytäkirjat, tarjoukset).

Tekoäly saa sivujen tekstit viitattavina lohkoina, joten jokainen lähdeviite kohdistuu
sivunumeroon ja voidaan tarkistaa sanatarkasti. Skannatuista PDF:istä ei saada tekstiä
(OCR lisätään myöhemmin).
"""

import io
import logging
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PAGES = 200
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")

logging.getLogger("pypdf").setLevel(logging.ERROR)


def extract_pages(data: bytes, max_pages: int = MAX_PAGES) -> list[str]:
    """Palauttaa sivujen tekstit. Tyhjä lista, jos PDF on rikki tai siinä ei ole tekstiä."""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages[:max_pages]:
            raw = page.extract_text() or ""
            cleaned = _NL.sub(
                "\n\n", "\n".join(_WS.sub(" ", ln).strip() for ln in raw.splitlines())
            )
            pages.append(cleaned.strip())
    except (PdfReadError, ValueError, KeyError, TypeError, OSError):
        return []
    return pages if any(pages) else []
