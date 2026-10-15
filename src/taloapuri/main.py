from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from taloapuri.api.v1 import router as api_v1_router
from taloapuri.web.account_routes import router as account_web_router
from taloapuri.web.admin_routes import router as admin_web_router
from taloapuri.web.cases_routes import router as cases_web_router
from taloapuri.web.chat_routes import router as chat_web_router
from taloapuri.web.documents_routes import router as documents_web_router
from taloapuri.web.faq_routes import router as faq_web_router
from taloapuri.web.live_routes import router as live_web_router
from taloapuri.web.members_routes import router as members_web_router
from taloapuri.web.messages_routes import router as messages_web_router
from taloapuri.web.routes import router as web_router
from taloapuri.web.templating import render
from taloapuri.web.tenders_routes import router as tenders_web_router

_ERROR_MESSAGES_FI = {
    status.HTTP_400_BAD_REQUEST: "Pyyntö oli virheellinen. Palaa takaisin ja yritä uudelleen.",
    status.HTTP_403_FORBIDDEN: "Sinulla ei ole oikeutta tähän toimintoon.",
    status.HTTP_404_NOT_FOUND: "Sivua ei löytynyt, tai sinulla ei ole siihen käyttöoikeutta.",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Toiminto ei ole käytettävissä tällä tavalla.",
}


async def _http_error(request: Request, exc: Exception) -> Response:
    """API saa JSON-virheet; selaimen sivut saavat selkokielisen HTML-sivun."""
    assert isinstance(exc, StarletteHTTPException)
    if request.url.path.startswith("/api/"):
        return await http_exception_handler(request, exc)
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    message = _ERROR_MESSAGES_FI.get(
        exc.status_code, "Jokin meni vikaan. Yritä hetken päästä uudelleen."
    )
    return render(request, "virhe.html", {"message": message}, code=exc.status_code)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Taloapuri API",
        version="0.0.1",
        # OpenAPI on webin ja tulevan mobiilisovelluksen yhteinen sopimus.
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.include_router(api_v1_router)
    app.include_router(web_router)
    app.include_router(cases_web_router)
    app.include_router(tenders_web_router)
    app.include_router(members_web_router)
    app.include_router(messages_web_router)
    app.include_router(chat_web_router)
    app.include_router(account_web_router)
    app.include_router(admin_web_router)
    app.include_router(documents_web_router)
    app.include_router(faq_web_router)
    app.include_router(live_web_router)
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "web" / "static"),
        name="static",
    )
    return app


app = create_app()
