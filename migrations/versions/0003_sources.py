"""Julkiset oikeuslähteet (Finlex): lähteet, versiot ja pykälä/momenttitason tekstit.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15

Lähteet ovat julkisia eivätkä kuulu millekään yhtiölle. Kirjautunut käyttäjä saa lukea niitä;
sovellusroolilla ei ole kirjoitusoikeutta (ingestio ajetaan omistajaroolilla).
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        CREATE TABLE sources (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_key varchar(64) NOT NULL UNIQUE,      -- esim. 'fi/statute/2009/1599'
            title varchar(300) NOT NULL,
            short_title varchar(32) NOT NULL,            -- esim. 'AOYL'
            public_url varchar(500) NOT NULL,
            current_version_id uuid,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE source_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid NOT NULL REFERENCES sources(id),
            version_label varchar(32) NOT NULL,          -- Finlexin FRBRversionNumber
            consolidated_date date,                      -- ajantasaistuksen päivä
            fetched_at timestamptz NOT NULL DEFAULT now(),
            sha256 char(64) NOT NULL,
            UNIQUE (source_id, sha256)
        );
        ALTER TABLE sources ADD CONSTRAINT fk_sources_current_version
            FOREIGN KEY (current_version_id) REFERENCES source_versions(id);

        CREATE TABLE source_sections (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            version_id uuid NOT NULL REFERENCES source_versions(id),
            ord integer NOT NULL,
            eid varchar(200) NOT NULL,
            chapter_num varchar(32),
            chapter_heading varchar(300),
            section_num varchar(32) NOT NULL,
            section_heading varchar(500),
            subsection_no integer,                       -- momentti; NULL jos pykälässä ei momentteja
            text text NOT NULL,
            -- Pykälän otsikko painavin (A), luvun otsikko (B), teksti (C).
            search tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('finnish', coalesce(section_heading, '')), 'A')
                || setweight(to_tsvector('finnish', coalesce(chapter_heading, '')), 'B')
                || setweight(to_tsvector('finnish', text), 'C')
            ) STORED,
            UNIQUE (version_id, eid)
        );
        CREATE INDEX ix_source_sections_search ON source_sections USING gin (search);
        CREATE INDEX ix_source_sections_trgm ON source_sections USING gin (text gin_trgm_ops);
        CREATE INDEX ix_source_sections_section
            ON source_sections (version_id, chapter_num, section_num);
        """
    )
    for table in ("sources", "source_versions", "source_sections"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_read ON {table} FOR SELECT"
            " USING (app_current_user_id() IS NOT NULL)"
        )
        op.execute(f"GRANT SELECT ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE sources DROP CONSTRAINT IF EXISTS fk_sources_current_version;
        DROP TABLE IF EXISTS source_sections, source_versions, sources;
        """
    )
