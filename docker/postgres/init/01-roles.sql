-- Ajetaan kerran, kun tietokantakontti luodaan ensimmäistä kertaa.
-- taloapuri_owner omistaa skeeman ja ajaa migraatiot ja ylläpitoskriptit (BYPASSRLS).
--   ÄLÄ KOSKAAN käytä sitä sovelluksen yhteydessä.
-- taloapuri_app on sovelluksen rooli: ei omista tauluja eikä ohita RLS:ää.
CREATE ROLE taloapuri_owner LOGIN PASSWORD 'local-dev-only' BYPASSRLS;
CREATE ROLE taloapuri_app LOGIN PASSWORD 'local-dev-only' NOSUPERUSER NOBYPASSRLS;

CREATE DATABASE taloapuri OWNER taloapuri_owner;
CREATE DATABASE taloapuri_test OWNER taloapuri_owner;

\connect taloapuri
CREATE EXTENSION IF NOT EXISTS vector;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO taloapuri_owner;
GRANT USAGE ON SCHEMA public TO taloapuri_app;

\connect taloapuri_test
CREATE EXTENSION IF NOT EXISTS vector;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO taloapuri_owner;
GRANT USAGE ON SCHEMA public TO taloapuri_app;
