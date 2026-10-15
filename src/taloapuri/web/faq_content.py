"""Yleinen UKK (usein kysytyt kysymykset): kiinteä sisältö, joka on LUONNOS ja odottaa tarkistusta.

Jokainen lakiin perustuva väite liittyy lainkohtaan (`refs`), ja sivu näyttää kohdan nykyisen
sanamuodon suoraan tallennetusta laista (versiopäivän ja Finlex-linkin kanssa). Jos lakia ei ole
tallennettu tai se ei ole käytössä, vastaus merkitään "ei vahvistettu lähteestä". Jos laki on
päivittynyt sen jälkeen, kun yhteenveto kirjoitettiin (`verified_version`), sivu varoittaa.

Etusivulla näytetään vain kysymykset, joissa ei ole lakiväitteitä (`front_page`, ei `refs`).
Yhteenvedot on kirjoitettu AOYL-version 20260535 (ajantasaistettu 16.6.2026) pohjalta.
"""

from dataclasses import dataclass

AOYL = "fi/statute/2009/1599"
AOYL_VERIFIED = "20260535"

GROUP_ORDER = ("Vahingot ja vuodot", "Remontit", "Palvelun käyttö")


@dataclass(frozen=True)
class LawRef:
    source_key: str
    chapter: str | None
    section: str
    subsections: tuple[int, ...] | None
    verified_version: str


@dataclass(frozen=True)
class FaqEntry:
    id: str
    group: str
    question: str
    paragraphs: tuple[str, ...] = ()
    refs: tuple[LawRef, ...] = ()
    front_page: bool = False
    first_aid: bool = False


def _aoyl(chapter: str, section: str, subsections: tuple[int, ...]) -> LawRef:
    return LawRef(AOYL, chapter, section, subsections, AOYL_VERIFIED)


