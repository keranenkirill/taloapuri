"""Finlexin avoimen datan Akoma Ntoso -asiakirjojen jäsennys ja haku.

Rajapinta: https://opendata.finlex.fi/finlex/avoindata/v1
- ei rekisteröitymistä, User-Agent on pakollinen, käyttöä voidaan rajoittaa (HTTP 429)
- ajantasainen versio: .../statute-consolidated/{vuosi}/{numero}/fin@latest

Ajantasainen säädöskokoelma ei ole virallisesti sitova julkaisu – kerro se käyttäjälle.
"""

import gzip
import hashlib
import io
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

FINLEX_API = "https://opendata.finlex.fi/finlex/avoindata/v1"
USER_AGENT = "Taloapuri/0.1 (taloyhtioiden avustaja; kehitys)"
NS = {"akn": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}
_AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"

MAX_RESPONSE_BYTES = 8 * 1024 * 1024  # AOYL on noin 0,8 Mt
MAX_ROWS = 20_000  # AOYL:ssä on 826 momenttia

# Tekstistä poistetaan muutosviittaukset kuten "(16.6.2026/535)" otsikoista.
_AMENDMENT_REF = re.compile(r"\(\d{1,2}\.\d{1,2}\.\d{4}/\d+\)")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedSection:
    ord: int
    eid: str
    chapter_num: str | None
    chapter_heading: str | None
    section_num: str
    section_heading: str | None
    subsection_no: int | None
    text: str


@dataclass
class ParsedAct:
    title: str
    version_label: str
    consolidated_date: date | None
    sha256: str
    sections: list[ParsedSection] = field(default_factory=list)


def consolidated_url(year: int, number: int) -> str:
    return f"{FINLEX_API}/akn/fi/act/statute-consolidated/{year}/{number}/fin%40latest"


def public_url(year: int, number: int) -> str:
    return f"https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/{year}/{number}"


class FinlexError(Exception):
    """Finlex-haku tai -jäsennys epäonnistui. Viesti on selkokielinen ja näytetään ylläpitäjälle."""


class ActNotFound(FinlexError):
    pass


Fetcher = Callable[[int, int], bytes]
"""Hakee säädöksen (vuosi, numero) ajantasaisen XML:n. Testit korvaavat tämän omalla."""


def fetch(url: str, timeout: float = 30.0) -> bytes:
    if not url.startswith(FINLEX_API):
        raise ValueError("Vain Finlexin avoimen datan rajapinta on sallittu")
    request = urllib.request.Request(  # noqa: S310 – osoite tarkistettu yllä (vain https/Finlex)
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            data: bytes = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ActNotFound(
                "Säädöstä ei löytynyt ajantasaisena versiona. Tarkista vuosi ja numero "
                "(vanhoilla säädöksillä ei aina ole ajantasaista versiota)."
            ) from exc
        if exc.code == 429:
            raise FinlexError(
                "Finlex rajoittaa tilapäisesti hakuja (liian monta pyyntöä). Yritä hetken päästä."
            ) from exc
        raise FinlexError(
            f"Finlex vastasi virheellä ({exc.code}). Yritä myöhemmin uudelleen."
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FinlexError(
            "Finlexiin ei saatu yhteyttä. Tarkista verkkoyhteys ja yritä uudelleen."
        ) from exc
    if len(data) > MAX_RESPONSE_BYTES:
        raise FinlexError("Säädös on liian suuri tuotavaksi (yli 8 Mt).")
    if data[:2] == b"\x1f\x8b":  # Finlex pakkaa osan vastauksista gzipillä pyytämättä
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as packed:
                data = packed.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, EOFError) as exc:
            raise FinlexError("Finlexin vastausta ei voitu purkaa.") from exc
        if len(data) > MAX_RESPONSE_BYTES:
            raise FinlexError("Säädös on liian suuri tuotavaksi (yli 8 Mt).")
    return data


def fetch_act(year: int, number: int) -> bytes:
    """Oletushakija: ajantasainen säädös Finlexin avoimesta datasta."""
    return fetch(consolidated_url(year, number))


def _text(element: Element | None) -> str:
    if element is None:
        return ""
    return _WS.sub(" ", "".join(element.itertext())).strip()


def _heading(element: Element) -> str | None:
    heading = element.find("akn:heading", NS)
    if heading is None:
        return None
    cleaned = _WS.sub(" ", _AMENDMENT_REF.sub("", _text(heading))).strip()
    return cleaned or None


def parse_akn(xml: bytes) -> ParsedAct:
    """Jäsentää ajantasaisen säädöksen pykälä- ja momenttitason osiin."""
    try:
        root = ElementTree.fromstring(xml)
    except (
        Exception
    ) as exc:  # rikkinäinen tai vaarallinen XML (defusedxml nostaa useita virhetyyppejä)
        raise FinlexError("Finlexin vastaus ei ollut kelvollista säädöstekstiä.") from exc
    expression = root.find(".//akn:FRBRExpression", NS)
    version_label = ""
    consolidated: date | None = None
    if expression is not None:
        version = expression.find("akn:FRBRversionNumber", NS)
        version_label = version.get("value", "") if version is not None else ""
        for frbr_date in expression.findall("akn:FRBRdate", NS):
            if frbr_date.get("name") == "dateConsolidated":
                consolidated = date.fromisoformat(frbr_date.get("date", ""))
    title = _text(root.find(".//akn:preface//akn:docTitle", NS)) or "Nimetön säädös"

    act = ParsedAct(
        title=title,
        version_label=version_label,
        consolidated_date=consolidated,
        sha256=hashlib.sha256(xml).hexdigest(),
    )
    body = root.find(".//akn:body", NS)
    if body is None:
        return act

    counter = 0

    def add_section(section: Element, chapter: Element | None) -> None:
        nonlocal counter
        chapter_num = _text(chapter.find("akn:num", NS)) if chapter is not None else None
        chapter_heading = _heading(chapter) if chapter is not None else None
        section_num = _text(section.find("akn:num", NS))
        section_heading = _heading(section)
        subsections = section.findall("akn:subsection", NS)
        parts: list[tuple[int | None, str, str]] = []
        if subsections:
            for index, sub in enumerate(subsections, start=1):
                parts.append((index, sub.get("eId", ""), _text(sub)))
        else:
            content = [c for c in section if c.tag not in (f"{_AKN}num", f"{_AKN}heading")]
            text = " ".join(_text(c) for c in content).strip()
            parts.append((None, section.get("eId", ""), text))
        for subsection_no, eid, text in parts:
            if not text:
                continue  # kumotut tai tyhjät momentit ohitetaan
            counter += 1
            if counter > MAX_ROWS:
                raise FinlexError(f"Säädöksessä on liikaa momentteja (yli {MAX_ROWS}).")
            act.sections.append(
                ParsedSection(
                    ord=counter,
                    eid=eid,
                    chapter_num=chapter_num or None,
                    chapter_heading=chapter_heading,
                    section_num=section_num,
                    section_heading=section_heading,
                    subsection_no=subsection_no,
                    text=text,
                )
            )

    chapters = body.findall(".//akn:chapter", NS)
    if chapters:
        for chapter in chapters:
            for section in chapter.findall("akn:section", NS):
                add_section(section, chapter)
    else:
        for section in body.findall(".//akn:section", NS):
            add_section(section, None)
    return act
