"""Palvelun ylläpitäjä, lakilähteiden hallinta ja taloyhtiön omat UKK-kysymykset.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-16

- users.is_platform_admin: palvelun ylläpitäjä (ei yhtiörooli). Lippua ei voi asettaa sovelluksen
  kautta: sovellusrooli saa lisätä käyttäjän vain sarakkeisiin (id, display_name, email).
- Lakilähteet (sources, source_versions, source_sections) ovat yhteisiä kaikille yhtiöille.
  Niihin kirjoittaa vain ylläpitäjä (RLS). DELETE-oikeutta ei ole kenelläkään: vanhat versiot
  säilyvät, koska aiemmat tekoälyvastaukset viittaavat niihin.
- company_faq: taloyhtiön omat usein kysytyt kysymykset; isännöitsijä hallitsee, jäsenet lukevat.
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE users ADD COLUMN is_platform_admin boolean NOT NULL DEFAULT false;
        REVOKE INSERT ON users FROM {APP_ROLE};
        GRANT INSERT (id, display_name, email) ON users TO {APP_ROLE};

        -- Kutsujan oma lippu; SECURITY DEFINER, jotta se toimii myös ilman yhtiökontekstia.
        CREATE FUNCTION app_is_platform_admin() RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
            $$ SELECT coalesce(
                   (SELECT is_platform_admin FROM users WHERE id = app_current_user_id()), false) $$;
        REVOKE ALL ON FUNCTION app_is_platform_admin() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_is_platform_admin() TO {APP_ROLE};

        ALTER TABLE sources ADD COLUMN act_year integer;
        ALTER TABLE sources ADD COLUMN act_number integer;
        UPDATE sources SET act_year = split_part(source_key, '/', 3)::integer,
                           act_number = split_part(source_key, '/', 4)::integer;
        ALTER TABLE sources ALTER COLUMN act_year SET NOT NULL;
        ALTER TABLE sources ALTER COLUMN act_number SET NOT NULL;
        ALTER TABLE sources ADD COLUMN active boolean NOT NULL DEFAULT true;
        ALTER TABLE sources ADD COLUMN is_core boolean NOT NULL DEFAULT false;
        ALTER TABLE sources ADD COLUMN last_checked_at timestamptz;
        -- Ei viiteavainta: TRUNCATE users CASCADE (seed) pyyhkisi muuten myös lait.
        ALTER TABLE sources ADD COLUMN added_by uuid;
        ALTER TABLE sources ADD COLUMN added_at timestamptz NOT NULL DEFAULT now();
        UPDATE sources SET is_core = true WHERE source_key = 'fi/statute/2009/1599';
        CREATE UNIQUE INDEX ux_sources_short_title ON sources (lower(short_title));

        ALTER TABLE source_versions ADD COLUMN change_summary jsonb;

        CREATE POLICY sources_admin_insert ON sources FOR INSERT
            WITH CHECK (app_is_platform_admin());
        CREATE POLICY sources_admin_update ON sources FOR UPDATE
            USING (app_is_platform_admin()) WITH CHECK (app_is_platform_admin());
        CREATE POLICY source_versions_admin_insert ON source_versions FOR INSERT
            WITH CHECK (app_is_platform_admin());
        CREATE POLICY source_sections_admin_insert ON source_sections FOR INSERT
            WITH CHECK (app_is_platform_admin());
        GRANT INSERT ON sources, source_versions, source_sections TO {APP_ROLE};
        GRANT UPDATE (title, short_title, public_url, current_version_id, last_checked_at, active)
            ON sources TO {APP_ROLE};

        CREATE TABLE company_faq (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            question varchar(200) NOT NULL CHECK (length(trim(question)) > 0),
            answer varchar(2000) NOT NULL CHECK (length(trim(answer)) > 0),
            sort_order integer NOT NULL DEFAULT 0,
            created_by uuid NOT NULL REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_company_faq_company ON company_faq (housing_company_id, sort_order);
        ALTER TABLE company_faq ENABLE ROW LEVEL SECURITY;
        ALTER TABLE company_faq FORCE ROW LEVEL SECURITY;
        CREATE POLICY company_faq_select ON company_faq FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND cardinality(app_member_roles(housing_company_id)) > 0);
        CREATE POLICY company_faq_insert ON company_faq FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id()
                        AND app_is_manager(housing_company_id)
                        AND created_by = app_current_user_id());
        CREATE POLICY company_faq_update ON company_faq FOR UPDATE
            USING (housing_company_id = app_current_company_id()
                   AND app_is_manager(housing_company_id))
            WITH CHECK (housing_company_id = app_current_company_id());
        CREATE POLICY company_faq_delete ON company_faq FOR DELETE
            USING (housing_company_id = app_current_company_id()
                   AND app_is_manager(housing_company_id));
        GRANT SELECT, INSERT, DELETE ON company_faq TO {APP_ROLE};
        GRANT UPDATE (question, answer, sort_order, updated_at) ON company_faq TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS company_faq;
        DROP POLICY IF EXISTS source_sections_admin_insert ON source_sections;
        DROP POLICY IF EXISTS source_versions_admin_insert ON source_versions;
        DROP POLICY IF EXISTS sources_admin_update ON sources;
        DROP POLICY IF EXISTS sources_admin_insert ON sources;
        REVOKE INSERT ON sources, source_versions, source_sections FROM taloapuri_app;
        REVOKE UPDATE ON sources FROM taloapuri_app;
        ALTER TABLE source_versions DROP COLUMN IF EXISTS change_summary;
        DROP INDEX IF EXISTS ux_sources_short_title;
        ALTER TABLE sources DROP COLUMN IF EXISTS added_at, DROP COLUMN IF EXISTS added_by,
            DROP COLUMN IF EXISTS last_checked_at, DROP COLUMN IF EXISTS is_core,
            DROP COLUMN IF EXISTS active, DROP COLUMN IF EXISTS act_number,
            DROP COLUMN IF EXISTS act_year;
        DROP FUNCTION IF EXISTS app_is_platform_admin();
        REVOKE INSERT ON users FROM taloapuri_app;
        GRANT INSERT ON users TO taloapuri_app;
        ALTER TABLE users DROP COLUMN IF EXISTS is_platform_admin;
        """
    )
