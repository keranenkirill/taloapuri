import os
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine

from taloapuri.models import Base

target_metadata = Base.metadata

# .env luetaan automaattisesti (ympäristömuuttujat ovat etusijalla).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or os.environ.get(
        "TALOAPURI_MIGRATION_DATABASE_URL"
    )
    if not url:
        raise RuntimeError(
            "Aseta TALOAPURI_MIGRATION_DATABASE_URL (taulut omistava rooli) tai anna -x url=..."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
