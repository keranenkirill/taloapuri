"""Asiakohtaiset lomaketiedot, lisätietopyyntöjen keskustelu ja valokuvat.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15

- cases.details: tyyppikohtaiset tiedot (validoidaan Pydantic-malleilla, domain/case_details.py).
- Tarjouspyynnön voi luoda vain hallitus tai isännöitsijä (cases_insert-politiikka).
- case_messages: lisätietopyynnöt, vastaukset ja kommentit. Näkyvyys perii asian näkyvyyden.
- case_attachments (+ _files): uudelleenkoodatut valokuvat ilman metatietoja.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"
# Pidä samana kuin taloapuri.domain.roles.ROLES_SEEING_ALL_CASES.
BOARD = "ARRAY['property_manager','board_chair','board_member','treasurer']::text[]"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE cases ADD COLUMN details jsonb NOT NULL DEFAULT '{{}}'::jsonb;

        DROP POLICY cases_insert ON cases;
        CREATE POLICY cases_insert ON cases FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND created_by = app_current_user_id()
                AND cardinality(app_member_roles(housing_company_id)) > 0
                AND (case_type <> 'tender_request'
                     OR app_member_roles(housing_company_id) && {BOARD})
            );

        CREATE TABLE case_messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL,
            case_id uuid NOT NULL,
            author_id uuid NOT NULL REFERENCES users(id),
            author_name varchar(200) NOT NULL,
            kind varchar(16) NOT NULL
                CHECK (kind IN ('info_request','info_response','comment')),
            body text NOT NULL CHECK (length(trim(body)) > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (case_id, housing_company_id) REFERENCES cases (id, housing_company_id)
        );
        CREATE INDEX ix_case_messages_case ON case_messages (case_id, created_at);

        CREATE TABLE case_attachments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL,
            case_id uuid NOT NULL,
            uploaded_by uuid NOT NULL REFERENCES users(id),
            filename varchar(200) NOT NULL,
            content_type varchar(50) NOT NULL CHECK (content_type = 'image/jpeg'),
            size_bytes integer NOT NULL CHECK (size_bytes > 0),
            width integer NOT NULL,
            height integer NOT NULL,
            sha256 char(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, housing_company_id),
            FOREIGN KEY (case_id, housing_company_id) REFERENCES cases (id, housing_company_id)
        );
        CREATE INDEX ix_case_attachments_case ON case_attachments (case_id, created_at);

        CREATE TABLE case_attachment_files (
            attachment_id uuid PRIMARY KEY,
            housing_company_id uuid NOT NULL,
            content bytea NOT NULL,
            FOREIGN KEY (attachment_id, housing_company_id)
                REFERENCES case_attachments (id, housing_company_id)
        );
        """
    )
    for table in ("case_messages", "case_attachments", "case_attachment_files"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        -- Näkyy, jos asia näkyy (cases-RLS pätee alikyselyssä).
        CREATE POLICY case_messages_select ON case_messages FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND case_id IN (SELECT id FROM cases));
        CREATE POLICY case_messages_insert ON case_messages FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id()
                        AND author_id = app_current_user_id()
                        AND case_id IN (SELECT id FROM cases));

        CREATE POLICY case_attachments_select ON case_attachments FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND case_id IN (SELECT id FROM cases));
        -- Kuvia voi lisätä asian tekijä sekä hallitus ja isännöitsijä.
        CREATE POLICY case_attachments_insert ON case_attachments FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND uploaded_by = app_current_user_id()
                AND (case_id IN (SELECT id FROM cases WHERE created_by = app_current_user_id())
                     OR (case_id IN (SELECT id FROM cases)
                         AND app_member_roles(housing_company_id) && {BOARD}))
            );

        CREATE POLICY case_attachment_files_select ON case_attachment_files FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND attachment_id IN (SELECT id FROM case_attachments));
        CREATE POLICY case_attachment_files_insert ON case_attachment_files FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id()
                        AND attachment_id IN (SELECT id FROM case_attachments));

        GRANT SELECT, INSERT ON case_messages, case_attachments, case_attachment_files
            TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS case_attachment_files, case_attachments, case_messages;
        DROP POLICY cases_insert ON cases;
        CREATE POLICY cases_insert ON cases FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND created_by = app_current_user_id()
                AND cardinality(app_member_roles(housing_company_id)) > 0
            );
        ALTER TABLE cases DROP COLUMN IF EXISTS details;
        """
    )
