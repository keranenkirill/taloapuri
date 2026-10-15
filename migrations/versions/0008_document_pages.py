"""Pöytäkirjojen sivukohtainen teksti hakua ja tekoälyn lähdeviitteitä varten.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-15

Sivun näkyvyys perii asiakirjan näkyvyyden: asukas löytää haulla vain asukkaille näkyviksi
merkityt pöytäkirjat, hallitus kaikki. chat_citations saa lähteen tyypin ja linkin.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE company_document_pages (
            document_id uuid NOT NULL,
            housing_company_id uuid NOT NULL,
            page_no integer NOT NULL CHECK (page_no >= 1),
            text text NOT NULL,
            search tsvector GENERATED ALWAYS AS (to_tsvector('finnish', text)) STORED,
            PRIMARY KEY (document_id, page_no),
            FOREIGN KEY (document_id, housing_company_id)
                REFERENCES company_documents (id, housing_company_id)
        );
        CREATE INDEX ix_company_document_pages_search
            ON company_document_pages USING gin (search);

        ALTER TABLE company_document_pages ENABLE ROW LEVEL SECURITY;
        ALTER TABLE company_document_pages FORCE ROW LEVEL SECURITY;
        CREATE POLICY document_pages_select ON company_document_pages FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND document_id IN (SELECT id FROM company_documents));
        CREATE POLICY document_pages_insert ON company_document_pages FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id()
                        AND app_is_manager(housing_company_id));
        GRANT SELECT, INSERT ON company_document_pages TO {APP_ROLE};

        ALTER TABLE chat_citations ADD COLUMN source_kind varchar(16) NOT NULL DEFAULT 'law';
        ALTER TABLE chat_citations ADD COLUMN link varchar(500);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_citations DROP COLUMN IF EXISTS link;
        ALTER TABLE chat_citations DROP COLUMN IF EXISTS source_kind;
        DROP TABLE IF EXISTS company_document_pages;
        """
    )
