# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Taloapuri is a Finnish SaaS assistant for housing companies (taloyhtiöt). Requirements are in `Claude_Code_Plan_Promt.md` (Finnish). The phase roadmap is in `docs/vaiheet.md`, and architecture decisions are in `docs/adr/`. Phase 0 is done, plus dark mode, resident/apartment management, apartment history, Finlex ingestion and an AI chat pilot (see `docs/vaiheet.md`). Start each later phase only after explicit user approval.

Stack (ADR 0001): Python 3.13, FastAPI, SQLAlchemy 2 (sync) + psycopg 3, Alembic, PostgreSQL 17 + pgvector, and server-rendered Jinja templates. There is no Node toolchain.

## Commands (PowerShell, venv at `.venv`)

```powershell
pip install -e ".[dev]"
docker compose up -d                       # Postgres; init script creates roles + taloapuri / taloapuri_test DBs
alembic upgrade head                       # needs TALOAPURI_MIGRATION_DATABASE_URL (owner role)
python scripts/seed_dev.py                 # fictional demo data; prints login emails (e.g. olli@esimerkki.fi)
python scripts/ingest_finlex.py            # check/update ALL active laws (bootstraps AOYL); --add 2002/453 --name KTJL; --file x.akn
python scripts/make_admin.py <email>       # grant platform admin (the flag cannot be set via the app)
python scripts/reindex_documents.py        # extract page text for minutes uploaded before migration 0008
cd scripts; python ai_smoke.py             # REAL paid AI calls (needs ANTHROPIC_API_KEY); never run in tests/CI
uvicorn taloapuri.main:app --reload        # http://localhost:8000, API docs at /api/v1/docs
pytest                                     # DB tests skip unless TEST_DATABASE_URL + TEST_MIGRATION_DATABASE_URL are set
pytest -m db                               # tenant-isolation tests only
pytest tests/test_case_states.py::test_board_member_cannot_approve_alone
ruff check . ; ruff format . ; mypy src    # mypy is strict
```

The environment variables are listed in `.env.example`. `.env` is loaded automatically by the app (pydantic-settings, including `ANTHROPIC_API_KEY` → `Settings.anthropic_api_key`), Alembic (`migrations/env.py`), the scripts and `tests/conftest.py` (`python-dotenv`), so no manual export is needed. In tests the real AI is always disabled (`get_ai_provider` returns `None` when `env == "test"`). If `docker/postgres/init/01-roles.sql` changes, recreate the DB volume: `docker compose down -v`. If you edit an already-applied migration locally, `alembic downgrade` to before it on both `taloapuri` and `taloapuri_test` (the test fixture only runs `upgrade head`).

On Windows, edit files with Python or the Edit tool, not PowerShell `Get-Content`/`Set-Content`. Windows PowerShell 5.1 reads UTF-8 as ANSI and corrupts the Finnish characters.

## Architecture

- **Tenant = housing company** (ADR 0002). Every tenant table has `housing_company_id`. Users get access only through time-limited `memberships` (`valid_from`/`valid_to`), never through the account/firm.
- **Three-layer isolation** (ADR 0004):
  1. The company ID is in the URL path: `/api/v1/companies/{company_id}/…` and `/yhtiot/{company_id}/…`.
  2. `auth.get_company_context` checks for an active membership and returns **404, not 403**.
  3. Postgres RLS:
     - The app connects as `taloapuri_app` (non-owner, NOBYPASSRLS). Every table has `FORCE ROW LEVEL SECURITY`.
     - Context is set per transaction via `set_config('app.current_user_id' | 'app.current_company_id', …, true)` in `db.py`.
     - Migrations and seeding use `taloapuri_owner` (BYPASSRLS). Never use it from the app.
- **RLS policies live in the Alembic migration**, not the ORM models. `models.py` mirrors the tables for ORM use. When adding a tenant table, add its RLS policy, `FORCE`, grants and an isolation test in `tests/test_tenant_isolation.py`.
- **Two lists must stay in sync:** `ROLES_SEEING_ALL_CASES` in `domain/roles.py` and the `SEE_ALL` array in the migration. Shareholders and residents see only the cases they created.
- **INSERT … RETURNING needs SELECT permission under RLS.** For write-only tables (e.g. `audit_events`, which only managers can read), insert with plain SQL and no RETURNING, as `services/audit.py:write_audit` does.
- **`SECURITY DEFINER` functions** (owned by `taloapuri_owner`, `SET search_path = public`) must check company and caller themselves and return only the caller's own data or safe columns:
  - `app_member_roles`: the caller's own roles; it is a definer function to avoid recursive RLS on `memberships`.
  - `app_apartment_history`: only type, status, dates and the manager-written `history_note`, never the title, description or creator.
  - `app_ai_month_cost`: a sum only.
- **Members and apartments** (`services/members.py`):
  - Managers (`MANAGER_ROLES`) add and end only shareholders and residents (`MANAGEABLE_ROLES`).
  - Ending sets `valid_to`; rows are never deleted.
  - Users and memberships are inserted with Python-generated UUIDs and no RETURNING, because the manager can't SELECT the user row until the membership exists.
