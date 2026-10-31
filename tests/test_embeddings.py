import httpx
import pytest

from backend.rag import embeddings
from backend.rag.embeddings import HashingEmbedder, OllamaEmbedder, to_pgvector


def test_hashing_embedder_is_deterministic_768_unit_vectors():
    e = HashingEmbedder()
    a, b = e.embed("chest pain sweating"), e.embed("chest pain sweating")
    assert a == b and len(a) == 768
    assert abs(sum(x * x for x in a) - 1) < 1e-6


def test_hashing_embedder_similar_text_is_closer():
    e = HashingEmbedder()
    dot = lambda u, v: sum(x * y for x, y in zip(u, v))
    q = e.embed("high fever with chills and sweating", "query")
    near = e.embed("Malaria. Fever with chills and shivering followed by sweating.")
    far = e.embed("Ankle sprain after twisting the foot while walking.")
    assert dot(q, near) > dot(q, far)


def test_to_pgvector_format():
    assert to_pgvector([0.5, -1.0]) == "[0.500000,-1.000000]"


def _mock_client(handler):
    real = httpx.Client
    return lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k)


def test_ollama_embedder_parses_embed_api(monkeypatch):
    seen = {}

    def handler(req):
        seen["body"] = req.content.decode()
        return httpx.Response(200, json={"embeddings": [[1.0] + [0.0] * 767]})

    monkeypatch.setattr(embeddings.httpx, "Client", _mock_client(handler))
    v = OllamaEmbedder("nomic-embed-text").embed("hello", "query")
    assert len(v) == 768 and abs(v[0] - 1.0) < 1e-9
    assert "search_query: hello" in seen["body"]  # nomic task prefix applied


def test_ollama_embedder_falls_back_to_legacy_endpoint(monkeypatch):
    def handler(req):
        if req.url.path == "/api/embed":
            return httpx.Response(404)
        return httpx.Response(200, json={"embedding": [0.0, 1.0] + [0.0] * 766})

    monkeypatch.setattr(embeddings.httpx, "Client", _mock_client(handler))
    assert len(OllamaEmbedder().embed("x")) == 768


def test_ollama_embedder_rejects_wrong_dimension(monkeypatch):
    monkeypatch.setattr(embeddings.httpx, "Client",
                        _mock_client(lambda r: httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})))
    with pytest.raises(ValueError):
        OllamaEmbedder().embed("x")
