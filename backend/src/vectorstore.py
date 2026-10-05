"""Load data/chunks/all_embeddings.pkl into the persistent ChromaDB collection "askmyreport" (backend/vectorstore/).

Idempotent: upsert by chunk_id, and ids no longer in the pickle are deleted, so the store always mirrors Stage 3.
Run: python src/vectorstore.py
"""
import pickle
import time
from pathlib import Path

import chromadb

BACKEND = Path(__file__).resolve().parent.parent
PICKLE = BACKEND / "data" / "chunks" / "all_embeddings.pkl"
BATCH = 500


def get_collection():
    client = chromadb.PersistentClient(path=str(BACKEND / "vectorstore"))
    # embedding_function=None: we always pass our own bge vectors, so chroma never loads its default model
    # ef_search 500 (default 100): with a company/year filter the default HNSW search missed true top hits
    # (TCS FY2024 revenue chunk) and varied between runs; 500 matches exact brute-force search at ~0.2s/query
    return client.get_or_create_collection(
        "askmyreport", embedding_function=None, configuration={"hnsw": {"space": "cosine", "ef_search": 500}}
    )


def main():
    start = time.time()
    records = pickle.loads(PICKLE.read_bytes())
    col = get_collection()
    before = col.count()
    for i in range(0, len(records), BATCH):
        batch = records[i:i + BATCH]
        col.upsert(
            ids=[r["chunk_id"] for r in batch],
            embeddings=[r["embedding"] for r in batch],
            documents=[r["text"] for r in batch],
            metadatas=[{"company": r["company"], "year": r["year"], "page_number": r["page_number"]} for r in batch],
        )
    # re-chunking can leave fewer chunks than last run; drop ids that no longer exist so no stale text is retrieved
    stale = set(col.get(include=[])["ids"]) - {r["chunk_id"] for r in records}
    if stale:
        col.delete(ids=list(stale))

    print("\n===== SUMMARY =====")
    print(f"Chunks upserted  : {len(records)} ({col.count() - before + len(stale)} new, {len(stale)} stale removed)")
    print(f"Collection size  : {col.count()}")
    print(f"Time taken       : {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
