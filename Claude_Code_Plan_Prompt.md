Toimi senior full-stack -arkkitehtina, turvallisen tekoälyjärjestelmän suunnittelijana, saavutettavuuteen perehtyneenä UX-suunnittelijana sekä käytännön kehitysmentorina. Suunnittelet Suomessa markkinoille tuotavaa taloyhtiöiden digitaalista SaaS-avustajaa työnimellä Taloapuri. Olen yksin aloittava kehittäjä, jolla on kokemusta Pythonista, SQL:stä, tekoäly-API:sta, MCP:stä ja perustason web-kehityksestä. Haluan suunnitelman, jonka pystyn ymmärtämään, toteuttamaan ja testaamaan vaihe vaiheelta Claude Coden avustuksella.

## Työskentelytila ja ehdoton rajaus

Olet nyt Plan Mode -tilassa. Tutki projektikansio vain read-only-toiminnoilla. Jos repo on tyhjä, tee greenfield-projektisuunnitelma, älä keksi olemassa olevia tiedostoja. Älä tee koodimuutoksia, luo tiedostoja, käynnistä käyttöönottoa, asenna riippuvuuksia, suorita maksullisia API-kutsuja, käsittele todellisia asiakastietoja tai luo tuotantotunnuksia. Älä toimi verkossa tai asiakkaan nimissä ilman myöhempää erillistä lupaa. Lähesty suunnittelua varovasti: tunnista epäselvyydet, mutta tarjoa niihin perustellut oletusratkaisut niin, ettei työ pysähdy tarpeettomiin kysymyksiin.
Jos paikallinen `PROJEKTISUUNNITELMA.md` on olemassa, lue se ja käytä vaatimusten päätukena. Jos sitä ei ole, käytä kaikkea tässä promptissa annettua sisältöä. Jos `README.md`, `CLAUDE.md`, `package.json`, `pyproject.toml` tai muuta projektikoodia on olemassa, tarkista ne ensin. Ilmoita ristiriidat ja ehdota muutoksia, mutta älä muuta tiedostoja.

Tiedossa oleva lähtötilanne (tarkista silti): kansio ei ole vielä git-repo, ja siellä on vain tämä tiedosto sekä Python 3.13 -virtuaaliympäristö `.venv` (vain pip asennettuna).

## Tuotevisio ja tavoite

Rakennamme ensin responsiivisen verkkopalvelun tietokoneen ja puhelimen selaimiin. Myöhemmin teemme erillisen iOS/Android-sovelluksen, joka käyttää samoja backend-API-rajapintoja, käyttäjätilejä, tietoja ja käyttöoikeussääntöjä.
Taloapuri auttaa isännöitsijöitä, taloyhtiöiden hallituksia, puheenjohtajia ja myöhemmässä vaiheessa asukkaita seuraavissa tehtävissä: vahinkoilmoitusten jäsentäminen, kunnossapitovastuiden selvittämisen tukeminen, remontti- ja muutostyöilmoitukset, tarjouspyyntöluonnokset, hallituksen valmistelutyö, yhtiön asiakirjoihin perustuva haku sekä avoimien tehtävien seuranta.
Palvelu ei ole ”automaattinen lakimies”. Se tukee valmistelua ja lähteiden etsimistä, mutta ei anna ehdottomia oikeudellisia takuulauseita eikä tee ihmisen puolesta korvaus-, vakuutus-, hyväksyntä-, maksu- tai urakoitsijavalintapäätöksiä. Pidä kunnossapitovastuu, mahdollinen vahingonkorvausvastuu ja vakuutusasiat selvästi erillään. Yhtiöjärjestys, tosiseikat ja ajantasainen säädösversio voivat vaikuttaa tulkintaan.

## Käyttäjäryhmät ja käyttöoikeusmalli

