"""
embeddings.py — Text embedders for the pgvector retriever.

Two interchangeable embedders, both 768-dimensional so they share one table:

  * OllamaEmbedder  - semantic embeddings from `nomic-embed-text` served by the
                      LOCAL Ollama instance (best quality, still fully offline).
  * HashingEmbedder - deterministic word + character n-gram hashing. Needs no
                      model download, no GPU and no network, so retrieval keeps
                      working on a very low-end machine or before any model is
                      pulled. Lexical (not semantic) - good for symptom words.

Rows in the database are tagged with the embedder name; queries always use the
embedder the stored rows were built with, so the two never get mixed.
"""

import numpy as np
import httpx
from sklearn.feature_extraction.text import HashingVectorizer

from backend import config

DIM = config.EMBED_DIM


def _l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n == 0 else v / n


class HashingEmbedder:
    name = "hashing-v1"
    dim = DIM

    def __init__(self):
        kw = dict(n_features=DIM, alternate_sign=True, norm=None, lowercase=True)
        self._word = HashingVectorizer(analyzer="word", ngram_range=(1, 2), **kw)
        self._char = HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5), **kw)

    def embed(self, text: str, kind: str = "document") -> list:
        w = self._word.transform([text]).toarray()[0]
        c = self._char.transform([text]).toarray()[0]
        return _l2(_l2(w) * 1.0 + _l2(c) * 0.6).astype(float).tolist()


class OllamaEmbedder:
    dim = DIM

    def __init__(self, model: str = None):
        self.model = model or config.EMBED_MODEL
        self.name = self.model

    def embed(self, text: str, kind: str = "document") -> list:
        # nomic-embed-text expects task prefixes for best retrieval quality.
        prefix = "search_query: " if kind == "query" else "search_document: "
        payload_text = prefix + text if "nomic" in self.model else text
        with httpx.Client(timeout=config.OLLAMA_TIMEOUT) as client:
            r = client.post(f"{config.OLLAMA_BASE_URL}/api/embed",
                            json={"model": self.model, "input": payload_text})
            if r.status_code == 404:  # older Ollama versions
                r = client.post(f"{config.OLLAMA_BASE_URL}/api/embeddings",
                                json={"model": self.model, "prompt": payload_text})
                r.raise_for_status()
                vec = r.json()["embedding"]
            else:
                r.raise_for_status()
                vec = r.json()["embeddings"][0]
        if len(vec) != DIM:
            raise ValueError(f"{self.model} returned {len(vec)} dims, expected {DIM}")
        return _l2(np.array(vec, dtype=float)).tolist()


def ollama_embedder_if_ready():
    """Return a working OllamaEmbedder, or None if Ollama / the model is absent."""
    from backend.llm_client import is_ollama_live

    if not is_ollama_live():
        return None
    emb = OllamaEmbedder()
    try:
        emb.embed("health check", "query")
        return emb
    except Exception:
        return None


def to_pgvector(vec: list) -> str:
    """Serialise for a `%s::vector` parameter (avoids needing the pgvector pip package)."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
