"""Sähköpostitunnistus, oman sähköpostin muutos ja hallituksen pöytäkirjat.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15

- users.email on yksilöllinen (kirjainkoosta riippumatta). Käyttäjä voi muuttaa omaa
  sähköpostiaan. app_find_user_by_email() on vain kehityskirjautumista varten.
- company_documents: isännöitsijän lataamat pöytäkirjat. Isännöitsijä päättää tiedostokohtaisesti,
  näkevätkö osakkaat ja asukkaat sen; hallitus ja isännöitsijä näkevät aina.
- Tiedoston sisältö on erillisessä taulussa (bytea), jotta listaukset eivät lataa tiedostoja.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"
# Pidä samana kuin taloapuri.domain.roles.ROLES_SEEING_ALL_CASES.
BOARD = "ARRAY['property_manager','board_chair','board_member','treasurer']::text[]"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_users_email_lower ON users (lower(email)) WHERE email IS NOT NULL;

        CREATE POLICY users_self_update ON users FOR UPDATE
            USING (id = app_current_user_id())
            WITH CHECK (id = app_current_user_id());
        GRANT UPDATE (email) ON users TO {APP_ROLE};

        -- Vain kehityskirjautumiseen: palauttaa tunnisteen, ei muita tietoja.
        CREATE FUNCTION app_find_user_by_email(address text) RETURNS uuid
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
            $$ SELECT id FROM users WHERE lower(email) = lower(trim(address)) LIMIT 1 $$;
        REVOKE ALL ON FUNCTION app_find_user_by_email(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_find_user_by_email(text) TO {APP_ROLE};

        CREATE TABLE company_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            kind varchar(32) NOT NULL DEFAULT 'board_minutes'
                CHECK (kind IN ('board_minutes')),
            title varchar(200) NOT NULL,
            meeting_date date,
            description varchar(1000),
            visible_to_residents boolean NOT NULL DEFAULT false,
            uploaded_by uuid NOT NULL REFERENCES users(id),
            uploaded_by_name varchar(200) NOT NULL,
            uploaded_at timestamptz NOT NULL DEFAULT now(),
            filename varchar(200) NOT NULL,
            content_type varchar(100) NOT NULL,
            size_bytes integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 10485760),
            sha256 char(64) NOT NULL,
            removed_at timestamptz,
            UNIQUE (id, housing_company_id)
        );
        CREATE INDEX ix_company_documents_company_time
            ON company_documents (housing_company_id, uploaded_at DESC);

        CREATE TABLE company_document_files (
            document_id uuid PRIMARY KEY,
            housing_company_id uuid NOT NULL,
            content bytea NOT NULL,
            FOREIGN KEY (document_id, housing_company_id)
                REFERENCES company_documents (id, housing_company_id)
        );
        """
    )
    for table in ("company_documents", "company_document_files"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY documents_select ON company_documents FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND removed_at IS NULL
                AND cardinality(app_member_roles(housing_company_id)) > 0
                AND (visible_to_residents OR app_member_roles(housing_company_id) && {BOARD})
            );
        -- Isännöitsijä näkee myös poistetut (UPDATE-rivin on läpäistävä SELECT-politiikka,
        -- muuten pehmeä poisto estyisi). Palvelukerros suodattaa poistetut listauksista.
        CREATE POLICY documents_manager_select ON company_documents FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
            );
        CREATE POLICY documents_insert ON company_documents FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
                AND uploaded_by = app_current_user_id()
            );
        CREATE POLICY documents_update ON company_documents FOR UPDATE
            USING (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
            )
            WITH CHECK (housing_company_id = app_current_company_id());

        -- Tiedosto näkyy vain, jos sen asiakirja näkyy (asiakirjan RLS pätee alikyselyssä).
        CREATE POLICY document_files_select ON company_document_files FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND document_id IN (SELECT id FROM company_documents)
            );
        CREATE POLICY document_files_insert ON company_document_files FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
            );

        GRANT SELECT, INSERT ON company_documents, company_document_files TO {APP_ROLE};
        GRANT UPDATE (visible_to_residents, removed_at, title) ON company_documents TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS company_document_files, company_documents;
        DROP FUNCTION IF EXISTS app_find_user_by_email(text);
        REVOKE UPDATE (email) ON users FROM taloapuri_app;
        DROP POLICY IF EXISTS users_self_update ON users;
        DROP INDEX IF EXISTS ux_users_email_lower;
        """
    )