Suunnittele roolit: isännöitsijä, hallituksen puheenjohtaja, hallituksen jäsen, rahastonhoitaja, osakas, asukas (esim. vuokralainen, joka ei ole osakas), ulkopuolinen asiantuntija sekä palveluntarjoajan ylläpitäjä. Asiakkuus voi olla yksi taloyhtiö tai useita taloyhtiöitä hallinnoiva isännöintiyritys. Yksi käyttäjä voi olla eri roolissa eri yhtiöissä. Huoneistolla voi olla useita omistajia, ja yksi henkilö voi omistaa useita huoneistoja. Mallinna yritys-/taloyhtiökohtainen käyttöoikeus palvelinpuolelle asti, myös asiakirjoihin, vektorihakuun, RAG:iin, rajapintoihin, taustatöihin ja mahdollisiin integraatioihin. Pelkkä frontendin piilotettu nappi ei ole käyttöoikeustarkistus.
Käyttöoikeusmallin on katettava myös: roolien voimassaoloaika (hallituksen kausi päättyy yhtiökokoukseen, asiantuntijan pääsy on tapaus- ja aikarajattu), tapauskohtainen näkyvyys (osakas näkee vain omat asiansa, esteellinen hallituksen jäsen rajataan, luottamukselliset hallitusasiat) sekä se, miten roolin todenperäisyys varmistetaan (kutsuketju: kuka saa kutsua kenet mihinkin rooliin).

## Käyttöliittymä ja saavutettavuus ovat tuotteen lähtökohta

Kohderyhmässä on ihmisiä, joille tekoäly ja monimutkaiset järjestelmät ovat vieraita. Älä suunnittele pelkkää chatbotia. Ensisijainen toimintatapa on ”Valitse tehtävä → Vastaa selkeisiin kysymyksiin → Tarkista yhteenveto → Hyväksy tarvittava toiminto → Seuraa asian etenemistä”. Chat voi täydentää tätä.

- Etusivun toimintokortit arkikielellä: ”Ilmoita vahingosta”, ”Selvitä kunnossapitovastuu”, ”Laadi tarjouspyyntö”, ”Valmistele kokous”, ”Etsi asiakirja”.
- Näytä selkeä vaiheistus, tallennus, ”En tiedä”, muokkaus ja avunpyyntö.
- Näytä selkokielinen yhteenveto aina ennen yksityiskohtia; lähteet avautuvat nimikkeellä ”Mihin tämä perustuu?”.
- Aina näkyvä tila: luonnos, odottaa tietoja, tarkistettavana, hyväksytty, lähetetty, suljettu (sekä poikkeustilat, ks. reunatapaukset).
- Tavoitteena WCAG 2.2 AA: semanttinen HTML, näppäimistö, näkyvä fokus, kontrastit, 200 % suurennus, ruudunlukijat, selkeät lomakevirheet, saavutettava kirjautuminen (ei muistitestejä, WCAG 3.3.8), ymmärrettävä sanasto sekä saavutettavat asiakirjat (tagattu PDF). Suunnittelun kosketuskohdetavoite 44 × 44 CSS-pikseliä mahdollisuuksien mukaan.
- Istunnon aikakatkaisu ei saa hävittää keskeneräistä lomaketta: varoitus ja jatkamismahdollisuus (WCAG 2.2.1).
- Testaa kriittiset polut myös vähän digipalveluja käyttävällä henkilöllä. Suomen digipalvelulain ja Euroopan saavutettavuusdirektiivin (EAA) soveltuminen pitää selvittää erikseen; suunnittelutavoite ei tarkoita automaattista lakisääteistä soveltumista.

Vaadin konkreettiset sivukohtaiset UI-suunnitelmat, tekstimuotoiset wireframet ja saavutettavuuden hyväksymiskriteerit. Älä kuittaa helppokäyttöisyyttä vain sanalla ”intuitiivinen”.

## Ensimmäinen MVP ja myöhemmät ominaisuudet

P0 / MVP: hallittu kirjautuminen ja kutsupohjainen käyttäjien lisäys; taloyhtiön valinta; saavutettava dashboard; ohjattu vahinko-/kunnossapitotapaus; asian tallennus ja tilat; liitteet; sähköposti-ilmoitukset tilamuutoksista; rajattu Finlex-aineisto ja yhtiöjärjestys; AI-avusteinen, lähteistetty analyysiluonnos; puuttuvien tietojen tunnistus; tarjouspyynnön ja viestin luonnokset; PDF-lataus; hyväksyntä ennen ulkoisia toimenpiteitä; käyttöoikeustestit, auditointi ja käytön kiintiöt.
P1: muutostyöilmoitus, kokousmateriaalit, tarjousvertailun tuki, kalenteri, käyttäjän hyväksymät sähköposti- ja Drive/OneDrive-integraatiot, yrityspaketti ja laskutus, ruotsinkielinen käyttöliittymä (i18n-valmius jo P0:ssa).
P2: rajattu asukasportaali, lisäpalveluna asiantuntijalle eskalointi, monipuoliset integraatiot ja erillinen mobiilisovellus.
Älä aloita pelkästä AI-chatista. Ehdota toteutusjärjestystä, jossa ensin toteutetaan selkeä, turvallinen ei-AI-työnkulku ja sen jälkeen kytketään RAG ja dokumenttigenerointi. Ei-AI-työnkulun on toimittava kokonaan myös silloin, kun AI-palvelu on poissa käytöstä.

