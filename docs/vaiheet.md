# Toteutusvaiheet

Vaatimukset ovat tiedostossa `Claude_Code_Plan_Promt.md`. Jokainen vaihe aloitetaan vasta erillisellä hyväksynnällä.

## Tehty

### Vaihe 0 – runko
- git
- `pyproject.toml` (Python 3.13)
- Docker Compose (PostgreSQL 17 + pgvector, roolit `taloapuri_owner` ja `taloapuri_app`)
- migraatio `0001` (tenant-ydin + RLS)
- asian tilakone
- REST-API `/api/v1` ja OpenAPI
- saavutettava web-runko
- staattiset vesivahingon ensiohjeet (luonnos)
- CI
- ADR:t 0001–0004

### Parannukset (2026-10-15)
- Selkokieliset HTML-virhesivut. Selaimessa 401 ohjaa etusivulle, ja API palauttaa edelleen JSONia.
- Tumma tila: laitteen asetus tai käyttäjän valinta, toimii ilman JavaScriptiä.
- **Huoneistot ja asukashallinta (migraatio `0002`):**
  - Isännöitsijä tai puheenjohtaja lisää osakkaita ja asukkaita sekä päättää heidän käyttöoikeutensa.
  - Rivejä ei poisteta, joten historia säilyy.
- **Huoneiston historia:**
  - Uusi asukas näkee huoneiston aiemmat asiat (tyyppi, tila, päivämäärät ja isännöitsijän historiamerkintä) ilman aiempien asukkaiden tietoja.
  - Rajaus tehdään tietokantafunktiossa `app_apartment_history`.
- **Finlex-lähteet (migraatio `0003`):**
  - AOYL 1599/2009 haetaan ajantasaisena, ja se jäsennetään pykälä- ja momenttitasolle.
  - Haku tehdään suomen kielen tekstihaulla.
- **Tekoälychat (migraatio `0004`, ADR 0005):**
  - Claude Haiku 5.5.
  - Lähdeviitteet tarkistetaan.
  - Kiintiöt ja kustannusseuranta.
  - Oletuksena pois päältä.

### Parannukset 2 (2026-10-15)
- Kirjautuminen sähköpostilla (kehitysvaihe, ei salasanaa).
- Oikean yläkulman ⚙ Asetukset: ulkoasu, oma sähköposti ja uloskirjautuminen.
- Yläpalkissa näkyy aina kirjautuneen käyttäjän nimi ja huoneisto.
- Huoneiston historia on omalla sivullaan ("Huoneiston historia" -painike).
- **Hallituksen pöytäkirjat (migraatio `0005`):**
  - Isännöitsijä lataa PDF:n ja valitsee, näkyykö se asukkaille.
  - Pöytäkirja näkyy etusivun kohdassa "Uusimmat tapahtumat" lisääjän nimen kanssa.

### Parannukset 3 (2026-10-15, ADR 0006)
- Vahinkoilmoitus ja tarjouspyyntö omilla lomakkeillaan.
- Valokuvat: metatiedot poistetaan.
- Lisätietopyynnöt ja vastaukset asian keskustelussa.
- Suorat viestit: asukas ↔ isännöitsijä tai hallitus; yläpalkissa ✉-laskuri.
- Tekoälychat viittaa lakiin ja käyttäjälle näkyviin pöytäkirjoihin sivunumeroineen.
- Tarjouspyynnöt: tapahtumana hallitukselle, tekoälyluonnos, tarjousten tallennus ja tekoälyvertailu lähdeviitteineen (ei suosittele urakoitsijaa).

### Parannukset 4 (2026-10-15)
- Lukemattomat asiat: uusi ilmoitus tai päivitys näkyy merkinnällä "Uusi" tai "Päivitetty", kunnes asia avataan.
- Yläpalkissa 🔔 Uutta -laskuri.
- Etusivun "Uusimmat tapahtumat" on yksi aikajärjestetty lista.
- Elävät päivitykset 30 sekunnin välein (kun välilehti on näkyvissä).
- `.env` luetaan automaattisesti.
- Englanninkielinen README GitHubia varten.

### Parannukset 5 (2026-10-16, ADR 0007)
- Palvelun ylläpitäjä hallitsee lakilähteitä: lisäys (esikatselun jälkeen), päivitys ja käytöstä poisto. Vanhat versiot säilyvät.
- Uusia lakeja voi lisätä Finlexistä, esim. kiinteistötietojärjestelmälaki 453/2002.
- UKK korvaa etusivun vesivuotobannerin: lakivastaukset näyttävät lain sanamuodon lähteestä, ja isännöitsijä voi lisätä taloyhtiön omia kysymyksiä.
- Yläpalkin 🔔-laskuri poistettu; lukemattomien määrä näkyy välilehden otsikossa.
- `.gitignore` laajennettu ja `.gitattributes` lisätty.

**Hyväksymiskriteerit:** `ruff check .`, `mypy src` ja `pytest` (myös `-m db`) menevät läpi.

## Luodaan myöhemmin
| Vaihe | Sisältö |
|---|---|
| 1 | OIDC + MFA tai sähköpostilinkki (ADR 0003), sähköpostin vahvistus muutettaessa, sähköpostikutsut (`invitations`), CSRF-tunnisteet, idempotenssiavaimet, Playwright + axe-core |
| 2 | Ohjattu vahinkotapaus vaiheittain, liitteet ja pöytäkirjat objektitallennukseen (S3, virustarkistus, EXIF-poisto, HEIC), taustatyöjono (`jobs`), sähköposti-ilmoitukset (outbox) |
| 3 | Tapahtumapäivän mukainen säädösversio, yhtiöjärjestys lähteeksi (OCR + tarkistus), upotukset (pgvector) ja hakuvertailu, retrieval-eval |
| 4 | Tekoälyn laajennus: keskustelumuisti, `prompt_versions`-taulu, asiantuntijan eval, eskalointi asiantuntijalle |
| 5 | PDF-generointi (tagattu PDF), tarjouspyyntö- ja viestiluonnokset, hyväksynnät (`approvals` + sisältötiiviste) |
| 6 | Staging, varmuuskopiot ja palautustestit, virheseuranta, DPIA, pilottiasiakas |

**Suositus:** asiakasvalidointi (3–5 haastattelua isännöitsijöiden ja hallitusten kanssa) ennen vaihetta 2.
