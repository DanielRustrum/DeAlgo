"""Settings → AI model: which language model a Text box writes with.

One account's own choice, like its theme. The key is a secret: kept, never
put back into the page — a blank field means "keep the one there is" — and
never in a backup.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ...db import get_settings, session_scope
from ...services import writing
from ..responses import owner_of, redirect, render

router = APIRouter()

PAGE = "/settings/ai"


@router.get(PAGE, response_class=HTMLResponse)
def ai_page(request: Request) -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        settings = get_settings(session, owner)
        return render(request, "ai_settings.html", {
            "providers": writing.PROVIDERS,
            "defaults": writing.DEFAULT_MODELS,
            "provider": settings.ai_provider or "",
            "model": settings.ai_model or "",
            "base_url": settings.ai_base_url or "",
            "has_key": bool(settings.ai_key),
            "chosen": writing.model_for(settings),
        })


@router.post(PAGE)
def save_ai(
    request: Request,
    provider: str = Form(""),
    model: str = Form(""),
    base_url: str = Form(""),
    key: str = Form(""),
    forget_key: str = Form(""),
) -> Response:
    owner = owner_of(request)
    if provider and provider not in dict(writing.PROVIDERS):
        return redirect(PAGE, err="That is not a kind of model this can use.")
    address = base_url.strip()
    if address and not address.startswith(("http://", "https://")):
        return redirect(PAGE, err="An address starts with http:// or https://.")
    with session_scope() as session:
        settings = get_settings(session, owner)
        settings.ai_provider = provider or None
        settings.ai_model = model.strip()[:120] or None
        settings.ai_base_url = address or None
        if forget_key == "1":
            settings.ai_key = None
        elif key.strip():
            settings.ai_key = key.strip()
        chosen = writing.model_for(settings)
    if provider and chosen is None:
        return redirect(PAGE, err="Saved — but say which model, as this kind of server has no default.")
    return redirect(PAGE, ok="Saved." if provider else "No model chosen: Text boxes will not write.")


@router.post(PAGE + "/try")
def try_ai(request: Request) -> JSONResponse:
    """Ask the saved model for a few words, to know it answers."""
    owner = owner_of(request)
    with session_scope() as session:
        chosen = writing.model_for(get_settings(session, owner))
    if chosen is None:
        return JSONResponse({"error": "Choose a model and save it first."}, status_code=400)
    try:
        said = writing.write(
            chosen, "Say, in one short sentence, that you are ready to write.", "[]",
            counted=(0, 0),
        )
    except writing.WritingError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"said": said[:400], "model": chosen.named})
