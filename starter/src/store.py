"""PostgreSQL + pgvector store. Exact (sequential-scan) cosine search, no ANN index."""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk

# Only these metadata fields may be used as filters; they map to real columns, and the
# values are always passed as SQL parameters.
FILTER_COLUMNS = {"chapter": "chapter", "page": "page", "document_id": "document_id"}


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in v) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive int")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, autocommit=False)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    strategy     text        NOT NULL,
                    chunk_id     text        NOT NULL,
                    document_id  text        NOT NULL,
                    source       text        NOT NULL,
                    page         integer     NOT NULL,
                    chapter      integer     NOT NULL,
                    char_start   integer     NOT NULL,
                    char_end     integer     NOT NULL,
                    text         text        NOT NULL,
                    content_hash text        NOT NULL,
                    metadata     jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding    vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_filter_idx ON chunks (strategy, chapter, page)")
            row = conn.execute(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            ).fetchone()
            if row and row[0] != self.dimensions:
                raise RuntimeError(
                    f"Table 'chunks' stores {row[0]}-dim vectors but the embedder produces "
                    f"{self.dimensions}. Use a new table/database or drop the table deliberately.")

    def existing_hashes(self, strategy: str) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT chunk_id, content_hash FROM chunks WHERE strategy = %s", (strategy,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def count(self, strategy: str | None = None) -> int:
        with self._connect() as conn:
            if strategy is None:
                return conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
            return conn.execute("SELECT count(*) FROM chunks WHERE strategy = %s", (strategy,)).fetchone()[0]

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               content_hashes: list[str] | None = None) -> None:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if content_hashes is not None and len(content_hashes) != len(chunks):
            raise ValueError("content_hashes length mismatch")
        for v in vectors:
            if len(v) != self.dimensions:
                raise ValueError(f"vector has {len(v)} dims, expected {self.dimensions}")
        rows = []
        for i, (c, v) in enumerate(zip(chunks, vectors)):
            rows.append((
                strategy, c.chunk_id, c.document_id, c.source, c.page,
                int(c.metadata["chapter"]), int(c.metadata["char_start"]), int(c.metadata["char_end"]),
                c.text, content_hashes[i] if content_hashes else "", Jsonb(c.metadata),
                _vec(v),
            ))
        with self._connect() as conn:
            conn.cursor().executemany(
                """INSERT INTO chunks (strategy, chunk_id, document_id, source, page, chapter,
                                       char_start, char_end, text, content_hash, metadata, embedding)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                   ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                       document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
                       chapter = EXCLUDED.chapter, char_start = EXCLUDED.char_start,
                       char_end = EXCLUDED.char_end, text = EXCLUDED.text,
                       content_hash = EXCLUDED.content_hash, metadata = EXCLUDED.metadata,
                       embedding = EXCLUDED.embedding""",
                rows)

    def delete_obsolete(self, strategy: str, document_id: str, keep_ids: set[str]) -> int:
        """Remove rows of this strategy/document whose chunk_id is no longer produced."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM chunks WHERE strategy = %s AND document_id = %s AND NOT (chunk_id = ANY(%s))",
                (strategy, document_id, list(keep_ids)))
            return cur.rowcount

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector has {len(query_vector)} dims, expected {self.dimensions}")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTER_COLUMNS:
                raise ValueError(f"Unsupported filter {key!r}; allowed: {sorted(FILTER_COLUMNS)}")
            where.append(f"{FILTER_COLUMNS[key]} = %s")
            params.append(value)
        qv = _vec(query_vector)
        sql = f"""SELECT chunk_id, document_id, source, page, chapter, char_start, char_end, text, metadata,
                         1 - (embedding <=> %s::vector) AS score
                  FROM chunks WHERE {' AND '.join(where)}
                  ORDER BY embedding <=> %s::vector LIMIT %s"""
        with self._connect() as conn:
            rows = conn.execute(sql, [qv, *params, qv, top_k]).fetchall()
        keys = ["chunk_id", "document_id", "source", "page", "chapter", "char_start", "char_end",
                "text", "metadata", "score"]
        return [dict(zip(keys, r)) for r in rows]
