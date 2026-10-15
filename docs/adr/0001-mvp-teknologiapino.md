# ADR 0001: MVP-teknologiapino

- Tila: Hyväksytty (vaihe 0). Voidaan arvioida uudelleen ennen vaihetta 2.
- Päivämäärä: 2026-10-15

## Konteksti
Kehittäjä on yksin ja vahvin Pythonissa ja SQL:ssä. Käyttäjissä on paljon ihmisiä, joille digipalvelut ovat vieraita. Saavutettavuuden tavoite on WCAG 2.2 AA. Mobiilisovellus tulee myöhemmin ja käyttää samaa backendia.

## Vaihtoehdot
| | A: FastAPI + Jinja (+ myöhemmin HTMX) | B: Next.js + FastAPI |
|---|---|---|
| Kielet | Python | Python + TypeScript |
| Käyttöönotot | 1 | 2 |
| Tunnistautuminen | Yksi eväste-istunto | BFF tai token-välitys, CSRF kahdessa paikassa |
| Saavutettavuus | Palvelinrenderöity HTML, toimii ilman JavaScriptiä | Hyvä, mutta vaatii kurinalaisuutta (fokuksen hallinta, reitinvaihdot) |
| Mobiilivalmius | Sama `/api/v1` REST + OpenAPI | Sama |
| Rikas vuorovaikutus | Rajallisempi | Vahva |

## Päätös
Valitaan **A**: FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL (pgvector), Jinja-mallit ja palvelinrenderöinti. HTMX lisätään vasta, kun sille on konkreettinen tarve. Silloin se vendoroidaan omaan staattiseen hakemistoon, ei ladata CDN:stä.

Web-käyttöliittymä ja REST-API käyttävät samaa palvelukerrosta (`taloapuri.services`), joten säännöt ovat yhdessä paikassa. Mobiilisovellus käyttää myöhemmin `/api/v1`:tä.

## Seuraukset
- Ei Node-työkaluketjua MVP:ssä. Node 24 on asennettuna, ja sitä tarvitaan vain mahdolliseen Playwright/axe-testaukseen.
- Jos myöhemmin tarvitaan rikas SPA-käyttöliittymä, sen voi rakentaa saman API:n päälle.
