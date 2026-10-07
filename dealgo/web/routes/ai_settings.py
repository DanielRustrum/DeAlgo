"""Settings → AI model: which language model a Text box writes with.

One account's own choice, like its theme. The key is a secret: kept, never
put back into the page — a blank field means "keep the one there is" — and
never in a backup.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from sqlalchemy import select
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ...db import get_settings, session_scope
from ...models import Channel
from ...services import algorithm, writing
from ...services.scope import owned
from ..responses import owner_of, redirect, render

router = APIRouter()

PAGE = "/settings/ai"


@router.get(PAGE, response_class=HTMLResponse)
def ai_page(request: Request) -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        settings = get_settings(session, owner)
        names = {
            channel.id: channel.title or channel.channel_id
            for channel in session.scalars(owned(select(Channel), Channel, owner))
        }
        signals = []
        for name, label in algorithm.SIGNALS:
            model = algorithm.learned(session, owner, name)
            toward, away = algorithm.leanings(model, names) if model is not None else ([], [])
            signals.append({"name": name, "label": label, "model": model,
                            "toward": toward, "away": away})
        return render(request, "ai_settings.html", {
            "site_allows": algorithm.site_allows(session),
            "algorithm_on": settings.algorithm_on,
            "algorithm_days": settings.algorithm_days,
            "algorithm_min": settings.algorithm_min,
            "algorithm_every": settings.algorithm_every,
            "every": algorithm.EVERY,
            "signals": signals,
            "seen": algorithm.counts(session, owner),
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


@router.post(PAGE + "/algorithm")
def save_algorithm(
    request: Request,
    on: str = Form(""),
    days: str = Form("90"),
    least: str = Form("20"),
    every: str = Form("daily"),
) -> Response:
    owner = owner_of(request)
    if every not in dict(algorithm.EVERY):
        return redirect(PAGE + "#algorithm", err="That is not how often it can learn.")
    with session_scope() as session:
        settings = get_settings(session, owner)
        settings.algorithm_on = on == "1"
        settings.algorithm_days = max(7, min(730, int(days) if days.isdigit() else 90))
        settings.algorithm_min = max(5, min(5000, int(least) if least.isdigit() else 20))
        settings.algorithm_every = every
    return redirect(PAGE + "#algorithm", ok="Saved.")


@router.post(PAGE + "/algorithm/learn")
def learn_now(request: Request) -> Response:
    """Learn again now, from everything there is."""
    owner = owner_of(request)
    with session_scope() as session:
        settings = get_settings(session, owner)
        if not algorithm.runs_for(session, settings):
            return redirect(PAGE + "#algorithm", err="Your algorithm is off, so there is nothing to learn.")
        learned = algorithm.train_all(session, owner, settings)
    done = [name for name, model in learned.items() if model is not None]
    if not done:
        return redirect(PAGE + "#algorithm",
                        err="Not enough yet: open and pass over more in Focus mode first.")
    return redirect(PAGE + "#algorithm", ok="Learned again: " + ", ".join(done) + ".")


@router.post(PAGE + "/algorithm/forget")
def forget_all(request: Request) -> Response:
    """Forget everything it saw and learned."""
    owner = owner_of(request)
    with session_scope() as session:
        algorithm.forget(session, owner)
    return redirect(PAGE + "#algorithm", ok="Forgotten: it starts again from nothing.")
