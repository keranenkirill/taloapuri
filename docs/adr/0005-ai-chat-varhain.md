# ADR 0005: Tekoälychat lakilähteistä jo ennen RAG-vaihetta

- Tila: Hyväksytty (kokeilu)
- Päivämäärä: 2026-10-15

## Konteksti
Alkuperäisen suunnitelman mukaan ei-tekoälyinen työnkulku tehdään ensin ja RAG vasta myöhemmin. Tuotteen omistaja halusi tekoälychatin jo nyt kokeiluna. Rajauksena on asunto-osakeyhtiölaki Finlexin avoimesta datasta.

## Päätös
- **Malli:** Claude Haiku 5.5 (`claude-haiku-5-5`), effort `medium`, `max_tokens` 2000 ja aikakatkaisu 30 s. Mallin voi vaihtaa asetuksella `TALOAPURI_AI_MODEL`.
- **Lähteet:** AOYL 1599/2009, ajantasainen versio (`.../statute-consolidated/2009/1599/fin@latest`). Ingestio tehdään skriptillä `scripts/ingest_finlex.py`, ja se tallentaa uuden version vain sisällön muuttuessa (SHA-256).
- **Haku:** PostgreSQL:n `finnish`-tekstihaku. Pykälän otsikko painaa eniten. Kysymyssanat poistetaan, ja arkikieli laajennetaan pienellä käsitesanastolla (`services/sources.py`). Upotuksia ei käytetä vielä.
- **Viitteet:** jokainen pykälä on oma dokumenttinsa ja jokainen momentti oma lohkonsa (Claude Citations, `content_block_location`). Jokainen viite tarkistetaan palvelimella: lainauksen on löydyttävä viitatusta momentista. Muuten viite merkitään "ei vahvistettu".
- **Turvarajat:**
  - Tekoäly saa vain kysymyksen ja julkisen lakitekstin, ei yhtiön, asioiden eikä henkilöiden tietoja.
  - Tekoälyllä ei ole työkaluja eikä sivuvaikutuksia.
  - Jos lähteitä ei löydy, tekoälyä ei kutsuta.
  - Kehote käsittelee lähteitä ja kysymystä aineistona, ei ohjeina.
  - Vastauksessa on aina merkintä "Tekoälyn tuottama" ja lähdeosio "Mihin tämä perustuu?".
  - Monimutkaisissa asioissa vastaus kehottaa asiantuntijan arvioon.
- **Kiintiöt:** yhtiökohtainen kuukausibudjetti (`TALOAPURI_AI_MONTHLY_BUDGET_USD`) ja käyttäjäkohtainen päiväraja. Kustannus arvioidaan jokaisesta ajosta (`ai_runs`).
- **Yksityisyys:** käyttäjä näkee vain omat keskustelunsa. Isännöitsijäkään ei näe asukkaan kysymyksiä.
- **Käytettävyys ilman tekoälyä:** tekoäly on oletuksena pois päältä (`TALOAPURI_AI_ENABLED=false`). Jos se on pois päältä, ei vastaa tai kiintiö on täynnä, käyttäjä ohjataan ohjattuihin toimintoihin.

## Rajoitukset (tiedossa)
- Käytössä on vain uusin ajantasainen versio. Tapahtumapäivän mukainen versio (`event_date`) puuttuu vielä.
- Mukana on vain AOYL. Yhtiöjärjestys ja muut lähteet lisätään asiakirjavaiheessa.
- Keskustelussa ei ole muistia: jokainen kysymys haetaan ja vastataan erikseen.
- Kustannus on arvio: hinnat on asetettu konfiguraatiossa (USD).

## Avoimet tarkistukset
- Finlexin avoimen datan käyttöehdot ja lähdemaininta. Avoimen datan sivulla ei mainita lisenssiä. Kysy osoitteesta finlex-tuki(at)om.fi.
- EU:n tekoälyasetuksen art. 50 (avoimuus): merkintä on toteutettu, mutta juridinen arvio on vielä tekemättä.
- Anthropicin tietojenkäsittelyehdot (DPA) ja tietojen säilytys ennen tuotantokäyttöä.
- Oikeudellinen asiantuntija arvioimaan vastausten laatua (eval-aineisto).