- **Case workflow:**
  - `domain/case_states.py` is a pure state machine: transitions, allowed roles, and creator-allowed flags.
  - `services/cases.py` applies transitions with optimistic locking (`expected_version` → 409 on mismatch) and writes `case_events` + `audit_events`.
  - The API (`api/v1/`) and the web UI (`web/routes.py`) both call the services layer. Don't duplicate rules in either.
- **Web layer:**
  - `web/templating.py` holds the shared Jinja setup: filters, the theme context processor, `render()` (adds `Cache-Control: private, no-store`) and `safe_next()`.
  - Routers are split by feature: `routes.py`, `members_routes.py`, `chat_routes.py`.
  - `main.py` turns `HTTPException` into Finnish HTML pages for non-`/api/` paths; a 401 redirects to `/`.
- **Finlex sources** (`sources/finlex.py`, `sources/ingest.py`, `services/sources.py`):
  - Akoma Ntoso is parsed with `defusedxml`, one row per momentti.
  - Search is the `finnish` tsvector with section headings weighted A, Finnish question stop-words removed, and a small everyday→legal term expansion (`_EXPANSIONS`).
  - Grow the expansion table based on search tests.
- **AI chat** (`ai/provider.py`, `ai/prompts.py`, `services/chat.py`, ADR 0005):
  - The `AiProvider` protocol has `AnthropicProvider` (Claude Haiku 5.5, citations on custom-content documents: one document per pykälä, one block per momentti) and `FakeProvider` (tests).
  - It sends only the question and public law text, with no tools.
  - Every citation is verified server-side (the quote must be a substring of the cited momentit).
  - No sources found → no AI call. There are quotas per company/month and per user/day.
  - Off by default (`TALOAPURI_AI_ENABLED`). Tests override `web.chat_routes.get_ai_provider` and never call the real API.
  - Bump `PROMPT_VERSION` whenever the prompt changes.
- **Auth is dev-only for now:**
  - The browser logs in by **email** (no password) through `POST /dev/kirjaudu`. This calls the definer function `app_find_user_by_email` and sets the `dev_user_id` cookie.
  - Tests and the API use the `X-Dev-User-Id` header.
  - It is enabled only when `TALOAPURI_ENV` is `local` or `test`. Real OIDC is planned in ADR 0003.
  - `auth.CurrentUser` and `CompanyContext` carry the user's name, email and current apartment labels for the header.
  - `users.email` is unique (case-insensitive). Users can change only their own email (`services/account.py`, column grant `UPDATE(email)`).
- **Case types:**
  - `cases.details` jsonb is validated per type by `domain/case_details.py`.
  - Tender requests are board-only: checked in Python and in RLS `cases_insert`.
  - Case pages are in `web/cases_routes.py`.
  - `REQUEST_INFO` and `PROVIDE_INFO` go through `services/cases.request_info` / `provide_info`, which require text and write `case_messages`. Never expose them as plain transition buttons.
- **Photos** (`services/attachments.py`):
  - Call `prepare_photos()` (validate + re-encode to JPEG, strip EXIF/GPS) **before** any DB write, then `add_photos()`. This keeps an invalid photo from leaving a half-saved case.
  - Photos are never sent to the AI.
- **Direct messages** (`services/messages.py`, migration 0007):
  - Threads can only be started via the definer function `app_start_thread` (contact rule: residents → manager/board only).
  - RLS limits visibility to participants via `app_is_thread_participant`.
  - The unread count is in `CompanyContext.unread_messages`.
- **Platform admin and law sources** (ADR 0007, migration 0011):
  - `users.is_platform_admin` is not a company role. The admin has no memberships and sees no company data.
  - The app role may INSERT into `users` only `(id, display_name, email)` and UPDATE only `email`, so the flag can't be written through the app. Don't widen those column grants.
  - Law tables are global. Writes need `app_is_platform_admin()` (RLS), and nobody has DELETE. Updates move `sources.current_version_id` and keep old versions, because `chat_citations` reference old sections.
  - `sources/updater.py` is shared by `services/law_admin.py` (admin pages, 5-minute cooldown, audit with no company) and `scripts/ingest_finlex.py`. The diff matches by chapter, section and subsection number because `eId`s change with amendments.
  - Don't add a foreign key from `sources` to `users`: `seed_dev.py` runs `TRUNCATE users CASCADE` and would wipe the laws.
  - Admin pages are under `/yllapito/lait` (404 for non-admins). The Finlex fetcher is injected via `get_law_fetcher`, so tests never use the network (`FakeLawFetcher`, `changed_aoyl_xml`, `reset_laws` in `tests/conftest.py`).