## Vaaditut käyttäjätarinat ja niiden hyväksymistestit

1. **US-1:** Isännöitsijä käsittelee astianpesukoneen vuotoa: kiireelliset ensiohjeet (staattinen, asiantuntijan tarkistama sisältö, ei riipu tekoälystä), vahingon tosiseikat ja tapahtumapäivä, erilliset vastuunäkökulmat, lisätietopyyntö ja viestiluonnos.
2. **US-2:** Hallituksen puheenjohtaja laatii porrashuoneen maalauksen tarjouspyynnön: työlaajuus, puuttuvat tiedot, sopimusehtojen oikea asema, tarkistettava PDF.
3. **US-3:** Osakas tekee kylpyhuoneremontin muutostyöilmoituksen: kysymykset, liitteet, luonnoksen välitallennus, ihmisen käsittely.
4. **US-4:** Hallituksen jäsen valmistelee kokouksen: esityslista, lähteet, erottelu ehdotuksen ja tehdyn päätöksen välillä (järjestelmä ei saa antaa ymmärtää, että yksi klikkaus on hallituksen päätös).
5. **US-5:** Vähän digitaalista kokemusta omaava henkilö selvittää vastuun ilman chat-promptia ja saa helpon yhteenvetonäkymän.
6. **US-6:** Isännöitsijä vaihtaa useiden taloyhtiöiden välillä: väärän yhtiön tietoja ei voi saada UI:n, API:n, AI-haun, välimuistin, toisen selainvälilehden eikä esiallekirjoitetun tiedostolinkin kautta.
7. **US-7:** Monimutkainen oikeudellinen tapaus: tekoäly tunnistaa epävarmuuden ja ehdottaa ihmisen asiantuntija-arviota ennen jatkoa.
8. **US-8:** Taloyhtiö vaihtaa isännöintiyritystä: tiedot siirretään hallitusti, vanhan yrityksen pääsy päättyy ja historia säilyy.

Kirjoita näistä käytännölliset Given/When/Then-tyyliset hyväksymiskriteerit ja negatiiviset testit.

## Tekninen tavoitepino (arvioi ja perustele)

Suositeltu lähtövalinta:

- Frontend: Next.js / React / TypeScript; semanttinen HTML ja testatut saavutettavat UI-komponentit; responsiivisuus.
- Backend: Python 3.13 / FastAPI / Pydantic; versioitu REST API ja OpenAPI.
- Tietokanta: PostgreSQL / SQLAlchemy / Alembic; moniasiakkuuden eristys ja tarvittaessa RLS.
- Taustatyöt: OCR, virustarkistus, upotukset, PDF-generointi ja sähköpostit ajetaan jonossa. Harkitse PostgreSQL-pohjaista jonoa (esim. procrastinate), jotta MVP ei tarvitse Redistä. Uudelleenyritykset, idempotenssi ja tenant-konteksti jokaisessa työssä.
- RAG: PostgreSQL pgvector + metadata-/käyttöoikeussuodatukset, tarkka tekstihaku; dokumentin ja pykälän versiot.
- Tiedostot: EU-alueelle soveltuva salattu S3-yhteensopiva objektitallennus; turvallinen lataus- ja poistoprosessi.
- AI: mallitoimittajasta erotettu adapteri, kustannusrajat, strukturoidut vastaukset, lähdeviitetarkistus; valitse mallien yhdistelmä arviointitulosten perusteella.
- Auth: luotettu OIDC/OAuth2-palvelu ja MFA; älä rakenna salasanojen käsittelyä itse. Suunnittele heti, miten tunnistautuminen kulkee Next.js:n ja FastAPI:n välillä (eväste-istunto vs. bearer-token, BFF-malli, CSRF) ja miten tuleva mobiilisovellus kirjautuu (OIDC + PKCE). Suunnittele myös tilin palautus ikääntyneille käyttäjille.
- Sähköposti: transaktionaalinen outbox-malli, SPF/DKIM/DMARC, palautusten käsittely.
- PDF: versioidut HTML-/PDF-mallit sekä saavutettavuuden varmistus; PDF-renderöijällä ei verkkoyhteyttä (SSRF-esto).
- Dev/CI: git, Docker Compose, GitHub Actions, pytest, Playwright + axe-core, linterit/tyyppitarkistus, riippuvuus- ja salaisuusskannaus. Lukitse Python- ja Node-versiot.
- Mobiili myöhemmin: harkitse React Native / Expoa, mutta älä rakenna tässä vaiheessa mobiilisovelluksen koodia.

