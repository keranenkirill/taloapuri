"""Tekoälychat: keskustelut, viestit, AI-ajot ja lähdeviitteet.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15

Käyttäjä näkee vain omat keskustelunsa. Yhtiön kuukausikulu lasketaan SECURITY DEFINER
-funktiolla, joka palauttaa vain summan (ei muiden käyttäjien kysymyksiä).
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"
TABLES = ("chat_threads", "chat_messages", "ai_runs", "chat_citations")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chat_threads (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            user_id uuid NOT NULL REFERENCES users(id),
            title varchar(200) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, housing_company_id)
        );
        CREATE INDEX ix_chat_threads_user ON chat_threads (housing_company_id, user_id, created_at);

        CREATE TABLE chat_messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL,
            thread_id uuid NOT NULL,
            user_id uuid NOT NULL REFERENCES users(id),
            role varchar(16) NOT NULL CHECK (role IN ('user','assistant')),
            status varchar(16) NOT NULL DEFAULT 'ok'
                CHECK (status IN ('ok','refused','unavailable','no_sources','over_quota')),
            text text NOT NULL,
            segments jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (thread_id, housing_company_id)
                REFERENCES chat_threads (id, housing_company_id)
        );
        CREATE INDEX ix_chat_messages_thread ON chat_messages (thread_id, created_at);

        CREATE TABLE ai_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            user_id uuid NOT NULL REFERENCES users(id),
            message_id uuid REFERENCES chat_messages(id),
            model varchar(64) NOT NULL,
            prompt_version varchar(32) NOT NULL,
            input_tokens integer NOT NULL DEFAULT 0,
            output_tokens integer NOT NULL DEFAULT 0,
            cache_read_tokens integer NOT NULL DEFAULT 0,
            cache_write_tokens integer NOT NULL DEFAULT 0,
            cost_usd numeric(12, 6) NOT NULL DEFAULT 0,
            section_ids uuid[] NOT NULL DEFAULT '{}',
            stop_reason varchar(32),
            latency_ms integer,
            error varchar(200),
            request_id varchar(100),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_ai_runs_company_time ON ai_runs (housing_company_id, created_at);

        CREATE TABLE chat_citations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL,
            user_id uuid NOT NULL REFERENCES users(id),
            message_id uuid NOT NULL REFERENCES chat_messages(id),
            ord integer NOT NULL,
            source_section_id uuid REFERENCES source_sections(id),
            citation_label varchar(100) NOT NULL,
            cited_text text NOT NULL,
            verified boolean NOT NULL
        );
        CREATE INDEX ix_chat_citations_message ON chat_citations (message_id, ord);

        -- Yhtiön tämän kuukauden AI-kulut (Europe/Helsinki). Palauttaa vain summan.
        CREATE FUNCTION app_ai_month_cost(company uuid) RETURNS numeric
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
            $$
            SELECT coalesce(sum(cost_usd), 0)
              FROM ai_runs
             WHERE housing_company_id = company
               AND company = app_current_company_id()
               AND cardinality(app_member_roles(company)) > 0
               AND created_at >= date_trunc('month', now() AT TIME ZONE 'Europe/Helsinki')
                                 AT TIME ZONE 'Europe/Helsinki'
            $$;
        REVOKE ALL ON FUNCTION app_ai_month_cost(uuid) FROM PUBLIC;
        """
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_own_select ON {table} FOR SELECT
                USING (housing_company_id = app_current_company_id()
                       AND user_id = app_current_user_id()
                       AND cardinality(app_member_roles(housing_company_id)) > 0);
            CREATE POLICY {table}_own_insert ON {table} FOR INSERT
                WITH CHECK (housing_company_id = app_current_company_id()
                            AND user_id = app_current_user_id()
                            AND cardinality(app_member_roles(housing_company_id)) > 0);
            GRANT SELECT, INSERT ON {table} TO {APP_ROLE};
            """
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION app_ai_month_cost(uuid) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS app_ai_month_cost(uuid);
        DROP TABLE IF EXISTS chat_citations, ai_runs, chat_messages, chat_threads;
        """
    )
