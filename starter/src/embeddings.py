"""OpenAI embeddings (real API). There is deliberately no mock/offline fallback."""
from __future__ import annotations

import os
import time
from typing import Protocol

DEFAULT_MODEL = "text-embedding-3-small"

# Native output sizes of the OpenAI embedding models (no ``dimensions`` override is used).
KNOWN_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}
# USD per 1M input tokens - list prices as I know them; verify on the OpenAI pricing page
# before quoting the cost in the report. Override with EMBEDDING_PRICE_PER_1M_TOKENS.
KNOWN_PRICE_PER_1M = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, question: str) -> list[float]: ...


class EmbeddingError(RuntimeError):
    pass


class MyEmbedder:
    """OpenAI adapter. Documents and queries use the same model and no prefix
    (OpenAI embedding models are symmetric)."""

    def __init__(self, model_name: str | None = None, batch_size: int = 96) -> None:
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
        if self.model_name not in KNOWN_DIMENSIONS:
            raise EmbeddingError(f"Unknown embedding model {self.model_name!r}; add it to KNOWN_DIMENSIONS.")
        self.dimensions = KNOWN_DIMENSIONS[self.model_name]
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise EmbeddingError("OPENAI_API_KEY is empty. Put your key in starter/.env (never commit it).")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise EmbeddingError("Install the SDK: python -m pip install -r requirements.txt") from exc
        self._client = OpenAI(api_key=api_key, max_retries=5, timeout=60)
        self.batch_size = batch_size
        self.total_tokens = 0
        self.api_calls = 0
        self.api_seconds = 0.0
        price = os.getenv("EMBEDDING_PRICE_PER_1M_TOKENS")
        self.price_per_1m = float(price) if price else KNOWN_PRICE_PER_1M[self.model_name]

    @property
    def cost_usd(self) -> float:
        return self.total_tokens / 1_000_000 * self.price_per_1m

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if any(not t.strip() for t in texts):
            raise EmbeddingError("Refusing to embed an empty text.")
        started = time.perf_counter()
        try:
            resp = self._client.embeddings.create(model=self.model_name, input=texts)
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embeddings request failed: {type(exc).__name__}: {exc}") from exc
        self.api_seconds += time.perf_counter() - started
        self.api_calls += 1
        self.total_tokens += resp.usage.total_tokens
        ordered = sorted(resp.data, key=lambda d: d.index)
        vectors = [d.embedding for d in ordered]
        if len(vectors) != len(texts) or any(len(v) != self.dimensions for v in vectors):
            raise EmbeddingError(
                f"Unexpected embedding shape: got {len(vectors)} vectors of "
                f"{len(vectors[0]) if vectors else 0} dims, expected {len(texts)} x {self.dimensions}.")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed(texts[i:i + self.batch_size]))
        return vectors

    def embed_query(self, question: str) -> list[float]:
        return self._embed([question])[0]