Tarkista repo ja kerro, onko yllä oleva liian raskas yksin aloittavalle kehittäjälle. Vertaa vähintään vaihtoehtoa FastAPI + Jinja-palvelinrenderöinti + HTMX (yksi kieli, yksi käyttöönotto, sama REST API voi palvella mobiilia myöhemmin). Päätöskriteerit: yksin ylläpidettävyys, yksi tunnistautumismalli, käyttöönottojen määrä, saavutettavuus ja mobiilivalmius. Anna yksiselitteinen MVP-valinta sekä perustellut arkkitehtuuripäätökset (ADR, Architecture Decision Record) vähintään näistä: (1) tietojen omistajuus (taloyhtiö vs. isännöintiyritys), (2) tunnistautuminen web/BFF/mobiili, (3) taustatyöjono, (4) tenant-eristys ja RLS.

## RAG, lähteet ja oikeudellinen luotettavuus

Käytä ensisijaisesti Finlexin avoimen datan REST-rajapinnan ajantasaisia säädösversioita. Aloita asunto-osakeyhtiölaista 1599/2009 ja sen keskeisistä kunnossapito- ja muutostyösäännöksistä. Rajapintavastaukset voivat olla Akoma Ntoso XML:ää. Suunnittele hakuhetken, voimaantulon, lainkohdan ja dokumenttiversion tallettaminen. Tarkista avoimen datan lisenssi ja lähdemainintavaatimus, ja kerro käyttäjälle, ettei ajantasainen säädöskokoelma ole virallisesti oikeudellisesti sitova julkaisu. Lisää asiakaskohtaisesti vain hyväksytysti ladattu yhtiöjärjestys ja muu tarpeellinen aineisto. Älä oleta YSE 1998:n, RT-korttien tai kaupallisen vastuunjakotaulukon vapaita uudelleenjakelu-/indeksointioikeuksia.

RAG-ketjun on erotettava: käyttäjän syöttämät tosiseikat; viralliset oikeuslähteet; yhtiön omat asiakirjat; AI:n tulkinta; avoimet epävarmuudet; ehdotetut jatkotoimet. Jokainen oikeudellisesti merkittävä väite joko sisältää todentamiskelpoisen lähdeviitteen tai merkinnän, ettei sitä ole vahvistettu. Älä lupaa 100 % oikeellisuutta. Suunnittele automaattinen retrieval-eval, viitetesti ja asiantuntijan validointiprosessi sekä lähteiden päivittämisen valvonta.

Lisäksi:
- Sovellettava säädösversio valitaan tapahtumapäivän (`event_date`) eikä hakupäivän mukaan. Vanhat yhtiöjärjestykset voivat viitata ennen vuotta 2010 voimassa olleeseen lakiin.
- Yhtiöjärjestyksellä on versioita (muutokset, rekisteröity vs. luonnos).
- Skannatut PDF:t vaativat OCR:n: OCR → ihmisen tarkistus → indeksointihyväksyntä, ja OCR-luotettavuus tallennetaan.
- Pilko lakiteksti pykälän ja momentin mukaan, ei pelkkinä token-ikkunoina.
- Malli saa viitata vain haettuihin chunkeihin, ja lainauksen on löydyttävä sanatarkasti viitatusta lähdeversiosta.
- Suomen kieli: vertaa PostgreSQL:n `finnish`-konfiguraatiota, trigrammihakua ja Voikkoa yhdyssanoille (esim. ”kunnossapitovastuu”) sekä upotusmallien suomen kielen laatua.
- Kun lähde päivittyy, merkitse avoimet analyysit, jotka viittaavat vanhaan versioon (”Lähde on päivittynyt”).
- Upotuksiin tallennetaan malli ja mallin versio, jotta mallinvaihto voi käynnistää uudelleenupotuksen.

