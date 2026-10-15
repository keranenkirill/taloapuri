# ADR 0003: Tunnistautuminen web ja mobiili

- Tila: Ehdotus. Vaihe 0 käyttää vain kehityskirjautumista.
- Päivämäärä: 2026-10-15

## Päätös
- **Vaihe 0:** kehityskirjautuminen (`X-Dev-User-Id`-otsake tai `dev_user_id`-eväste) toimii vain, kun `TALOAPURI_ENV` on `local` tai `test`. Muissa ympäristöissä kaikki suojatut reitit palauttavat 401.
- **Vaihe 1:** ulkoinen OIDC-palvelu, jossa on MFA. Salasanoja ei käsitellä itse. Palvelun on oltava EU-alueella, ja se valitaan erikseen.
  - Web: OIDC Authorization Code + PKCE palvelimella. Istunto tallennetaan `HttpOnly; Secure; SameSite=Lax` -evästeeseen, ja lomakkeissa on CSRF-tunniste.
  - Mobiili (P2): OIDC + PKCE natiivisti, ja API:lle lähetetään bearer-token. Sama `/api/v1` hyväksyy molemmat.
  - `users.oidc_subject` yhdistää käyttäjän OIDC-tunnisteeseen.
- Saavutettava kirjautuminen (WCAG 3.3.8): ei muistitestejä, ja salasananhallinnan sekä sähköpostilinkin käyttö sallitaan.
- Tilin palautus ikääntyneille käyttäjille: isännöitsijä voi lähettää uuden kutsun. Prosessi suunnitellaan vaiheessa 1.

## Avoimet päätökset
- OIDC-palvelun valinta (kustannus, EU-sijainti, MFA-vaihtoehdot).
