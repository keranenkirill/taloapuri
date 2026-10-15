"""Tarjoukset tarjouspyyntöihin ja tekoälyn tuotokset (luonnos, vertailu).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15

Tarjoukset ja tekoälyn tuotokset näkyvät vain hallitukselle ja isännöitsijälle.
Tekoäly ei valitse urakoitsijaa: vertailu on päätöksenteon tukiaineisto.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"
BOARD = "ARRAY['property_manager','board_chair','board_member','treasurer']::text[]"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tender_offers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL,
            case_id uuid NOT NULL,
            contractor_name varchar(200) NOT NULL,
            total_price numeric(12, 2),
            uploaded_by uuid NOT NULL REFERENCES users(id),
            uploaded_by_name varchar(200) NOT NULL,
            filename varchar(200) NOT NULL,
            size_bytes integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 10485760),
            sha256 char(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            removed_at timestamptz,
            UNIQUE (id, housing_company_id),
            FOREIGN KEY (case_id, housing_company_id) REFERENCES cases (id, housing_company_id)
        );
        CREATE INDEX ix_tender_offers_case ON tender_offers (case_id, created_at);

        CREATE TABLE tender_offer_files (
            offer_id uuid PRIMARY KEY,
            housing_company_id uuid NOT NULL,
            content bytea NOT NULL,
            FOREIGN KEY (offer_id, housing_company_id)
                REFERENCES tender_offers (id, housing_company_id)
        );

        CREATE TABLE tender_offer_pages (
            offer_id uuid NOT NULL,
            housing_company_id uuid NOT NULL,
            page_no integer NOT NULL CHECK (page_no >= 1),
            text text NOT NULL,
            PRIMARY KEY (offer_id, page_no),
            FOREIGN KEY (offer_id, housing_company_id)
                REFERENCES tender_offers (id, housing_company_id)
        );

        CREATE TABLE case_ai_outputs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL,
            case_id uuid NOT NULL,
            kind varchar(32) NOT NULL CHECK (kind IN ('tender_draft','offer_comparison')),
            created_by uuid NOT NULL REFERENCES users(id),
            created_by_name varchar(200) NOT NULL,
            text text NOT NULL,
            segments jsonb NOT NULL DEFAULT '[]'::jsonb,
            citations jsonb NOT NULL DEFAULT '[]'::jsonb,
            model varchar(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (case_id, housing_company_id) REFERENCES cases (id, housing_company_id)
        );
        CREATE INDEX ix_case_ai_outputs_case ON case_ai_outputs (case_id, kind, created_at);

        ALTER TABLE ai_runs ADD COLUMN kind varchar(32) NOT NULL DEFAULT 'chat';
        ALTER TABLE ai_runs ADD COLUMN output_id uuid REFERENCES case_ai_outputs(id);
        """
    )
    tables = ("tender_offers", "tender_offer_files", "tender_offer_pages", "case_ai_outputs")
    for table in tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    board_ok = f"app_member_roles(housing_company_id) && {BOARD}"
    op.execute(
        f"""
        CREATE POLICY tender_offers_select ON tender_offers FOR SELECT
            USING (housing_company_id = app_current_company_id() AND {board_ok}
                   AND case_id IN (SELECT id FROM cases));
        CREATE POLICY tender_offers_insert ON tender_offers FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id() AND {board_ok}
                        AND uploaded_by = app_current_user_id()
                        AND case_id IN (SELECT id FROM cases));
        CREATE POLICY tender_offers_update ON tender_offers FOR UPDATE
            USING (housing_company_id = app_current_company_id() AND {board_ok})
            WITH CHECK (housing_company_id = app_current_company_id());

        CREATE POLICY tender_offer_files_select ON tender_offer_files FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND offer_id IN (SELECT id FROM tender_offers));
        CREATE POLICY tender_offer_files_insert ON tender_offer_files FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id()
                        AND offer_id IN (SELECT id FROM tender_offers));
        CREATE POLICY tender_offer_pages_select ON tender_offer_pages FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND offer_id IN (SELECT id FROM tender_offers));
        CREATE POLICY tender_offer_pages_insert ON tender_offer_pages FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id()
                        AND offer_id IN (SELECT id FROM tender_offers));

        CREATE POLICY case_ai_outputs_select ON case_ai_outputs FOR SELECT
            USING (housing_company_id = app_current_company_id() AND {board_ok}
                   AND case_id IN (SELECT id FROM cases));
        CREATE POLICY case_ai_outputs_insert ON case_ai_outputs FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id() AND {board_ok}
                        AND created_by = app_current_user_id()
                        AND case_id IN (SELECT id FROM cases));

        GRANT SELECT, INSERT ON {", ".join(tables)} TO {APP_ROLE};
        GRANT UPDATE (removed_at) ON tender_offers TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ai_runs DROP COLUMN IF EXISTS output_id;
        ALTER TABLE ai_runs DROP COLUMN IF EXISTS kind;
        DROP TABLE IF EXISTS case_ai_outputs, tender_offer_pages, tender_offer_files,
            tender_offers;
        """
    )
