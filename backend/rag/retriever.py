"""
retriever.py — Retrieval-Augmented Generation (RAG) module
Owner: Shreyas (RAG & Knowledge Base)

WHAT THIS DOES
--------------
Grounds the Triage Agent's reasoning in real medical reference data instead
of relying purely on the LLM's memory. Given a patient's extracted symptoms,
it searches the local knowledge base and returns the most relevant condition
entries, ranked by similarity.

CURRENT IMPLEMENTATION (prototype scope)
-----------------------------------------
Uses scikit-learn's TF-IDF vectorizer + cosine similarity. This is a real,
working retrieval method — not a placeholder — and requires zero external
model downloads, which is why it's the right choice for a fast, fully
offline demo.

UPGRADE PATH (documented for the full system)
------------------------------------------------
Swap `TfidfRetriever` for `PgVectorRetriever` (see pgvector_retriever.py
stub at the bottom) once PostgreSQL + pgvector + an Ollama embedding model
(nomic-embed-text) are available in the deployment environment. The public
interface (`retrieve(query, top_k)`) stays identical, so nothing else in
the pipeline needs to change — this is intentional so the orchestrator and
other agents never need to know which retrieval backend is active.
"""

import json
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")


class TfidfRetriever:
    def __init__(self, kb_path: str = KB_PATH):
        with open(kb_path, "r") as f:
            self.kb = json.load(f)

        # Build the searchable corpus: condition name + description + keywords
        self._corpus = [
            f"{entry['condition']} {entry['description']} {' '.join(entry['keywords'])}"
            for entry in self.kb
        ]
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = self._vectorizer.fit_transform(self._corpus)

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Returns up to `top_k` knowledge base entries most relevant to `query`,
        each annotated with a similarity score in [0, 1].
        """
        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._matrix).flatten()

        ranked_indices = scores.argsort()[::-1]
        results = []
        for idx in ranked_indices[:top_k]:
            score = float(scores[idx])
            if score <= 0:
                continue
            entry = dict(self.kb[idx])
            entry["similarity"] = round(score, 3)
            results.append(entry)
        return results

    def all_conditions(self) -> list[str]:
        return [entry["condition"] for entry in self.kb]


# ---------------------------------------------------------------------------
# Additional retrievers (full-scale system)
# ---------------------------------------------------------------------------
import math
import re


class SymptomOverlapRetriever:
    RARE_IDF = 4.0  # symptom appearing in only a handful of conditions
    # Everyday, non-specific symptoms: even if few entries list them, one of these alone
    # says almost nothing, so a lone generic symptom never triggers single-symptom retrieval.
    GENERIC = frozenset({
        "swelling", "mild swelling", "redness", "rash", "red rash", "itchy skin", "pain", "fever", "mild fever",
        "high fever", "cough", "mild cough", "headache", "nausea", "vomiting", "diarrhea", "fatigue", "weakness",
        "dizzy", "sweating", "fall", "wound", "blisters", "bruising", "shortness of breath", "abdominal pain",
        "chest pain", "back pain", "joint pain", "muscle pain", "stress", "swollen legs", "pale skin", "confusion",
        "drowsiness", "constipation", "runny nose", "sore throat", "chills", "loss of appetite", "weight loss",
        "stiffness", "heat exposure", "palpitations", "sneezing", "congestion"})
    """
    Ranks conditions by IDF-weighted overlap between the symptoms recognised in
    the patient's text (via the shared lexicon/negation-aware extractor) and each
    condition's keyword profile. Cheap, deterministic, fully offline, and strong
    for structured symptom reports. Explicitly ruled-out symptoms ("no fever")
    lower a condition's score.
    """

    def __init__(self, kb_path: str = KB_PATH):
        from backend.rag.decision_tree import keyword_extract_known_symptoms

        self._extract = keyword_extract_known_symptoms
        with open(kb_path, "r", encoding="utf-8") as f:
            self.kb = json.load(f)
        df = {}
        for e in self.kb:
            for k in set(e["keywords"]):
                df[k] = df.get(k, 0) + 1
        n = len(self.kb)
        self._idf = {k: math.log((n + 1) / (c + 0.5)) + 1.0 for k, c in df.items()}

    def retrieve(self, query: str, top_k: int = 3) -> list:
        known = self._extract(query)
        pos = {k for k, v in known.items() if v == 1}
        neg = {k for k, v in known.items() if v == 0}
        if len(pos) < 2:
            # One recognised symptom is usually not enough evidence - unless it is a
            # highly distinctive one (rare across the knowledge base, e.g. 'nosebleed').
            if not any(self._idf.get(k, 0.0) >= self.RARE_IDF and k not in self.GENERIC for k in pos):
                return []
        pat_total = sum(self._idf.get(k, 1.0) for k in pos) or 1.0
        scored = []
        for e in self.kb:
            kws = set(e["keywords"])
            hit = sum(self._idf[k] for k in kws & pos)
            if hit == 0:
                continue
            total = sum(self._idf[k] for k in kws)
            miss_penalty = sum(self._idf[k] for k in kws & neg)
            # IDF-weighted cosine between patient symptoms and the condition profile
            score = max(0.0, hit / math.sqrt(total * pat_total) - 0.15 * miss_penalty / (total or 1.0))
            scored.append((score, e))
        scored.sort(key=lambda t: -t[0])
        out = []
        for score, e in scored[:top_k]:
            d = dict(e)
            d["similarity"] = round(min(1.0, score), 3)
            out.append(d)
        return out


class PgVectorRetriever:
    """
    Semantic retrieval over PostgreSQL + pgvector (cosine distance, HNSW index).
    Uses `nomic-embed-text` via local Ollama when its embeddings are stored and
    the model is reachable; otherwise the offline hashing embedder. The query
    always uses the same embedder as the rows it searches.
    """

    def __init__(self, kb_path: str = KB_PATH):
        from backend import database
        from backend.rag.embeddings import HashingEmbedder

        with open(kb_path, "r", encoding="utf-8") as f:
            self.kb = json.load(f)
        self._by_id = {e["id"]: e for e in self.kb}
        self._db = database
        self._hash = HashingEmbedder()
        self._available_embedders = self._stored_embedders()
        if not self._available_embedders:
            raise RuntimeError("pgvector store is empty - run `python -m backend.rag.ingest`")

    def _stored_embedders(self) -> list:
        with self._db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT embedder FROM medical_chunks")
            return [r[0] for r in cur.fetchall()]

    def _pick_embedder(self):
        from backend import config
        from backend.rag.embeddings import ollama_embedder_if_ready

        if config.EMBED_MODEL in self._available_embedders:
            oe = ollama_embedder_if_ready()
            if oe:
                return oe
        return self._hash

    @property
    def backend_name(self) -> str:
        return f"pgvector ({self._pick_embedder().name})"

    def retrieve(self, query: str, top_k: int = 3) -> list:
        from backend.rag.embeddings import to_pgvector

        emb = self._pick_embedder()
        qv = to_pgvector(emb.embed(query, "query"))
        with self._db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT condition_id, 1 - (embedding <=> %s::vector) AS sim
                   FROM medical_chunks WHERE embedder = %s
                   ORDER BY embedding <=> %s::vector LIMIT %s""",
                (qv, emb.name, qv, top_k * 6),
            )
            rows = cur.fetchall()
        best = {}
        for cid, sim in rows:
            best[cid] = max(best.get(cid, -1.0), float(sim))
        ranked = sorted(best.items(), key=lambda t: -t[1])[:top_k]
        out = []
        for cid, sim in ranked:
            if sim <= 0 or cid not in self._by_id:
                continue
            d = dict(self._by_id[cid])
            d["similarity"] = round(sim, 3)
            out.append(d)
        return out


