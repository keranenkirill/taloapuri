"""Huoneistot ja yhtiön jäsenten (osakkaat, asukkaat) hallinta.

Jäseniä ei poisteta: käyttöoikeus päätetään asettamalla valid_to,
jolloin historia ja audit säilyvät.
Uudet rivit lisätään Pythonissa luodulla UUID:llä ilman RETURNING-osaa, koska RLS ei anna
isännöitsijän lukea käyttäjäriviä ennen kuin jäsenyys on olemassa.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext
from taloapuri.domain.roles import MANAGEABLE_ROLES, Role
from taloapuri.models import Apartment, ApartmentOccupancy, Membership, User
from taloapuri.services.audit import write_audit


class NotAllowed(Exception):
    """Käyttäjällä ei ole oikeutta toimintoon."""


class NotFound(Exception):
    pass


class InvalidInput(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(errors)
        self.errors = errors


@dataclass
class MemberRow:
    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    email: str | None
    role: str
    valid_from: datetime
    valid_to: datetime | None
    active: bool
    apartments: list[str] = field(default_factory=list)


def _require_manager(ctx: CompanyContext) -> None:
    if not ctx.is_manager:
        raise NotAllowed


# --- Huoneistot ---


def list_apartments(db: Session, ctx: CompanyContext) -> list[Apartment]:
    stmt = (
        select(Apartment)
        .where(Apartment.housing_company_id == ctx.company_id)
        .order_by(Apartment.label)
    )
    return list(db.execute(stmt).scalars())


def add_apartment(db: Session, ctx: CompanyContext, label: str) -> uuid.UUID:
    _require_manager(ctx)
    label = label.strip()
    if not label:
        raise InvalidInput({"label": "Kirjoita huoneiston tunnus, esimerkiksi ”A 12”."})
    if len(label) > 32:
        raise InvalidInput({"label": "Tunnus on liian pitkä. Käytä enintään 32 merkkiä."})
    apartment_id = uuid.uuid4()
    try:
        with db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO apartments (id, housing_company_id, label)"
                    " VALUES (:id, :company, :label)"
                ),
                {"id": apartment_id, "company": ctx.company_id, "label": label},
            )
    except IntegrityError as exc:
        raise InvalidInput({"label": f"Huoneisto ”{label}” on jo olemassa."}) from exc
    write_audit(db, ctx, "apartment.created", "apartment", apartment_id)
    return apartment_id


def get_apartment(db: Session, ctx: CompanyContext, apartment_id: uuid.UUID) -> Apartment:
    apartment = db.execute(
        select(Apartment).where(
            Apartment.id == apartment_id, Apartment.housing_company_id == ctx.company_id
        )
    ).scalar_one_or_none()
    if apartment is None:
        raise NotFound(apartment_id)
    return apartment


def my_active_apartments(db: Session, ctx: CompanyContext) -> list[Apartment]:
    """Huoneistot, joissa kirjautunut käyttäjä asuu tai on osakkaana nyt."""
    stmt = (
        select(Apartment)
        .join(ApartmentOccupancy, ApartmentOccupancy.apartment_id == Apartment.id)
        .where(
            Apartment.housing_company_id == ctx.company_id,
            ApartmentOccupancy.user_id == ctx.user_id,
            ApartmentOccupancy.valid_from <= text("now()"),
            (ApartmentOccupancy.valid_to.is_(None)) | (ApartmentOccupancy.valid_to > text("now()")),
        )
        .order_by(Apartment.label)
        .distinct()
    )
    return list(db.execute(stmt).scalars())


# --- Jäsenet ---


def list_members(db: Session, ctx: CompanyContext) -> list[MemberRow]:
    _require_manager(ctx)
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.housing_company_id == ctx.company_id)
        .order_by(User.display_name, Membership.valid_from)
    ).all()
    occupancies = db.execute(
        select(ApartmentOccupancy.user_id, ApartmentOccupancy.valid_to, Apartment.label)
        .join(Apartment, Apartment.id == ApartmentOccupancy.apartment_id)
        .where(ApartmentOccupancy.housing_company_id == ctx.company_id)
    ).all()
    now = db.execute(text("SELECT now()")).scalar_one()
    result: list[MemberRow] = []
    for membership, user in rows:
        active = membership.valid_from <= now and (
            membership.valid_to is None or membership.valid_to > now
        )
        labels = sorted(
            {
                label
                for occ_user, occ_to, label in occupancies
                if occ_user == user.id and (occ_to is None or occ_to > now or not active)
            }
        )
        result.append(
            MemberRow(
                membership_id=membership.id,
                user_id=user.id,
                display_name=user.display_name,
                email=user.email,
                role=membership.role,
                valid_from=membership.valid_from,
                valid_to=membership.valid_to,
                active=active,
                apartments=labels,
            )
        )
    result.sort(key=lambda r: (not r.active, r.display_name.lower()))
    return result


def add_resident(
    db: Session,
    ctx: CompanyContext,
    *,
    display_name: str,
    email: str,
    role: str,
    apartment_id: uuid.UUID | None,
) -> uuid.UUID:
    """Lisää osakkaan tai asukkaan. Palauttaa jäsenyyden tunnisteen.

    Vaiheessa 1 tämä korvautuu sähköpostikutsulla (OIDC-kirjautuminen, ks. ADR 0003).
    """
    _require_manager(ctx)
    errors: dict[str, str] = {}
    display_name = display_name.strip()
    email = email.strip()
    if not display_name:
        errors["display_name"] = "Kirjoita henkilön nimi."
    elif len(display_name) > 200:
        errors["display_name"] = "Nimi on liian pitkä."
    if email and ("@" not in email or len(email) > 320):
        errors["email"] = "Tarkista sähköpostiosoite, esimerkiksi nimi@esimerkki.fi."
    try:
        parsed_role = Role(role)
    except ValueError:
        parsed_role = None
    if parsed_role not in MANAGEABLE_ROLES:
        errors["role"] = "Valitse, onko henkilö osakas vai asukas."
    if apartment_id is not None:
        try:
            get_apartment(db, ctx, apartment_id)
        except NotFound:
            errors["apartment_id"] = "Valitse huoneisto listasta."
    if errors:
        raise InvalidInput(errors)
    assert parsed_role is not None

    user_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    db.execute(
        text("INSERT INTO users (id, display_name, email) VALUES (:id, :name, :email)"),
        {"id": user_id, "name": display_name, "email": email or None},
    )
    db.execute(
        text(
            "INSERT INTO memberships (id, user_id, housing_company_id, role, invited_by)"
            " VALUES (:id, :user, :company, :role, :by)"
        ),
        {
            "id": membership_id,
            "user": user_id,
            "company": ctx.company_id,
            "role": parsed_role.value,
            "by": ctx.user_id,
        },
    )
    if apartment_id is not None:
        db.execute(
            text(
                "INSERT INTO apartment_occupancies"
                " (housing_company_id, apartment_id, user_id, relation, created_by)"
                " VALUES (:company, :apartment, :user, :relation, :by)"
            ),
            {
                "company": ctx.company_id,
                "apartment": apartment_id,
                "user": user_id,
                "relation": parsed_role.value,
                "by": ctx.user_id,
            },
        )
    write_audit(db, ctx, "member.added", "membership", membership_id, role=parsed_role.value)
    return membership_id


def end_membership(db: Session, ctx: CompanyContext, membership_id: uuid.UUID) -> None:
    """Päättää käyttöoikeuden heti. Huoneiston asumishistoria päätetään samalla."""
    _require_manager(ctx)
    membership = db.execute(
        select(Membership).where(
            Membership.id == membership_id, Membership.housing_company_id == ctx.company_id
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotFound(membership_id)
    if membership.user_id == ctx.user_id:
        raise NotAllowed("Omaa käyttöoikeutta ei voi päättää.")
    if Role(membership.role) not in MANAGEABLE_ROLES:
        raise NotAllowed("Vain osakkaiden ja asukkaiden käyttöoikeuden voi päättää täällä.")
    result = db.execute(
        text(
            "UPDATE memberships SET valid_to = now()"
            " WHERE id = :id AND (valid_to IS NULL OR valid_to > now())"
        ),
        {"id": membership_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        return  # jo päättynyt – toisto on harmiton
    # Päätetään asumishistoria vain, jos henkilölle ei jää muuta voimassa olevaa
    # jäsenyyttä yhtiössä.
    remaining = db.execute(
        select(Membership.id).where(
            Membership.user_id == membership.user_id,
            Membership.housing_company_id == ctx.company_id,
            (Membership.valid_to.is_(None)) | (Membership.valid_to > text("now()")),
        )
    ).first()
    if remaining is None:
        db.execute(
            text(
                "UPDATE apartment_occupancies SET valid_to = now()"
                " WHERE user_id = :user AND housing_company_id = :company"
                " AND (valid_to IS NULL OR valid_to > now())"
            ),
            {"user": membership.user_id, "company": ctx.company_id},
        )
    write_audit(db, ctx, "member.ended", "membership", membership_id, role=membership.role)


# --- Huoneiston historia ---


@dataclass
class HistoryRow:
    case_type: str
    status: str
    event_date: date | None
    closed_at: datetime | None
    history_note: str | None


def apartment_history(
    db: Session, ctx: CompanyContext, apartment_id: uuid.UUID
) -> list[HistoryRow]:
    """Huoneiston aiemmat asiat ilman aiempien asukkaiden henkilötietoja (ks. migraatio 0002).

    Tietokantafunktio tarkistaa, että kutsuja asuu huoneistossa nyt tai on isännöitsijä.
    """
    rows = db.execute(
        text(
            "SELECT case_type, status, event_date, closed_at, history_note"
            " FROM app_apartment_history(:apartment)"
        ),
        {"apartment": apartment_id},
    ).all()
    return [HistoryRow(*row) for row in rows]
