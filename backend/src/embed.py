# NOTE: Stage 4+Stage 5 query embedding must use this same model (BAAI/bge-small-en-v1.5) — never change one side without the other.
"""Embed every chunk in data/chunks/<company>/<year>.json -> data/chunks/all_embeddings.pkl (feeds Stage 4).

Model: sentence-transformers BAAI/bge-small-en-v1.5 (384-dim, reads up to 512 tokens, CPU-friendly).
Run: python src/embed.py
"""
import json
import pickle
import time
from pathlib import Path

from sentence_transformers import SentenceTransformer

CHUNKS = Path(__file__).resolve().parent.parent / "data" / "chunks"
OUT = CHUNKS / "all_embeddings.pkl"
MODEL = "BAAI/bge-small-en-v1.5"


def main():
    start = time.time()
    chunks = [c for f in sorted(CHUNKS.glob("*/*.json")) for c in json.loads(f.read_text(encoding="utf-8"))]
    texts = [c["text"] for c in chunks]
    model = SentenceTransformer(MODEL)
    vectors = model.encode(texts, batch_size=32, show_progress_bar=True)
    OUT.write_bytes(pickle.dumps([{**c, "embedding": v} for c, v in zip(chunks, vectors)]))
    # tokens beyond max_seq_length are silently cut off before embedding
    truncated = sum(len(ids) > model.max_seq_length for ids in model.tokenizer(texts)["input_ids"])

    print("\n===== SUMMARY =====")
    print(f"Chunks embedded : {len(chunks)}")
    print(f"Embedding dim   : {vectors.shape[1]}")
    print(f"Truncated       : {truncated} chunks longer than {model.max_seq_length} tokens")
    print(f"Time taken      : {time.time() - start:.1f}s")
    print(f"Saved to        : {OUT}")


if __name__ == "__main__":
    main()