class HybridRetriever:
    """
    Reciprocal-rank fusion of several retrievers (symptom-overlap + TF-IDF +
    pgvector when available). Fusion makes the shortlist robust: a miss by one
    signal is usually rescued by another - important because Triage can only
    conclude with a condition that Retrieval shortlisted.
    """

    RRF_K = 20

    def __init__(self, retrievers: list, kb: list):
        self.retrievers = retrievers
        self.kb = kb
        self._by_id = {e["id"]: e for e in kb}

    @property
    def backend_name(self) -> str:
        names = []
        for r in self.retrievers:
            names.append(getattr(r, "backend_name", r.__class__.__name__.replace("Retriever", "").lower()))
        return "hybrid[" + " + ".join(names) + "]"

    def retrieve(self, query: str, top_k: int = 3) -> list:
        fused, best_sim = {}, {}
        depth = max(top_k * 4, 12)
        for r in self.retrievers:
            try:
                results = r.retrieve(query, top_k=depth)
            except Exception:
                continue  # a failed signal must never take retrieval down
            for rank, m in enumerate(results):
                fused[m["id"]] = fused.get(m["id"], 0.0) + 1.0 / (self.RRF_K + rank + 1)
                best_sim[m["id"]] = max(best_sim.get(m["id"], 0.0), m.get("similarity", 0.0))
        ranked = sorted(fused.items(), key=lambda t: -t[1])[:top_k]
        out = []
        for cid, score in ranked:
            d = dict(self._by_id[cid])
            d["similarity"] = round(best_sim.get(cid, 0.0), 3)
            d["fusion_score"] = round(score, 4)
            out.append(d)
        return out

    def all_conditions(self) -> list:
        return [e["condition"] for e in self.kb]


def build_retriever():
    """Factory: best retriever the environment supports, always degrading to offline."""
    from backend import config, database

    tfidf = TfidfRetriever()
    parts = [SymptomOverlapRetriever(), tfidf]
    if config.RETRIEVER in ("auto", "pgvector") and database.pg_available():
        try:
            parts.append(PgVectorRetriever())
        except Exception as e:  # empty store, missing extension, ...
            print(f"[retriever] pgvector unavailable ({e}); using offline retrievers only.")
    if config.RETRIEVER == "tfidf":
        parts = [tfidf]
    return HybridRetriever(parts, tfidf.kb)


if __name__ == "__main__":
    # quick manual sanity check
    r = TfidfRetriever()
    test_query = "chest pain radiating to left arm sweating dizzy"
    for match in r.retrieve(test_query):
        print(f"{match['similarity']:.2f}  {match['condition']}")
