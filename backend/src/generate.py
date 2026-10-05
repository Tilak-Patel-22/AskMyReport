"""generate_answer(query) -> {"answer", "sources"}: retrieve top 8 chunks, ask a Groq LLM to answer from them only.

Needs GROQ_API_KEY in backend/.env. Run: python src/generate.py   (manual test with the 3 Stage 5 questions)
"""
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from retrieve import retrieve

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
client = Groq()  # reads GROQ_API_KEY loaded from .env

# llama-3.3-70b-versatile was retired on 2026-08-16; Groq's deprecation page names gpt-oss-120b as its replacement
MODEL = "openai/gpt-oss-120b"
TOP_K = 8  # Reliance's CSR answer ranked #7 in Stage 5, outside the default top 5
DISPLAY = {"tcs": "TCS", "hdfc_bank": "HDFC Bank"}  # others read fine as Title Case

SYSTEM = """You answer questions about company annual reports using ONLY the numbered excerpts given to you.
Rules:
- Use only facts and numbers that appear in the excerpts. Never use outside knowledge, never guess, never make up example numbers.
- If the excerpts do not contain the answer, say plainly that the reports provided don't contain this information. Do not guess.
- Explain in simple, plain English for someone with no finance background: briefly say what any finance term means.
- Quote real figures exactly as written, with units (₹ crore, %, etc.) and the year they belong to.
- Never convert figures into other units (million, billion, dollars) and never do arithmetic: copy numbers exactly as
  written. You may say "1 crore = 10 million", but do not apply it to any figure.
- If the excerpts give different figures for the same thing (e.g. whole group/consolidated vs company-only/standalone,
  or different years), give each one and say what it covers.
- Do not put citation marks (like [1] or 【1】) inside the answer text; cite only on the final Sources line.
- Finish with one last line: "Sources:" followed by the numbers of the excerpts you actually used, e.g. "Sources: [2], [5]".
  If you used none, write "Sources: none"."""


def name(company):
    return DISPLAY.get(company, company.replace("_", " ").title())


def excerpts(chunks):
    """Numbered, labelled chunk texts for an LLM prompt (shared with charts.py)."""
    return "\n\n".join(
        f"[{i}] {name(c['company'])}, {c['year']} annual report, page {c['page_number']}:\n{c['text']}"
        for i, c in enumerate(chunks, 1)
    )


def split_sources(text: str, n_excerpts: int) -> tuple[str, list[int]]:
    """Split the LLM reply into (answer body, cited excerpt numbers).

    Only the last 1–2 non-empty lines are checked: that's where the prompt puts "Sources: [2], [5]". A line counts if,
    after stripping markdown (*, _, #), it starts with "source"; a bare "Sources" heading may carry its numbers on the
    line below. A number anywhere else in the answer is never read as a citation.
    """
    lines = text.split("\n")
    last_two = [i for i, line in enumerate(lines) if line.strip()][-2:]
    for i in reversed(last_two):  # last line first, so a body line that merely begins "Source…" is checked last
        if lines[i].strip().lstrip("*_# \t").lower().startswith("source"):
            cited = dict.fromkeys(int(n) for n in re.findall(r"\d+", "\n".join(lines[i:])))
            return "\n".join(lines[:i]).rstrip(" *\n"), [n for n in cited if 1 <= n <= n_excerpts]
    return text, []


def generate_answer(query: str, retrieved_chunks: list = None) -> dict:
    chunks = retrieved_chunks if retrieved_chunks is not None else retrieve(query, top_k=TOP_K)
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Excerpts:\n\n{excerpts(chunks)}\n\nQuestion: {query}"},
        ],
    )
    # drop gpt-oss inline cite marks (e.g. 【1†L4-L6】) first, so their digits can't be read as citations
    text = re.sub(r"\s*【[^】]*】", "", resp.choices[0].message.content or "").strip()

    # the LLM cites excerpt numbers; we turn them into company/year/page ourselves so page numbers can't be invented
    answer, cited = split_sources(text, len(chunks))
    pages = dict.fromkeys((chunks[n - 1]["company"], chunks[n - 1]["year"], chunks[n - 1]["page_number"]) for n in cited)
    sources = [{"company": c, "year": y, "page_number": p} for c, y, p in pages]  # deduped, in cited order
    return {"answer": answer, "sources": sources}  # citations travel in "sources"; the UI shows them as chips


if __name__ == "__main__":
    for q in ["What was Reliance's CSR spending?", "What was TCS revenue in FY2024?", "What was HDFC Bank's Gross NPA?"]:
        r = generate_answer(q)
        print(f"\n{'=' * 80}\nQ: {q}\n\n{r['answer']}\n\nsources = {r['sources']}")
