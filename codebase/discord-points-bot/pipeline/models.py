"""Shared dataclasses for the grading pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InteractionMeta:
    reaction_count: int = 0
    reply_count: int = 0
    unique_repliers: int = 0
    reply_depth: int = 0
    raw_engagement: float = 0.0


@dataclass
class NormalizedPost:
    post_id: str
    channel_id: str
    author_id: str
    author_name: str
    title: str
    body: str
    created_at: str | None
    week_key: str
    url: str | None = None
    interaction: InteractionMeta = field(default_factory=InteractionMeta)


@dataclass
class RelatedPost:
    post_id: str
    title: str
    body_excerpt: str
    similarity: float


@dataclass
class QualityAxis:
    name: str
    score: float
    evidence: list[str]


@dataclass
class NoveltyResult:
    score: float
    rationale: str
    related_post_ids: list[str]
    needs_review: bool = False
    review_reason: str | None = None


@dataclass
class QualityResult:
    axes: list[QualityAxis]
    score: float
    rationale: str


@dataclass
class GradeResult:
    status: str  # graded | escalated | rejected
    needs_review: bool
    escalate_reason: str | None
    novelty: NoveltyResult | None
    quality: QualityResult | None
    interaction_score: float | None
    content_score: float | None
    total_score: float | None
    related_posts: list[RelatedPost] = field(default_factory=list)
    evidence_issues: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
