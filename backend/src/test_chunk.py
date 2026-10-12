"""Self-check for chunk.py. Run: python src/test_chunk.py"""
from chunk import SIZE, ntok, page_unit, table_chunks, text_chunks

long_para = "Revenue grew strongly this year across all segments. " * 60  # ~600 tokens -> sentence split
pages = [
    {"page_number": 1, "text": long_para + "\n\nShort closing paragraph.", "tables": []},
    {"page_number": 2, "text": "word " * 900, "tables": []},  # no sentence ends -> word-level hard cut
]
chunks, _ = text_chunks(pages)

assert all(ntok(t) <= SIZE + 5 for _, t in chunks), [ntok(t) for _, t in chunks]
assert chunks[0][0] == 1 and chunks[-1][0] == 2
for (_, a), (_, b) in zip(chunks, chunks[1:]):
    assert b.split("\n")[0] in a, "chunk must start with the tail of the previous chunk"
assert not any("Revenue grew" in t and t.count("Revenue") != t.count("segments.") for _, t in chunks), "sentence was cut"
assert text_chunks([{"page_number": 1, "text": "Plain sentence one. Plain sentence two.", "tables": []}])[0][0][1].startswith("Plain")

# section carried across pages: a segment's figure on its 2nd page still names the segment (JPMorgan 10-K p107-108),
# and a page with its own big-font heading doesn't inherit the old one (HDFC p48: a subsidiary's figures)
seg = "CONSUMER & COMMUNITY BANKING"
texts, tables = text_chunks([
    {"page_number": 107, "text": f"{seg}\n\n{long_para}", "tables": [], "headings": [seg]},
    {"page_number": 108, "text": f"2024 compared with 2023\n\n{long_para}\n\nNet income was $17.6 billion.",
     "tables": [[["Net income", "17,641"]]], "headings": []},
    {"page_number": 48, "text": f"POWER OF THE GROUP\n\nFY25 Financials\n\n{long_para}\n\nGNPA stood at 1.90 per cent.",
     "tables": [], "headings": ["POWER OF THE GROUP", "FY25 Financials"]},
])
assert next(t for _, t in texts if "17.6" in t).startswith(f"[{seg} > 2024 compared with 2023]\n")
assert tables == [(108, f"[{seg} > 2024 compared with 2023]\nNet income | 17,641")], tables
assert next(t for _, t in texts if "1.90" in t).startswith("[POWER OF THE GROUP > FY25 Financials]\n")
# a big running header counts as the page's own: the cash-flow section doesn't spread over 60 notes pages (TCS 2024)
notes = "Notes forming part of Standalone Financial Statements"
texts, _ = text_chunks([
    {"page_number": 276, "text": f"Standalone Statement of Cash Flows\n\n{long_para}", "tables": [],
     "headings": ["Standalone Statement of Cash Flows"]},
    {"page_number": 282, "text": f"{notes}\n\n{long_para}\n\nSubsidiaries are consolidated.", "tables": [], "headings": [notes]},
])
assert next(t for _, t in texts if "Subsidiaries" in t).startswith(f"[{notes}]\n")

# unit caption on the page reaches every chunk of it, cut at its first comma (Apple 10-K p32: "Net income $ 93,736")
apple = "CONSOLIDATED STATEMENTS OF OPERATIONS\n\n(In millions, except number of shares, which are reflected in thousands)"
texts, _ = text_chunks([{"page_number": 32, "text": f"{apple}\n\n{long_para}\n\nNet income $ 93,736", "tables": []}])
assert next(t for _, t in texts if "93,736" in t).startswith("[CONSOLIDATED STATEMENTS OF OPERATIONS > (In millions)]\n")
assert page_unit({"text": "Revenue (₹ in crore)"}) == "(₹ in crore)" and page_unit({"text": "grew (₹ 2,40,893 crore)"}) == ""
assert page_unit({"text": "(In ₹ crore)"}) == "(In ₹ crore)" and page_unit({"text": "(Rupees Forty Lakhs only)"}) == ""

# big table: split on rows, 2-row header ("FY" years under a blank label cell) repeated in every part
table = [["", "FY 2024", "FY 2023"], ["", "Units", "Units"]] + [[f"Item {i}", f"{i},000.5", f"{i},111.2"] for i in range(150)]
parts = table_chunks(table)
assert len(parts) > 1 and all(t.startswith(" | FY 2024 | FY 2023\n | Units | Units\n") for t in parts)
assert sum(t.count("Item ") for t in parts) == 150, "every row exactly once"
assert all(ntok(t) <= SIZE for t in parts)
assert table_chunks(table[:5]) == ["\n".join(" | ".join(r) for r in table[:5])], "small table stays whole"

print(f"chunk checks passed ({len(chunks)} chunks)")
