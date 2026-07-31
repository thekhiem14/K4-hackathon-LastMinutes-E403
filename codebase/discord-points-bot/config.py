"""Runtime configuration for the AI grading bot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Rubric weights (novelty 40% + quality 40% + interaction 20%)
WEIGHT_NOVELTY = 0.40
WEIGHT_QUALITY = 0.40
WEIGHT_INTERACTION = 0.20
INTERACTION_CAP = 1.5

# OpenRouter model slugs
OPENROUTER_CHAT_MODEL = "google/gemini-2.5-flash"
OPENROUTER_EMBED_MODEL = "openai/text-embedding-3-small"
RETRIEVAL_TOP_K = 8
MIN_POST_CHARS = 80


@dataclass(frozen=True)
class Settings:
    token: str
    guild_id: int
    forum_channel_id: int
    openrouter_api_key: str | None
    sync_interval_minutes: int
    database_path: Path
    chat_model: str
    embed_model: str


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("Missing DISCORD_TOKEN. Copy .env.example → .env and fill it in.")

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip() or None
    sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "3"))
    db_path = Path(os.getenv("DATABASE_PATH", "./data/grades.db")).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        token=token,
        guild_id=_require_int("GUILD_ID"),
        forum_channel_id=_require_int("FORUM_CHANNEL_ID"),
        openrouter_api_key=openrouter_api_key,
        sync_interval_minutes=max(1, sync_interval),
        database_path=db_path,
        chat_model=os.getenv("OPENROUTER_CHAT_MODEL", OPENROUTER_CHAT_MODEL).strip(),
        embed_model=os.getenv("OPENROUTER_EMBED_MODEL", OPENROUTER_EMBED_MODEL).strip(),
    )


def _require_int(name: str) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise SystemExit(f"Missing {name}. Copy .env.example → .env and fill it in.")
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer snowflake ID.") from exc
