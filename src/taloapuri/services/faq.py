"""Taloyhtiön omat usein kysytyt kysymykset. Isännöitsijä hallitsee, kaikki jäsenet lukevat.

Sisältö on pelkkää tekstiä (näytetään HTML-suojattuna, rivinvaihdot säilyvät). Oikeudet on
varmistettu sekä täällä että RLS:ssä (migraatio 0011).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext
from taloapuri.models import CompanyFaq
from taloapuri.services.audit import write_audit

MAX_QUESTION = 200
MAX_ANSWER = 2000


class NotAllowed(Exception):
    pass


class NotFound(Exception):
    pass


class InvalidFaq(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(errors)
        self.errors = errors


@dataclass(frozen=True)
class FaqRow:
    id: uuid.UUID
    question: str
    answer: str
    sort_order: int
    updated_at: datetime


def _require_manager(ctx: CompanyContext) -> None:
    if not ctx.is_manager:
        raise NotAllowed


def _validate(question: str, answer: str, sort_order: str) -> tuple[str, str, int | None]:
    errors: dict[str, str] = {}
    question, answer = question.strip(), answer.strip()
    if not question:
        errors["question"] = "Kirjoita kysymys, esimerkiksi ”Milloin sauna on varattavissa?”."
    elif len(question) > MAX_QUESTION:
        errors["question"] = f"Kysymys on liian pitkä. Käytä enintään {MAX_QUESTION} merkkiä."
    if not answer:
        errors["answer"] = "Kirjoita vastaus."
    elif len(answer) > MAX_ANSWER:
        errors["answer"] = f"Vastaus on liian pitkä. Käytä enintään {MAX_ANSWER} merkkiä."
    order: int | None = None
    if sort_order.strip():
        try:
            order = int(sort_order.strip())
            if not 0 <= order <= 9999:
                raise ValueError
        except ValueError:
            errors["sort_order"] = "Anna järjestysnumero väliltä 0–9999 tai jätä tyhjäksi."
    if errors:
        raise InvalidFaq(errors)
    return question, answer, order


def list_faq(db: Session, ctx: CompanyContext) -> list[FaqRow]:
    rows = db.execute(
        select(CompanyFaq)
        .where(CompanyFaq.housing_company_id == ctx.company_id)
        .order_by(CompanyFaq.sort_order, CompanyFaq.created_at)
    ).scalars()
    return [FaqRow(r.id, r.question, r.answer, r.sort_order, r.updated_at) for r in rows]


def add_entry(
    db: Session, ctx: CompanyContext, question: str, answer: str, sort_order: str = ""
) -> uuid.UUID:
    _require_manager(ctx)
    question, answer, order = _validate(question, answer, sort_order)
    if order is None:
        top = db.execute(
            select(func.coalesce(func.max(CompanyFaq.sort_order), 0)).where(
                CompanyFaq.housing_company_id == ctx.company_id
            )
        ).scalar_one()
        order = min(int(top) + 10, 9999)
    entry_id = uuid.uuid4()
    db.add(
        CompanyFaq(
            id=entry_id,
            housing_company_id=ctx.company_id,
            question=question,
            answer=answer,
            sort_order=order,
            created_by=ctx.user_id,
        )
    )
    db.flush()
    write_audit(db, ctx, "faq.added", "faq", entry_id)
    return entry_id


def update_entry(
    db: Session,
    ctx: CompanyContext,
    entry_id: uuid.UUID,
    question: str,
    answer: str,
    sort_order: str = "",
) -> None:
    _require_manager(ctx)
    question, answer, order = _validate(question, answer, sort_order)
    result = db.execute(
        text(
            "UPDATE company_faq SET question = :q, answer = :a,"
            " sort_order = coalesce(:o, sort_order), updated_at = now()"
            " WHERE id = :id AND housing_company_id = :c"
        ),
        {"q": question, "a": answer, "o": order, "id": entry_id, "c": ctx.company_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFound(entry_id)
    write_audit(db, ctx, "faq.updated", "faq", entry_id)


def delete_entry(db: Session, ctx: CompanyContext, entry_id: uuid.UUID) -> None:
    _require_manager(ctx)
    result = db.execute(
        text("DELETE FROM company_faq WHERE id = :id AND housing_company_id = :c"),
        {"id": entry_id, "c": ctx.company_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFound(entry_id)
    write_audit(db, ctx, "faq.deleted", "faq", entry_id)


def get_entry(db: Session, ctx: CompanyContext, entry_id: uuid.UUID) -> FaqRow:
    for row in list_faq(db, ctx):
        if row.id == entry_id:
            return row
    raise NotFound(entry_id)