## Suojaus, tietosuoja ja käyttöoikeudet

Laadi selkeä uhkamalli, jossa käsitellään: tenant-eristys, IDOR/BOLA, auth/MFA, XSS/CSRF, API-avaimet ja salaisuudet, dokumenttien skannaus, prompt injection (myös PDF:ien, OCR-tekstin, tiedostonimien, EXIF-tietojen, lomakkeiden vapaatekstikenttien ja sähköpostien kautta), RAG:n vektorivuodot, henkilötietojen minimointi, logien sisältö, AI-palvelun alihankkijasopimukset, tietojen säilytys/poisto, siirto EU/ETA:n ulkopuolelle, väärät juridiset päätelmät, käyttöbudjetin ylitys (myös dokumenttien sisäänluvussa) ja vahingossa tehdyt ulkoiset toimenpiteet. Käytä uusinta julkaistua OWASP Top 10 for LLM Applications -versiota (tarkista vuosi) soveltuvin osin.

Kirjaa GDPR:n osalta tarpeelliset oikeusperuste- ja rooliarviot (rekisterinpitäjä vs. käsittelijä tapauskohtaisesti), DPA, alihankkijat, DPIA-arvion tarve ja yksilöiden oikeuksien käsittely. Vahinkokuvat ja remonttiasiakirjat voivat sisältää erityisiä henkilötietoryhmiä (esim. terveys, home, esteettömyysmuutokset). Kirjaa EU:n tekoälyasetuksen avoimuusvelvoitteet (art. 50) tarkistettavaksi. Erota suunnitteluehdotus oikeudellisesta lopullisesta tulkinnasta.

Pakollinen turvasääntö: AI ei saa lähettää viestejä, muuttaa asiakirjojen virallista hyväksyntätilaa, avata toisen yhtiön tietoja, antaa maksumääräystä tai julkaista päätöstä ilman palvelinpuolista oikeustarkistusta ja tarvittavaa ihmisen nimenomaista hyväksyntää.

## Pakolliset reunatapaukset ja arkkitehtuuripäätökset

Jokaiselle alla olevalle kohdalle on annettava päätös, ADR tai testi. Pelkkä maininta ei riitä.

**Tenant-eristys ja käyttöoikeudet**
- Isännöitsijän vaihtuminen: tietojen omistaja, vienti/luovutus, vanhan yrityksen pääsyn päättyminen ja historian säilyminen.
- Jäsenyyksien `valid_from`/`valid_to`, automaattinen vanheneminen ja offboarding-testi.
- Tapauskohtainen näkyvyys ja esteellisyys.
- RLS:
  - Sovellus käyttää roolia, joka ei omista tauluja, ja `FORCE ROW LEVEL SECURITY` on päällä.
  - Tenant-konteksti asetetaan `SET LOCAL`-komennolla transaktiossa (yhteyspoolauksen kanssa).
  - Taustatyöt asettavat tenant-kontekstin.
  - Julkisille Finlex-riveille (`tenant_id IS NULL`) on erillinen lukupolitiikka.
- Yhtiön tunniste kulkee URL-polussa (`/companies/{id}/…`) eikä pelkästään istunnossa.
- Välimuistiavaimiin sisältyy tenant, käytetään `Cache-Control: private`-otsaketta ja lyhytikäisiä esiallekirjoitettuja URL-osoitteita.
- Palveluntarjoajan tukipääsy (break-glass): syy, aikaraja, auditointi ja tarvittaessa ilmoitus asiakkaalle.

**Arkkitehtuuri ja työnkulku**
- Idempotenssiavaimet kaikkiin sivuvaikutuksellisiin endpointeihin (ei tuplalähetyksiä).
- Optimistinen lukitus (`version`/ETag) ja käyttöliittymä samanaikaisen muokkauksen ristiriidoille.
- Hyväksyntä sidotaan sisällön versioon tai tiivisteeseen; muutos hyväksynnän jälkeen mitätöi sen.
- Täydellinen tilakone siirtymineen, rooleineen ja audit-tapahtumineen. Mukaan myös tilat peruttu, hylätty, uudelleen avattu, eskaloitu asiantuntijalle ja lähetys epäonnistui.
- Aikavyöhyke Europe/Helsinki ja kesäaika määräajoissa ja audit-lokissa.

