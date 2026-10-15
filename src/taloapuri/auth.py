"""Tunnistautuminen ja yhtiökohtainen valtuutus.

Vaihe 0: vain kehityskirjautuminen sähköpostilla (eväste dev_user_id; testeissä ja API:ssa
otsake X-Dev-User-Id), joka on käytössä AINOASTAAN ympäristöissä local ja test.
Ei salasanaa. Oikea OIDC + MFA tulee vaiheessa 1 (docs/adr/0003-tunnistautuminen.md).
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from taloapuri.config import get_settings
from taloapuri.db import get_db, set_company_context, set_user_context
from taloapuri.domain.roles import MANAGER_ROLES, Role
from taloapuri.models import HousingCompany, User

DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    display_name: str = ""
    email: str | None = None
    is_platform_admin: bool = False


@dataclass(frozen=True)
class CompanyContext:
    company_id: uuid.UUID
    company_name: str
    user_id: uuid.UUID
    roles: frozenset[Role]
    user_name: str = ""
    user_email: str | None = None
    # Huoneistot, joissa käyttäjä asuu tai on osakkaana nyt (näytetään sivun yläreunassa).
    apartment_labels: tuple[str, ...] = ()
    # Lukemattomat viestiketjut (yläpalkin ✉ Viestit -laskuri).
    unread_messages: int = 0
    # Lukemattomat asiat (yläpalkin 🔔 Uutta -laskuri), ks. services/activity.py.
    unread_cases: int = 0

    @property
    def is_manager(self) -> bool:
        return bool(self.roles & MANAGER_ROLES)


def _load_user(db: Session, raw: str | None) -> CurrentUser | None:
    if not get_settings().dev_auth_enabled or not raw:
        # Tuotantotyyppisissä ympäristöissä ei ole vielä kirjautumista → kaikki estetään.
        return None
    try:
        user_id = uuid.UUID(raw)
    except ValueError:
        return None
    set_user_context(db, user_id)
    row = db.execute(  # RLS: käyttäjä näkee oman rivinsä
        select(User.display_name, User.email, User.is_platform_admin).where(User.id == user_id)
    ).first()
    if row is None:
        return None
    return CurrentUser(
        id=user_id,
        display_name=row.display_name,
        email=row.email,
        is_platform_admin=row.is_platform_admin,
    )


def get_current_user(
    db: DbSession,
    x_dev_user_id: Annotated[str | None, Header()] = None,
    dev_user_id: Annotated[str | None, Cookie()] = None,
) -> CurrentUser:
    user = _load_user(db, x_dev_user_id or dev_user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Kirjautuminen vaaditaan")
    return user


def get_optional_user(
    db: DbSession,
    x_dev_user_id: Annotated[str | None, Header()] = None,
    dev_user_id: Annotated[str | None, Cookie()] = None,
) -> CurrentUser | None:
    """Sivuille, jotka toimivat myös kirjautumatta (etusivu)."""
    return _load_user(db, x_dev_user_id or dev_user_id)


def get_company_context(
    company_id: uuid.UUID,
    db: DbSession,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CompanyContext:
    """Tarkistaa voimassa olevan jäsenyyden ja asettaa tenant-kontekstin.

    Palauttaa 404 eikä 403, jos jäsenyyttä ei ole: näin ei paljasteta, onko yhtiö olemassa.
    """
    set_company_context(db, company_id)
    company = db.execute(
        select(HousingCompany).where(HousingCompany.id == company_id)
    ).scalar_one_or_none()
    if company is None:  # RLS piilottaa yhtiöt, joissa ei ole voimassa olevaa jäsenyyttä
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Taloyhtiötä ei löytynyt")
    roles_raw: list[str] = db.execute(select(func.app_member_roles(company_id))).scalar_one()
    roles = frozenset(Role(r) for r in roles_raw)
    if not roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Taloyhtiötä ei löytynyt")
    labels = db.execute(
        text(
            "SELECT DISTINCT a.label FROM apartments a"
            " JOIN apartment_occupancies o ON o.apartment_id = a.id"
            " WHERE a.housing_company_id = :c AND o.user_id = :u"
            " AND o.valid_from <= now() AND (o.valid_to IS NULL OR o.valid_to > now())"
            " ORDER BY a.label"
        ),
        {"c": company_id, "u": user.id},
    ).scalars()
    return CompanyContext(
        company_id=company_id,
        company_name=company.name,
        user_id=user.id,
        roles=roles,
        user_name=user.display_name,
        user_email=user.email,
        apartment_labels=tuple(labels),
        unread_cases=_unread_case_count(db, company_id, user.id),
        unread_messages=db.execute(
            text(
                "SELECT count(*) FROM message_participants p"
                " WHERE p.user_id = :u AND p.housing_company_id = :c AND EXISTS ("
                "  SELECT 1 FROM direct_messages dm WHERE dm.thread_id = p.thread_id"
                "  AND dm.sender_id <> :u"
                "  AND dm.created_at > coalesce(p.last_read_at, '-infinity'::timestamptz))"
            ),
            {"u": user.id, "c": company_id},
        ).scalar_one(),
    )


def _unread_case_count(db: Session, company_id: uuid.UUID, user_id: uuid.UUID) -> int:
    from taloapuri.services.activity import unread_case_count

    return unread_case_count(db, company_id, user_id)


CompanyCtx = Annotated[CompanyContext, Depends(get_company_context)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_platform_admin(user: UserDep) -> CurrentUser:
    """Vain palvelun ylläpitäjälle. Muille 404, jotta sivun olemassaoloa ei paljasteta."""
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return user


AdminUser = Annotated[CurrentUser, Depends(require_platform_admin)]
OptionalUser = Annotated[CurrentUser | None, Depends(get_optional_user)]
