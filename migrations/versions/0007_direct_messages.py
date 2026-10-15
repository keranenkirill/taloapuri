"""Suorat viestit yhtiön sisällä.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-15

Säännöt:
- Osakkaat ja asukkaat voivat aloittaa keskustelun vain isännöitsijän tai hallituksen kanssa.
- Isännöitsijä ja hallitus voivat aloittaa keskustelun kenen tahansa yhtiön jäsenen kanssa.
- Keskustelun näkevät ja siihen voivat vastata vain sen osallistujat.

Keskustelu aloitetaan aina funktiolla app_start_thread, joka tarkistaa säännöt. Sovelluksella
ei ole suoraa INSERT-oikeutta keskusteluihin eikä osallistujiin.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APP_ROLE = "taloapuri_app"
BOARD = "ARRAY['property_manager','board_chair','board_member','treasurer']::text[]"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE message_threads (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            housing_company_id uuid NOT NULL REFERENCES housing_companies(id),
            subject varchar(200) NOT NULL,
            created_by uuid NOT NULL REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, housing_company_id)
        );

        CREATE TABLE message_participants (
            thread_id uuid NOT NULL,
            housing_company_id uuid NOT NULL,
            user_id uuid NOT NULL REFERENCES users(id),
            last_read_at timestamptz,
            PRIMARY KEY (thread_id, user_id),
            FOREIGN KEY (thread_id, housing_company_id)
                REFERENCES message_threads (id, housing_company_id)
        );
        CREATE INDEX ix_message_participants_user
            ON message_participants (user_id, housing_company_id);

        CREATE TABLE direct_messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            thread_id uuid NOT NULL,
            housing_company_id uuid NOT NULL,
            sender_id uuid NOT NULL REFERENCES users(id),
            sender_name varchar(200) NOT NULL,
            body text NOT NULL CHECK (length(trim(body)) > 0 AND length(body) <= 5000),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (thread_id, housing_company_id)
                REFERENCES message_threads (id, housing_company_id)
        );
        CREATE INDEX ix_direct_messages_thread ON direct_messages (thread_id, created_at);

        -- Onko kutsuja keskustelun osallistuja nykyisessä yhtiössä (ei rekursiivista RLS:ää).
        CREATE FUNCTION app_is_thread_participant(thread uuid) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
            $$
            SELECT EXISTS (
                SELECT 1 FROM message_participants p
                 WHERE p.thread_id = thread
                   AND p.user_id = app_current_user_id()
                   AND p.housing_company_id = app_current_company_id()
            )
            $$;

        -- Kenelle kutsuja saa aloittaa viestin: nimi ja roolit, ei muita tietoja.
        CREATE FUNCTION app_contactable_members()
            RETURNS TABLE (user_id uuid, display_name varchar, roles text)
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
            $$
            SELECT u.id, u.display_name, string_agg(m.role, ',' ORDER BY m.role)
              FROM memberships m
              JOIN users u ON u.id = m.user_id
             WHERE m.housing_company_id = app_current_company_id()
               AND cardinality(app_member_roles(app_current_company_id())) > 0
               AND m.user_id <> app_current_user_id()
               AND m.valid_from <= now() AND (m.valid_to IS NULL OR m.valid_to > now())
               AND (app_member_roles(app_current_company_id()) && {BOARD}
                    OR m.role = ANY({BOARD}))
             GROUP BY u.id, u.display_name
             ORDER BY u.display_name
            $$;

        CREATE FUNCTION app_start_thread(recipient uuid, subject text, body text) RETURNS uuid
            LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public AS
            $$
            DECLARE
                me uuid := app_current_user_id();
                company uuid := app_current_company_id();
                thread uuid := gen_random_uuid();
                my_name varchar;
            BEGIN
                IF me IS NULL OR company IS NULL
                   OR cardinality(app_member_roles(company)) = 0 THEN
                    RAISE EXCEPTION 'not a member' USING ERRCODE = '42501';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM app_contactable_members() c
                                WHERE c.user_id = recipient) THEN
                    RAISE EXCEPTION 'recipient not allowed' USING ERRCODE = '42501';
                END IF;
                IF length(trim(subject)) = 0 OR length(subject) > 200
                   OR length(trim(body)) = 0 OR length(body) > 5000 THEN
                    RAISE EXCEPTION 'invalid message' USING ERRCODE = '22023';
                END IF;
                SELECT display_name INTO my_name FROM users WHERE id = me;
                INSERT INTO message_threads (id, housing_company_id, subject, created_by)
                     VALUES (thread, company, trim(subject), me);
                INSERT INTO message_participants (thread_id, housing_company_id, user_id, last_read_at)
                     VALUES (thread, company, me, now()), (thread, company, recipient, NULL);
                INSERT INTO direct_messages (thread_id, housing_company_id, sender_id, sender_name, body)
                     VALUES (thread, company, me, my_name, body);
                RETURN thread;
            END
            $$;

        REVOKE ALL ON FUNCTION app_is_thread_participant(uuid), app_contactable_members(),
            app_start_thread(uuid, text, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_is_thread_participant(uuid), app_contactable_members(),
            app_start_thread(uuid, text, text) TO {APP_ROLE};
        """
    )
    for table in ("message_threads", "message_participants", "direct_messages"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY message_threads_select ON message_threads FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND app_is_thread_participant(id));
        CREATE POLICY message_participants_select ON message_participants FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND app_is_thread_participant(thread_id));
        CREATE POLICY message_participants_update ON message_participants FOR UPDATE
            USING (housing_company_id = app_current_company_id()
                   AND user_id = app_current_user_id())
            WITH CHECK (user_id = app_current_user_id());
        CREATE POLICY direct_messages_select ON direct_messages FOR SELECT
            USING (housing_company_id = app_current_company_id()
                   AND app_is_thread_participant(thread_id));
        CREATE POLICY direct_messages_insert ON direct_messages FOR INSERT
            WITH CHECK (housing_company_id = app_current_company_id()
                        AND sender_id = app_current_user_id()
                        AND cardinality(app_member_roles(housing_company_id)) > 0
                        AND app_is_thread_participant(thread_id));

        GRANT SELECT ON message_threads, message_participants, direct_messages TO {APP_ROLE};
        GRANT INSERT ON direct_messages TO {APP_ROLE};
        GRANT UPDATE (last_read_at) ON message_participants TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS app_start_thread(uuid, text, text);
        DROP FUNCTION IF EXISTS app_contactable_members();
        DROP FUNCTION IF EXISTS app_is_thread_participant(uuid);
        DROP TABLE IF EXISTS direct_messages, message_participants, message_threads;
        """
    )
