"""Split data/parsed/<company>/<year>.json -> data/chunks/<company>/<year>.json.

Text: ~400-token chunks with 80-token overlap, cut at paragraph > sentence > word boundaries.
Tables: one chunk per table; tables over SIZE split on row boundaries with the header repeated.
Every chunk is prefixed with "[page title > nearest heading]" (tables: page title) for context.
Run: python src/chunk.py
"""
import json
import re
from pathlib import Path

import tiktoken

DATA = Path(__file__).resolve().parent.parent / "data"
PARSED, CHUNKS = DATA / "parsed", DATA / "chunks"
SIZE, OVERLAP, HEADING = 400, 80, 30
BODY = SIZE - OVERLAP - HEADING  # new text per chunk; the heading line and the previous chunk's overlap fill the rest
BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n")  # sentence end, or "\n" = paragraph break inside a chunk

enc = tiktoken.get_encoding("cl100k_base")


def ntok(s):
    return len(enc.encode(s))


def pack(items, budget):
    """Greedily group (item, n_tokens) pairs; each group's tokens (+1 per joining separator) stay <= budget,
    except an item that is bigger than the budget on its own, which gets a group to itself."""
    groups, cur, size = [], [], 0
    for item, n in items:
        if cur and size + n > budget:
            groups.append(cur)
            cur, size = [], 0
        cur.append(item)
        size += n + 1
    return groups + [cur] if cur else groups


def fit(text):
    """Split a paragraph into sentences, and over-long sentences at word boundaries, until each piece <= BODY."""
    if ntok(text) <= BODY:
        return [text]
    sentences = BOUNDARY.split(text)
    if len(sentences) > 1:
        return [p for s in sentences for p in fit(s)]
    # hard cut, never mid-word; " w" usually encodes to one token with its space, and pack adds +1 per separator
    return [" ".join(g) for g in pack([(w, ntok(" " + w) - 1) for w in text.split()], BODY)]


def tail(text):
    """Longest run of whole trailing sentences/paragraphs within OVERLAP tokens; last OVERLAP tokens if none fit."""
    for m in BOUNDARY.finditer(text):
        if ntok(text[m.end():]) <= OVERLAP:
            return text[m.end():]
    s = enc.decode(enc.encode(text)[-OVERLAP:])
    return s[s.find(" ") + 1:]  # drop the partial first word (a token cut can split a word or multi-byte char)


def paragraphs(page):
    return [s for s in (" ".join(x.split()) for x in page["text"].split("\n\n")) if s]  # PDF line breaks -> spaces


def is_heading(para):
    # short, no closing full stop, real words: "POWER OF THE GROUP", "FY25 Financials", "Directors' Report"
    return len(para.split()) <= 8 and not para.endswith(".") and re.search(r"[A-Za-z]{3}", para) is not None


def page_title(page):
    return next((s for s in paragraphs(page) if is_heading(s)), "")


def text_chunks(pages):
    """[(page_number, text)] running continuously across pages; page_number = page the chunk starts on.
    Each chunk starts with "[page title > nearest heading above it]" so e.g. a subsidiary's figures keep their context."""
    pieces = []
    for p in pages:
        title = heading = page_title(p)
        for para in paragraphs(p):
            heading = para if is_heading(para) else heading
            context = title if heading == title else f"{title} > {heading}"
            pieces += [(p["page_number"], s, ntok(s), context) for s in fit(para)]

    out, prev = [], ""
    for g in pack([(p, p[2]) for p in pieces], BODY):
        body = "\n".join(p[1] for p in g)
        head = f"[{g[0][3]}]\n" if g[0][3] else ""
        out.append((g[0][0], head + (f"{tail(prev)}\n{body}" if prev else body)))
        prev = body
    return out


AMOUNT = re.compile(r"\d[,.]\d")  # 12,50,000 or 58.2 -> a data row, not a header


def table_chunks(table):
    """Whole table if it fits in SIZE; else split on row boundaries with the header rows repeated in every part."""
    rows = [" | ".join(" ".join(c.split()) for c in row) for row in table]
    whole = "\n".join(rows)
    if ntok(whole) <= SIZE:
        return [whole]
    # ponytail: header = row 0 + up to 2 rows with a blank label cell and no amounts ("Standalone" over "FY 2024");
    # heuristic, an odd layout may repeat one data row or miss a header row
    h = 1
    while h < min(3, len(table)) and not table[h][0].strip() and not any(AMOUNT.search(c) for c in table[h]):
        h += 1
    header = "\n".join(rows[:h])
    parts = pack([(r, ntok(r)) for r in rows[h:]], SIZE - ntok(header) - 1)  # rows are never split
    return [f"{header}\n" + "\n".join(p) for p in parts] or [whole]


def doc_chunks(doc, prefix=None):
    """All chunks of one parsed document (text + table chunks, in page order) and how many came from tables.
    Used for the report library (main) and for user-uploaded PDFs (uploads.py)."""
    texts = text_chunks(doc["pages"])
    tables = []
    for p in doc["pages"]:
        head = f"[{title}]\n" if (title := page_title(p)) else ""
        tables += [(p["page_number"], head + part) for t in p["tables"] for part in table_chunks(t)]
    items = sorted(texts + tables, key=lambda x: x[0])  # stable sort: page order, text before its page's tables
    prefix = prefix or f"{doc['company']}_{doc['year']}"
    chunks = [
        {"company": doc["company"], "year": doc["year"], "page_number": pg, "chunk_id": f"{prefix}_{i}", "text": t}
        for i, (pg, t) in enumerate(items)
    ]
    return chunks, len(tables)


def main():
    total = n_tables = tokens = 0
    for f in sorted(PARSED.glob("*/*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        chunks, n_doc_tables = doc_chunks(doc)
        prefix = f"{doc['company']}_{doc['year']}"
        out = CHUNKS / f.parent.name / f.name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
        total += len(chunks)
        n_tables += n_doc_tables
        tokens += sum(ntok(c["text"]) for c in chunks)
        print(f"{prefix}: {len(chunks)} chunks ({n_doc_tables} tables)")

    print("\n===== SUMMARY =====")
    print(f"Total chunks      : {total}")
    print(f"Avg chunk size    : {tokens / max(total, 1):.0f} tokens")
    print(f"Table chunks      : {n_tables}")
    print(f"Plain-text chunks : {total - n_tables}")


if __name__ == "__main__":
    main()
