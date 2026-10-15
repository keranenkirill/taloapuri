"""Tekoälyn vastauksen striimaus selaimeen (Server-Sent Events POST-vastauksena).

Striimi ajetaan omassa tietokantaistunnossaan, koska vastausta lähetetään vielä pyynnön
käsittelijän palattua. Tenant-konteksti asetetaan uudelleen, joten RLS pätee kuten muuallakin.
Tallennus vahvistetaan (commit) ennen "done"-tapahtumaa, jotta uudelleenohjattu sivu näkee tuloksen.
Ilman JavaScriptiä samat toiminnot toimivat tavallisina lomakkeina (ei striimiä).
"""

import json
import logging
import uuid
from collections.abc import Callable, Iterator

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from taloapuri.ai.events import StreamEvent
from taloapuri.auth import CompanyContext
from taloapuri.db import get_session_factory, set_company_context, set_user_context

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Jokin meni vikaan. Yritä hetken päästä uudelleen."


def sse(event: str, data: dict[str, str]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_events(
    ctx: CompanyContext,
    run: Callable[[Session], Iterator[StreamEvent]],
    done_url: Callable[[uuid.UUID | None], str],
    expected_errors: tuple[type[Exception], ...] = (),
    commit_on_error: bool = False,
) -> StreamingResponse:
    def generate() -> Iterator[str]:
        yield sse("status", {"text": "Aloitetaan…"})
        session = get_session_factory()()
        try:
            session.begin()
            set_user_context(session, ctx.user_id)
            set_company_context(session, ctx.company_id)
            for event in run(session):
                if event.kind == "done":
                    session.commit()
                    yield sse("done", {"redirect": done_url(event.ref_id)})
                    return
                yield sse(event.kind, {"text": event.text})
            session.commit()
        except expected_errors as exc:
            # Esim. kiintiö täynnä tai tekoäly ei vastannut: virheen kirjaus (ai_runs) säilytetään.
            if commit_on_error:
                session.commit()
            else:
                session.rollback()
            yield sse("error", {"message": str(exc)})
        except Exception:
            session.rollback()
            logger.exception("Tekoälystriimi epäonnistui")
            yield sse("error", {"message": GENERIC_ERROR})
        finally:
            session.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "private, no-store",
            "X-Accel-Buffering": "no",  # välityspalvelimet eivät puskuroi striimiä
        },
    )
