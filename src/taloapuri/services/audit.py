import uuid
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext


def write_audit(
    db: Session,
    ctx: CompanyContext,
    action: str,
    target_type: str,
    target_id: uuid.UUID,
    **meta: Any,
) -> None:
    """Kirjaa audit-tapahtuman. Metadataan ei henkilötietoja eikä vapaatekstiä.

    Pelkkä INSERT ilman RETURNING-osaa: RLS sallii kaikkien jäsenten kirjoittaa audit-lokiin,
    mutta vain isännöitsijä ja puheenjohtaja saavat lukea sitä.
    """
    db.execute(
        text(
            "INSERT INTO audit_events"
            " (housing_company_id, actor_user_id, action, target_type, target_id, metadata)"
            " VALUES (:company, :actor, :action, :target_type, :target, :meta)"
        ).bindparams(bindparam("meta", type_=JSONB)),
        {
            "company": ctx.company_id,
            "actor": ctx.user_id,
            "action": action,
            "target_type": target_type,
            "target": str(target_id),
            "meta": meta,
        },
    )


def write_user_audit(
    db: Session,
    user_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: str,
    **meta: Any,
) -> None:
    """Audit-tapahtuma ilman yhtiötä (esim. ylläpitäjän lakipäivitys). Ei henkilötietoja."""
    db.execute(
        text(
            "INSERT INTO audit_events (housing_company_id, actor_user_id, action, target_type,"
            " target_id, metadata) VALUES (NULL, :actor, :action, :target_type, :target, :meta)"
        ).bindparams(bindparam("meta", type_=JSONB)),
        {
            "actor": user_id,
            "action": action,
            "target_type": target_type,
            "target": target_id,
            "meta": meta,
        },
    )
