"""B3 — embedding retrieval of top-k similar posts."""

from __future__ import annotations

import math

from db.database import Database, HistoryHit, PostRecord
from pipeline.models import RelatedPost


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def retrieve_similar(
    db: Database,
    *,
    query_vector: list[float],
    exclude_post_id: str,
    top_k: int = 8,
) -> list[RelatedPost]:
    embeddings = await db.list_all_embeddings()
    scored: list[tuple[str, float]] = []
    for post_id, vector in embeddings:
        if post_id == exclude_post_id:
            continue
        scored.append((post_id, cosine_similarity(query_vector, vector)))
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:top_k]
    posts = await db.fetch_posts_by_ids([pid for pid, _ in top])
    by_id = {p.post_id: p for p in posts}
    related: list[RelatedPost] = []
    for pid, sim in top:
        post = by_id.get(pid)
        if post is None:
            continue
        related.append(
            RelatedPost(
                post_id=post.post_id,
                title=post.title,
                body_excerpt=_excerpt(post),
                similarity=round(sim, 4),
            )
        )
    return related


def to_history_hits(related: list[RelatedPost]) -> list[HistoryHit]:
    return [
        HistoryHit(
            post_id=r.post_id,
            title=r.title,
            body=r.body_excerpt,
            author_name="",
            created_at=None,
            score=r.similarity,
        )
        for r in related
    ]


def _excerpt(post: PostRecord, limit: int = 500) -> str:
    text = f"{post.title}\n{post.body}".strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
