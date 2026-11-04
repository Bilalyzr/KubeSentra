"""Local embeddings via sentence-transformers (bge-small-en-v1.5, 384 dims).

The model is cached in the repo-local .models/ directory (git-ignored).
Loading is lazy and process-wide; everything runs on CPU.
"""

from __future__ import annotations

from pathlib import Path

from common.config import get_settings

_model = None

# BGE retrieval queries should carry this instruction prefix (docs recommend
# it for short queries); passages are embedded without it.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

ROOT = Path(__file__).resolve().parents[1]


def get_model():  # noqa: ANN201 - lazy sentence-transformers type
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        cache = Path(settings.embedding_cache_dir)
        if not cache.is_absolute():
            cache = ROOT / cache
        cache.mkdir(parents=True, exist_ok=True)
        _model = SentenceTransformer(settings.embedding_model, cache_folder=str(cache))
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed passages (no query prefix). Returns 384-dim vectors."""
    if not texts:
        return []
    vectors = get_model().encode(texts, normalize_embeddings=True,
                                 show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    """Embed a retrieval query with the BGE query instruction."""
    return embed_texts([QUERY_PREFIX + text])[0]
