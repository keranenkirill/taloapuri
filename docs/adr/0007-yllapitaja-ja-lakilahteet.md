# ADR 0007: Palvelun ylläpitäjä ja lakilähteiden hallinta

- Tila: Hyväksytty
- Päivämäärä: 2026-10-16

## Konteksti
Lait (Finlexin ajantasaiset säädökset) ovat yhteisiä kaikille taloyhtiöille: yksi kopio tietokannassa, ja tekoäly viittaa niihin kaikissa yhtiöissä. Tarvitaan tapa lisätä lakeja (esim. laki kiinteistötietojärjestelmästä, 453/2002) ja päivittää olemassa olevia (esim. AOYL) ilman, että yhden taloyhtiön isännöitsijä muuttaa kaikkien yhteistä aineistoa.

## Päätökset
- **Palvelun ylläpitäjä** on käyttäjän lippu (`users.is_platform_admin`), ei yhtiörooli. Ylläpitäjällä ei ole jäsenyyksiä, eikä hän näe yhtiöiden tietoja (RLS pätee häneenkin). Hän hallitsee vain lakilähteitä sivulla `/yllapito/lait`. Muille sivu vastaa 404.
- **Lippua ei voi asettaa sovelluksen kautta.** Sovellusroolin INSERT-oikeus `users`-tauluun on rajattu sarakkeisiin `id, display_name, email`, ja UPDATE-oikeus vain sarakkeeseen `email`. Ensimmäinen ylläpitäjä luodaan skriptillä `scripts/make_admin.py` (omistajarooli) tai kehitysdatassa.
- **Kirjoitusoikeus lakitauluihin** on vain ylläpitäjällä (RLS-politiikat `app_is_platform_admin()`). Kenelläkään ei ole DELETE-oikeutta.
- **Teksti tulee vain Finlexistä.** Ylläpitäjä antaa vain vuoden ja numeron. Haku sallii vain Finlexin avoimen datan osoitteen, vastauksen koko on rajattu (8 Mt) ja rivimäärä rajattu.
- **Lisäys vaatii esikatselun.** Ylläpitäjä näkee nimen, version ja sisällön määrän ja vahvistaa. Vahvistaessa haettu teksti tarkistetaan SHA-256-tiivisteellä samaksi kuin esikatselussa.
- **Päivitys ei poista vanhaa versiota.** Uusi versio otetaan käyttöön ja vanha säilyy historiana, koska aiemmat tekoälyvastaukset viittaavat vanhan version momentteihin ja koska säädösversio on myöhemmin valittava tapahtumapäivän mukaan. Muuttumaton teksti ei luo uutta versiota.
- **Muutosyhteenveto:** versioita verrataan luvun, pykälän ja momentin numerolla (momentin tunniste `eId` muuttuu muutoksen mukana). Yhteenveto (lisätty/muuttunut/poistettu ja enintään 20 kohtaa) tallennetaan versioon.
- **Suojat:** sama laki voidaan tarkistaa kerran 5 minuutissa; rinnakkaiset päivitykset estetään (advisory lock); jos uusi versio on alle puolet vanhasta, päivitystä ei tehdä; jokainen lisäys, päivitys ja käytöstä poisto kirjataan audit-lokiin (yhtiö tyhjä).
- **Käytöstä poisto:** laki voidaan ottaa pois haun lähteistä ja palauttaa. Ydinlakia (AOYL) ei voi poistaa käytöstä.
- **Läpinäkyvyys:** kaikki jäsenet näkevät lukulistalta (`/yhtiot/{id}/lait`), mitä lakeja tekoäly käyttää ja milloin ne on ajantasaistettu.
- **Ajastus:** `scripts/ingest_finlex.py` päivittää kaikki käytössä olevat lait ja palauttaa virhekoodin virheessä, joten se sopii cronille tai Windowsin Tehtävien ajoitukseen.

## Seuraukset ja avoimet asiat
- Laki on yhteinen: päivitys vaikuttaa kaikkiin taloyhtiöihin. Tämä on tarkoitus, ja siksi päivitys on rajattu ylläpitäjälle.
- Avoinna: automaattinen ajastus palvelun sisällä (taustatyöjono), avoimien analyysien merkitseminen lainmuutoksen jälkeen ja säädösversion valinta tapahtumapäivän mukaan.
- Finlexin avoimen datan käyttöehdot on edelleen tarkistamatta (ks. ADR 0005).
- Yleinen UKK kirjoittaa lakiväitteet auki lähteen sanamuodon viereen ja varoittaa, jos laki on päivittynyt sen jälkeen, kun yhteenveto kirjoitettiin (`verified_version`).
