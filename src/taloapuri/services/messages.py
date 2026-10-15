"""Suorat viestit (ks. migraatio 0007 säännöistä). Viestejä ei lähetetä tekoälylle."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext
from taloapuri.domain.roles import ROLE_LABELS_FI, Role


class InvalidMessage(Exception):
    pass


class NotFound(Exception):
    pass


@dataclass
class Contact:
    user_id: uuid.UUID
    display_name: str
    roles_label: str


@dataclass
class ThreadRow:
    id: uuid.UUID
    subject: str
    last_message_at: datetime
    last_sender_name: str
    other_names: str
    unread: bool


@dataclass
class MessageRow:
    sender_name: str
    body: str
    created_at: datetime
    mine: bool


def contacts(db: Session, ctx: CompanyContext) -> list[Contact]:
    rows = db.execute(text("SELECT user_id, display_name, roles FROM app_contactable_members()"))
    result = []
    for user_id, name, roles in rows:
        labels = [ROLE_LABELS_FI[Role(r)] for r in roles.split(",") if r in Role._value2member_map_]
        result.append(Contact(user_id, name, ", ".join(labels)))
    return result


def start_thread(
    db: Session, ctx: CompanyContext, recipient: uuid.UUID, subject: str, body: str
) -> uuid.UUID:
    subject, body = subject.strip(), body.strip()
    errors = []
    if not subject:
        errors.append("Kirjoita viestille aihe.")
    if not body:
        errors.append("Kirjoita viesti.")
    if len(subject) > 200 or len(body) > 5000:
        errors.append("Viesti on liian pitkä.")
    if errors:
        raise InvalidMessage(" ".join(errors))
    if recipient not in {c.user_id for c in contacts(db, ctx)}:
        raise InvalidMessage("Valitse vastaanottaja listasta.")
    try:
        with db.begin_nested():
            thread_id: uuid.UUID = db.execute(
                text("SELECT app_start_thread(:r, :s, :b)"),
                {"r": recipient, "s": subject, "b": body},
            ).scalar_one()
    except DBAPIError as exc:  # tietokanta tarkistaa säännöt vielä kerran
        raise InvalidMessage("Viestiä ei voitu lähettää tälle vastaanottajalle.") from exc
    return thread_id


def reply(db: Session, ctx: CompanyContext, thread_id: uuid.UUID, body: str) -> None:
    get_thread_subject(db, ctx, thread_id)
    body = body.strip()
    if not body:
        raise InvalidMessage("Kirjoita viesti.")
    if len(body) > 5000:
        raise InvalidMessage("Viesti on liian pitkä. Käytä enintään 5000 merkkiä.")
    db.execute(
        text(
            "INSERT INTO direct_messages (thread_id, housing_company_id, sender_id, sender_name,"
            " body) VALUES (:t, :c, :u, :n, :b)"
        ),
        {
            "t": thread_id,
            "c": ctx.company_id,
            "u": ctx.user_id,
            "n": ctx.user_name or "Käyttäjä",
            "b": body,
        },
    )
    mark_read(db, ctx, thread_id)


def mark_read(db: Session, ctx: CompanyContext, thread_id: uuid.UUID) -> None:
    db.execute(
        text(
            "UPDATE message_participants SET last_read_at = clock_timestamp()"
            " WHERE thread_id = :t AND user_id = :u AND housing_company_id = :c"
        ),
        {"t": thread_id, "u": ctx.user_id, "c": ctx.company_id},
    )


_THREADS_SQL = """
SELECT t.id, t.subject, last.created_at, last.sender_name,
       (SELECT string_agg(u_names.name, ', ')
          FROM (SELECT DISTINCT dm.sender_name AS name FROM direct_messages dm
                 WHERE dm.thread_id = t.id AND dm.sender_id <> :u) u_names) AS others,
       EXISTS (SELECT 1 FROM direct_messages dm
                WHERE dm.thread_id = t.id AND dm.sender_id <> :u
                  AND dm.created_at > coalesce(p.last_read_at, '-infinity'::timestamptz)) AS unread
  FROM message_threads t
  JOIN message_participants p ON p.thread_id = t.id AND p.user_id = :u
  JOIN LATERAL (SELECT dm.created_at, dm.sender_name FROM direct_messages dm
                 WHERE dm.thread_id = t.id ORDER BY dm.created_at DESC LIMIT 1) last ON true
 WHERE t.housing_company_id = :c
 ORDER BY last.created_at DESC
"""


def list_threads(db: Session, ctx: CompanyContext) -> list[ThreadRow]:
    rows = db.execute(text(_THREADS_SQL), {"u": ctx.user_id, "c": ctx.company_id}).all()
    return [ThreadRow(r[0], r[1], r[2], r[3], r[4] or "", bool(r[5])) for r in rows]


def unread_threads(db: Session, ctx: CompanyContext) -> list[ThreadRow]:
    return [t for t in list_threads(db, ctx) if t.unread]


def get_thread_subject(db: Session, ctx: CompanyContext, thread_id: uuid.UUID) -> str:
    subject = db.execute(
        text("SELECT subject FROM message_threads WHERE id = :t AND housing_company_id = :c"),
        {"t": thread_id, "c": ctx.company_id},
    ).scalar_one_or_none()
    if subject is None:
        raise NotFound(thread_id)
    return str(subject)


def thread_messages(db: Session, ctx: CompanyContext, thread_id: uuid.UUID) -> list[MessageRow]:
    get_thread_subject(db, ctx, thread_id)
    rows = db.execute(
        text(
            "SELECT sender_name, body, created_at, sender_id = :u FROM direct_messages"
            " WHERE thread_id = :t AND housing_company_id = :c ORDER BY created_at"
        ),
        {"t": thread_id, "c": ctx.company_id, "u": ctx.user_id},
    ).all()
    mark_read(db, ctx, thread_id)
    return [MessageRow(*r) for r in rows]
