"""Käyttäjän omat asetukset (sähköposti)."""

import re

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from taloapuri.auth import CurrentUser

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InvalidEmail(Exception):
    pass


def change_email(db: Session, user: CurrentUser, new_email: str) -> str:
    """Vaihtaa oman sähköpostin heti.

    Vahvistusviesti lisätään, kun sähköpostin lähetys on käytössä.
    """
    email = new_email.strip()
    if not _EMAIL.match(email) or len(email) > 320:
        raise InvalidEmail("Tarkista sähköpostiosoite, esimerkiksi nimi@esimerkki.fi.")
    try:
        with db.begin_nested():
            db.execute(
                text("UPDATE users SET email = :e WHERE id = :id"), {"e": email, "id": user.id}
            )
    except IntegrityError as exc:
        raise InvalidEmail("Sähköpostiosoite on jo toisen käyttäjän käytössä.") from exc
    # Audit ilman yhtiötä (käyttäjätason muutos); osoitetta ei kirjata lokiin.
    db.execute(
        text(
            "INSERT INTO audit_events (housing_company_id, actor_user_id, action, target_type,"
            " target_id) VALUES (NULL, :u, 'user.email_changed', 'user', :t)"
        ),
        {"u": user.id, "t": str(user.id)},
    )
    return email
