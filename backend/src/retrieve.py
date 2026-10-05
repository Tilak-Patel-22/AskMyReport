"""retrieve(query) -> best chunks: auto-detect company/year, then dense (bge in Chroma) top 30 + BM25 keyword top 30,
union, cross-encoder rerank.

Run: python src/retrieve.py   (manual test with the 3 Stage 4 problem questions)
"""
import re
import time
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from embed import MODEL  # single source: queries must use the model the chunks were embedded with
from vectorstore import get_collection

CHUNKS = Path(__file__).resolve().parent.parent / "data" / "chunks"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge: queries only, never chunks
RERANKER = "BAAI/bge-reranker-base"  # replaced ms-marco-MiniLM-L-6-v2, which buried number-heavy table chunks
CANDIDATES = 20  # per source (dense and BM25): 30+30 made bge-reranker take ~12 s/query; 20 keeps margin over
                 # Q12's TCS revenue chunk (BM25 rank 15)

# what's actually indexed: {"tcs": {"2019", "2023", "2024"}, ...}
YEARS = {d.name: {f.stem for f in d.glob("*.json")} for d in CHUNKS.iterdir() if d.is_dir()}
# "hdfc_bank" -> "hdfc bank", "hdfc"; plus abbreviations a folder name can't give us
EXTRA_ALIASES = {"tcs": ["tata consultancy"], "reliance": ["ril"], "hindustan_unilever": ["hul"]}
ALIASES = {c: {c.replace("_", " "), c.split("_")[0], *EXTRA_ALIASES.get(c, [])} for c in YEARS}
# stored year = fiscal year END: "FY 2023-24" / "2023-2024" -> "2024", "FY24" -> "2024"
YEAR_PATTERNS = [
    (re.compile(r"\b(20\d{2})\s*[-–/]\s*(?:20)?\d{2}\b"), lambda m: str(int(m[1]) + 1)),
    (re.compile(r"\bfy\s*'?(20\d{2}|\d{2})\b"), lambda m: m[1] if len(m[1]) == 4 else "20" + m[1]),
    (re.compile(r"\b(20\d{2})\b"), lambda m: m[1]),
]


def detect(query):
    """Companies and fiscal years mentioned in the query, keeping only years we actually have reports for."""
    q = query.lower()
    companies = [c for c, names in ALIASES.items() if any(re.search(rf"\b{re.escape(n)}\b", q) for n in names)]
    years = []
    for pattern, to_year in YEAR_PATTERNS:
        years += [to_year(m) for m in pattern.finditer(q)]
        q = pattern.sub(" ", q)  # "2023-24" must not be read again as a bare "2023"
    indexed = set().union(*(YEARS[c] for c in companies or YEARS))
    return companies, sorted(set(years) & indexed)


def where_filter(companies, years):
    # several companies/years (e.g. "TCS vs Infosys") -> $in, so comparisons still see both
    conds = [{k: v[0] if len(v) == 1 else {"$in": v}} for k, v in (("company", companies), ("year", years)) if v]
    return None if not conds else conds[0] if len(conds) == 1 else {"$and": conds}


@lru_cache(maxsize=1)
def model():
    return SentenceTransformer(MODEL)


@lru_cache(maxsize=1)
def reranker():
    # 384 (card allows 512): same 20/21 retrieval on the eval set, ~18% faster on CPU. int8 quantization was 2x faster
    # but dropped to 16/21 at 512 and 19/21 at 384, so it isn't used.
    return CrossEncoder(RERANKER, max_length=384)


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


# BM25 keyword index over every indexed chunk, built once at import from what Chroma already stores (~4 s, ~200 MB).
# Dense search misses number-heavy table chunks (TCS's "Revenue from operations 2,40,893" row); exact words catch them.
_indexed = get_collection().get(include=["documents", "metadatas"])
BM25_IDS, BM25_META, BM25_TEXT = _indexed["ids"], _indexed["metadatas"], _indexed["documents"]
BM25 = BM25Okapi([tokens(t) for t in BM25_TEXT]) if BM25_TEXT else None  # empty store: api.py's startup check reports it


def best_keyword(bm, query, positions, n=CANDIDATES):
    """The n positions (among `positions`) with the best BM25 score for the query; zero-score matches dropped."""
    if bm is None or not positions:
        return []
    scores = bm.get_batch_scores(tokens(query), positions)
    best = sorted(range(len(positions)), key=lambda j: -scores[j])[:n]
    return [positions[j] for j in best if scores[j] > 0]


def bm25_top(query, companies, years, n=CANDIDATES):
    """Positions (into BM25_*) of the n best keyword matches among chunks that pass the company/year filter."""
    allowed = [
        i for i, m in enumerate(BM25_META)
        if (not companies or m["company"] in companies) and (not years or m["year"] in years)
    ]
    return best_keyword(BM25, query, allowed, n)