FAQ_ENTRIES: tuple[FaqEntry, ...] = (
    FaqEntry(
        id="vesivuoto",
        group="Vahingot ja vuodot",
        question="Vesi vuotaa juuri nyt – mitä teen?",
        first_aid=True,
        front_page=True,
    ),
    FaqEntry(
        id="vahinkoilmoitus",
        group="Vahingot ja vuodot",
        question="Miten teen vahinkoilmoituksen?",
        paragraphs=(
            "Valitse etusivulta ”Ilmoita vahingosta”. Kirjoita lyhyt otsikko, kerro paikka ja "
            "milloin vahinko tapahtui tai huomattiin, ja lisää kuvia, jos voit.",
            "Isännöitsijä näkee ilmoituksen ja voi pyytää lisätietoja. Pyynnön näet asian "
            "sivulla ja etusivun kohdassa ”Uusimmat tapahtumat”, ja voit vastata siihen "
            "tekstillä ja kuvilla.",
        ),
        front_page=True,
    ),
    FaqEntry(
        id="korjausvastuu",
        group="Vahingot ja vuodot",
        question="Kuka vastaa korjauksesta: yhtiö vai osakas?",
        paragraphs=(
            "Vastuu riippuu siitä, mikä osa on vahingoittunut. Lain mukaan yhtiö huolehtii "
            "huoneistojen rakenteista, eristeistä, ikkunoista ja perusjärjestelmistä (esimerkiksi "
            "vesi- ja viemärijärjestelmistä), ja osakas huoneistonsa sisäosista.",
            "Yhtiöjärjestys voi kuitenkin määrätä toisin, ja jokaisen tapauksen tosiseikat "
            "vaikuttavat. Pyydä arvio isännöitsijältä tai kysy tekoälyltä lähdeviitteineen.",
        ),
        refs=(
            _aoyl("4 luku", "1 §", (1,)),
            _aoyl("4 luku", "2 §", (2,)),
            _aoyl("4 luku", "3 §", (1,)),
        ),
    ),
    FaqEntry(
        id="vahingonkorvaus",
        group="Vahingot ja vuodot",
        question="Kuka maksaa vahingon, jos joku on aiheuttanut sen?",
        paragraphs=(
            "Kunnossapitovastuu, vahingonkorvausvastuu ja vakuutus ovat kolme eri asiaa. Lain "
            "mukaan osakkeenomistajan on korvattava vahinko, jonka hän on tahallaan tai "
            "huolimattomuudesta aiheuttanut yhtiölle, toiselle osakkeenomistajalle tai muulle "
            "henkilölle myötävaikuttamalla lain tai yhtiöjärjestyksen rikkomiseen.",
            "Taloapuri ei ratkaise korvaus- tai vakuutusasioita. Ne arvioi isännöitsijä, "
            "hallitus tai tarvittaessa asiantuntija.",
        ),
        refs=(_aoyl("24 luku", "2 §", (1,)),),
    ),
    FaqEntry(
        id="muutostyo",
        group="Remontit",
        question="Tarvitsenko ilmoittaa remontista?",
        paragraphs=(
            "Osakkaalla on lain mukaan oikeus tehdä muutoksia huoneistossaan, mutta joistakin "
            "töistä pitää ilmoittaa etukäteen kirjallisesti hallitukselle tai isännöitsijälle. "
            "Työtä ei saa aloittaa ennen kuin yhtiöllä on ollut kohtuullinen aika käsitellä "
            "ilmoitus, jos yhtiöllä on oikeus asettaa työlle ehtoja tai kieltää se.",
            "Epäselvässä tapauksessa kysy isännöitsijältä ennen töiden aloittamista. "
            "Muutostyöilmoituksen lomake on tulossa palveluun myöhemmin.",
        ),
        refs=(
            _aoyl("5 luku", "1 §", (1,)),
            _aoyl("5 luku", "2 §", (1,)),
            _aoyl("5 luku", "4 §", (1,)),
        ),
    ),
    FaqEntry(
        id="kuka-nakee",
        group="Palvelun käyttö",
        question="Kuka näkee ilmoitukseni?",
        paragraphs=(
            "Ilmoituksesi näkevät sinä, isännöitsijä ja hallitus. Muut osakkaat ja asukkaat "
            "eivät näe sitä.",
            "Kun huoneistossa asuu myöhemmin uusi henkilö, hän näkee vain huoneiston historian: "
            "asian tyypin, tilan, päivämäärät ja isännöitsijän kirjoittaman merkinnän. Nimeäsi, "
            "kuvauksiasi tai kuviasi ei näytetä.",
        ),
        front_page=True,
    ),
    FaqEntry(
        id="sahkoposti",
        group="Palvelun käyttö",
        question="Miten vaihdan sähköpostiosoitteeni?",
        paragraphs=(
            "Avaa oikean yläkulman ”Asetukset”, kirjoita uusi osoite ja tallenna. "
            "Kirjautuminen toimii uudella osoitteella heti.",
        ),
    ),
    FaqEntry(
        id="tekoaly",
        group="Palvelun käyttö",
        question="Mihin voin käyttää tekoälyä?",
        paragraphs=(
            "”Kysy tekoälyltä” hakee vastauksen Suomen lainsäädännöstä ja niistä hallituksen "
            "pöytäkirjoista, jotka saat itse nähdä, ja näyttää, mihin vastaus perustuu. "
            "Jokainen lainaus tarkistetaan lähteestä.",
            "Tekoäly voi erehtyä, eikä se korvaa isännöitsijän tai juristin arviota. "
            "Älä kirjoita kysymykseen henkilö- tai terveystietoja.",
        ),
        front_page=True,
    ),
    FaqEntry(
        id="viestit",
        group="Palvelun käyttö",
        question="Miten otan yhteyttä isännöitsijään?",
        paragraphs=(
            "Käytä oikean yläkulman ”Viestit”-toimintoa: valitse vastaanottaja, kirjoita aihe ja "
            "viesti. Vastauksen näet samassa paikassa, ja uudet viestit näkyvät laskurina "
            "sekä etusivun kohdassa ”Uusimmat tapahtumat”.",
        ),
        front_page=True,
    ),
)


def front_page_entries() -> tuple[FaqEntry, ...]:
    return tuple(e for e in FAQ_ENTRIES if e.front_page)
