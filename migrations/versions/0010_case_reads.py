"""Luetuksi merkitseminen: case_reads ja case_events.actor_name.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15

Asia on käyttäjälle "lukematon", jos joku muu on tehnyt siinä jotain sen jälkeen, kun käyttäjä
viimeksi avasi asian. actor_name tallennetaan tapahtumaan, jotta uusimmat tapahtumat voivat kertoa
tekijän avaamatta käyttäjätaulun RLS:ää hallituksen jäsenille.
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE case_reads (
            user_id uuid NOT NULL REFERENCES users(id),
            housing_company_id uuid NOT NULL,
            case_id uuid NOT NULL,
            last_read_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, case_id),
            FOREIGN KEY (case_id, housing_company_id) REFERENCES cases (id, housing_company_id)
        );
        ALTER TABLE case_reads ENABLE ROW LEVEL SECURITY;
        ALTER TABLE case_reads FORCE ROW LEVEL SECURITY;
        CREATE POLICY case_reads_select ON case_reads FOR SELECT
            USING (user_id = app_current_user_id()
                   AND housing_company_id = app_current_company_id());
        CREATE POLICY case_reads_insert ON case_reads FOR INSERT
            WITH CHECK (user_id = app_current_user_id()
                        AND housing_company_id = app_current_company_id()
                        AND case_id IN (SELECT id FROM cases));
        CREATE POLICY case_reads_update ON case_reads FOR UPDATE
            USING (user_id = app_current_user_id()
                   AND housing_company_id = app_current_company_id())
            WITH CHECK (user_id = app_current_user_id());
        GRANT SELECT, INSERT ON case_reads TO {APP_ROLE};
        GRANT UPDATE (last_read_at) ON case_reads TO {APP_ROLE};

        ALTER TABLE case_events ADD COLUMN actor_name varchar(200);
        UPDATE case_events e SET actor_name = u.display_name
          FROM users u WHERE u.id = e.actor_user_id;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE case_events DROP COLUMN IF EXISTS actor_name;
        DROP TABLE IF EXISTS case_reads;
        """
    )
