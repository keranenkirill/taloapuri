"""Tietokantayhteys ja tenant-konteksti.

Jokainen pyyntö ajetaan yhdessä transaktiossa. Kontekstimuuttujat asetetaan
set_config(..., is_local => true) -kutsulla, joten ne ovat voimassa vain tämän transaktion
ajan eivätkä vuoda yhteyspoolissa seuraavalle pyynnölle.
"""

import uuid
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from taloapuri.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI-riippuvuus: yksi transaktio per pyyntö, commit onnistuessa."""
    session = get_session_factory()()
    try:
        with session.begin():
            yield session
    finally:
        session.close()


def set_user_context(session: Session, user_id: uuid.UUID) -> None:
    session.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(user_id)})


def set_company_context(session: Session, company_id: uuid.UUID) -> None:
    session.execute(
        text("SELECT set_config('app.current_company_id', :v, true)"), {"v": str(company_id)}
    )