- **FAQ** (`web/faq_content.py`, `web/faq_routes.py`, `services/faq.py`):
  - The fixed FAQ is code. Entries with legal claims have `refs` (law subsections) and are shown only with the live quote from the stored law. A missing law means "ei vahvistettu lähteestä", and a changed version means a staleness warning.
  - Front-page entries must have no `refs`.
  - The company FAQ (`company_faq`) is plain text that managers edit, and is escaped on output.
- **Unread markers and live updates** (`services/activity.py`, `web/live_routes.py`, `static/live-updates.js`, migration 0010):
  - A case is unread for a user when someone else acted on it after the user's `case_reads.last_read_at`. Activity means `case_events` (with `actor_name`), `case_messages` or `case_attachments`.
  - Never-opened cases count only within 30 days.
  - `case_page()` calls `mark_case_read` and refreshes `ctx.unread_cases`.
  - `activity.feed()` builds the dashboard's single "Uusimmat tapahtumat" list.
  - `GET /yhtiot/{id}/tilanne` returns the counts and `feed_version`; the JS polls it every 30 s while the tab is visible.
  - The tab title shows the unread count (there is no header bell).
  - When adding a new kind of case activity, include it in `_ACTIVITY_SQL` and `feed_version`, and always store the actor's name.
- **AI streaming** (`ai/events.py`, `web/streaming.py`, `static/ai-stream.js`):
  - The services are generators (`chat.ask_events`, `tenders.generate_draft_events` / `compare_offers_events`) that yield `StreamEvent`s: status, delta, done or error. The non-streaming `ask()` / `generate_draft()` / `compare_offers()` wrap them.
  - `AiProvider.stream_answer` yields text chunks and finally an `AiResult` (Anthropic `messages.stream` → `get_final_message()`, which still carries the citations).
  - The SSE endpoints (`…/stream`) run in their **own DB session** with the tenant context re-set, and commit **before** sending `done`.
  - The browser shows the live text, then redirects to the saved page where the citations are verified.
  - Forms opt in via `data-ai-stream` + `data-ai-panel` (+ `data-ai-target`) and still work without JS.
- **AI citations** (`ai/citations.py`):
  - Every AI feature builds `CitableSource`s (law momentit, minutes pages, offer pages, tender form fields), sends them as custom-content documents, then calls `resolve_all()`. This maps citations to labels and links, and verifies each quote by exact substring.
  - Reuse this module for any new AI feature.
  - Never use structured outputs together with citations (the API rejects it).
- **Tenders** (`services/tenders.py`, `web/tenders_routes.py`):
  - The AI draft never includes `budget_note` or names, and it is saved only via `save_tender_draft` by a human.
  - The comparison must never recommend a contractor.
  - Outputs are stored in `case_ai_outputs`, and every run in `ai_runs` (with `kind` and `output_id`).
- **PDF text:** `sources/pdf_text.extract_pages` runs at upload for minutes and offers. Scanned PDFs yield no text, and the UI says so; OCR comes later.
- **Board minutes** (`services/documents.py`, `web/documents_routes.py`, migration 0005):
  - PDF only (magic bytes), ≤ 10 MB, stored as `bytea` in `company_document_files`, separate from the metadata.
  - RLS: residents see only `visible_to_residents` documents; board roles see all. Managers have an extra SELECT policy that includes removed rows, because an UPDATE's new row must pass a SELECT policy, so soft-delete would fail otherwise.
  - Always filter `removed_at IS NULL` in queries.
  - Uploads are manager-only. The uploader's name is stored on the row (`uploaded_by_name`).
  - Downloads send `nosniff`, an attachment disposition and `Cache-Control: private, no-store`.

## Rules

- Code identifiers are in English. UI text, docs and ADRs are in Finnish, in plain language for non-technical users.
- **No AI side effects without approval.** AI must never send messages, change approval states, access another company's data, issue payment orders or publish decisions. Each needs a server-side permission check and explicit human approval.
- **Legal output separates** user facts, official sources, company documents, AI interpretation, uncertainties and next steps. Every legal claim cites a verifiable source version or is marked unverified.
- **The applicable law version is chosen by the case's `event_date`, not by the retrieval date.**
- **Urgent first-aid content** (`web/templates/ensiohjeet_vesivahinko.html`) is static and must never depend on the DB or the AI. It is currently a draft awaiting expert review.
- **Accessibility target is WCAG 2.2 AA:**
  - semantic HTML, `lang="fi"` and a skip link
  - exactly one `<h1>`
  - error summary + `aria-invalid`/`aria-describedby` on forms
  - 44px targets
  - state shown as text
  - tenant pages send `Cache-Control: private, no-store`
- **Licensing:** don't assume redistribution or indexing rights for YSE 1998, RT cards or commercial responsibility tables.

## Test pitfalls

- Never call `next(some_generator())` and discard the generator. It is garbage-collected and its `finally` closes the session, which silently drops the RLS context. Use a `@contextmanager` (`app_session` in `tests/test_law_admin.py`).
- An unauthorized UPDATE under RLS changes 0 rows instead of raising. Assert that the data is unchanged.
