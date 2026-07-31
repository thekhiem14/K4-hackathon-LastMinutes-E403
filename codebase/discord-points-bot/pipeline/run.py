"""End-to-end grading pipeline B1→B8."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ai.gemini_client import GeminiClient
from config import RETRIEVAL_TOP_K
from db.database import Database, PostRecord
from pipeline.interaction import interaction_score_for_post
from pipeline.models import GradeResult, NormalizedPost
from pipeline.novelty import grade_novelty
from pipeline.prefilter import prefilter_post
from pipeline.quality import grade_quality
from pipeline.retrieve import retrieve_similar
from pipeline.score import (
    build_grade_payload,
    compose_total,
    enforce_novelty_related_ids,
)
from pipeline.verify import verify_quality_evidence

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_grading_pipeline(
    *,
    db: Database,
    gemini: GeminiClient,
    post: NormalizedPost,
    has_attachments: bool = False,
    attachment_only: bool = False,
) -> GradeResult:
    # B1
    gate = prefilter_post(
        title=post.title,
        body=post.body,
        has_attachments=has_attachments,
        attachment_only=attachment_only,
    )
    if not gate.ok:
        result = build_grade_payload(
            status=gate.status,
            needs_review=True,
            escalate_reason=gate.reason,
            novelty=None,
            quality=None,
            interaction_score=None,
            content=None,
            total=None,
            related_posts=[],
            evidence_issues=[],
        )
        await _persist(db, post, result, vector=None)
        return result

    # Persist post early so novelty corpus grows
    await _upsert_post(db, post)

    # B3 embed + retrieve
    embed_text = f"{post.title}\n\n{post.body}"
    try:
        vector = gemini.embed(embed_text)
    except Exception:
        logger.exception("Embedding failed")
        result = build_grade_payload(
            status="escalated",
            needs_review=True,
            escalate_reason="Lỗi embedding — đẩy coach.",
            novelty=None,
            quality=None,
            interaction_score=None,
            content=None,
            total=None,
            related_posts=[],
            evidence_issues=[],
        )
        await _persist(db, post, result, vector=None)
        return result

    await db.save_embedding(post.post_id, gemini.embed_model, vector, _now())
    await db.commit()

    related = await retrieve_similar(
        db,
        query_vector=vector,
        exclude_post_id=post.post_id,
        top_k=RETRIEVAL_TOP_K,
    )

    # B4 novelty
    try:
        novelty = await grade_novelty(gemini, post, related)
    except Exception:
        logger.exception("Novelty grading failed")
        result = build_grade_payload(
            status="escalated",
            needs_review=True,
            escalate_reason="Lỗi LLM tính mới — đẩy coach.",
            novelty=None,
            quality=None,
            interaction_score=None,
            content=None,
            total=None,
            related_posts=related,
            evidence_issues=[],
        )
        await _persist(db, post, result, vector=vector)
        return result

    retrieved_ids = {r.post_id for r in related}
    novelty = enforce_novelty_related_ids(novelty, retrieved_ids)

    # B5 quality
    try:
        quality = await grade_quality(gemini, post)
    except Exception:
        logger.exception("Quality grading failed")
        result = build_grade_payload(
            status="escalated",
            needs_review=True,
            escalate_reason="Lỗi LLM chất lượng — đẩy coach.",
            novelty=novelty,
            quality=None,
            interaction_score=None,
            content=None,
            total=None,
            related_posts=related,
            evidence_issues=[],
        )
        await _persist(db, post, result, vector=vector)
        return result

    # B7 evidence check
    evidence = verify_quality_evidence(post.body, post.title, quality)
    quality = evidence.cleaned
    needs_review = novelty.needs_review or (not evidence.ok)
    review_reasons: list[str] = []
    if novelty.review_reason:
        review_reasons.append(novelty.review_reason)
    if evidence.issues:
        review_reasons.extend(evidence.issues)

    # B6 interaction
    peers = await db.list_posts_for_week(post.week_key)
    interaction = interaction_score_for_post(
        reaction_count=post.interaction.reaction_count,
        reply_count=post.interaction.reply_count,
        unique_repliers=post.interaction.unique_repliers,
        reply_depth=post.interaction.reply_depth,
        week_peers=peers,
    )

    # If novelty was invalidated (needs_review due to missing related ids),
    # do not apply the low novelty score — escalate draft for coach.
    if novelty.needs_review and novelty.score < 6 and not novelty.related_post_ids:
        result = build_grade_payload(
            status="escalated",
            needs_review=True,
            escalate_reason="; ".join(review_reasons) or novelty.review_reason,
            novelty=novelty,
            quality=quality,
            interaction_score=interaction,
            content=None,
            total=None,
            related_posts=related,
            evidence_issues=evidence.issues,
        )
        await _persist(db, post, result, vector=vector)
        return result

    content, total, _uncapped = compose_total(
        novelty=novelty.score,
        quality=quality.score,
        interaction=interaction,
    )

    if not evidence.ok:
        needs_review = True
        review_reasons.append("Evidence không verify được — coach cần duyệt.")

    result = build_grade_payload(
        status="graded",
        needs_review=needs_review,
        escalate_reason="; ".join(review_reasons) if needs_review else None,
        novelty=novelty,
        quality=quality,
        interaction_score=round(interaction, 2),
        content=round(content, 2),
        total=round(total, 2),
        related_posts=related,
        evidence_issues=evidence.issues,
    )
    await _persist(db, post, result, vector=vector)
    return result


async def _upsert_post(db: Database, post: NormalizedPost) -> None:
    record = PostRecord(
        post_id=post.post_id,
        channel_id=post.channel_id,
        author_id=post.author_id,
        author_name=post.author_name,
        title=post.title,
        body=post.body,
        created_at=post.created_at,
        reaction_count=post.interaction.reaction_count,
        reply_count=post.interaction.reply_count,
        unique_repliers=post.interaction.unique_repliers,
        reply_depth=post.interaction.reply_depth,
        week_key=post.week_key,
    )
    await db.upsert_post(record, _now())
    await db.commit()


async def _persist(
    db: Database,
    post: NormalizedPost,
    result: GradeResult,
    vector: list[float] | None,
) -> None:
    await _upsert_post(db, post)
    if vector is not None:
        # embedding may already be saved; ignore if empty
        pass
    await db.save_grade(
        post_id=post.post_id,
        status=result.status,
        novelty_score=None if result.novelty is None else result.novelty.score,
        quality_score=None if result.quality is None else result.quality.score,
        interaction_score=result.interaction_score,
        content_score=result.content_score,
        total_score=result.total_score,
        needs_review=result.needs_review,
        escalate_reason=result.escalate_reason,
        related_post_ids=[]
        if result.novelty is None
        else result.novelty.related_post_ids,
        evidence={
            "issues": result.evidence_issues,
            "axes": []
            if result.quality is None
            else [
                {"name": a.name, "score": a.score, "evidence": a.evidence}
                for a in result.quality.axes
            ],
        },
        grade_payload=result.payload,
        created_at=_now(),
    )
