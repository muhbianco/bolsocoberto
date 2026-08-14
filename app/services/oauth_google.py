from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.exceptions import AuthenticationError, DomainError, ForbiddenError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def build_login_url(state: str) -> str:
    if not settings.google_client_id:
        raise DomainError("GOOGLE_CLIENT_ID não configurado.")
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{AUTH_URL}?{query}"


def new_state() -> str:
    return secrets.token_urlsafe(32)


async def exchange_code(code: str) -> str:
    secret = settings.google_client_secret.get_secret_value().strip()
    if not settings.google_client_id or not secret:
        raise DomainError("OAuth Google não configurado.")
    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token_response = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code >= 400:
            raise AuthenticationError("Google recusou o código OAuth.")
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise AuthenticationError("Google não devolveu access_token.")
        info_response = await client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_response.status_code >= 400:
            raise AuthenticationError("Não deu para ler o perfil Google.")
        email = str(info_response.json().get("email") or "").strip().lower()
        verified = info_response.json().get("email_verified")
    if not email or verified is False:
        raise AuthenticationError("E-mail Google não verificado.")
    if email not in settings.oauth_allowlist_set:
        raise ForbiddenError("Este e-mail não tem acesso ao editor.")
    return email