**AI**
- Kiireelliset ensiohjeet ovat staattisia, eivätkä ne riipu tekoälystä.
- Määritellään aikakatkaisu ja varatoiminta, kun AI-palvelu ei vastaa.
- `ai_runs` tallentaa promptin version, mallin tunnisteen, parametrit sekä haettujen chunkien ja lähdeversioiden tunnisteet, jotta analyysin perusta voidaan näyttää jälkikäteen.
- Kustannusrajat kattavat myös dokumenttien sisäänluvun: koko, sivumäärä sekä tenant- ja kuukausikohtainen kiintiö.

**Tiedostot, tietosuoja ja audit**
- Tiedostotyyppi tarkistetaan magic bytes -tunnisteesta.
- Virustarkistus (esim. ClamAV).
- EXIF/GPS-tiedot poistetaan.
- iPhonen HEIC-kuvat muunnetaan.
- Tiedostoille asetetaan kokorajat.
- Säilytysvelvollisuudet vs. poisto-oikeus: käyttäjän poistuessa tiedot pseudonymisoidaan, ja hänen luomansa asiat säilyvät. Säilytysajat merkitään tarkistettaviksi oikeudellisiksi kysymyksiksi ilman keksittyjä lukuja.
- Audit-loki on append-only (valinnaisesti hash-ketju), sisältää minimaalisesti henkilötietoja ja sillä on oma säilytysaika.

## Suunniteltavat tietorakenteet ja sopimukset

Ehdota ER-malli ja skeema vähintään tauluille: accounts, housing_companies, account_companies, apartments, users, memberships, invitations, cases, case_events, tasks, documents, document_versions, sources, source_versions, chunks, embeddings, prompt_versions, ai_runs, citations, approvals, notifications/outbox, jobs, audit_events, usage_events.

Erityisesti näihin tauluihin tarvitaan nämä kentät:

| Taulu | Vaadittavat kentät |
|---|---|
| memberships | voimassaoloaika |
| cases | `event_date`, `version` |
| document_versions | `effective_from` ja tila (rekisteröity/luonnos) sekä OCR-luotettavuus |
| embeddings | malli ja mallin versio |
| approvals | sisältötiiviste |

Kerro yksilöivät kentät, viiteavaimet, tenant-rajaus, indeksointi, poistopolitiikka ja tilasiirtymät. Suunnittele API-reitit perusteluineen sekä OpenAPI:n käyttö webin ja tulevan mobiilin yhteisenä sopimuksena. Anna alustava repository-puurakenne, mutta vältä ennenaikaista mikropalveluarkkitehtuuria.

## Tuotannon elinkaari ja talous

Suunnittele ympäristöt (local/test/staging/production), tietokantamigraatiot, varmuuskopiot ja palautustestit, keskitetty virheseuranta ilman tarpeettomia henkilötietoja, CI/CD sekä hyväksyntäportit. Arvioi AI:n token-kustannusten, tallennuksen, infrastruktuurin, sähköpostipalvelun, tukityön (myös tilien palautus) ja lisenssien seuranta. Hinnoittelu on vasta hypoteesi: 49 €/kk Basic, 119 €/kk Professional, 490 €/kk Business + laajennukset (alv 0 %), eikä maksullista toteutusta tarvita ensimmäisessä sprintissä. Merkitse kustannusoletukset erikseen laskutuksesta. Nimeä, kuka on oikeudellinen asiantuntija RAG-evalin ja validoinnin osalta, ja paljonko siihen varataan budjettia (tai merkitse avoimeksi päätökseksi).

## Vastauksen jakaminen kolmeen kierrokseen

Älä tuota kaikkea yhdellä kertaa. Tuota vastaus kolmessa kierroksessa. Jokaisen kierroksen lopussa kysy vain, hyväksynkö seuraavan kierroksen.

1. **Kierros 1:** repositoryn nykytila, arkkitehtuuri ja ADR:t, roolit ja käyttöoikeusmatriisi, tietoarkkitehtuuri.
2. **Kierros 2:** käyttäjäpolut ja UI-suunnitelma, MVP-rajaus, API-sopimukset ja tilakoneet, hyväksymistestit.
3. **Kierros 3:** lähde- ja AI-arkkitehtuuri, tietoturva ja compliance, testaus ja laatuportit, vaiheittainen toteutus, riskit, ensimmäinen seuraava toimenpide.

