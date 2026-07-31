"""Forum post censor — rule prefilter + LLM allow/deny for chia-sẻ."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pipeline.prefilter import prefilter_post


class JsonLLM(Protocol):
    def generate_json(self, prompt: str, *, system: str) -> dict[str, Any]: ...


CENSOR_SYSTEM = """Bạn là kiểm duyệt viên kênh forum "chia-sẻ" của lớp học AI (Lab05).
Quyết định bài có ĐƯỢC ĐĂNG không.

Cho phép (allowed=true) khi:
- Liên quan chia sẻ kiến thức AI / ML / coding / học tập trong khóa
- Có nội dung văn bản hữu ích (không chỉ spam, toxic, NSFW, hate, quảng cáo)
- Không lạc đề hoàn toàn (meme vô nghĩa, tán gẫu không liên quan lớp)

Từ chối (allowed=false) khi:
- Spam, toxic, hate, NSFW, quấy rối
- Off-topic rõ ràng so với kênh chia sẻ học AI
- Nội dung vô nghĩa / troll / copy rác

Trả JSON đúng schema:
{"allowed": true/false, "reason": "một câu tiếng Việt ngắn giải thích"}
"""


@dataclass
class CensorResult:
    allowed: bool
    reason: str
    source: str  # rules | llm


def censor_post_rules(
    *,
    title: str,
    body: str,
    has_attachments: bool,
    attachment_only: bool,
) -> CensorResult | None:
    """Return a deny result if rules fail; None if rules pass (needs LLM)."""
    pf = prefilter_post(
        title=title,
        body=body,
        has_attachments=has_attachments,
        attachment_only=attachment_only,
    )
    if pf.ok:
        return None
    reason = pf.reason or "Bài không đủ điều kiện đăng trên chia-sẻ."
    # Soften grading-jargon for authors
    reason = reason.replace("đẩy coach duyệt tay.", "vui lòng viết lại nội dung rõ hơn.")
    reason = reason.replace("đẩy coach.", "vui lòng rút gọn / giải thích bằng lời.")
    reason = reason.replace("không đủ để chấm vòng đầu.", "quá ngắn cho kênh chia-sẻ.")
    return CensorResult(allowed=False, reason=reason, source="rules")


def censor_post_llm(
    llm: JsonLLM,
    *,
    title: str,
    body: str,
) -> CensorResult:
    prompt = (
        f"Tiêu đề: {title}\n\n"
        f"Nội dung:\n{body[:4000]}"
    )
    data = llm.generate_json(prompt, system=CENSOR_SYSTEM)
    allowed = bool(data.get("allowed"))
    reason = str(data.get("reason") or "").strip()
    if not reason:
        reason = (
            "Bài phù hợp kênh chia-sẻ."
            if allowed
            else "Bài chưa phù hợp kênh chia-sẻ."
        )
    return CensorResult(allowed=allowed, reason=reason, source="llm")


def censor_post(
    llm: JsonLLM | None,
    *,
    title: str,
    body: str,
    has_attachments: bool,
    attachment_only: bool,
) -> CensorResult:
    ruled = censor_post_rules(
        title=title,
        body=body,
        has_attachments=has_attachments,
        attachment_only=attachment_only,
    )
    if ruled is not None:
        return ruled
    if llm is None:
        return CensorResult(
            allowed=True,
            reason="Bỏ qua LLM (chưa cấu hình API) — cho phép tạm.",
            source="rules",
        )
    return censor_post_llm(llm, title=title, body=body)
