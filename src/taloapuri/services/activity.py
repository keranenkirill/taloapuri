"""Lukemattomat asiat ja "Uusimmat tapahtumat".

Asia on käyttäjälle lukematon, jos joku muu on luonut sen, muuttanut sen tilaa, kirjoittanut
siihen tai lisännyt kuvia sen jälkeen, kun käyttäjä viimeksi avasi asian. Omat toimet eivät koskaan
tee asiasta lukematonta. Jos käyttäjä ei ole koskaan avannut asiaa, se on lukematon vain, jos
tapahtuma on viimeisen 30 päivän ajalta (muuten vanhat asiat näkyisivät kaikki uusina).

Kaikki kyselyt kulkevat RLS:n läpi: käyttäjä näkee vain asiat, jotka hän saa muutenkin nähdä.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.orm import Session

from taloapuri.domain.case_states import STATUS_LABELS_FI, CaseStatus

if TYPE_CHECKING:
    from taloapuri.auth import CompanyContext


CASE_TYPE_NOUNS_FI = {
    "damage": "vahinkoilmoitus",
    "tender_request": "tarjouspyyntö",
    "maintenance_responsibility": "kunnossapitovastuun selvitys",
    "renovation_notice": "muutostyöilmoitus",
}

# Viimeisin toisen käyttäjän tekemä asia kussakin asiassa.
# Avaamattomat asiat ovat lukemattomia vain 30 päivän ajan.
_ACTIVITY_SQL = """
WITH acts AS (
    SELECT e.case_id, e.created_at AS at, coalesce(e.actor_name, '') AS actor,
           e.event_type AS kind, e.to_status AS to_status
      FROM case_events e
     WHERE e.housing_company_id = :c AND e.actor_user_id <> :u
    UNION ALL
    SELECT m.case_id, m.created_at, m.author_name, 'msg_' || m.kind, NULL
      FROM case_messages m
     WHERE m.housing_company_id = :c AND m.author_id <> :u
    UNION ALL
    SELECT a.case_id, a.created_at, '', 'photos', NULL
      FROM case_attachments a
     WHERE a.housing_company_id = :c AND a.uploaded_by <> :u
), latest AS (
    SELECT DISTINCT ON (case_id) case_id, at, actor, kind, to_status
      FROM acts ORDER BY case_id, at DESC
)
SELECT c.id, c.title, c.case_type, l.at, l.actor, l.kind, l.to_status,
       (r.last_read_at IS NULL) AS never_read, ap.label AS apartment
  FROM cases c
  JOIN latest l ON l.case_id = c.id
  LEFT JOIN case_reads r ON r.case_id = c.id AND r.user_id = :u
  LEFT JOIN apartments ap ON ap.id = c.apartment_id
 WHERE c.housing_company_id = :c
   AND ((r.last_read_at IS NULL AND l.at > now() - interval '30 days')
        OR l.at > r.last_read_at)
 ORDER BY l.at DESC
