"""SQLite persistence: posts history, embeddings, and grade drafts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts_history (
    post_id         TEXT PRIMARY KEY,
    channel_id      TEXT NOT NULL,
    author_id       TEXT NOT NULL,
    author_name     TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    created_at      TEXT,
    reaction_count  INTEGER NOT NULL DEFAULT 0,
    reply_count     INTEGER NOT NULL DEFAULT 0,
    unique_repliers INTEGER NOT NULL DEFAULT 0,
    reply_depth     INTEGER NOT NULL DEFAULT 0,
    week_key        TEXT,
    synced_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    post_id     TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (post_id) REFERENCES posts_history(post_id)
);

CREATE TABLE IF NOT EXISTS grades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         TEXT NOT NULL,
    status          TEXT NOT NULL,
    novelty_score   REAL,
    quality_score   REAL,
    interaction_score REAL,
    content_score   REAL,
    total_score     REAL,
    needs_review    INTEGER NOT NULL DEFAULT 0,
    escalate_reason TEXT,
    related_post_ids TEXT,
    evidence_json   TEXT,
    grade_json      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (post_id) REFERENCES posts_history(post_id)
);

CREATE TABLE IF NOT EXISTS comments (
    message_id  TEXT PRIMARY KEY,
    post_id     TEXT NOT NULL,
    author_id   TEXT NOT NULL,
    author_name TEXT NOT NULL,
    created_at  TEXT,
    synced_at   TEXT NOT NULL,
    FOREIGN KEY (post_id) REFERENCES posts_history(post_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,
    posts_synced  INTEGER NOT NULL DEFAULT 0,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_week ON posts_history(week_key);
CREATE INDEX IF NOT EXISTS idx_grades_post ON grades(post_id);
CREATE INDEX IF NOT EXISTS idx_comments_author ON comments(author_id);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
"""


@dataclass
class PostRecord:
    post_id: str
    channel_id: str
    author_id: str
    author_name: str
    title: str
    body: str
    created_at: str | None
    reaction_count: int = 0
    reply_count: int = 0
    unique_repliers: int = 0
    reply_depth: int = 0
    week_key: str | None = None


@dataclass
class CommentRecord:
    message_id: str
    post_id: str
    author_id: str
    author_name: str
    created_at: str | None


@dataclass
class UserGradeStats:
    """Aggregated AI rubric scores for a member (averages across graded posts)."""

    user_id: str
    display_name: str
    graded_posts: int
    avg_novelty: float
    avg_quality: float
    avg_interaction: float
    avg_total: float
    needs_review_posts: int = 0
    rank: int | None = None


