from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.logging import get_logger

logger = get_logger(__name__)


class WordPressClient:
    def __init__(self) -> None:
        self.base = settings.wp_base_url.rstrip("/")
        self.user = settings.wp_app_user.strip()
        self.password = settings.wp_app_password.get_secret_value().strip()

    def is_configured(self) -> bool:
        return bool(self.base and self.user and self.password)

    async def create_draft(
        self,
        *,
        title: str,
        slug: str,
        content: str,
        excerpt: str,
        category_slug: str,
    ) -> int:
        if not self.is_configured():
            raise DomainError("WordPress REST não configurado (WP_APP_USER / WP_APP_PASSWORD).")
        category_id = await self._category_id(category_slug)
        payload: dict[str, Any] = {
            "title": title,
            "slug": slug,
            "content": content,
            "excerpt": excerpt,
            "status": "draft",
        }
        if category_id is not None:
            payload["categories"] = [category_id]
        data = await self._request("POST", "/wp-json/wp/v2/posts", json=payload)
        post_id = data.get("id")
        if not isinstance(post_id, int):
            raise DomainError("WordPress não devolveu id do rascunho.")
        return post_id

    async def _category_id(self, slug: str) -> int | None:
        data = await self._request("GET", "/wp-json/wp/v2/categories", params={"slug": slug})
        if isinstance(data, list) and data and isinstance(data[0].get("id"), int):
            return data[0]["id"]
        return None

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base}{path}"
        timeout = httpx.Timeout(30.0, connect=8.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    url,
                    auth=(self.user, self.password),
                    headers={"User-Agent": "BolsoCobertoEditor/1.0"},
                    **kwargs,
                )
        except httpx.HTTPError as exc:
            logger.exception("Falha de rede no WP REST")
            raise DomainError("WordPress indisponível.") from exc
        if response.status_code >= 400:
            logger.error(
                "WP REST recusou",
                extra={"status": response.status_code, "body": (response.text or "")[:400]},
            )
            raise DomainError("WordPress recusou o rascunho.")
        return response.json()
