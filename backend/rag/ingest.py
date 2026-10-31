"""
ingest.py — Seed PostgreSQL + pgvector from knowledge_base.json.

    python -m backend.rag.ingest                 # create schema, upsert, embed (idempotent)
    python -m backend.rag.ingest --embedder hashing
    python -m backend.rag.ingest --reset         # wipe KB tables first

Idempotent: unchanged conditions/chunks are skipped (content hashes), so it is
safe to run on every container start. Always builds the offline hashing
embeddings; also builds `nomic-embed-text` embeddings when Ollama has the
model, so semantic search switches on automatically once the model is pulled.
"""

import argparse
import hashlib
import json
import sys

from backend import config, database
from backend.rag.embeddings import HashingEmbedder, ollama_embedder_if_ready, to_pgvector
from backend.rag.retriever import KB_PATH


def _hash(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:32]


def make_chunks(entry: dict) -> list:
    """Several retrievable facts per condition (this is what makes it real RAG)."""
    chunks = [
        ("profile", f"{entry['condition']}. {entry['description']}"),
        ("symptoms", f"{entry['condition']} - typical symptoms: {', '.join(entry['keywords'])}."),
        ("guidance", f"{entry['condition']} - what to do: {entry.get('recommendation','')} "
                     f"{entry.get('self_care','')}".strip()),
    ]
    if entry.get("red_flags"):
        chunks.append(("red_flags", f"{entry['condition']} - warning signs needing urgent care: "
                                    f"{', '.join(entry['red_flags'])}."))
    return chunks


def ingest(embedder_choice: str = "auto", reset: bool = False, verbose: bool = True) -> dict:
    with open(KB_PATH, encoding="utf-8") as f:
        kb = json.load(f)

    embedders = []
    if embedder_choice in ("auto", "hashing"):
        embedders.append(HashingEmbedder())
    if embedder_choice in ("auto", "ollama"):
        oe = ollama_embedder_if_ready()
        if oe:
            embedders.append(oe)
        elif embedder_choice == "ollama":
            raise RuntimeError(f"Ollama / model '{config.EMBED_MODEL}' not available")

    database.init_schema()
    stats = {"conditions": len(kb), "chunks_written": 0, "chunks_skipped": 0,
             "embedders": [e.name for e in embedders]}

    with database.connect(timeout=10) as conn:
        if reset:
            conn.execute("TRUNCATE medical_chunks, conditions CASCADE")
        for e in kb:
            chash = _hash(json.dumps(e, sort_keys=True))
            conn.execute(
                """INSERT INTO conditions (id, condition, description, keywords, acuity, acuity_label,
                       source, recommendation, caution, red_flags, self_care, review_status, reviewed_by, reviewed_on, reviewer_comments, content_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET
                       condition=EXCLUDED.condition, description=EXCLUDED.description,
                       keywords=EXCLUDED.keywords, acuity=EXCLUDED.acuity,
                       acuity_label=EXCLUDED.acuity_label, source=EXCLUDED.source,
                       recommendation=EXCLUDED.recommendation, caution=EXCLUDED.caution,
                       red_flags=EXCLUDED.red_flags, self_care=EXCLUDED.self_care,
                       review_status=EXCLUDED.review_status, reviewed_by=EXCLUDED.reviewed_by,
                       reviewed_on=EXCLUDED.reviewed_on, reviewer_comments=EXCLUDED.reviewer_comments,
                       content_hash=EXCLUDED.content_hash,
                       updated_at=now()""",
                (e["id"], e["condition"], e["description"], e["keywords"], e["acuity"],
                 e["acuity_label"], e.get("source"), e.get("recommendation"), e.get("caution"),
                 e.get("red_flags", []), e.get("self_care", ""), e.get("review_status"),
                 e.get("reviewed_by"), e.get("reviewed_on"), e.get("reviewer_comments"), chash),
            )
            for ctype, content in make_chunks(e):
                for emb in embedders:
                    ch = _hash(content, emb.name)
                    row = conn.execute(
                        "SELECT content_hash FROM medical_chunks WHERE condition_id=%s AND chunk_type=%s AND embedder=%s",
                        (e["id"], ctype, emb.name)).fetchone()
                    if row and row[0] == ch:
                        stats["chunks_skipped"] += 1
                        continue
                    vec = to_pgvector(emb.embed(content, "document"))
                    conn.execute(
                        """INSERT INTO medical_chunks (condition_id, chunk_type, content, content_hash, embedder, embedding)
                           VALUES (%s,%s,%s,%s,%s,%s::vector)
                           ON CONFLICT (condition_id, chunk_type, embedder) DO UPDATE SET
                               content=EXCLUDED.content, content_hash=EXCLUDED.content_hash,
                               embedding=EXCLUDED.embedding""",
                        (e["id"], ctype, content, ch, emb.name, vec))
                    stats["chunks_written"] += 1
        # drop conditions removed from the JSON
        conn.execute("DELETE FROM conditions WHERE NOT (id = ANY(%s))", ([e["id"] for e in kb],))
    if verbose:
        print(f"[ingest] {stats}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", choices=["auto", "hashing", "ollama"], default="auto")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    if not database.pg_configured():
        sys.exit("DATABASE_URL is not set - nothing to ingest into.")
    ingest(a.embedder, a.reset)
