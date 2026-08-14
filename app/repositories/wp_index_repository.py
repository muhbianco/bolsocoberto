from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.job import WpPostIndex
from app.services.wordpress import PublishedPost


class WpIndexRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def all_posts(self) -> list[WpPostIndex]:
        result = await self.session.execute(
            select(WpPostIndex).order_by(WpPostIndex.published_at.desc())
        )
        return list(result.scalars().all())

    async def is_stale(self, ttl_minutes: int) -> bool:
        result = await self.session.execute(
            select(WpPostIndex.synced_at)
            .order_by(WpPostIndex.synced_at.desc())
            .limit(1)
        )
        newest = result.scalar_one_or_none()
        if newest is None:
            return True
        return utcnow() - newest > timedelta(minutes=ttl_minutes)

    async def replace_all(self, posts: list[PublishedPost]) -> int:
        existing = {row.wp_post_id: row for row in await self.all_posts()}
        stamp = utcnow()
        for post in posts:
            row = existing.get(post.wp_post_id)
            if row is None:
                row = WpPostIndex(wp_post_id=post.wp_post_id, title="", slug="", link="")
                self.session.add(row)
            row.title = post.title
            row.slug = post.slug
            row.link = post.link
            row.excerpt = post.excerpt
            row.category_slug = post.category_slug
            row.published_at = post.published_at
            row.synced_at = stamp
        await self.session.flush()
        return len(posts)
