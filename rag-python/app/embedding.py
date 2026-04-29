from __future__ import annotations

import hashlib
import logging
import math
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def embed_texts(self, texts: list[str]) -> tuple[list[list[float]], int, str]:
        if not texts:
            return [], 0, self._settings.embedding_model
        if self._settings.embedding_api_key:
            try:
                return await self._embed_remote(texts)
            except Exception as exc:
                if not self._settings.embedding_allow_local_fallback:
                    logger.exception("Remote embedding failed and local fallback is disabled.")
                    raise
                logger.warning("Remote embedding failed, falling back to local hash embedding: %s", exc)
        elif not self._settings.embedding_allow_local_fallback:
            raise RuntimeError(
                "EMBEDDING_API_KEY is required unless EMBEDDING_ALLOW_LOCAL_FALLBACK=true"
            )
        else:
            logger.warning("EMBEDDING_API_KEY is empty, using local hash embedding fallback.")
        vectors = [self._embed_local(text) for text in texts]
        return vectors, 0, f"local-hash:{self._settings.embedding_dimension}"

    async def _embed_remote(self, texts: list[str]) -> tuple[list[list[float]], int, str]:
        embeddings: list[list[float]] = []
        total_tokens = 0
        model_version = self._settings.embedding_model
        batch_size = max(1, self._settings.embedding_batch_size)

        headers = {
            "Authorization": f"Bearer {self._settings.embedding_api_key}",
            "Content-Type": "application/json",
        }
        base = self._settings.embedding_api_url.rstrip("/")
        url = f"{base}/embeddings"

        timeout = httpx.Timeout(self._settings.embedding_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                payload: dict[str, Any] = {
                    "model": self._settings.embedding_model,
                    "input": batch,
                }
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
                data = body.get("data", [])
                if len(data) != len(batch):
                    raise RuntimeError("embedding result length mismatch")
                for item in data:
                    emb = item.get("embedding")
                    if not isinstance(emb, list):
                        raise RuntimeError("invalid embedding format")
                    vector = [float(v) for v in emb]
                    if len(vector) != self._settings.embedding_dimension:
                        raise RuntimeError(
                            "embedding dimension mismatch: "
                            f"expected {self._settings.embedding_dimension}, got {len(vector)}"
                        )
                    embeddings.append(vector)
                usage = body.get("usage", {})
                total_tokens += int(usage.get("total_tokens", 0) or 0)
                if body.get("model"):
                    model_version = str(body["model"])
        return embeddings, total_tokens, model_version

    def _embed_local(self, text: str) -> list[float]:
        dim = max(32, self._settings.embedding_dimension)
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big", signed=False)
        values: list[float] = []
        state = seed
        for _ in range(dim):
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            value = (state / 0x7FFFFFFF) * 2 - 1
            values.append(float(value))
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]