"""


@dataclass(frozen=True)
class UnreadCase:
    case_id: uuid.UUID
    title: str
    case_type: str
    at: datetime
    actor: str
    apartment: str | None
    label: str  # "Uusi" tai "Päivitetty"
    what: str  # selkokielinen kuvaus, esim. "Uusi vahinkoilmoitus"


@dataclass(frozen=True)
class FeedItem:
    kind_label: str
    title: str
    url: str
    at: datetime
    actor: str = ""
    unread: bool = False
    pinned: bool = False
    detail: str = ""
    badge: str = ""
    link_label: str = ""


def _describe(case_type: str, kind: str, to_status: str | None, never_read: bool) -> str:
    noun = CASE_TYPE_NOUNS_FI.get(case_type, "asia")
    if kind == "created":
        return f"Uusi {noun}"
    if kind == "msg_info_request":
        return "Lisätietopyyntö"
    if kind == "msg_info_response":
        return "Vastaus lisätietopyyntöön"
    if kind == "msg_comment":
        return "Uusi kommentti"
    if kind == "photos":
        return "Uusia kuvia"
    if to_status:
        try:
            return f"Tila muuttui: {STATUS_LABELS_FI[CaseStatus(to_status)]}"
        except ValueError:
            pass
    return f"Päivitetty {noun}" if never_read else "Päivitetty"


def unread_cases(db: Session, company_id: uuid.UUID, user_id: uuid.UUID) -> list[UnreadCase]:
    rows = db.execute(text(_ACTIVITY_SQL), {"c": company_id, "u": user_id}).all()
    result = []
    for case_id, title, case_type, at, actor, kind, to_status, never_read, apartment in rows:
        result.append(
            UnreadCase(
                case_id=case_id,
                title=title,
                case_type=case_type,
                at=at,
                actor=actor,
                apartment=apartment,
                label="Uusi" if never_read and kind == "created" else "Päivitetty",
                what=_describe(case_type, kind, to_status, never_read),
            )
        )
    return result


def unread_case_count(db: Session, company_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return len(unread_cases(db, company_id, user_id))


def mark_case_read(db: Session, ctx: "CompanyContext", case_id: uuid.UUID) -> None:
    db.execute(
        text(
            "INSERT INTO case_reads (user_id, housing_company_id, case_id, last_read_at)"
            " VALUES (:u, :c, :case, clock_timestamp())"
            " ON CONFLICT (user_id, case_id) DO UPDATE SET last_read_at = clock_timestamp()"
        ),
        {"u": ctx.user_id, "c": ctx.company_id, "case": case_id},
    )


def feed_version(db: Session, ctx: "CompanyContext") -> str:
    """Muuttuu aina, kun käyttäjälle näkyvää uutta tapahtuu.

    Huomioi muiden toimet asioissa, pöytäkirjat ja viestit.
    """
    value = db.execute(
        text(
            """
            SELECT greatest(
                (SELECT max(created_at) FROM case_events
                  WHERE housing_company_id = :c AND actor_user_id <> :u),
                (SELECT max(created_at) FROM case_messages
                  WHERE housing_company_id = :c AND author_id <> :u),
                (SELECT max(created_at) FROM case_attachments
                  WHERE housing_company_id = :c AND uploaded_by <> :u),
                (SELECT max(uploaded_at) FROM company_documents
                  WHERE housing_company_id = :c AND removed_at IS NULL),
                (SELECT max(created_at) FROM direct_messages
                  WHERE housing_company_id = :c AND sender_id <> :u)
            )
            """
        ),
        {"c": ctx.company_id, "u": ctx.user_id},
    ).scalar_one()
    return value.isoformat() if value else ""


def feed(db: Session, ctx: "CompanyContext", limit: int = 12) -> list[FeedItem]:
    """Yksi aikajärjestetty lista etusivun "Uusimmat tapahtumat" -osioon."""
    from taloapuri.services import cases, documents, messages

    base = f"/yhtiot/{ctx.company_id}"
    items: list[FeedItem] = []
    pinned_ids: set[uuid.UUID] = set()
    for case in cases.my_cases_awaiting_info(db, ctx):
        pinned_ids.add(case.id)
        items.append(
            FeedItem(
                kind_label="Sinulta pyydetään lisätietoja",
                title=case.title,
                url=f"{base}/asiat/{case.id}",
                at=case.updated_at,
                unread=True,
                pinned=True,
            )
        )
    unread = unread_cases(db, ctx.company_id, ctx.user_id)
    unread_ids = {u.case_id for u in unread}
    for u in unread:
        if u.case_id in pinned_ids:
            continue
        apartment = f"huoneisto {u.apartment}" if u.apartment else ""
        who = ", ".join(p for p in (u.actor, apartment) if p)
        items.append(
            FeedItem(
                kind_label=u.what,
                title=u.title,
                url=f"{base}/asiat/{u.case_id}",
                at=u.at,
                actor=who,
                unread=True,
                # "Uusi vahinkoilmoitus" kertoo jo itse olevansa uusi; merkintä vain päivityksille.
                badge="" if u.what.startswith("Uusi") else u.label,
            )
        )
    for t in messages.unread_threads(db, ctx)[:5]:
        items.append(
            FeedItem(
                kind_label="Uusi viesti",
                title=t.subject,
                url=f"{base}/viestit/{t.id}",
                at=t.last_message_at,
                actor=t.last_sender_name,
                unread=True,
            )
        )
    for c in cases.recent_tenders(db, ctx):
        if c.id in unread_ids:
            continue
        items.append(
            FeedItem(
                kind_label="Tarjouspyyntö",
                title=c.title,
                url=f"{base}/asiat/{c.id}",
                at=c.created_at,
                detail=STATUS_LABELS_FI[CaseStatus(c.status)],
            )
        )
    for d in documents.list_documents(db, ctx, limit=5):
        meeting = (
            f"kokous {d.meeting_date.day}.{d.meeting_date.month}.{d.meeting_date.year}"
            if d.meeting_date
            else ""
        )
        items.append(
            FeedItem(
                kind_label="Pöytäkirja",
                title=d.title,
                url=f"{base}/asiakirjat/{d.id}/lataa",
                at=d.uploaded_at,
                actor=f"Lisännyt {d.uploaded_by_name}",
                detail=" – ".join(p for p in (meeting, d.description or "") if p),
                badge="" if d.visible_to_residents else "Vain hallitus",
                link_label=f"Lataa pöytäkirja (PDF, {round(d.size_bytes / 1024)} kt)",
            )
        )
    items.sort(key=lambda i: (not i.pinned, not i.unread, -i.at.timestamp()))
    return items[:limit]


def unread_case_ids(db: Session, ctx: "CompanyContext") -> dict[uuid.UUID, str]:
    """Asian tunniste → "Uusi"/"Päivitetty" (asialistan merkintöjä varten)."""
    return {u.case_id: u.label for u in unread_cases(db, ctx.company_id, ctx.user_id)}
