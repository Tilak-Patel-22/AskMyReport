"""Evaluation harness: retrieval accuracy, generation accuracy and overall accuracy on hand-written questions.

Run from backend/:  python eval/run_evaluation.py [questions.json] [--retry-errors] [--retrieval-only]
  questions.json   default eval/eval_questions.json; results go next to it (eval_results.json, eval_complex_results.json)
  --retry-errors   keep last run's scored questions and re-ask only the ones whose LLM call errored or was skipped
  --retrieval-only score retrieval for every question without calling the LLM (no Groq tokens); generation = "error"
Calls retrieve() and generate_answer() directly (no API server needed) and prints a summary to paste into a report.
Retrieval is scored on the first search only; follow-up searches the LLM asks for show in "searches".
Substring matching is a fast first pass, not a full correctness judgement: read the failure list by hand.

Question fields: question, type, company, year, expected_facts. A fact may be a list of accepted spellings
(["FY18", "FY 2018", "2017-18"]). "expect_refusal": true marks a question the documents can't answer: it passes when
the answer says so, and has no retrieval score.

Groq free tier: per-minute limits are waited out; once the daily limit is hit the remaining questions are marked
"error" (not "fail") so they stay out of the generation/overall scores until --retry-errors picks them up.
"""
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from openai import RateLimitError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))  # the pipeline modules use flat imports ("from retrieve import ...")

from generate import PROVIDERS, TOP_K, generate_answer
from retrieve import retrieve

del PROVIDERS[1:]  # score Groq's model only: no silent fallback to Gemini/Ollama mid-run, and its rate limits reach answer()

# how an answer says "the documents don't have this" (prompt: "say plainly that the documents provided don't contain …")
REFUSALS = (
    "don't contain", "do not contain", "does not contain", "doesn't contain", "not contain", "no information",
    "not provided", "not available", "not mentioned", "not include", "not found", "not given", "not reported",
    "not disclosed", "cannot find", "can't find", "no data",
)


def norm(text):
    """Compare loosely: lower-case, any hyphen/dash = space, one space, no thousands separators inside numbers."""
    text = unicodedata.normalize("NFKC", text).lower().replace("’", "'")  # NFKC also turns no-break spaces into spaces
    text = re.sub(r"[‐-―-]", " ", text)  # "Non‑Performing" (U+2011) == "non performing" == "non-performing"
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"(?<=\d)[,\s](?=\d{2,3}\b)", "", text)  # 2,40,893 == 240,893 == 240893; "FY 2024 2,40,893" stays apart


def missing(facts, texts):
    """Expected facts not found inside any single one of the texts (a list-fact passes if any spelling is found)."""
    normed = [norm(t) for t in texts]
    return [f for f in facts if not any(norm(o) in t for o in (f if isinstance(f, list) else [f]) for t in normed)]


def refused(answer):
    return any(norm(m) in norm(answer) for m in REFUSALS)


class DailyLimit(Exception):
    pass


