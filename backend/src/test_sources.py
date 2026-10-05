"""Self-check for generate.split_sources. Run: python src/test_sources.py"""
from generate import split_sources

cases = [
    ("Revenue was ₹2,40,893 crore.\n\nSources: [2], [5]", "Revenue was ₹2,40,893 crore.", [2, 5]),
    ("Answer.\n\n**Sources**\n[3]", "Answer.", [3]),  # heading, numbers on the next line (the TCS case)
    ("Answer.\n\n**Sources**: 1, 3, 1", "Answer.", [1, 3]),  # bold + colon, plain numbers, deduped
    ("Answer.\n\n### Source\n[2], [4]", "Answer.", [2, 4]),
    ("Answer.\n\nsources - [6]", "Answer.", [6]),  # no colon, lower case
    ("Answer.\n\nSources: none", "Answer.", []),
    ("Answer.\n\nSources: [9], [2]", "Answer.", [2]),  # 9 is not an excerpt number (only 8 given)
    # numbers mid-answer are never citations when the last lines aren't a Sources line
    ("Revenue grew 6.8% in FY 2024 [2].\n\nGNPA was 1.33 per cent.", "Revenue grew 6.8% in FY 2024 [2].\n\nGNPA was 1.33 per cent.", []),
    # a body line that merely begins "Source…" stays in the answer when the real Sources line follows it
    ("Source of funds: ₹500 crore.\nSources: [1]", "Source of funds: ₹500 crore.", [1]),
]
for text, body, cited in cases:
    assert split_sources(text, 8) == (body, cited), (text, split_sources(text, 8))
print(f"split_sources checks passed ({len(cases)} cases)")
