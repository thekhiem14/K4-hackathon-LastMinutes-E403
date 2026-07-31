"""B8 — compose weighted total with interaction cap; novelty related_post_ids rule."""

from __future__ import annotations

from config import (
    INTERACTION_CAP,
    WEIGHT_INTERACTION,
    WEIGHT_NOVELTY,
    WEIGHT_QUALITY,
)
from pipeline.models import GradeResult, NoveltyResult, QualityResult, RelatedPost


def content_score(novelty: float, quality: float) -> float:
    """Content-only score on the same 0–10-ish weighted scale (max 8.0)."""
    return novelty * WEIGHT_NOVELTY + quality * WEIGHT_QUALITY


def compose_total(
    *,
    novelty: float,
    quality: float,
    interaction: float,
) -> tuple[float, float, float]:
    """Return (content_part, capped_total, uncapped_total)."""
    content = content_score(novelty, quality)
    uncapped = content + interaction * WEIGHT_INTERACTION
    capped = min(uncapped, content + INTERACTION_CAP)
    return content, capped, uncapped


def enforce_novelty_related_ids(
    novelty: NoveltyResult,
    retrieved_ids: set[str],
) -> NoveltyResult:
    """Low novelty (<6) requires related_post_ids that exist in retrieval set."""
    if novelty.score >= 6:
        return novelty
    valid = [pid for pid in novelty.related_post_ids if pid in retrieved_ids]
    if valid:
        return NoveltyResult(
            score=novelty.score,
            rationale=novelty.rationale,
            related_post_ids=valid,
            needs_review=novelty.needs_review,
            review_reason=novelty.review_reason,
        )
    return NoveltyResult(
        score=novelty.score,
        rationale=novelty.rationale,
        related_post_ids=[],
        needs_review=True,
        review_reason=(
            "Điểm tính mới thấp nhưng không chỉ ra related_post_ids hợp lệ "
            "trong top bài truy hồi — không được hạ điểm; cần coach duyệt."
        ),
    )


def build_grade_payload(
    *,
    status: str,
    needs_review: bool,
    escalate_reason: str | None,
    novelty: NoveltyResult | None,
    quality: QualityResult | None,
    interaction_score: float | None,
    content: float | None,
    total: float | None,
    related_posts: list[RelatedPost],
    evidence_issues: list[str],
) -> GradeResult:
    payload = {
        "status": status,
        "needs_review": needs_review,
        "escalate_reason": escalate_reason,
        "novelty": None
        if novelty is None
        else {
            "score": novelty.score,
            "rationale": novelty.rationale,
            "related_post_ids": novelty.related_post_ids,
            "needs_review": novelty.needs_review,
            "review_reason": novelty.review_reason,
        },
        "quality": None
        if quality is None
        else {
            "score": quality.score,
            "rationale": quality.rationale,
            "axes": [
                {"name": a.name, "score": a.score, "evidence": a.evidence}
                for a in quality.axes
            ],
        },
        "interaction_score": interaction_score,
        "content_score": content,
        "total_score": total,
        "related_posts": [
            {
                "post_id": r.post_id,
                "title": r.title,
                "similarity": r.similarity,
            }
            for r in related_posts
        ],
        "evidence_issues": evidence_issues,
        "disclaimer": "Điểm bot là bản nháp — coach lab là quyết định cuối.",
    }
    return GradeResult(
        status=status,
        needs_review=needs_review,
        escalate_reason=escalate_reason,
        novelty=novelty,
        quality=quality,
        interaction_score=interaction_score,
        content_score=content,
        total_score=total,
        related_posts=related_posts,
        evidence_issues=evidence_issues,
        payload=payload,
    )
