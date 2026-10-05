"""Self-check for chunk.py. Run: python src/test_chunk.py"""
from chunk import SIZE, ntok, table_chunks, text_chunks

long_para = "Revenue grew strongly this year across all segments. " * 60  # ~600 tokens -> sentence split
pages = [
    {"page_number": 1, "text": long_para + "\n\nShort closing paragraph.", "tables": []},
    {"page_number": 2, "text": "word " * 900, "tables": []},  # no sentence ends -> word-level hard cut
]
chunks = text_chunks(pages)

assert all(ntok(t) <= SIZE + 5 for _, t in chunks), [ntok(t) for _, t in chunks]
assert chunks[0][0] == 1 and chunks[-1][0] == 2
for (_, a), (_, b) in zip(chunks, chunks[1:]):
    assert b.split("\n")[0] in a, "chunk must start with the tail of the previous chunk"
assert not any("Revenue grew" in t and t.count("Revenue") != t.count("segments.") for _, t in chunks), "sentence was cut"
# heading context: a subsidiary's figure keeps "[page title > nearest heading]" (HDFC p48 case)
page48 = "POWER OF THE GROUP\n\nFY25 Financials\n\n" + long_para + "\n\nGNPA stood at 1.90 per cent."
sub = text_chunks([{"page_number": 48, "text": page48, "tables": []}])
assert len(sub) > 1 and all(t.startswith("[POWER OF THE GROUP") for _, t in sub)
assert next(t for _, t in sub if "1.90" in t).startswith("[POWER OF THE GROUP > FY25 Financials]\n"), sub[-1]
assert text_chunks([{"page_number": 1, "text": "Plain sentence one. Plain sentence two.", "tables": []}])[0][1].startswith("Plain")

# big table: split on rows, 2-row header ("FY" years under a blank label cell) repeated in every part
table = [["", "FY 2024", "FY 2023"], ["", "Units", "Units"]] + [[f"Item {i}", f"{i},000.5", f"{i},111.2"] for i in range(150)]
parts = table_chunks(table)
assert len(parts) > 1 and all(t.startswith(" | FY 2024 | FY 2023\n | Units | Units\n") for t in parts)
assert sum(t.count("Item ") for t in parts) == 150, "every row exactly once"
assert all(ntok(t) <= SIZE for t in parts)
assert table_chunks(table[:5]) == ["\n".join(" | ".join(r) for r in table[:5])], "small table stays whole"

print(f"chunk checks passed ({len(chunks)} chunks)")
