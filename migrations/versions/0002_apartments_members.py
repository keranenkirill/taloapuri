"""Huoneistot, asumishistoria ja jäsenten hallinta.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15

- apartments ja apartment_occupancies (kuka asuu/omistaa minkä huoneiston ja milloin).
- cases.apartment_id ja cases.history_note (isännöitsijän kirjoittama, myöhemmille asukkaille
  näytettävä merkintä).
- Isännöitsijä ja puheenjohtaja voivat lisätä osakkaita/asukkaita ja päättää heidän
  käyttöoikeutensa. Rivejä ei poisteta, vaan valid_to asetetaan (historia säilyy).
- app_member_roles() muutetaan SECURITY DEFINERiksi, jotta memberships-taulun
  isännöitsijäpolitiikka ei ole rekursiivinen. Funktio palauttaa vain kutsujan omat roolit.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"
MANAGERS = "ARRAY['property_manager','board_chair']::text[]"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE apartments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            label varchar(32) NOT NULL CHECK (length(trim(label)) > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (housing_company_id, label),
            UNIQUE (id, housing_company_id)
        );

        CREATE TABLE apartment_occupancies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL,
            apartment_id uuid NOT NULL,
            user_id uuid NOT NULL REFERENCES users(id),
            relation varchar(16) NOT NULL CHECK (relation IN ('shareholder','resident')),
            valid_from timestamptz NOT NULL DEFAULT now(),
            valid_to timestamptz,
            created_by uuid REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (apartment_id, housing_company_id)
                REFERENCES apartments (id, housing_company_id),
            CHECK (valid_to IS NULL OR valid_to > valid_from)
        );
        CREATE INDEX ix_occupancies_apartment ON apartment_occupancies (apartment_id);
        CREATE INDEX ix_occupancies_user ON apartment_occupancies (user_id, housing_company_id);

        ALTER TABLE cases ADD COLUMN apartment_id uuid;
        ALTER TABLE cases ADD COLUMN history_note varchar(500);
        ALTER TABLE cases ADD CONSTRAINT fk_cases_apartment
            FOREIGN KEY (apartment_id, housing_company_id)
            REFERENCES apartments (id, housing_company_id);
        CREATE INDEX ix_cases_apartment ON cases (apartment_id);

        -- Palauttaa vain kutsujan omat voimassa olevat roolit, joten SECURITY DEFINER on turvallinen.
        CREATE OR REPLACE FUNCTION app_member_roles(company uuid) RETURNS text[]
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
            $$
            SELECT coalesce(array_agg(role::text), '{}'::text[])
              FROM memberships
             WHERE user_id = app_current_user_id()
               AND housing_company_id = company
               AND valid_from <= now()
               AND (valid_to IS NULL OR valid_to > now())
            $$;
        REVOKE ALL ON FUNCTION app_member_roles(uuid) FROM PUBLIC;
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app_is_manager(company uuid) RETURNS boolean
            LANGUAGE sql STABLE AS
            $$ SELECT app_member_roles(company) && {MANAGERS} $$;
        """
    )

    # Huoneiston historia uudelle asukkaalle: VAIN turvalliset sarakkeet, ei otsikkoa, kuvausta
    # eikä tekijää. SECURITY DEFINER ohittaa RLS:n, joten yhtiö ja oikeus tarkistetaan tässä.
    op.execute(
        """
        CREATE FUNCTION app_apartment_history(apartment uuid)
            RETURNS TABLE (case_type varchar, status varchar, event_date date,
                           closed_at timestamptz, history_note varchar)
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
            $$
            SELECT c.case_type, c.status, c.event_date,
                   (SELECT max(e.created_at) FROM case_events e
                     WHERE e.case_id = c.id AND e.to_status = 'closed') AS closed_at,
                   c.history_note
              FROM cases c
              JOIN apartments a ON a.id = c.apartment_id
             WHERE a.id = apartment
               AND a.housing_company_id = app_current_company_id()
               AND c.housing_company_id = app_current_company_id()
               AND c.status NOT IN ('draft', 'cancelled')
               AND (
                    app_is_manager(a.housing_company_id)
                    OR EXISTS (
                        SELECT 1 FROM apartment_occupancies o
                         WHERE o.apartment_id = a.id
                           AND o.user_id = app_current_user_id()
                           AND o.valid_from <= now()
                           AND (o.valid_to IS NULL OR o.valid_to > now())
                    )
               )
               AND cardinality(app_member_roles(a.housing_company_id)) > 0
             ORDER BY coalesce(c.event_date, c.created_at::date) DESC
            $$;
        REVOKE ALL ON FUNCTION app_apartment_history(uuid) FROM PUBLIC;
        """
    )

    for table in ("apartments", "apartment_occupancies"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY apartments_select ON apartments FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND cardinality(app_member_roles(housing_company_id)) > 0
            );
        CREATE POLICY apartments_insert ON apartments FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
            );

        CREATE POLICY occupancies_select ON apartment_occupancies FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND (app_is_manager(housing_company_id) OR user_id = app_current_user_id())
            );
        CREATE POLICY occupancies_insert ON apartment_occupancies FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
                AND created_by = app_current_user_id()
            );
        CREATE POLICY occupancies_update ON apartment_occupancies FOR UPDATE
            USING (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
            )
            WITH CHECK (housing_company_id = app_current_company_id());

        -- Jäsenyydet: isännöitsijä näkee yhtiön kaikki jäsenyydet ja hallitsee osakkaita/asukkaita.
        CREATE POLICY memberships_manager_select ON memberships FOR SELECT
            USING (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
            );
        CREATE POLICY memberships_insert ON memberships FOR INSERT
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
                AND role IN ('shareholder','resident')
                AND invited_by = app_current_user_id()
            );
        CREATE POLICY memberships_update ON memberships FOR UPDATE
            USING (
                housing_company_id = app_current_company_id()
                AND app_is_manager(housing_company_id)
                AND role IN ('shareholder','resident')
            )
            WITH CHECK (
                housing_company_id = app_current_company_id()
                AND role IN ('shareholder','resident')
            );

        CREATE POLICY users_company_select ON users FOR SELECT
            USING (
                app_is_manager(app_current_company_id())
                AND id IN (SELECT user_id FROM memberships
                            WHERE housing_company_id = app_current_company_id())
            );
        CREATE POLICY users_insert ON users FOR INSERT
            WITH CHECK (app_is_manager(app_current_company_id()));
        """
    )

    op.execute(
        f"""
        GRANT SELECT, INSERT ON apartments TO {APP_ROLE};
        GRANT SELECT, INSERT ON apartment_occupancies TO {APP_ROLE};
        GRANT UPDATE (valid_to) ON apartment_occupancies TO {APP_ROLE};
        GRANT INSERT ON memberships TO {APP_ROLE};
        GRANT UPDATE (valid_to) ON memberships TO {APP_ROLE};
        GRANT INSERT ON users TO {APP_ROLE};
        GRANT EXECUTE ON FUNCTION app_member_roles(uuid), app_is_manager(uuid),
            app_apartment_history(uuid) TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS users_insert ON users;
        DROP POLICY IF EXISTS users_company_select ON users;
        DROP POLICY IF EXISTS memberships_update ON memberships;
        DROP POLICY IF EXISTS memberships_insert ON memberships;
        DROP POLICY IF EXISTS memberships_manager_select ON memberships;
        REVOKE INSERT ON users FROM taloapuri_app;
        REVOKE INSERT, UPDATE ON memberships FROM taloapuri_app;
        ALTER TABLE cases DROP CONSTRAINT IF EXISTS fk_cases_apartment;
        ALTER TABLE cases DROP COLUMN IF EXISTS history_note;
        ALTER TABLE cases DROP COLUMN IF EXISTS apartment_id;
        DROP FUNCTION IF EXISTS app_apartment_history(uuid);
        DROP TABLE IF EXISTS apartment_occupancies, apartments;
        DROP FUNCTION IF EXISTS app_is_manager(uuid);
        ALTER FUNCTION app_member_roles(uuid) SECURITY INVOKER;
        GRANT EXECUTE ON FUNCTION app_member_roles(uuid) TO PUBLIC;
        """
    )
