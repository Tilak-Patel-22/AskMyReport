"""generate_answer(query) -> {"answer", "sources"}: retrieve top 8 chunks, ask an LLM to answer from them only.

LLM: Groq, falling back to Gemini, then a local Ollama model. Keys go in backend/.env (GROQ_API_KEY, GEMINI_API_KEY);
models can be overridden with GROQ_MODEL / GEMINI_MODEL / OLLAMA_MODEL.
Run: python src/generate.py   (manual test with the 3 Stage 5 questions)
"""
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError

from retrieve import CANDIDATES, YEARS, detect, retrieve

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Tried in this order (max_retries=0: call_llm decides what to retry); one without an API key is left out. All three speak the OpenAI API.
# Groq: llama-3.3-70b-versatile was retired on 2026-08-16; Groq's deprecation page names gpt-oss-120b as its replacement.
# Ollama runs locally (`ollama serve`) and ignores the key.
PROVIDERS = [
    (OpenAI(base_url=url, api_key=key, max_retries=0), model)
    for url, key, model in [
        ("https://api.groq.com/openai/v1", os.getenv("GROQ_API_KEY"), os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")),
        ("https://generativelanguage.googleapis.com/v1beta/openai/", os.getenv("GEMINI_API_KEY"),
         os.getenv("GEMINI_MODEL", "gemini-3.8-flash")),
        ("http://localhost:11434/v1", "ollama", os.getenv("OLLAMA_MODEL", "llama3.1:latest")),
    ]
    if key
]


SHORT_WAIT = 15  # seconds: a rate limit that clears this soon is waited out once, keeping the stronger model


def call_llm(messages, **kwargs):
    """Chat completion from the first provider that answers. Any API error (rate limit, bad key, server down, Ollama not
    running) moves on to the next; if all fail, the last error is raised (api.py turns it into a 502). A rate limit
    whose retry-after is within SHORT_WAIT (Groq's per-minute cap, hit by an answer plus its follow-up) is waited out."""
    for client, model in PROVIDERS:
        for attempt in range(2):
            try:
                return client.chat.completions.create(model=model, messages=messages, **kwargs)
            except APIError as e:
                error = e
                limited = isinstance(e, RateLimitError)
                wait = float(e.response.headers.get("retry-after") or "inf") if limited else float("inf")
                if attempt or wait > SHORT_WAIT:
                    break
                time.sleep(wait)
        logging.warning(f"LLM {model} failed ({type(error).__name__}), trying the next provider")
    raise error


TOP_K = 8  # Reliance's CSR answer ranked #7 in Stage 5, outside the default top 5

SEARCHES, NEW_PER_SEARCH = 2, 3  # follow-up searches per question, and new chunks each one adds
# Questions asking for a cause: the document's stated reason usually sits away from the figures the question matches
# (Apple's $10.2B tax charge was 4 chunks after the tax table, 9th for the question). Given a search tool, gpt-oss
# mostly skipped it and invented a reason from other figures, and with the tool required Groq rejected its reply
# (tool_use_failed). So these questions get a plain-text step instead: read the excerpts, then name what's missing.
# ponytail: only causal wording triggers it; other multi-part questions get one search, add a gate if they need more.
CAUSAL = re.compile(r"\b(why|how come|reasons?|caus\w*|explain\w*|led to|drove|driv\w+|due to|despite|even though)\b", re.I)
MISSING = """You will answer a question about a document from the numbered excerpts below, but not yet. First, list
what the excerpts are missing: above all, the reason the document itself gives for a change the question asks about
(the excerpts may show that a figure changed, e.g. a cost or tax that rose, without the document's explanation of it).
Reply with up to 2 short search queries for the missing facts, one per line, nothing else. Keep any company name and
year from the question in each query. If nothing is missing, reply exactly: NONE"""
DISPLAY = {"tcs": "TCS", "hdfc_bank": "HDFC Bank"}  # others read fine as Title Case

SYSTEM = """You answer questions about documents (company annual reports, or a PDF the user uploaded) using ONLY the
numbered excerpts given to you.
Rules:
- Use only facts and numbers that appear in the excerpts. Never use outside knowledge, never guess, never make up example numbers.
- If the excerpts do not contain the answer, say plainly that the documents provided don't contain this information. Do not guess.
- Explain in simple, plain English for someone with no finance background: briefly say what any finance term means.
- Quote real figures exactly as written, with units (₹ crore, %, etc.) and the year they belong to.
- Never convert figures into other units (million, billion, dollars) and never do arithmetic: copy numbers exactly as
  written. You may say "1 crore = 10 million", but do not apply it to any figure.
- If the excerpts give different figures for the same thing (e.g. whole group/consolidated vs company-only/standalone,
  or different years), give each one and say what it covers.
- "This year", "latest" or "current" in a question means the most recent year the excerpts report: answer for that
  year and name it.
- An excerpt may begin with a line like "[Section > Heading > (In millions)]": the part of the document it comes from,
  and the unit its tables are in. A figure under a segment, subsidiary or business-unit section belongs to that part,
  not to the whole company: say whose figure it is. Give table figures with that unit, e.g. "$58,471 million".
- When asked why something changed, explain it with the causes the excerpts state, for that change or for the items
  behind it (profit fell because tax rose; tax rose because of a stated charge). Never invent a cause from other
  figures: costs that grew are not a cause unless the excerpts say so.
- Don't stretch a different fact into an answer (a gain on shares is not an investment received). If the excerpts don't
  show what was asked, say so first; you may then mention the closest related fact as what it is.
- Do not put citation marks (like [1] or 【1】) inside the answer text; cite only on the final Sources line.
- Finish with one last line: "Sources:" followed by the numbers of the excerpts you actually used, e.g. "Sources: [2], [5]".
  If you used none, write "Sources: none"."""


def name(company):
    """Display name: library ids become "HDFC Bank" / "Sun Pharma"; an uploaded file's name is shown as-is."""
    if company not in YEARS:
        return company
    return DISPLAY.get(company, company.replace("_", " ").title())


def label(c):
    """"HDFC Bank, 2025 annual report, page 8" for library chunks; "my-file.pdf, page 8" for uploads (no year)."""
    report = f", {c['year']} annual report" if c["year"] else ""
    return f"{name(c['company'])}{report}, page {c['page_number']}"


def excerpts(chunks):
    """Numbered, labelled chunk texts for an LLM prompt (shared with charts.py)."""
    return "\n\n".join(f"[{i}] {label(c)}:\n{c['text']}" for i, c in enumerate(chunks, 1))


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


def missing_searches(query, chunks):
    """Up to SEARCHES queries for what the excerpts lack to answer a causal question (MISSING); [] if none or no LLM."""
    prompt = f"Excerpts:\n\n{excerpts(chunks)}\n\nQuestion: {query}"
    try:
        reply = call_llm([{"role": "system", "content": MISSING}, {"role": "user", "content": prompt}], temperature=0)
    except APIError as e:  # the follow-up only adds chunks: answer from what we have
        logging.warning(f"follow-up planning failed ({type(e).__name__}); answering from the first search")
        return []
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", s).strip().strip('"') for s in (reply.choices[0].message.content or "").splitlines()]
    return [s for s in lines if s and s.upper() != "NONE"][:SEARCHES]


def generate_answer(query: str, retrieved_chunks: list = None, company=None, year=None, upload_id=None) -> dict:
    """Answer from the chunks. A causal question first gets up to SEARCHES follow-up searches of the same document(s)
    for what the excerpts lack (missing_searches), e.g. the $10.2B EU tax charge behind "why did Apple's profit fall when
    sales grew?"; their new chunks are added before answering."""
    if not upload_id:  # follow-up searches that drop the company or year stay within the question's
        companies, years = detect(query)
        company = company or (companies[0] if len(companies) == 1 else None)
        year = year or (years[0] if len(years) == 1 else None)
    chunks = list(retrieved_chunks if retrieved_chunks is not None else retrieve(query, company, year, TOP_K, upload_id))

    searches = missing_searches(query, chunks) if CAUSAL.search(query) else []
    # a wider pool: JPMorgan's "net income of $58.5 billion, up 18%" overview (reranker score 0.91) wasn't among the
    # 20+20 candidates for "net income drivers" ("JPMorganChase" isn't the keyword "JPMorgan"); at 40+40 it ranked 6th
    with ThreadPoolExecutor(SEARCHES) as pool:
        found = pool.map(lambda q: retrieve(q, company, year, TOP_K, upload_id, candidates=2 * CANDIDATES), searches)
    have = {c["text"] for c in chunks}
    for q, hits in zip(searches, found):
        new = [c for c in hits if c["text"] not in have][:NEW_PER_SEARCH]
        logging.info(f"follow-up search {q!r}: +{len(new)} chunks")
        have |= {c["text"] for c in new}
        chunks += new
    resp = call_llm(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Excerpts:\n\n{excerpts(chunks)}\n\nQuestion: {query}"},
        ],
        temperature=0.3,
    )
    # drop gpt-oss inline cite marks (e.g. 【1†L4-L6】) first, so their digits can't be read as citations; its narrow
    # no-break spaces ("$58.5 billion") render as no space at all in the UI font
    text = re.sub(r"\s*【[^】]*】", "", resp.choices[0].message.content or "").replace(" ", " ").strip()

    # the LLM cites excerpt numbers; we turn them into company/year/page ourselves so page numbers can't be invented
    answer, cited = split_sources(text, len(chunks))
    pages = dict.fromkeys((chunks[n - 1]["company"], chunks[n - 1]["year"], chunks[n - 1]["page_number"]) for n in cited)
    sources = [{"company": c, "year": y, "page_number": p} for c, y, p in pages]  # deduped, in cited order
    # citations travel in "sources" (the UI shows them as chips); "searches" = the follow-up searches that ran
    return {"answer": answer, "sources": sources, "searches": searches}


if __name__ == "__main__":
    for q in ["What was Reliance's CSR spending?", "What was TCS revenue in FY2024?", "What was HDFC Bank's Gross NPA?"]:
        r = generate_answer(q)
        print(f"\n{'=' * 80}\nQ: {q}\n\n{r['answer']}\n\nsources = {r['sources']}")
