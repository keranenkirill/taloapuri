"""Tenant-ydin: asiakkuudet, yhtiöt, käyttäjät, jäsenyydet, asiat, tapahtumat, audit + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-10-15

RLS-periaatteet (ks. docs/adr/0004-tenant-eristys-ja-rls.md):
- Sovellusrooli taloapuri_app ei omista tauluja ja kaikissa tauluissa on FORCE ROW LEVEL SECURITY.
- Sovellus asettaa jokaisen transaktion alussa SET LOCAL -tyyppisesti
  app.current_user_id ja app.current_company_id (set_config(..., true)).
- Jäsenyyden voimassaolo tarkistetaan myös tietokannassa (app_member_roles), ei vain Pythonissa.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"

ROLES = (
    "'property_manager','board_chair','board_member','treasurer',"
    "'shareholder','resident','external_expert'"
)
STATUSES = (
    "'draft','awaiting_info','in_review','escalated','approved','sent',"
    "'send_failed','rejected','cancelled','closed'"
)
# Pidä samana kuin taloapuri.domain.roles.ROLES_SEEING_ALL_CASES.
SEE_ALL = "ARRAY['property_manager','board_chair','board_member','treasurer']::text[]"

TABLES = (
    "accounts",
    "housing_companies",
    "account_companies",
    "users",
    "memberships",
    "cases",
    "case_events",
    "audit_events",
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE accounts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name varchar(200) NOT NULL,
            account_type varchar(32) NOT NULL
                CHECK (account_type IN ('housing_company','management_firm')),
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE housing_companies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name varchar(200) NOT NULL,
            business_id varchar(16) UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE account_companies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id uuid NOT NULL REFERENCES accounts(id),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            valid_from timestamptz NOT NULL,
            valid_to timestamptz,
            CHECK (valid_to IS NULL OR valid_to > valid_from)
        );
        CREATE INDEX ix_account_companies_company ON account_companies (housing_company_id);

        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            oidc_subject varchar(255) UNIQUE,
            display_name varchar(200) NOT NULL,
            email varchar(320),
            pseudonymized_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE memberships (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            role varchar(32) NOT NULL CHECK (role IN ({ROLES})),
            valid_from timestamptz NOT NULL DEFAULT now(),
            valid_to timestamptz,
            invited_by uuid REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (valid_to IS NULL OR valid_to > valid_from)
        );
        CREATE INDEX ix_memberships_user_company ON memberships (user_id, housing_company_id);

        CREATE TABLE cases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            case_type varchar(32) NOT NULL,
            title varchar(200) NOT NULL,
            description text NOT NULL DEFAULT '',
            status varchar(32) NOT NULL CHECK (status IN ({STATUSES})),
            event_date date,
            created_by uuid NOT NULL REFERENCES users(id),
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- Mahdollistaa komposiittiviiteavaimen, joka estää liittämästä tapahtumaa
            -- toisen yhtiön asiaan.
            UNIQUE (id, housing_company_id)
        );
        CREATE INDEX ix_cases_company_status ON cases (housing_company_id, status);

        CREATE TABLE case_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL,
            case_id uuid NOT NULL,
            event_type varchar(32) NOT NULL,
            from_status varchar(32),
            to_status varchar(32),
            actor_user_id uuid NOT NULL REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (case_id, housing_company_id)
                REFERENCES cases (id, housing_company_id)
        );
        CREATE INDEX ix_case_events_case ON case_events (case_id, created_at);

        CREATE TABLE audit_events (
            id bigserial PRIMARY KEY,
            housing_company_id uuid REFERENCES housing_companies(id),
            actor_user_id uuid REFERENCES users(id),
            action varchar(64) NOT NULL,
            target_type varchar(32) NOT NULL,
            target_id varchar(64),
            metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_audit_events_company_time ON audit_events (housing_company_id, created_at);
        """
    )

    # Kontekstifunktiot. STABLE + SECURITY INVOKER: ne näkevät vain sen, minkä RLS sallii.
    op.execute(
        """
        CREATE FUNCTION app_current_user_id() RETURNS uuid
            LANGUAGE sql STABLE AS
            $$ SELECT nullif(current_setting('app.current_user_id', true), '')::uuid $$;

        CREATE FUNCTION app_current_company_id() RETURNS uuid
            LANGUAGE sql STABLE AS
            $$ SELECT nullif(current_setting('app.current_company_id', true), '')::uuid $$;

        -- Nykyisen käyttäjän voimassa olevat roolit annetussa yhtiössä.
        CREATE FUNCTION app_member_roles(company uuid) RETURNS text[]
            LANGUAGE sql STABLE AS
            $$
            SELECT coalesce(array_agg(role::text), '{}'::text[])
              FROM memberships
             WHERE user_id = app_current_user_id()
               AND housing_company_id = company
               AND valid_from <= now()
               AND (valid_to IS NULL OR valid_to > now())
            $$;
        """
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        f"""
        -- Jäsenyydet: käyttäjä näkee vain omat jäsenyytensä. (Jäsenluettelo toteutetaan
        -- myöhemmin erillisellä, tarkistetulla funktiolla – ei rekursiivista politiikkaa.)
        CREATE POLICY memberships_own ON memberships FOR SELECT
            USING (user_id = app_current_user_id());

        CREATE POLICY users_self ON users FOR SELECT
            USING (id = app_current_user_id());

        CREATE POLICY housing_companies_member ON housing_companies FOR SELECT
            USING (cardinality(app_member_roles(id)) > 0);

        CREATE POLICY account_companies_member ON account_companies FOR SELECT
            USING (cardinality(app_member_roles(housing_company_id)) > 0);

        CREATE POLICY accounts_member ON accounts FOR SELECT
            USING (id IN (SELECT account_id FROM account_companies));

        -- Asiat: vain valittu yhtiö; hallitus/isännöitsijä näkee kaikki, muut omansa.
        CREATE POLICY cases_select ON cases FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND (
                    app_member_roles(housing_company_id) && {SEE_ALL}
                    OR (created_by = app_current_user_id()
                        AND cardinality(app_member_roles(housing_company_id)) > 0)
                )
            );
        CREATE POLICY cases_insert ON cases FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND created_by = app_current_user_id()
                AND cardinality(app_member_roles(housing_company_id)) > 0
            );
        CREATE POLICY cases_update ON cases FOR UPDATE
            USING (
                housing_company_id = app_current_company_id()
                AND (
                    app_member_roles(housing_company_id) && {SEE_ALL}
                    OR (created_by = app_current_user_id()
                        AND cardinality(app_member_roles(housing_company_id)) > 0)
                )
            )
            WITH CHECK (housing_company_id = app_current_company_id());

        CREATE POLICY case_events_select ON case_events FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND case_id IN (SELECT id FROM cases)
            );
        CREATE POLICY case_events_insert ON case_events FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND actor_user_id = app_current_user_id()
                AND case_id IN (SELECT id FROM cases)
            );

        CREATE POLICY audit_events_insert ON audit_events FOR INSERT
            WITH CHECK (
                actor_user_id = app_current_user_id()
                AND (housing_company_id IS NULL
                     OR housing_company_id = app_current_company_id())
            );
        CREATE POLICY audit_events_select ON audit_events FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND app_member_roles(housing_company_id)
                    && ARRAY['property_manager','board_chair']::text[]
            );
        """
    )

    # Oikeudet: vain tarvittava. Ei DELETE-oikeuksia; audit-loki on append-only.
    op.execute(
        f"""
        GRANT SELECT ON {", ".join(TABLES)} TO {APP_ROLE};
        GRANT INSERT, UPDATE ON cases TO {APP_ROLE};
        GRANT INSERT ON case_events, audit_events TO {APP_ROLE};
        GRANT USAGE ON SEQUENCE audit_events_id_seq TO {APP_ROLE};
        GRANT EXECUTE ON FUNCTION app_current_user_id(), app_current_company_id(),
            app_member_roles(uuid) TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS audit_events, case_events, cases, memberships, users,
            account_companies, housing_companies, accounts CASCADE;
        DROP FUNCTION IF EXISTS app_member_roles(uuid);
        DROP FUNCTION IF EXISTS app_current_company_id();
        DROP FUNCTION IF EXISTS app_current_user_id();
        """
    )
