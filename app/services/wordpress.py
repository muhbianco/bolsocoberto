from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PublishedPost:
    wp_post_id: int
    title: str
    slug: str
    link: str
    excerpt: str
    category_slug: str | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class PostPayload:
    title: str
    slug: str
    content: str
    excerpt: str
    category_slug: str
    tags: list[str]
    seo_title: str
    focus_keyword: str
    featured_media: int | None
    post_id: int | None


class WordPressClient:
    def __init__(self) -> None:
        self.base = settings.wp_base_url.rstrip("/")
        self.user = settings.wp_app_user.strip()
        self.password = settings.wp_app_password.get_secret_value().strip()

    def is_configured(self) -> bool:
        return bool(self.base and self.user and self.password)

    def _require_config(self) -> None:
        if not self.is_configured():
            raise DomainError("WordPress REST não configurado (WP_APP_USER / WP_APP_PASSWORD).")

    async def upload_media(
        self,
        *,
        content: bytes,
        filename: str,
        alt_text: str,
        mime: str = "image/jpeg",
    ) -> int:
        self._require_config()
        data = await self._request(
            "POST",
            "/wp-json/wp/v2/media",
            content=content,
            headers={
                "Content-Type": mime,
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
        media_id = data.get("id")
        if not isinstance(media_id, int):
            raise DomainError("WordPress não devolveu id da mídia.")
        # alt_text é o que o Discover e a acessibilidade leem; vale a segunda chamada.
        await self._request(
            "POST",
            f"/wp-json/wp/v2/media/{media_id}",
            json={"alt_text": alt_text[:300], "title": alt_text[:300]},
        )
        return media_id

    async def upsert_post(self, payload: PostPayload) -> tuple[int, str]:
        self._require_config()
        body: dict[str, Any] = {
            "title": payload.title,
            "slug": payload.slug,
            "content": payload.content,
            "excerpt": payload.excerpt,
            "status": "draft",
            "meta": {
                "rank_math_title": payload.seo_title or payload.title,
                "rank_math_description": payload.excerpt,
                "rank_math_focus_keyword": payload.focus_keyword,
            },
        }
        category_id = await self._category_id(payload.category_slug)
        if category_id is not None:
            body["categories"] = [category_id]
        if payload.tags:
            tag_ids = await self._tag_ids(payload.tags)
            if tag_ids:
                body["tags"] = tag_ids
        if payload.featured_media:
            body["featured_media"] = payload.featured_media
        if settings.wp_author_id > 0:
            body["author"] = settings.wp_author_id

        path = (
            f"/wp-json/wp/v2/posts/{payload.post_id}"
            if payload.post_id
            else "/wp-json/wp/v2/posts"
        )
        data = await self._request("POST", path, json=body)
        post_id = data.get("id")
        if not isinstance(post_id, int):
            raise DomainError("WordPress não devolveu id do rascunho.")
        return post_id, str(data.get("link") or "")

    async def list_published(self, *, max_posts: int = 300) -> list[PublishedPost]:
        self._require_config()
        categories = await self._category_slugs()
        posts: list[PublishedPost] = []
        page = 1
        while len(posts) < max_posts:
            batch = await self._request(
                "GET",
                "/wp-json/wp/v2/posts",
                params={
                    "status": "publish",
                    "per_page": 100,
                    "page": page,
                    "orderby": "date",
                    "order": "desc",
                    "_fields": "id,slug,link,title,excerpt,date_gmt,categories",
                },
            )
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if not isinstance(item, dict):
                    continue
                post_id = item.get("id")
                if not isinstance(post_id, int):
                    continue
                raw_categories = item.get("categories") or []
                slug = None
                if isinstance(raw_categories, list):
                    for term_id in raw_categories:
                        if term_id in categories:
                            slug = categories[term_id]
                            break
                posts.append(
                    PublishedPost(
                        wp_post_id=post_id,
                        title=_rendered(item.get("title")),
                        slug=str(item.get("slug") or ""),
                        link=str(item.get("link") or ""),
                        excerpt=_rendered(item.get("excerpt")),
                        category_slug=slug,
                        published_at=_parse_gmt(item.get("date_gmt")),
                    )
                )
            if len(batch) < 100:
                break
            page += 1
        return posts[:max_posts]

    async def _category_id(self, slug: str) -> int | None:
        data = await self._request("GET", "/wp-json/wp/v2/categories", params={"slug": slug})
        if isinstance(data, list) and data and isinstance(data[0].get("id"), int):
            return data[0]["id"]
        return None

    async def _category_slugs(self) -> dict[int, str]:
        data = await self._request(
            "GET",
            "/wp-json/wp/v2/categories",
            params={"per_page": 100, "_fields": "id,slug"},
        )
        if not isinstance(data, list):
            return {}
        return {
            item["id"]: str(item.get("slug") or "")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }

    async def _tag_ids(self, names: list[str]) -> list[int]:
        ids: list[int] = []
        for name in names:
            clean = name.strip()[:60]
            if not clean:
                continue
            try:
                ids.append(await self._resolve_tag(clean))
            except DomainError:
                logger.warning("Tag ignorada", extra={"tag": clean})
        return ids

    async def _resolve_tag(self, name: str) -> int:
        found = await self._request(
            "GET",
            "/wp-json/wp/v2/tags",
            params={"search": name, "per_page": 100, "_fields": "id,name"},
        )
        if isinstance(found, list):
            for item in found:
                if isinstance(item, dict) and str(item.get("name", "")).lower() == name.lower():
                    if isinstance(item.get("id"), int):
                        return item["id"]
        created = await self._request("POST", "/wp-json/wp/v2/tags", json={"name": name})
        tag_id = created.get("id") if isinstance(created, dict) else None
        if isinstance(tag_id, int):
            return tag_id
        raise DomainError(f"Não consegui criar a tag {name}.")

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base}{path}"
        timeout = httpx.Timeout(60.0, connect=8.0)
        headers = {"User-Agent": "BolsoCobertoEditor/1.0"}
        headers.update(kwargs.pop("headers", {}))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    url,
                    auth=(self.user, self.password),
                    headers=headers,
                    **kwargs,
                )
        except httpx.HTTPError as exc:
            logger.exception("Falha de rede no WP REST")
            raise DomainError("WordPress indisponível.") from exc
        if response.status_code >= 400:
            detail = _wp_error_detail(response)
            logger.error(
                "WP REST recusou",
                extra={"status": response.status_code, "path": path, "body": detail},
            )
            raise DomainError(f"WordPress recusou a chamada ({response.status_code}): {detail}")
        if not response.content:
            return {}
        return response.json()


def _wp_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "")[:200]
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("code") or payload)[:200]
    return str(payload)[:200]


def _rendered(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("rendered") or "")
    return str(value or "")


def _parse_gmt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=UTC)
    except ValueError:
        return None
