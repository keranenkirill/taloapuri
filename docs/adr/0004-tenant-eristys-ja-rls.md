# ADR 0004: Tenant-eristys ja Row Level Security

- Tila: Hyväksytty (vaihe 0)
- Päivämäärä: 2026-10-15

## Päätös
Eristys tehdään kolmessa kerroksessa:

1. **URL:** yhtiön tunniste on aina polussa (`/companies/{id}/…`, `/yhtiot/{id}/…`), ei pelkästään istunnossa. Näin kaksi välilehteä eri yhtiöillä ei voi sekoittua.
2. **Sovellus:** `get_company_context` tarkistaa voimassa olevan jäsenyyden. Kyselyt rajataan myös eksplisiittisesti `housing_company_id`:llä. Jos jäsenyyttä ei ole, palautetaan 404 eikä 403, jotta ei paljasteta yhtiön olemassaoloa.
3. **Tietokanta (RLS):**
   - Sovellusrooli `taloapuri_app` ei omista tauluja (`NOBYPASSRLS`), ja kaikissa tauluissa on `FORCE ROW LEVEL SECURITY`.
   - Konteksti asetetaan transaktiokohtaisesti: `set_config('app.current_user_id' / 'app.current_company_id', …, true)`. Konteksti ei siis vuoda yhteyspoolissa seuraavalle pyynnölle.
   - `app_member_roles()` tarkistaa jäsenyyden voimassaolon myös tietokannassa.
   - Osakas ja asukas näkevät vain itse luomansa asiat.
   - `case_events` viittaa asiaan komposiittiavaimella `(case_id, housing_company_id)`, joten tapahtumaa ei voi liittää toisen yhtiön asiaan.
   - `audit_events`: sovellusroolilla on vain INSERT- ja SELECT-oikeus (append-only).
   - Migraatiot ja ylläpitoskriptit ajetaan roolilla `taloapuri_owner` (`BYPASSRLS`). Sitä ei koskaan käytetä sovelluksen yhteydessä.

## Myöhemmin
- Taustatyöt asettavat saman kontekstin jokaisen työn alussa (työssä on `housing_company_id`).
- Julkiset Finlex-lähteet (`tenant_id IS NULL`) saavat erillisen lukupolitiikan.
- Jäsenluettelo toteutetaan erillisellä, tarkistetulla funktiolla. `memberships`-politiikka näyttää nyt vain omat rivit, jotta politiikka ei olisi rekursiivinen.
- Ulkopuolisen asiantuntijan tapauskohtainen pääsy toteutetaan omalla taulullaan (`case_access_grants`).
- Välimuisti: tenant-sisällössä `Cache-Control: private, no-store` (tehty), ja esiallekirjoitetut tiedostolinkit ovat lyhytikäisiä (tiedostovaiheessa).

## Testit
`tests/test_tenant_isolation.py` testaa nämä asiat:
- vieras yhtiö palauttaa 404
- toisen yhtiön asian tunniste ei löydy
- osakas näkee vain omat asiansa
- vanhentunut jäsenyys ei anna pääsyä
- RLS ilman kontekstia palauttaa tyhjän
- konteksti ei vuoda transaktiosta toiseen
- audit-loki on append-only
- komposiittiviiteavain estää tapahtuman liittämisen toisen yhtiön asiaan
