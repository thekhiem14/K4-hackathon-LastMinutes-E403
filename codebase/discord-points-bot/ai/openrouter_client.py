"""OpenRouter client — OpenAI-compatible chat + embeddings."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    """Same surface as the old GeminiClient: embed() + generate_json()."""

    def __init__(
        self,
        api_key: str,
        *,
        chat_model: str,
        embed_model: str,
    ) -> None:
        self.api_key = api_key
        self.chat_model = chat_model
        self.embed_model = embed_model

    def embed(self, text: str) -> list[float]:
        text = text.strip()
        if not text:
            return []
        payload = {
            "model": self.embed_model,
            "input": text[:8000],
        }
        data = self._post("/embeddings", payload)
        items = data.get("data") or []
        if not items:
            raise RuntimeError(f"Empty embedding response: {data!r}")
        return list(items[0]["embedding"])

    def generate_json(self, prompt: str, *, system: str) -> dict[str, Any]:
        payload = {
            "model": self.chat_model,
            "temperature": 0.2,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        data = self._post("/chat/completions", payload)
        try:
            raw = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected chat response: {data!r}") from exc
        return _parse_json((raw or "").strip())

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{OPENROUTER_BASE}{path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/last-minutes-bot",
                "X-Title": "Discord AI Grading Bot",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            logger.error("OpenRouter HTTP %s: %s", exc.code, err_body[:500])
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {err_body[:300]}") from exc


# Back-compat alias used by pipeline modules
GeminiClient = OpenRouterClient


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"Model did not return JSON: {raw[:300]}")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data
