"""B1 — rule-based prefilter (prefer refuse / escalate). No LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import MIN_POST_CHARS

CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
URL_ONLY_RE = re.compile(r"^(?:\s*https?://\S+\s*)+$", re.IGNORECASE)


@dataclass
class PrefilterResult:
    ok: bool
    status: str  # pass | escalated | rejected
    reason: str | None = None


def prefilter_post(
    *,
    title: str,
    body: str,
    has_attachments: bool,
    attachment_only: bool,
) -> PrefilterResult:
    text = f"{title}\n{body}".strip()
    if not text:
        return PrefilterResult(False, "escalated", "Bài trống — đẩy coach duyệt tay.")

    if attachment_only or (has_attachments and len(body.strip()) < MIN_POST_CHARS):
        return PrefilterResult(
            False,
            "escalated",
            "v0.1 không chấm ảnh/video/file đính kèm (hoặc bài gần như chỉ có media).",
        )

    if URL_ONLY_RE.match(body.strip() or title.strip()):
        return PrefilterResult(
            False,
            "escalated",
            "Bài chỉ chứa link — thiếu nội dung văn bản để chấm.",
        )

    code_chars = sum(len(m.group(0)) for m in CODE_FENCE_RE.finditer(body))
    if body and code_chars / max(len(body), 1) > 0.6:
        return PrefilterResult(
            False,
            "escalated",
            "v0.1 không chấm code dump — đẩy coach.",
        )

    plain = CODE_FENCE_RE.sub(" ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) < MIN_POST_CHARS:
        return PrefilterResult(
            False,
            "escalated",
            f"Bài quá ngắn (<{MIN_POST_CHARS} ký tự văn bản) — không đủ để chấm vòng đầu.",
        )

    return PrefilterResult(True, "pass")
