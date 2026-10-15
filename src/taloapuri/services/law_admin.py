"""Lakilähteiden hallinta: vain palvelun ylläpitäjälle (ks. docs/adr/0007).

Lait ovat yhteisiä kaikille taloyhtiöille. Teksti haetaan vain Finlexin virallisesta osoitteesta
(`sources/finlex.fetch`), joten ylläpitäjä ei voi syöttää omaa lakitekstiä. Jokainen lisäys,
päivitys ja käytöstä poisto kirjataan audit-lokiin. Sama lain tarkistus voidaan tehdä vain
kerran `law_check_cooldown_seconds` sekunnissa (suojaa Finlexiä ja tietokantaa).
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from taloapuri.auth import CurrentUser
from taloapuri.services.audit import write_user_audit
from taloapuri.sources import updater
from taloapuri.sources.finlex import Fetcher, FinlexError
from taloapuri.sources.updater import PreviewResult, SourceInfo, UpdateResult


class NotAdmin(Exception):
    """Käyttäjä ei ole palvelun ylläpitäjä."""


class Cooldown(FinlexError):
    def __init__(self, seconds_left: int) -> None:
        minutes = max(1, round(seconds_left / 60))
        super().__init__(
            "Tämä laki tarkistettiin juuri äsken. "
            f"Odota noin {minutes} min ennen uutta tarkistusta."
        )
        self.seconds_left = seconds_left


@dataclass
class CheckOutcome:
    source: SourceInfo
    result: UpdateResult | None = None
    error: str | None = None


def _require_admin(db: Session) -> None:
    if not db.execute(text("SELECT app_is_platform_admin()")).scalar_one():
        raise NotAdmin


def list_laws(db: Session) -> list[SourceInfo]:
    """Kaikki lakilähteet. Lukeminen on sallittu kaikille kirjautuneille (julkista tietoa)."""
    return updater.list_sources(db.connection())


def preview_law(db: Session, year: int, number: int, fetcher: Fetcher) -> PreviewResult:
    _require_admin(db)
    return updater.preview(year, number, fetcher)


def add_law(
    db: Session,
    admin: CurrentUser,
    *,
    year: int,
    number: int,
    short_title: str,
    expected_sha256: str,
    fetcher: Fetcher,
) -> str:
    _require_admin(db)
    try:
        with db.begin_nested():
            key = updater.add_source(
                db.connection(),
                year=year,
                number=number,
                short_title=short_title,
                expected_sha256=expected_sha256,
                fetcher=fetcher,
                added_by=admin.id,
            )
    except IntegrityError as exc:  # rinnakkainen lisäys tai lyhenne ehti varatuksi
        raise updater.AlreadyAdded(
            "Lain lisäys epäonnistui: laki tai lyhenne on jo olemassa."
        ) from exc
    write_user_audit(db, admin.id, "source.added", "source", key, short_title=short_title or "")
    return key


def _check_cooldown(db: Session, source_key: str, cooldown_seconds: int) -> None:
    left = db.execute(
        text(
            "SELECT extract(epoch FROM (last_checked_at + make_interval(secs => :s) - now()))"
            " FROM sources WHERE source_key = :k AND last_checked_at IS NOT NULL"
        ),
        {"s": cooldown_seconds, "k": source_key},
    ).scalar_one_or_none()
    if left is not None and left > 0:
        raise Cooldown(int(left))


def check_law(
    db: Session,
    admin: CurrentUser,
    source_key: str,
    fetcher: Fetcher,
    cooldown_seconds: int,
) -> UpdateResult:
    _require_admin(db)
    _check_cooldown(db, source_key, cooldown_seconds)
    result = updater.check_and_update(db.connection(), source_key, fetcher)
    write_user_audit(
        db,
        admin.id,
        "source.updated" if result.changed else "source.checked",
        "source",
        source_key,
        version=result.version_label,
        changed=result.changed,
    )
    return result


def check_all(
    db: Session, admin: CurrentUser, fetcher: Fetcher, cooldown_seconds: int
) -> list[CheckOutcome]:
    """Tarkistaa kaikki käytössä olevat lait. Yhden virhe ei estä muiden tarkistusta."""
    _require_admin(db)
    outcomes = []
    for source in list_laws(db):
        if not source.active:
            continue
        try:
            with db.begin_nested():
                result = check_law(db, admin, source.source_key, fetcher, cooldown_seconds)
            outcomes.append(CheckOutcome(source, result=result))
        except FinlexError as exc:
            outcomes.append(CheckOutcome(source, error=str(exc)))
    return outcomes


def set_law_active(db: Session, admin: CurrentUser, source_key: str, active: bool) -> None:
    _require_admin(db)
    updater.set_active(db.connection(), source_key, active)
    write_user_audit(
        db, admin.id, "source.activated" if active else "source.deactivated", "source", source_key
    )
