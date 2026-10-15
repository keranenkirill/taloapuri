# ADR 0002: Tietojen omistajuus – taloyhtiö on tenant

- Tila: Hyväksytty (vaihe 0). Oikeudellinen rooliarvio on vielä tarkistamatta.
- Päivämäärä: 2026-10-15

## Konteksti
Asiakkuus voi olla yksittäinen taloyhtiö tai isännöintiyritys, joka hallinnoi useita yhtiöitä. Taloyhtiöt vaihtavat isännöitsijää (US-8). Jos tiedot kuuluisivat isännöintiyritykselle, ne lähtisivät vaihdossa väärään paikkaan.

## Päätös
- **Tenant-raja on `housing_companies`.** Kaikilla yhtiön tiedoilla (asiat, tapahtumat, myöhemmin asiakirjat, chunkit ja ai_runs) on `housing_company_id`.
- Isännöintiyritys (`accounts`) liitetään yhtiöön aikarajatulla `account_companies`-rivillä (`valid_from`/`valid_to`).
- Käyttäjien pääsy perustuu aina henkilökohtaisiin, aikarajattuihin `memberships`-riveihin, ei asiakkuuteen.

## Isännöitsijän vaihdos (toteutetaan myöhemmin)
1. Vanhan `account_companies`-rivin `valid_to` asetetaan, ja uusi rivi luodaan.
2. Vanhan yrityksen käyttäjien jäsenyydet päätetään (`valid_to`). Historia säilyy, koska rivejä ei poisteta.
3. Uudet käyttäjät saavat pääsyn kutsulla.

## Avoimet tarkistukset
- GDPR-roolit: taloyhtiö on todennäköisesti rekisterinpitäjä ja Taloapuri käsittelijä, mutta tämä on varmistettava juristilta.
