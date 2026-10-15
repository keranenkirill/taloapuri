# ADR 0006: Valokuvat, lisätietopyynnöt, suorat viestit ja tarjouspyyntöjen tekoäly

- Tila: Hyväksytty
- Päivämäärä: 2026-10-15

## Päätökset

### Lomakkeet ja lisätietopyynnöt
- `cases.details` (jsonb) sisältää tyyppikohtaiset tiedot. Ne validoidaan Pydantic-malleilla (`domain/case_details.py`).
- Tarjouspyynnön voi luoda vain hallitus tai isännöitsijä. Tämä tarkistetaan sekä Pythonissa että RLS:ssä (`cases_insert`).
- Lisätietopyyntö vaatii kysymyksen ja vastaus vaatii tekstin.
- Kysymykset, vastaukset ja kommentit tallentuvat `case_messages`-tauluun. Ne näkyvät kaikille, jotka näkevät asian.

### Valokuvat
- Sallitut muodot: JPEG, PNG, WebP ja HEIC. Enintään 10 Mt/kuva ja 10 kuvaa/asia.
- Jokainen kuva koodataan uudelleen JPEGiksi ilman metatietoja (GPS, laite) ja käännetään EXIF-suunnan mukaan. Suurin sivu on 2560 px.
- Kuvat tarkistetaan ennen tallennusta, joten virheellinen kuva ei jätä puolikasta asiaa.
- Kuvia ei lähetetä tekoälylle, eivätkä ne näy huoneiston historiassa.
- Tallennus on toistaiseksi `bytea`-kentässä. Objektitallennus ja virustarkistus tulevat vaiheessa 2.

### Suorat viestit
- Osakkaat ja asukkaat voivat viestiä isännöitsijälle ja hallitukselle. Isännöitsijä ja hallitus voivat viestiä kaikille jäsenille.
- Osakkaat ja asukkaat eivät voi viestiä toisilleen (yksityisyys).
- Keskustelu aloitetaan SECURITY DEFINER -funktiolla `app_start_thread`, joka tarkistaa säännöt. Viestit näkyvät vain keskustelun osallistujille.
- Viestejä ei lähetetä tekoälylle. Sähköposti-ilmoitukset tulevat myöhemmin, nyt käytössä on yläpalkin laskuri.

### Tekoäly ja lähdeviitteet
Lähteet:
- Asunto-osakeyhtiölaki (momentit).
- Hallituksen pöytäkirjat, joita kysyjä saa itsekin nähdä (RLS). Pöytäkirjat jaetaan PDF-sivuiksi `pypdf`:llä.
- Tarjoukset (sivuittain).
- Tarjouspyyntölomake.

Lähdeviitteet:
- Jokainen lähde lähetetään omana dokumenttinaan ja jokainen sivu tai momentti omana lohkonaan (Claude Citations, `content_block_location`).
- Viite on "tarkistettu" vain, jos lainaus löytyy sanatarkasti viitatusta lohkosta (`ai/citations.py`).

Tarjouspyynnöt:
- **Luonnos:** tekoäly saa vain lomaketiedot. Budjettimuistiinpano ja henkilöiden nimet jätetään pois. Puuttuvat tiedot merkitään `[TÄYDENNÄ]`. Vakiosopimusehtoja (YSE 1998) ei lainata. Luonnos tallentuu vasta, kun ihminen tallentaa sen, eikä sitä lähetetä automaattisesti.
- **Vertailu:** tekoäly vertaa tarjouksia kohta kohdalta lähdeviitteineen. **Se ei suosittele urakoitsijaa**, ja vastaus päättyy "Päätöksen tekee hallitus." Vertailuun otetaan enintään 5 tarjousta ja yhteensä 30 sivua. Skannattuja tarjouksia ei voi vertailla, ennen kuin OCR on käytössä.

Kaikkia tekoälytoimintoja koskee yhtiön kuukausibudjetti. Jokainen ajo kirjataan `ai_runs`-tauluun, ja siihen tallennetaan tyyppi ja tuotos.

### Striimaus
- Vastauksen teksti näytetään sitä mukaa kuin tekoäly kirjoittaa sitä (Anthropic streaming → Server-Sent Events). Etenemispaneelissa on vaiheet ja kulunut aika.
- Lähdeviitteet tarkistetaan vasta, kun vastaus on valmis. Valmis vastaus näytetään tarkistettuine viitteineen.
- Animaatio noudattaa `prefers-reduced-motion`-asetusta. Tila kerrotaan ruudunlukijalle tekstinä (`role="status"`); itse striimattua tekstiä ei lueta ääneen kesken kaiken.
- Ilman JavaScriptiä toiminnot toimivat ennallaan tavallisina lomakkeina.

## Avoimet tarkistukset
- DPIA ja Anthropicin DPA: pöytäkirjojen ja tarjousten teksti lähtee tekoälypalveluun.
- Tarjoajien liikesalaisuudet: kerro tarjoajille, että tarjouksia voidaan käsitellä tekoälyllä.
- Valokuvien säilytysaika.
