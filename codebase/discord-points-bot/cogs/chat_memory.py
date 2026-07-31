"""In-memory chat history with a hard byte budget (default 1 MiB total)."""

from __future__ import annotations

from collections import defaultdict, deque


class ConversationMemory:
    """Stores user/assistant turns across users; trims oldest turns when over budget."""

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        self.max_bytes = max_bytes
        self._histories: dict[int, list[tuple[str, str]]] = defaultdict(list)
        self._order: deque[tuple[int, int]] = deque()  # (user_id, turn_bytes) FIFO
        self._bytes = 0

    @property
    def used_bytes(self) -> int:
        return self._bytes

    def history(self, user_id: int) -> list[dict[str, str]]:
        return [
            {"role": role, "content": content}
            for role, content in self._histories.get(user_id, [])
        ]

    def append(self, user_id: int, role: str, content: str) -> None:
        content = (content or "").strip()
        if not content:
            return
        size = _turn_bytes(role, content)
        # Single turn larger than budget: keep only a truncated copy
        if size > self.max_bytes:
            content = _truncate_to_bytes(content, max(0, self.max_bytes - _turn_bytes(role, "")))
            size = _turn_bytes(role, content)
            self.clear()
        self._histories[user_id].append((role, content))
        self._order.append((user_id, size))
        self._bytes += size
        self._trim()

    def clear(self) -> None:
        self._histories.clear()
        self._order.clear()
        self._bytes = 0

    def _trim(self) -> None:
        while self._bytes > self.max_bytes and self._order:
            uid, size = self._order.popleft()
            turns = self._histories.get(uid)
            if not turns:
                continue
            turns.pop(0)
            self._bytes = max(0, self._bytes - size)
            if not turns:
                self._histories.pop(uid, None)


def _turn_bytes(role: str, content: str) -> int:
    return len(role.encode("utf-8")) + len(content.encode("utf-8"))


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
