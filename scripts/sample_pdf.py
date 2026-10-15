"""Pieni tekstipohjaisten PDF-tiedostojen tekijä kehitysdataa ja testejä varten.

Ei riippuvuuksia. Teksti kirjoitetaan Helvetica-fontilla WinAnsi-koodauksella, joten
ääkköset toimivat ja pypdf pystyy poimimaan tekstin takaisin.
"""


def _escape(line: str) -> bytes:
    raw = line.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_text_pdf(pages: list[list[str]]) -> bytes:
    """Jokainen sivu on lista rivejä."""
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    pages_id = len(objects) + 1 + 2 * len(pages)  # varataan numero sivupuulle
    page_ids = []
    for lines in pages:
        stream = b"BT /F1 11 Tf 50 800 Td 14 TL\n"
        for line in lines:
            stream += b"(" + _escape(line) + b") Tj T*\n"
        stream += b"ET"
        content = add(
            b"<</Length " + str(len(stream)).encode() + b">>\nstream\n" + stream + b"\nendstream"
        )
        page_ids.append(
            add(
                b"<</Type/Page/Parent "
                + str(pages_id).encode()
                + b" 0 R/MediaBox[0 0 595 842]/Contents "
                + str(content).encode()
                + b" 0 R/Resources<</Font<</F1 "
                + str(font).encode()
                + b" 0 R>>>>>>"
            )
        )
    kids = b" ".join(str(p).encode() + b" 0 R" for p in page_ids)
    assert (
        add(b"<</Type/Pages/Kids[" + kids + b"]/Count " + str(len(page_ids)).encode() + b">>")
        == pages_id
    )
    catalog = add(b"<</Type/Catalog/Pages " + str(pages_id).encode() + b" 0 R>>")

    out = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<</Size "
        + str(len(objects) + 1).encode()
        + b"/Root "
        + str(catalog).encode()
        + b" 0 R>>\nstartxref\n"
        + str(xref).encode()
        + b"\n%%EOF\n"
    )
    return out