@dataclass
class HistoryHit:
    post_id: str
    title: str
    body: str
    author_name: str
    created_at: str | None
    score: float


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def begin_sync(self, started_at: str) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO sync_runs (started_at, status) VALUES (?, 'running')",
            (started_at,),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def finish_sync(
        self,
        run_id: int,
        *,
        finished_at: str,
        status: str,
        posts_synced: int,
        error: str | None = None,
    ) -> None:
        await self.conn.execute(
            """
            UPDATE sync_runs
            SET finished_at = ?, status = ?, posts_synced = ?, error = ?
            WHERE id = ?
            """,
            (finished_at, status, posts_synced, error, run_id),
        )
        await self.conn.commit()

    async def upsert_post(self, post: PostRecord, synced_at: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO posts_history (
                post_id, channel_id, author_id, author_name, title, body, created_at,
                reaction_count, reply_count, unique_repliers, reply_depth, week_key, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                author_id = excluded.author_id,
                author_name = excluded.author_name,
                title = excluded.title,
                body = excluded.body,
                created_at = excluded.created_at,
                reaction_count = excluded.reaction_count,
                reply_count = excluded.reply_count,
                unique_repliers = excluded.unique_repliers,
                reply_depth = excluded.reply_depth,
                week_key = excluded.week_key,
                synced_at = excluded.synced_at
            """,
            (
                post.post_id,
                post.channel_id,
                post.author_id,
                post.author_name,
                post.title,
                post.body,
                post.created_at,
                post.reaction_count,
                post.reply_count,
                post.unique_repliers,
                post.reply_depth,
                post.week_key,
                synced_at,
            ),
        )

    async def replace_comments_for_post(
        self,
        post_id: str,
        comments: list[CommentRecord],
        synced_at: str,
    ) -> int:
        await self.conn.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        if comments:
            await self.conn.executemany(
                """
                INSERT INTO comments (message_id, post_id, author_id, author_name, created_at, synced_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.message_id,
                        c.post_id,
                        c.author_id,
                        c.author_name,
                        c.created_at,
                        synced_at,
                    )
                    for c in comments
                ],
            )
        return len(comments)

    async def last_successful_sync(self) -> str | None:
        cursor = await self.conn.execute(
            """
            SELECT finished_at FROM sync_runs
            WHERE status = 'ok' AND finished_at IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return None if row is None else row["finished_at"]

    async def fetch_leaderboard(self, *, limit: int | None = None) -> list[UserGradeStats]:
        """Rank members by average AI total_score (latest graded draft per post)."""
        sql = """
        WITH latest AS (
            SELECT g.*
            FROM grades g
            INNER JOIN (
                SELECT post_id, MAX(id) AS max_id
                FROM grades
                WHERE status = 'graded' AND total_score IS NOT NULL
                GROUP BY post_id
            ) t ON g.id = t.max_id
        ),
        per_user AS (
            SELECT
                p.author_id AS user_id,
                MAX(p.author_name) AS display_name,
                COUNT(*) AS graded_posts,
                AVG(l.novelty_score) AS avg_novelty,
                AVG(l.quality_score) AS avg_quality,
                AVG(l.interaction_score) AS avg_interaction,
                AVG(l.total_score) AS avg_total,
                SUM(CASE WHEN l.needs_review = 1 THEN 1 ELSE 0 END) AS needs_review_posts
            FROM latest l
            JOIN posts_history p ON p.post_id = l.post_id
            GROUP BY p.author_id
        )
        SELECT * FROM per_user
        ORDER BY avg_total DESC, graded_posts DESC, display_name COLLATE NOCASE ASC
        """
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        cursor = await self.conn.execute(sql)
        rows = await cursor.fetchall()
        return [
            UserGradeStats(
                user_id=row["user_id"],
                display_name=row["display_name"] or row["user_id"],
                graded_posts=row["graded_posts"],
                avg_novelty=float(row["avg_novelty"] or 0),
                avg_quality=float(row["avg_quality"] or 0),
                avg_interaction=float(row["avg_interaction"] or 0),
                avg_total=float(row["avg_total"] or 0),
                needs_review_posts=int(row["needs_review_posts"] or 0),
                rank=idx,
            )
            for idx, row in enumerate(rows, start=1)
        ]

    async def fetch_user_stats(self, user_id: str) -> UserGradeStats | None:
        board = await self.fetch_leaderboard()
        for entry in board:
            if entry.user_id == user_id:
                return entry
        return None

    async def save_embedding(
        self,
        post_id: str,
        model: str,
        vector: list[float],
        updated_at: str,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO embeddings (post_id, model, vector_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                model = excluded.model,
                vector_json = excluded.vector_json,
                updated_at = excluded.updated_at
            """,
            (post_id, model, json.dumps(vector), updated_at),
        )

    async def save_grade(
        self,
        *,
        post_id: str,
        status: str,
        novelty_score: float | None,
        quality_score: float | None,
        interaction_score: float | None,
        content_score: float | None,
        total_score: float | None,
        needs_review: bool,
        escalate_reason: str | None,
        related_post_ids: list[str],
        evidence: dict[str, Any],
        grade_payload: dict[str, Any],
        created_at: str,
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO grades (
                post_id, status, novelty_score, quality_score, interaction_score,
                content_score, total_score, needs_review, escalate_reason,
                related_post_ids, evidence_json, grade_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                status,
                novelty_score,
                quality_score,
                interaction_score,
                content_score,
                total_score,
                int(needs_review),
                escalate_reason,
                json.dumps(related_post_ids),
                json.dumps(evidence),
                json.dumps(grade_payload, ensure_ascii=False),
                created_at,
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def commit(self) -> None:
        await self.conn.commit()

    async def get_post(self, post_id: str) -> PostRecord | None:
        cursor = await self.conn.execute(
            "SELECT * FROM posts_history WHERE post_id = ?",
            (post_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_post(row)

    async def list_posts_for_week(self, week_key: str) -> list[PostRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM posts_history WHERE week_key = ?",
            (week_key,),
        )
        rows = await cursor.fetchall()
        return [_row_to_post(r) for r in rows]

    async def list_all_embeddings(self) -> list[tuple[str, list[float]]]:
        cursor = await self.conn.execute("SELECT post_id, vector_json FROM embeddings")
        rows = await cursor.fetchall()
        out: list[tuple[str, list[float]]] = []
        for row in rows:
            out.append((row["post_id"], json.loads(row["vector_json"])))
        return out

    async def posts_missing_grades(self) -> list[PostRecord]:
        """Posts in history that have never received a successful graded total."""
        cursor = await self.conn.execute(
            """
            SELECT p.*
            FROM posts_history p
            WHERE length(trim(p.body)) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM grades g
                  WHERE g.post_id = p.post_id
                    AND g.status = 'graded'
                    AND g.total_score IS NOT NULL
              )
            ORDER BY p.created_at ASC
            """
        )
        rows = await cursor.fetchall()
        return [_row_to_post(r) for r in rows]

    async def posts_missing_embeddings(self) -> list[PostRecord]:
        cursor = await self.conn.execute(
            """
            SELECT p.* FROM posts_history p
            LEFT JOIN embeddings e ON e.post_id = p.post_id
            WHERE e.post_id IS NULL AND length(trim(p.body)) > 0
            """
        )
        rows = await cursor.fetchall()
        return [_row_to_post(r) for r in rows]

    async def fetch_posts_by_ids(self, post_ids: list[str]) -> list[PostRecord]:
        if not post_ids:
            return []
        placeholders = ",".join("?" for _ in post_ids)
        cursor = await self.conn.execute(
            f"SELECT * FROM posts_history WHERE post_id IN ({placeholders})",
            post_ids,
        )
        rows = await cursor.fetchall()
        by_id = {r["post_id"]: _row_to_post(r) for r in rows}
        return [by_id[pid] for pid in post_ids if pid in by_id]


def _row_to_post(row: aiosqlite.Row) -> PostRecord:
    return PostRecord(
        post_id=row["post_id"],
        channel_id=row["channel_id"],
        author_id=row["author_id"],
        author_name=row["author_name"],
        title=row["title"],
        body=row["body"],
        created_at=row["created_at"],
        reaction_count=row["reaction_count"] or 0,
        reply_count=row["reply_count"] or 0,
        unique_repliers=row["unique_repliers"] or 0,
        reply_depth=row["reply_depth"] or 0,
        week_key=row["week_key"],
    )
