"""Embedding generation (`text-embedding-3-small`, 1536 dims) and deterministic test embeddings."""

from __future__ import annotations

import hashlib
import math

EMBEDDING_DIMENSIONS = 1536


class EmbeddingClient:
    """Produces 1536-dimensional unit vectors for chunks and queries (Architecture.md §1 & §7b).

    Supports graceful degradation (`available=False`) to test full-text fallback mode when the
    embedding service is unreachable (Rules.md §3).
    """

    def __init__(self, *, available: bool = True, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.available = available
        self.dimensions = dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return 1536-dim normalized embeddings for `texts`, or raise RuntimeError if down."""
        if not self.available:
            msg = "Embedding provider is currently unreachable"
            raise RuntimeError(msg)
        return [self._deterministic_vector(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        """Return 1536-dim normalized embedding for `query`."""
        res = await self.embed_texts([query])
        return res[0]

    def _deterministic_vector(self, text: str) -> list[float]:
        tokens = [
            tok.strip(".,!?;:\"'()[]{}").lower()
            for tok in text.split()
            if len(tok.strip(".,!?;:\"'()[]{}")) >= 3
        ]
        vec = [0.0] * self.dimensions
        if not tokens:
            vec[0] = 1.0
            return vec
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:2], "big") % self.dimensions
            sign = 1.0 if (digest[2] % 2 == 0) else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [round(v / norm, 6) for v in vec]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    return sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
