"""Haku julkisista oikeuslähteistä (Finlex). Ei upotuksia vielä: PostgreSQL:n tekstihaku
suomen kielen sanavartaloilla ja etuliitteillä. Pykälän otsikko painaa eniten.

Arkikielen sanat eivät aina esiinny laissa (esim. "kylpyhuone" → laissa "sisäosat", "eristeet"),
joten kysymystä laajennetaan pienellä käsitesanastolla. Laajenna sanastoa hakutestien avulla.

Tulokset ryhmitellään pykälittäin, jotta tekoäly näkee koko pykälän (momentit viittaavat
toisiinsa, esim. "Edellä 2 momentissa tarkoitettu").
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

_WORD = re.compile(r"[a-zåäö0-9]{3,}", re.IGNORECASE)

# Kysymyssanat ja muut yleiset sanat, jotka vain lisäävät kohinaa.
_STOPWORDS = frozenset(
    [
        "kuka",
        "kenen",
        "kenelle",
        "mikä",
        "mitä",
        "mihin",
        "miten",
        "miksi",
        "milloin",
        "missä",
        "mistä",
        "saako",
        "saanko",
        "voiko",
        "voinko",
        "pitääkö",
        "täytyykö",
        "onko",
        "ovatko",
        "ilman",
        "kanssa",
        "minun",
        "meidän",
        "minulla",
        "meillä",
        "sen",
        "tämä",
        "tässä",
        "joka",
        "jos",
        "kun",
        "myös",
        "että",
        "olla",
        "ole",
        "ovat",
        "oma",
        "omaa",
        "oman",
        "vastaa",
        "vastaako",
        "maksaa",
        "maksaako",
        "hoitaa",
        "hoitaako",
    ]
)

# Arkikielen sanan alku → lain käsitteet. Avaimet ovat sanan alkuja (pienillä kirjaimilla).
_EXPANSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kylpyhuone", ("sisäosat", "eristeet", "rakenteet")),
    ("pesuhuone", ("sisäosat", "eristeet", "rakenteet")),
    ("sauna", ("sisäosat", "rakenteet")),
    ("märkätila", ("sisäosat", "eristeet", "rakenteet")),
    ("vedeneristy", ("eristeet", "rakenteet")),
    ("vesieristy", ("eristeet", "rakenteet")),
    ("remont", ("muutostyö",)),
    ("korja", ("kunnossapito",)),
    ("keittiö", ("sisäosat",)),
    ("vuot", ("vahinko", "kunnossapito")),
    ("vesivahin", ("vahinko", "kunnossapito")),
    ("putk", ("perusjärjestelmät", "viemäri")),
    ("lattiakaivo", ("viemäri", "perusjärjestelmät")),
    ("ikkun", ("ikkunat",)),
    ("parvek", ("parveke",)),
    ("vastaa", ("kunnossapitovastuu",)),
    ("vastuu", ("kunnossapitovastuu",)),
    ("maksa", ("kunnossapitovastuu",)),
)


@dataclass
class Subsection:
    id: uuid.UUID
    subsection_no: int | None
    text: str


@dataclass
class SectionHit:
    source_short_title: str
    source_title: str
    public_url: str
    version_label: str
    consolidated_date: date | None
    fetched_at: datetime
    chapter_num: str | None
    chapter_heading: str | None
    section_num: str
    section_heading: str | None
    eid_prefix: str
    subsections: list[Subsection] = field(default_factory=list)

    @property
    def citation_label(self) -> str:
        """Esim. 'AOYL 4 luku 2 §'."""
        parts = [self.source_short_title, self.chapter_num or "", self.section_num]
        return " ".join(p for p in parts if p)


def build_tsquery(query: str) -> str | None:
    """Muodostaa turvallisen OR-haun etuliitteillä: 'sana1:* | sana2:*'.

    Mukaan otetaan vain kirjaimet ja numerot, joten käyttäjän syöte ei voi muuttaa kyselyä.
    """
    words = list(dict.fromkeys(w.lower() for w in _WORD.findall(query)))[:12]
    terms: list[str] = []
    for word in words:
        if word not in _STOPWORDS:
            terms.append(word)
        for prefix, expansions in _EXPANSIONS:
            if word.startswith(prefix):
                terms.extend(expansions)
    terms = list(dict.fromkeys(terms))[:20]
    if not terms:
        return None
    return " | ".join(f"{t}:*" for t in terms)


def search_sections(db: Session, query: str, max_sections: int = 5) -> list[SectionHit]:
    tsq = build_tsquery(query)
    if tsq is None:
        return []
    rows = db.execute(
        text(
            """
            WITH q AS (SELECT to_tsquery('finnish', :tsq) AS tsq)
            SELECT s.version_id, s.chapter_num, s.section_num,
                   max(ts_rank_cd(s.search, q.tsq, 1)) + 0.05 * count(*) AS score
              FROM source_sections s
              JOIN sources src ON src.current_version_id = s.version_id AND src.active,
                   q
             WHERE s.search @@ q.tsq
             GROUP BY s.version_id, s.chapter_num, s.section_num
             ORDER BY score DESC
             LIMIT :limit
            """
        ),
        {"tsq": tsq, "limit": max_sections},
    ).all()
    hits: list[SectionHit] = []
    for version_id, chapter_num, section_num, _score in rows:
        detail = db.execute(
            text(
                """
                SELECT s.id, s.subsection_no, s.text, s.eid, s.chapter_heading,
                       s.section_heading, src.short_title, src.title, src.public_url,
                       v.version_label, v.consolidated_date, v.fetched_at
                  FROM source_sections s
                  JOIN source_versions v ON v.id = s.version_id
                  JOIN sources src ON src.id = v.source_id
                 WHERE s.version_id = :v AND s.section_num = :sn
                   AND s.chapter_num IS NOT DISTINCT FROM :cn
                 ORDER BY s.ord
                """
            ),
            {"v": version_id, "sn": section_num, "cn": chapter_num},
        ).all()
        if not detail:
            continue
        first = detail[0]
        hits.append(
            SectionHit(
                source_short_title=first.short_title,
                source_title=first.title,
                public_url=first.public_url,
                version_label=first.version_label,
                consolidated_date=first.consolidated_date,
                fetched_at=first.fetched_at,
                chapter_num=chapter_num,
                chapter_heading=first.chapter_heading,
                section_num=section_num,
                section_heading=first.section_heading,
                eid_prefix=first.eid.split("__subsec_")[0],
                subsections=[Subsection(r.id, r.subsection_no, r.text) for r in detail],
            )
        )
    return hits


@dataclass
class DocumentHit:
    id: uuid.UUID
    title: str
    meeting_date: date | None
    pages: list[tuple[int, str]]  # (sivunumero, teksti)


def search_company_documents(
    db: Session, company_id: uuid.UUID, query: str, max_documents: int = 2, max_pages: int = 10
) -> list[DocumentHit]:
    """Hakee yhtiön pöytäkirjoista. RLS rajaa: asukas löytää vain asukkaille näkyvät."""
    tsq = build_tsquery(query)
    if tsq is None:
        return []
    rows = db.execute(
        text(
            """
            WITH q AS (SELECT to_tsquery('finnish', :tsq) AS tsq)
            SELECT d.id, d.title, d.meeting_date, max(ts_rank_cd(p.search, q.tsq, 1)) AS score
              FROM company_document_pages p
              JOIN company_documents d ON d.id = p.document_id, q
             WHERE p.housing_company_id = :c AND d.removed_at IS NULL AND p.search @@ q.tsq
             GROUP BY d.id, d.title, d.meeting_date
             ORDER BY score DESC
             LIMIT :limit
            """
        ),
        {"tsq": tsq, "c": company_id, "limit": max_documents},
    ).all()
    hits = []
    for doc_id, title, meeting_date, _score in rows:
        pages = db.execute(
            text(
                "SELECT page_no, text FROM company_document_pages WHERE document_id = :d"
                " ORDER BY page_no LIMIT :n"
            ),
            {"d": doc_id, "n": max_pages},
        ).all()
        hits.append(DocumentHit(doc_id, title, meeting_date, [(n, t) for n, t in pages]))
    return hits


@dataclass
class LawQuote:
    """Tarkka lainkohta (valitut momentit) nykyisestä versiosta, UKK:n lähdeviitteitä varten."""

    label: str  # esim. "AOYL 4 luku 2 §"
    heading: str | None
    version_label: str
    consolidated_date: date | None
    public_url: str
    subsections: list[tuple[int | None, str]]


def get_law_quote(
    db: Session,
    source_key: str,
    chapter: str | None,
    section: str,
    subsection_nos: tuple[int, ...] | None = None,
) -> LawQuote | None:
    """Hakee lainkohdan sanatarkasti. None, jos lakia ei ole tallennettu tai se ei ole käytössä."""
    rows = db.execute(
        text(
            """
            SELECT s.section_heading, s.subsection_no, s.text, src.short_title, src.public_url,
                   v.version_label, v.consolidated_date
              FROM source_sections s
              JOIN sources src ON src.current_version_id = s.version_id
              JOIN source_versions v ON v.id = s.version_id
             WHERE src.source_key = :k AND src.active
               AND s.chapter_num IS NOT DISTINCT FROM :c AND s.section_num = :s
             ORDER BY s.ord
            """
        ),
        {"k": source_key, "c": chapter, "s": section},
    ).all()
    chosen = [
        (r.subsection_no, r.text)
        for r in rows
        if subsection_nos is None or r.subsection_no in subsection_nos
    ]
    if not rows or not chosen:
        return None
    first = rows[0]
    label = " ".join(p for p in (first.short_title, chapter or "", section) if p)
    return LawQuote(
        label=label,
        heading=first.section_heading,
        version_label=first.version_label,
        consolidated_date=first.consolidated_date,
        public_url=first.public_url,
        subsections=chosen,
    )
