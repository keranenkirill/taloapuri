"""SQLAlchemy-mallit vaiheen 0 tenant-ytimelle.

Skeeman totuuslähde on Alembic-migraatio (RLS-politiikat, oikeudet). Nämä mallit kuvaavat
samat taulut ORM-käyttöä varten. Myöhemmät taulut (documents, sources, chunks, ai_runs, ...)
lisätään omissa vaiheissaan, ks. docs/vaiheet.md.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Account(Base):
    """Asiakkuus: yksittäinen taloyhtiö tai isännöintiyritys."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    account_type: Mapped[str] = mapped_column(String(32))  # housing_company | management_firm
    created_at: Mapped[datetime] = _created_at()


class HousingCompany(Base):
    """Taloyhtiö on tenant ja tietojen omistaja (ks. docs/adr/0002)."""

    __tablename__ = "housing_companies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    business_id: Mapped[str | None] = mapped_column(String(16), unique=True)  # Y-tunnus
    created_at: Mapped[datetime] = _created_at()


class AccountCompany(Base):
    """Isännöintisopimus: mikä asiakkuus hallinnoi yhtiötä ja milloin."""

    __tablename__ = "account_companies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    housing_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("housing_companies.id"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    pseudonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Palvelun ylläpitäjä (ei yhtiörooli). Lippua ei voi asettaa sovelluksen kautta.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = _created_at()


class Membership(Base):
    """Käyttäjän aikarajattu rooli yhdessä yhtiössä."""

    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    housing_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("housing_companies.id"))
    role: Mapped[str] = mapped_column(String(32))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("housing_companies.id"))
    case_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32))
    # Tapahtumapäivä ratkaisee sovellettavan säädösversion (ei hakupäivä).
    event_date: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistinen lukitus
    apartment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Isännöitsijän kirjoittama merkintä; ainoa teksti, joka näytetään myöhemmille asukkaille.
    history_note: Mapped[str | None] = mapped_column(String(500))
    # Tyyppikohtaiset lomaketiedot (domain/case_details.py).
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Apartment(Base):
    __tablename__ = "apartments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("housing_companies.id"))
    label: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created_at()


class ApartmentOccupancy(Base):
    """Kuka omistaa tai asuu missäkin huoneistossa ja milloin."""

    __tablename__ = "apartment_occupancies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    apartment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    relation: Mapped[str] = mapped_column(String(16))  # shareholder | resident
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


class CaseEvent(Base):
    __tablename__ = "case_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("housing_companies.id"))
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"))
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class AuditEvent(Base):
    """Append-only: sovellusroolilla ei ole UPDATE- eikä DELETE-oikeutta."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    housing_company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("housing_companies.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    # Ei henkilötietoja eikä vapaatekstiä metadataan.
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("housing_companies.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    status: Mapped[str] = mapped_column(String(16), default="ok")
    text: Mapped[str] = mapped_column(Text)
    # [{"text": "...", "citations": [1, 2]}] – viitenumerot viittaavat chat_citations.ord-arvoihin
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _created_at()


class AiRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("housing_companies.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_messages.id"))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    section_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32), default="chat")
    output_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


class ChatCitation(Base):
    __tablename__ = "chat_citations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_messages.id"))
    ord: Mapped[int] = mapped_column(Integer)
    source_section_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    citation_label: Mapped[str] = mapped_column(String(100))
    cited_text: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean)
    source_kind: Mapped[str] = mapped_column(String(16), default="law")
    link: Mapped[str | None] = mapped_column(String(500))


class CaseMessage(Base):
    """Lisätietopyyntö, vastaus tai kommentti asiaan."""

    __tablename__ = "case_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    author_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))  # info_request | info_response | comment
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class CaseAttachment(Base):
    __tablename__ = "case_attachments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()


class CompanyFaq(Base):
    """Taloyhtiön oma usein kysytty kysymys (isännöitsijä hallitsee)."""

    __tablename__ = "company_faq"

    id: Mapped[uuid.UUID] = _uuid_pk()
    housing_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("housing_companies.id"))
    question: Mapped[str] = mapped_column(String(200))
    answer: Mapped[str] = mapped_column(String(2000))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()