def rerank(query, found):
    """found: {chunk_id: chunk} candidates from dense + keyword search -> list sorted by cross-encoder score."""
    hits = list(found.values())
    # cross-encoder reads query + chunk together -> sharper relevance than comparing two separate vectors
    scores = reranker().predict([(query, h["text"]) for h in hits]) if hits else []
    for h, s in zip(hits, scores):
        h["score"] = float(s)
    return sorted(hits, key=lambda h: -h["score"])


def dense(collection, query, where):
    r = collection.query(query_embeddings=[model().encode(QUERY_PREFIX + query)], n_results=CANDIDATES, where=where)
    return {i: {"chunk_id": i, **m, "text": d} for i, m, d in zip(r["ids"][0], r["metadatas"][0], r["documents"][0])}


def ranked(query, companies, years):
    """Dense top CANDIDATES ∪ BM25 top CANDIDATES for one company/year filter, reranked by the cross-encoder."""
    found = dense(get_collection(), query, where_filter(companies, years))
    for i in bm25_top(query, companies, years):  # union with the keyword hits, deduped by chunk_id
        found.setdefault(BM25_IDS[i], {"chunk_id": BM25_IDS[i], **BM25_META[i], "text": BM25_TEXT[i]})
    return rerank(query, found)


@lru_cache(maxsize=32)
def upload_index(upload_id):
    """(ids, metadatas, texts, BM25) of one uploaded PDF, built on the first question about it."""
    got = get_collection("uploads").get(where={"upload_id": upload_id}, include=["documents", "metadatas"])
    texts = got["documents"]
    return got["ids"], got["metadatas"], texts, BM25Okapi([tokens(t) for t in texts]) if texts else None


def ranked_upload(query, upload_id):
    """Same hybrid search + rerank as the library, restricted to one user-uploaded PDF."""
    found = dense(get_collection("uploads"), query, {"upload_id": upload_id})
    ids, metas, texts, bm = upload_index(upload_id)
    for i in best_keyword(bm, query, list(range(len(ids)))):
        found.setdefault(ids[i], {"chunk_id": ids[i], **metas[i], "text": texts[i]})
    return rerank(query, found)


def library_lists(query, company, year):
    """One reranked list per company searched in the report library (company/year auto-detected if not given)."""
    found_companies, found_years = detect(query)
    companies = [company] if company else found_companies
    years = [year] if year else found_years
    if len(companies) > 1:
        # comparison ("TCS vs Infosys"): search each company on its own, so the one whose chunks happen to
        # score higher can't fill every slot (one shared search returned 7 Infosys + 1 TCS chunks)
        return [ranked(query, [c], years) for c in companies]
    return [ranked(query, companies, years)]


_cache = {}  # (query, company, year, upload_id) -> one ranked list per searched company; any top_k is cut from these


def retrieve(query: str, company: str = None, year: str = None, top_k: int = 5, upload_id: str = None) -> list:
    """Best chunks for the query: from one uploaded PDF if upload_id is given, else from the report library."""
    key = (query, company, year, upload_id)
    if key not in _cache:
        _cache[key] = [ranked_upload(query, upload_id)] if upload_id else library_lists(query, company, year)
    lists = _cache[key]
    if len(lists) == 1:
        return lists[0][:top_k]
    share = max(1, top_k // len(lists))  # equal slots per company, e.g. 4 + 4 for top_k=8
    return sorted((h for hits in lists for h in hits[:share]), key=lambda h: -h["score"])


if __name__ == "__main__":
    assert detect("TCS revenue in FY 2023-24 vs FY2019") == (["tcs"], ["2019", "2024"])
    assert detect("HDFC Bank's Gross NPA in FY25") == (["hdfc_bank"], ["2025"])
    assert detect("Infosys headcount in 2019") == (["infosys"], [])  # no Infosys 2019 report indexed

    # question -> the figure the correct chunk contains (Reliance p44 ₹1,309 cr, TCS ₹2,40,893 cr, HDFC 1.33%)
    expected = {
        "What was Reliance's CSR spending?": "1,309 crore",
        "What was TCS revenue in FY2024?": "2,40,893",
        "What was HDFC Bank's Gross NPA?": "1.33",
    }
    found = 0
    for q, answer in expected.items():
        hits = retrieve(q, top_k=8)  # Stage 6 uses top_k=8
        print(f"\nQ: {q}   detected={detect(q)}")
        for rank, h in enumerate(hits, 1):
            mark = "<-- answer" if answer in h["text"] else ""
            print(f"  #{rank} {h['score']:6.2f}  {h['company']} {h['year']} p{h['page_number']}  {mark}")
        hit = any(answer in h["text"] for h in hits)
        found += hit
        print(f"  correct chunk ({answer}) in top 8: {'YES' if hit else 'NO'}")
    print(f"\n{found}/{len(expected)} questions have their correct chunk in the top 8")
    t = time.time()
    retrieve(next(iter(expected)), top_k=8)
    print(f"Repeat query served from cache in {time.time() - t:.4f}s")
