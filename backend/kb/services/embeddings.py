"""Embedding backends.

- local (default): TF-IDF vectors fitted over the whole chunk corpus.
  Works fully offline; vectors are stored per chunk at index time.
- openai: text-embedding-3-small via the OpenAI-compatible API (requires
  LLM_API_KEY).

Both backends produce per-chunk dense vectors consumed by kb.services.store.
"""
import logging

import numpy as np

logger = logging.getLogger(__name__)

_BACKEND = None
_VECTORIZER = None


def get_backend():
    from django.conf import settings

    global _BACKEND
    if _BACKEND is None:
        _BACKEND = settings.EMBEDDING_BACKEND
    return _BACKEND


def fit_corpus(texts):
    """Local backend: fit the shared TF-IDF vectorizer on all chunks."""
    global _VECTORIZER
    if get_backend() != "local":
        return
    from sklearn.feature_extraction.text import TfidfVectorizer

    _VECTORIZER = TfidfVectorizer(max_features=5000, stop_words="english", lowercase=True)
    if texts:
        _VECTORIZER.fit(texts)
    logger.info("Local TF-IDF embedding backend fitted on %d chunks", len(texts))


def vectorizer_ready():
    return _VECTORIZER is not None


def embed_texts(texts):
    """Return (n, d) float array of embeddings for the given texts."""
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    if get_backend() == "openai":
        return _embed_openai(texts)
    if _VECTORIZER is None:
        raise RuntimeError("Local embedding backend used before fit_corpus().")
    return _VECTORIZER.transform(texts).toarray().astype(np.float32)


def _embed_openai(texts):
    from django.conf import settings

    if not settings.LLM_API_KEY:
        raise RuntimeError("OpenAI embeddings selected but LLM_API_KEY is not configured.")
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL, timeout=settings.LLM_TIMEOUT_SECONDS)
        response = client.embeddings.create(model="text-embedding-3-small", input=list(texts))
        return np.asarray([item.embedding for item in response.data], dtype=np.float32)
    except Exception:
        logger.exception("OpenAI embedding call failed")
        raise
