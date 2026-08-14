from __future__ import annotations

import hmac

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import AuthenticationError


async def db_session(session: AsyncSession = Depends(get_session)) -> AsyncSession:
    return session


def current_email(request: Request) -> str | None:
    email = request.session.get("email")
    if isinstance(email, str) and email:
        return email
    return None


def require_email(request: Request) -> str:
    email = current_email(request)
    if not email:
        raise AuthenticationError("Faça login.")
    return email


def require_email_html(request: Request) -> str:
    email = current_email(request)
    if not email:
        raise LoginRedirect()
    return email


class LoginRedirect(Exception):
    pass


async def login_redirect_handler(_request: Request, _exc: LoginRedirect) -> RedirectResponse:
    return RedirectResponse("/auth/login", status_code=303)


def csrf_ok(request: Request, token: str) -> bool:
    expected = request.session.get("csrf")
    if not isinstance(expected, str) or not token:
        return False
    return hmac.compare_digest(expected, token)
