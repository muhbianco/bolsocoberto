from __future__ import annotations

import secrets

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.core.exceptions import AuthenticationError
from app.services import oauth_google

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    state = oauth_google.new_state()
    request.session["oauth_state"] = state
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return RedirectResponse(oauth_google.build_login_url(state), status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    if error:
        raise AuthenticationError("Login Google cancelado.")
    expected = request.session.get("oauth_state")
    if not code or not state or not expected or state != expected:
        raise AuthenticationError("State OAuth inválido.")
    request.session.pop("oauth_state", None)
    email = await oauth_google.exchange_code(code)
    request.session["email"] = email
    request.session["csrf"] = secrets.token_urlsafe(32)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=303)
