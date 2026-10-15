# Taloapuri

**Taloapuri** ("housing company helper") is a web assistant for Finnish housing companies (*taloyhtiö*). It serves property managers (*isännöitsijä*), board members and residents. It guides people through everyday tasks step by step, such as reporting damage, requesting tenders, reading board minutes and messaging the manager. An optional AI assistant answers questions about Finnish housing company law, and every answer carries **verified citations**.

The user interface is in **Finnish**. This README is in English so that anyone can try the project.

> **Status: development / pilot.** The login is a passwordless *development* login and there is no production authentication yet. Run it locally only. See [Security notes](#security-notes).

---

## Features

- **Guided forms instead of a chatbot**: damage reports (with photos) and tender requests are separate, plain-language forms.
- **Photos**: JPEG/PNG/WebP/HEIC. Every photo is re-encoded and its location (GPS) and device metadata are removed.
- **Info requests**: the manager asks a question, the resident sees it highlighted and answers with text and photos, and the case returns to review.
- **Unread markers and live updates**: new reports and updates show as **"Uusi" / "Päivitetty"** until opened. The page checks for news every 30 seconds without reloading: the ✉ Viestit badge updates, a "Uusia tapahtumia" notice appears, and the browser tab title shows the count, e.g. "(2) Taloapuri".
- **Direct messages**: residents ↔ manager/board. Residents cannot message each other.
- **Board minutes**: the manager uploads PDFs and chooses per file whether residents can see them.
- **Apartment history**: a new resident sees past repairs to their apartment, without the previous residents' personal data.
- **Resident management**: the manager adds residents and ends their access. History is kept.
- **AI (optional, Anthropic Claude)**:
  - Chat that answers from the **Housing Companies Act (Finlex open data)** and the board minutes the user is allowed to see. It shows each source (section/page) and marks every quote ✓ verified or ⚠ unverified.
  - A tender request draft and a **comparison of contractors' offers** with page citations. The AI never picks a contractor; the board decides.
  - Answers **stream live** with a progress animation.
- **FAQ ("Usein kysytyt kysymykset")**: a general FAQ whose legal answers show the **exact current law text** with a Finlex link (and warn if the law has been updated since the answer was written), plus company-specific questions that the manager edits. The water-leak first steps are the first FAQ item on the front page.
- **Law sources managed by a platform admin**: add acts from Finlex (e.g. the Real Estate Information System Act 453/2002), check for updates and switch to the newest version. Old versions are kept as history.
- **Accessibility** (target WCAG 2.2 AA): semantic HTML, keyboard use, visible focus, an error summary on forms, dark mode, and support for reduced motion.
- **Tenant isolation**: each housing company's data is separated with PostgreSQL row-level security as well as application checks.

## Tech stack

Python 3.13 · FastAPI · SQLAlchemy 2 + Alembic · PostgreSQL 17 + pgvector (Docker) · server-rendered Jinja templates with small vanilla JS · Anthropic Claude API (optional, `claude-haiku-5-5`).

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| [Git](https://git-scm.com/) | any recent | |
| [Python](https://www.python.org/downloads/) | **3.13** | `python --version` must show 3.13.x |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose) | recent | runs the PostgreSQL database |
| Anthropic API key | optional | only needed for the AI features |

## Quick start

Run the commands in a terminal: **PowerShell** on Windows, or a shell on macOS/Linux.

### 1. Get the code

```bash
git clone https://github.com/<your-account>/taloapuri.git
cd taloapuri
```

### 2. Create a Python environment and install

**Windows (PowerShell)**
```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**macOS / Linux**
```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Start the database

Make sure Docker Desktop is running, then:

```bash
docker compose up -d
docker compose ps        # wait until the db service shows "healthy"
```

The first start creates two databases (`taloapuri` for the app and `taloapuri_test` for tests) and two roles. The app role cannot bypass row-level security.

### 4. Create your `.env`

**Windows**: `Copy-Item .env.example .env`
**macOS / Linux**: `cp .env.example .env`

The defaults work as they are for a local setup. Everything reads `.env` automatically, so you don't need to export variables.

### 5. Create the tables and demo data

```bash
alembic upgrade head
python scripts/seed_dev.py        # fictional demo company, users, minutes and apartment history
python scripts/ingest_finlex.py   # downloads the Housing Companies Act (1599/2009) from Finlex (free); run again to update all laws
```

### 6. Run the app

```bash
uvicorn taloapuri.main:app --reload
```

Open **http://localhost:8000** and log in with one of the demo emails below. No password is needed.

The API documentation (OpenAPI) is at http://localhost:8000/api/v1/docs.

## Demo accounts

All data is fictional. Running `python scripts/seed_dev.py` again resets everything.

| Email | Role | Try this |
|---|---|---|
| `isa@esimerkki.fi` | Property manager (both companies) | **Asukkaat ja osakkaat** (add or remove residents) · **Pöytäkirjat** (upload minutes) · **Laadi tarjouspyyntö** (tender + AI draft + offer comparison) |
| `olli@esimerkki.fi` | Shareholder, apartment A 1 | **Ilmoita vahingosta** with photos · **Huoneiston historia** · **Kysy tekoälyltä** · ✉ message the manager |
| `ville@esimerkki.fi` | Tenant, apartment A 2 | Sees only his own cases, not Olli's |
| `hanna@esimerkki.fi` | Board member of *As Oy Testimänty* | Sees new tender requests in that company as events |
| `yllapito@esimerkki.fi` | **Platform admin** (no company access) | **Ylläpito → Lakilähteet**: add a law, check for updates (see below) |
| `maija@esimerkki.fi`, `entinen@esimerkki.fi` | Former resident / former board member | Access ended: shows how offboarding works |

**A 2-minute tour of unread markers and live updates:**
1. Log in as `isa@esimerkki.fi` in one browser window and as `olli@esimerkki.fi` in a private window.
2. As Olli, file a damage report.
3. Within 30 seconds, Isa's browser tab title shows **(1)** and a "Uusia tapahtumia" notice appears. The report is marked **Uusi** in "Uusimmat tapahtumat" and in the case list until Isa opens it.
4. Isa asks for more information ("Pyydä lisätietoja"). Olli's report becomes **Päivitetty**, and the question is shown at the top of the case.

## Managing the laws the AI uses

Laws are shared by all housing companies, so only a **platform admin** can change them. Everyone else sees a read-only list ("Lue lisää lähteistä" on the AI chat page).

- **In the browser:** log in as `yllapito@esimerkki.fi` → **Ylläpito** → **Lakilähteet**.
  - **Tarkista päivitykset** fetches the newest consolidated text from Finlex. If it changed, the new version becomes the one in use and the page shows what changed (e.g. "1 muuttunut: 4 luku 2 § 2 mom."). The old version is kept as history because earlier AI answers cite it.
  - **Lisää laki**: enter the year and number (e.g. `2002` and `453`), review the preview, then confirm. The text always comes from Finlex, never from typed input.
  - **Poista käytöstä** stops the AI from using a law (the Housing Companies Act cannot be switched off).
- **From the command line** (also suitable for a weekly scheduled task; exit code 1 on failure):
  ```bash
  python scripts/ingest_finlex.py                          # update all active laws
  python scripts/ingest_finlex.py --add 2002/453 --name KTJL
  python scripts/make_admin.py someone@example.com         # grant the platform admin role
  ```

## Enabling the AI (optional)

1. Create a key at [console.anthropic.com](https://console.anthropic.com) → **API Keys**. Billing must be set up on the account.
2. In `.env`, set the following (no quotes, no spaces):
   ```
   TALOAPURI_AI_ENABLED=true
   ANTHROPIC_API_KEY=sk-ant-...
   ```
3. Check the key with a short real test. It makes 4 calls and usually costs less than USD 0.10:
   ```bash
   cd scripts
   python ai_smoke.py
   cd ..
   python scripts/seed_dev.py   # optional: reset the demo data afterwards
   ```
4. Restart `uvicorn` and try **Kysy tekoälyltä**, for example "Kuka vastaa kylpyhuoneen vedeneristyksestä?" ("Who is responsible for bathroom waterproofing?").

**Costs and limits:** Claude Haiku 5.5 costs fractions of a cent per question. Each housing company has a monthly budget (`TALOAPURI_AI_MONTHLY_BUDGET_USD`, default USD 5) and each user has a daily question limit. With the AI turned off, everything else works normally.

**"Tekoäly ei ole juuri nyt käytettävissä"** ("AI is not available right now")? Run `python ai_smoke.py` as in step 3. If it says *API-avain hylättiin (401 invalid x-api-key)*, Anthropic rejected the key: create a new key and update `.env`.

## Running tests and checks

```bash
pytest              # all tests; database tests use the taloapuri_test database
pytest -m "not db"  # tests that need no database
ruff check .        # lint
ruff format .       # format
mypy src            # strict type check
```

The tests never call the real AI. They use a fake provider.

## Project structure

```
src/taloapuri/
  main.py              app factory, error pages
  auth.py              (dev) login, company context, roles
  models.py            SQLAlchemy models (RLS policies live in the migrations)
  domain/              case state machine, roles, form schemas
  services/            business logic: cases, members, documents, messages, chat, tenders, activity
  ai/                  AI provider (Claude + fake), prompts, citation verification, streaming events
  sources/             Finlex (Akoma Ntoso) parsing, law updates (updater.py) and PDF text extraction
  api/v1/              REST API (OpenAPI)
  web/                 pages, templates, static CSS/JS
migrations/versions/   database schema + row-level security policies
scripts/               seed data, Finlex import, AI smoke test, PDF reindex
tests/                 pytest suite
docs/adr/              architecture decisions (in Finnish)
docs/vaiheet.md        roadmap (in Finnish)
```

The original requirements (in Finnish) are in `Claude_Code_Plan_Promt.md`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again. |
| `connection refused` / `could not connect to server` | Docker isn't running or the database isn't ready yet: start Docker Desktop, run `docker compose up -d`, and wait for `healthy`. |
| Port 5432 already in use | Another PostgreSQL is running. Stop it, or change the port mapping in `docker-compose.yml` and in the URLs in `.env`. |
| Database in a strange state / start from scratch | `docker compose down -v`, then `docker compose up -d` and repeat step 5. **This deletes all local data.** |
| Pages are slow (about 2 s) on Windows | Use http://127.0.0.1:8000 instead of `localhost`. |
| Login says the email was not found | Run `python scripts/seed_dev.py` and use an email from the table above. |

## Security notes

- The **email login has no password** and works only when `TALOAPURI_ENV` is `local` or `test`. **Don't deploy this as it is.** Real login (OIDC/MFA) is on the roadmap.
- Keep `.env` and API keys out of git. `.env` (and `.env.*` except `.env.example`) is already in `.gitignore`.
- The platform admin flag can only be set with `scripts/make_admin.py`, not through the app. Laws are fetched only from Finlex's official address.
- AI requests send only the question plus legal texts, minutes and offers that the user is allowed to see. Photos, messages and personal data aren't sent. See `docs/adr/0005-ai-chat-varhain.md` and `docs/adr/0006-kuvat-viestit-tarjoukset.md`.
- The consolidated Finlex texts aren't the official legal publication, and the AI's answers aren't legal advice.

## License

No license has been chosen yet, so all rights are reserved by the author. Please open an issue if you'd like to use the code.
