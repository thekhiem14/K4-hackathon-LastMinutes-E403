"""B7 — evidence quotes must be real substrings of the post body."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.models import QualityResult


@dataclass
class EvidenceCheck:
    ok: bool
    cleaned: QualityResult
    issues: list[str]


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_in_source(quote: str, source: str) -> bool:
    q = quote.strip()
    if len(q) < 8:
        return False
    if q in source:
        return True
    return _normalize_ws(q) in _normalize_ws(source)


def verify_quality_evidence(body: str, title: str, quality: QualityResult) -> EvidenceCheck:
    source = f"{title}\n{body}"
    issues: list[str] = []
    cleaned_axes = []
    for axis in quality.axes:
        valid = [q for q in axis.evidence if quote_in_source(q, source)]
        invalid = [q for q in axis.evidence if q not in valid]
        for bad in invalid:
            issues.append(f"[{axis.name}] evidence không nằm trong bài: {bad[:80]}")
        if not valid:
            issues.append(f"[{axis.name}] thiếu evidence nguyên văn hợp lệ")
        cleaned_axes.append(
            type(axis)(name=axis.name, score=axis.score, evidence=valid)
        )

    cleaned = QualityResult(
        axes=cleaned_axes,
        score=quality.score,
        rationale=quality.rationale,
    )
    # Recalculate mean only over axes that still have evidence; flag review if any missing.
    scored = [a.score for a in cleaned_axes if a.evidence]
    if scored:
        cleaned.score = sum(scored) / len(scored)
    ok = all(a.evidence for a in cleaned_axes)
    return EvidenceCheck(ok=ok, cleaned=cleaned, issues=issues)
