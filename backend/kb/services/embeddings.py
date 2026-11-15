"""Embedding backends.

- local (default): TF-IDF vectors fitted over the whole chunk corpus.
  Works fully offline; vectors are stored per chunk at index time.
- openai: text-embedding-3-small via the OpenAI-compatible API (requires
  LLM_API_KEY).

Both backends produce per-chunk dense vectors consumed by kb.services.store.
"""
import logging
import os
import pickle
import tempfile
from pathlib import Path

import joblib
import numpy as np

logger = logging.getLogger(__name__)

_BACKEND = None
_VECTORIZER = None
_CORPUS_HASH = None
LOCAL_VECTOR_SIZE = 5000


def _corpus_hash(texts):
    import hashlib

    digest = hashlib.sha256()
    for text in texts:
        encoded = text.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _artifact_path():
    from django.conf import settings

    directory = Path(getattr(settings, "RAG_ARTIFACTS_DIR", settings.BASE_DIR / "rag_artifacts"))
    return directory / "tfidf.joblib"


def _persist_vectorizer(texts):
    global _CORPUS_HASH

    path = _artifact_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "backend": "local",
        "corpus_hash": _corpus_hash(texts),
        "vectorizer": _VECTORIZER,
    }
    fd, temporary_path = tempfile.mkstemp(prefix="tfidf-", suffix=".joblib", dir=path.parent)
    os.close(fd)
    try:
        joblib.dump(payload, temporary_path)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
    _CORPUS_HASH = payload["corpus_hash"]


def _load_persisted_vectorizer(texts):
    global _VECTORIZER, _CORPUS_HASH

    expected_hash = _corpus_hash(texts)
    path = _artifact_path()
    if path.is_file():
        try:
            payload = joblib.load(path)
            if (
                payload.get("backend") == "local"
                and payload.get("corpus_hash") == expected_hash
                and payload.get("vectorizer") is not None
            ):
                _VECTORIZER = payload["vectorizer"]
                _CORPUS_HASH = expected_hash
                return
        except (
            OSError, EOFError, ValueError, KeyError, TypeError,
            AttributeError, ImportError, pickle.UnpicklingError,
        ):
            logger.exception("Persisted TF-IDF artifact is invalid; rebuilding from stored chunks")

    if not texts:
        raise RuntimeError("The knowledge base is empty; index a document before retrieval.")

    logger.warning("TF-IDF artifact is missing or stale; rebuilding from stored document chunks")
    _fit_vectorizer(texts)
    _persist_vectorizer(texts)
    _persist_chunk_embeddings(texts)
    from django.conf import settings

    if settings.VECTOR_BACKEND == "qdrant":
        from kb.services import store

        store.sync_qdrant_index()


def _fit_vectorizer(texts):
    global _VECTORIZER

    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(max_features=LOCAL_VECTOR_SIZE, stop_words="english", lowercase=True)
    try:
        vectorizer.fit(texts)
    except ValueError as exc:
        raise RuntimeError(f"Unable to build the local TF-IDF index: {exc}") from exc
    _VECTORIZER = vectorizer


def _persist_chunk_embeddings(texts):
    from kb.models import DocumentChunk

    chunks = list(DocumentChunk.objects.order_by("id"))
    if [chunk.text for chunk in chunks] != texts:
        raise RuntimeError("Knowledge chunks changed while rebuilding the TF-IDF index; retry indexing.")
    vectors = _transform_local(texts)
    for chunk, vector in zip(chunks, vectors):
        chunk.embedding = vector.tolist()
        chunk.embedding_backend = "local"
    DocumentChunk.objects.bulk_update(chunks, ["embedding", "embedding_backend"], batch_size=200)


def get_backend():
    from django.conf import settings

    global _BACKEND
    if _BACKEND is None:
        _BACKEND = settings.EMBEDDING_BACKEND
    if _BACKEND not in {"local", "openai"}:
        raise RuntimeError(f"Unsupported embedding backend: {_BACKEND}")
    return _BACKEND


def fit_corpus(texts):
    """Local backend: fit the shared TF-IDF vectorizer on all chunks."""
    if get_backend() != "local":
        return
    if not texts:
        raise RuntimeError("Cannot fit the local TF-IDF backend on an empty corpus.")
    _fit_vectorizer(texts)
    _persist_vectorizer(texts)
    logger.info("Local TF-IDF embedding backend fitted on %d chunks", len(texts))


def vectorizer_ready():
    return _VECTORIZER is not None


def embed_texts(texts):
    """Return (n, d) float array of embeddings for the given texts."""
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    if get_backend() == "openai":
        return _embed_openai(texts)
    from kb.models import DocumentChunk

    corpus_texts = list(DocumentChunk.objects.order_by("id").values_list("text", flat=True))
    if _VECTORIZER is None or _CORPUS_HASH != _corpus_hash(corpus_texts):
        _load_persisted_vectorizer(corpus_texts)
    return _transform_local(texts)


def _transform_local(texts):
    if _VECTORIZER is None:
        raise RuntimeError("The local TF-IDF index is unavailable; reindex the knowledge base.")
    vectors = _VECTORIZER.transform(texts).toarray().astype(np.float32)
    if vectors.shape[1] > LOCAL_VECTOR_SIZE:
        raise RuntimeError("Local TF-IDF vector dimension exceeds the configured vector size.")
    if vectors.shape[1] < LOCAL_VECTOR_SIZE:
        vectors = np.pad(vectors, ((0, 0), (0, LOCAL_VECTOR_SIZE - vectors.shape[1])))
    return vectors


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