## Toivottu vastausmuoto – tuota juuri nämä otsikot (jaettuna kierroksiin)

- Repositoryn nykytila: mitä tarkistit, mitä löytyi ja mitä ei; ei keksittyjä olemassa olevia tiedostoja.
- Tiivis arkkitehtuuriehdotus ja vaihtoehdot: lopullinen MVP-teknologiapino, perustelut sekä vaihtoehtoiset valinnat ja riskit; ADR:t.
- Käyttäjäroolit ja käyttöoikeusmatriisi: rajaukset, tenant-eristys, tapauskohtainen näkyvyys, roolien voimassaolo ja valtuudet.
- Käyttäjäpolut ja UI-suunnitelma: sivukartta, yksinkertaiset tekstiwireframet, saavutettavuuskriteerit ja selkokieliset esimerkkitekstit.
- Toiminnallinen MVP-rajaus: P0/P1/P2, selkeät out-of-scope-kohdat ja perustelut.
- Tietoarkkitehtuuri: ER-kaavio Mermaidillä, entiteetit, versiot, RLS ja tallennus.
- Järjestelmäarkkitehtuuri: Mermaid-kaavio, frontend/backend/taustatyöt/AI/Finlex/tiedostot/sähköposti, luottamusrajat, tuleva mobiili.
- API-sopimukset ja tilakoneet: endpointit, payload-esimerkit, idempotenssi, versiointi ja asian hyväksyntäprosessi.
- Lähde- ja AI-arkkitehtuuri: ingestio (myös OCR), käyttöoikeusrajattu retrieval, citational validation, uncertainty/escalation, mallikustannusrajat.
- Tietoturva, tietosuoja ja compliance: uhkamalli, kontrollit ja avoimet oikeudelliset tarkistuskohdat.
- Testaus ja laatuportit: pytest, API, DB, E2E, WCAG, RAG-eval, tenant-escape- ja prompt injection -testit, reunatapausten testit; julkaisuportti.
- Vaiheittainen toteutus: vaihe −1 (asiakasvalidointi: 3–5 haastattelua isännöitsijöiden/hallitusten kanssa ja klikattava prototyyppi) sekä vaiheet 0–6, riippuvuudet, kunkin vaiheen deliverables ja yksiselitteiset hyväksymiskriteerit. Vaiheeseen 0 kuuluvat `git init`, lukitut Python- ja Node-versiot sekä `CLAUDE.md`-luonnos (kieli, komennot, säännöt ”jokainen kysely on tenant-rajattu” ja ”ei AI-toimintoa ilman hyväksyntää”). Anna ensimmäisten kahden sprintin tarkka tehtäväjärjestys, tarvittavat komennot ja alustavat tiedostopolut. Erota ”luodaan myöhemmin” olemassa olevasta.
- Riskit ja avoimet päätökset: riski, vaikutus, toimenpide, omistaja; esitä oletussuositus jokaiselle. Mukaan vähintään: oikeudellinen asiantuntija ja budjetti, ruotsin kieli/i18n, tekoälyasetuksen art. 50, EAA/digipalvelulaki, jäsenyyksien todentaminen (esim. HTJ/PRH-tiedot tarkistettavana lähteenä).
- Ensimmäinen seuraava toimenpide: ehdota yhtä tarkasti rajattua toteutusaskelta, jonka voin hyväksyä erikseen.

## Laadulliset vaatimukset vastaukselle

Älä kirjoita toteutuskoodia vielä. Kirjoita suunnitelma suomeksi, selitä uudet käsitteet ensimmäisellä esiintymällä lyhyesti, käytä johdonmukaista terminologiaa ja tarkkoja tiedostonimiä. Erota faktat, oletukset ja tarkistettavat asiat. Älä keksi laki- tai standarditekstejä, standardien versiovuosia tai todellisia hinnastoja. Jos internet-yhteys ei ole käytettävissä, listaa tarkistettavat lähteet sen sijaan, että väittäisit niiden tulleen tarkistetuiksi. Muista, että käyttäjäkunta voi olla tekoälystä täysin kokematon. Lopuksi kysy vain, hyväksynkö suunnitelman ensimmäisen toteutusvaiheen aloittamisen, äläkä tee koodimuutoksia ennen nimenomaista lupaani.