def answer(q, chunks):
    """generate_answer, waiting out Groq per-minute limits; raises DailyLimit when the daily token cap is reached."""
    for _ in range(5):
        try:
            return generate_answer(q["question"], chunks, q["company"], q["year"])
        except RateLimitError as e:
            msg = str(e)
            wait = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", msg)
            if "per day" in msg or not wait:
                raise DailyLimit(msg) from e
            h, m, s = wait.groups()
            time.sleep(int(h or 0) * 3600 + int(m or 0) * 60 + float(s) + 1)
    raise DailyLimit("still rate-limited after 5 waits")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    q_path = Path(args[0]) if args else HERE / "eval_questions.json"
    stem = q_path.stem.replace("questions", "results") if "questions" in q_path.stem else q_path.stem + "_results"
    out_path = q_path.with_name(stem + ".json")
    questions = json.loads(q_path.read_text(encoding="utf-8"))
    reuse = {}
    if "--retry-errors" in sys.argv and out_path.exists():
        reuse = {r["question"]: r for r in json.loads(out_path.read_text(encoding="utf-8")) if not r["error"]}
    skip_llm = "skipped: --retrieval-only" if "--retrieval-only" in sys.argv else None

    results = []
    for i, q in enumerate(questions, 1):
        if q["question"] in reuse:
            results.append(reuse[q["question"]] | {"id": i})
            print(f"[{i:2d}/{len(questions)}] reused from last run                 {q['question']}")
            continue
        start = time.time()
        chunks = retrieve(q["question"], q["company"], q["year"], top_k=TOP_K)
        refusal = q.get("expect_refusal", False)
        not_retrieved = [] if refusal else missing(q["expected_facts"], [c["text"] for c in chunks])
        reply, sources, searches, error = "", [], [], skip_llm
        if not error:
            try:
                out = answer(q, chunks)
                reply, sources, searches = out["answer"], out["sources"], out["searches"]
            except DailyLimit as e:  # stop calling the LLM for the rest of this run
                error = skip_llm = f"skipped: Groq daily token limit ({str(e)[:80]}…)"
            except Exception as e:  # network, bad key, …: counts as not scored, the run continues
                error = f"{type(e).__name__}: {e}"
        not_answered = [] if refusal and refused(reply) else ["(a clear 'not in the documents')"] if refusal \
            else missing(q["expected_facts"], [reply])
        results.append({
            "id": i,
            "type": q["type"],
            "question": q["question"],
            "company": q["company"],
            "year": q["year"],
            "expected_facts": q["expected_facts"],
            "expect_refusal": refusal,
            "retrieved": "n/a" if refusal else "pass" if not not_retrieved else "fail",
            "missing_from_retrieval": not_retrieved,
            "generated": "error" if error else "pass" if not not_answered else "fail",
            "missing_from_answer": not_answered,
            "answer": reply,
            "sources": sources,
            "searches": searches,
            "error": error,
            "seconds": round(time.time() - start, 1),
        })
        r = results[-1]
        print(f"[{i:2d}/{len(questions)}] retrieval {r['retrieved']:4}  generation {r['generated']:5}  {q['question']}")

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(results, out_path)


def rate(rows, *fields):
    """'NN%' of rows where every given field passed. Rows whose LLM call errored aren't scored on generation; refusal
    questions have no retrieval score ("n/a") and are left out of the retrieval-only column."""
    if "generated" in fields:
        rows = [r for r in rows if r["generated"] != "error"]
    if fields == ("retrieved",):
        rows = [r for r in rows if r["retrieved"] != "n/a"]
    if not rows:
        return "n/a"
    return f"{100 * sum(all(r[f] in ('pass', 'n/a') for f in fields) for r in rows) / len(rows):.0f}%"


def print_summary(results, out_path):
    print("\n## Evaluation results\n")
    print("| # | Type | Question | Retrieval | Generation |")
    print("|---|------|----------|-----------|------------|")
    for r in results:
        print(f"| {r['id']} | {r['type']} | {r['question']} | {r['retrieved']} | {r['generated']} |")

    print("\n| Type | Questions | Retrieval | Generation | Overall |")
    print("|------|-----------|-----------|------------|---------|")
    for t in [*dict.fromkeys(r["type"] for r in results), None]:  # None = all questions
        rows = [r for r in results if t is None or r["type"] == t]
        name = t or "**all**"
        print(
            f"| {name} | {len(rows)} | {rate(rows, 'retrieved')} | {rate(rows, 'generated')} "
            f"| {rate(rows, 'retrieved', 'generated')} |"
        )
    errored = [r for r in results if r["generated"] == "error"]
    if errored:
        print(
            f"\n{len(errored)} question(s) not scored on generation/overall (LLM call failed or skipped): "
            + ", ".join(f"Q{r['id']}" for r in errored)
            + ". Re-run later with --retry-errors."
        )

    failed = [r for r in results if r["retrieved"] == "fail" or r["generated"] == "fail"]
    print(f"\n### Failures to review by hand ({len(failed)})\n")
    for r in failed:
        reasons = []
        if r["missing_from_retrieval"]:
            reasons.append(f"missing from retrieval: {r['missing_from_retrieval']}")
        lost = [f for f in r["missing_from_answer"] if f not in r["missing_from_retrieval"]]
        if lost:
            reasons.append(f"retrieved but not in answer (generation): {lost}")
        print(f"- Q{r['id']} ({r['type']}) {r['question']}\n  - " + "\n  - ".join(reasons))
    print(f"\nFull answers: {out_path}")


if __name__ == "__main__":
    main()
