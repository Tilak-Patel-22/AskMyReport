"""Evaluation harness: retrieval accuracy, generation accuracy and overall accuracy on hand-written questions.

Run from backend/:  python eval/run_evaluation.py  [--retry-errors]
Calls retrieve() and generate_answer() directly (no API server needed). Writes eval/eval_results.json and prints a
summary to paste into the project report. Substring matching is a fast first pass, not a full correctness judgement:
read the failure list by hand.

An LLM call that errors (e.g. Groq's 200k tokens/day free limit) is marked "error", not "fail", and is left out of the
generation/overall scores. --retry-errors keeps last run's scored questions and re-asks only the errored ones.
"""
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))  # the pipeline modules use flat imports ("from retrieve import ...")

from generate import TOP_K, generate_answer
from retrieve import retrieve


def norm(text):
    """Compare loosely: lower-case, any hyphen/dash = space, one space, no thousands separators inside numbers."""
    text = unicodedata.normalize("NFKC", text).lower()  # also turns no-break / narrow spaces into plain spaces
    text = re.sub(r"[‐-―-]", " ", text)  # "Non‑Performing" (U+2011) == "non performing" == "non-performing"
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"(?<=\d)[,\s](?=\d{2,3}\b)", "", text)  # 2,40,893 == 240,893 == 240893; "FY 2024 2,40,893" stays apart


def missing(facts, texts):
    """Expected facts not found inside any single one of the texts."""
    normed = [norm(t) for t in texts]
    return [f for f in facts if not any(norm(f) in t for t in normed)]


def main():
    questions = json.loads((HERE / "eval_questions.json").read_text(encoding="utf-8"))
    out_path = HERE / "eval_results.json"
    reuse = {}
    if "--retry-errors" in sys.argv and out_path.exists():
        reuse = {r["question"]: r for r in json.loads(out_path.read_text(encoding="utf-8")) if not r["error"]}
    results = []
    for i, q in enumerate(questions, 1):
        if q["question"] in reuse:
            results.append(reuse[q["question"]] | {"id": i})
            print(f"[{i:2d}/{len(questions)}] reused from last run                 {q['question']}")
            continue
        start = time.time()
        chunks = retrieve(q["question"], q["company"], q["year"], top_k=TOP_K)
        not_retrieved = missing(q["expected_facts"], [c["text"] for c in chunks])
        try:
            out = generate_answer(q["question"], chunks)
            answer, sources, error = out["answer"], out["sources"], None
        except Exception as e:  # e.g. Groq rate limit or network: counts as a generation failure, the run continues
            answer, sources, error = "", [], f"{type(e).__name__}: {e}"
        not_answered = missing(q["expected_facts"], [answer])
        results.append({
            "id": i,
            "type": q["type"],
            "question": q["question"],
            "company": q["company"],
            "year": q["year"],
            "expected_facts": q["expected_facts"],
            "retrieved": "pass" if not not_retrieved else "fail",
            "missing_from_retrieval": not_retrieved,
            "generated": "error" if error else "pass" if not not_answered else "fail",
            "missing_from_answer": not_answered,
            "answer": answer,
            "sources": sources,
            "error": error,
            "seconds": round(time.time() - start, 1),
        })
        r = results[-1]
        print(f"[{i:2d}/{len(questions)}] retrieval {r['retrieved']:4}  generation {r['generated']:4}  {q['question']}")

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(results)


def rate(rows, *fields):
    """'NN%' of rows where every given field passed; rows whose LLM call errored aren't scored on generation."""
    if "generated" in fields:
        rows = [r for r in rows if r["generated"] != "error"]
    if not rows:
        return "n/a"
    return f"{100 * sum(all(r[f] == 'pass' for f in fields) for r in rows) / len(rows):.0f}%"


def print_summary(results):
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
            f"\n{len(errored)} question(s) not scored on generation/overall (LLM call failed): "
            + ", ".join(f"Q{r['id']}" for r in errored)
            + ". Re-run later with --retry-errors."
        )

    failed = [r for r in results if r["retrieved"] != "pass" or r["generated"] != "pass"]
    print(f"\n### Failures to review by hand ({len(failed)})\n")
    for r in failed:
        reasons = []
        if r["missing_from_retrieval"]:
            reasons.append(f"missing from retrieval: {r['missing_from_retrieval']}")
        lost = [f for f in r["missing_from_answer"] if f not in r["missing_from_retrieval"]]
        if r["error"]:  # no answer at all, so "lost" facts would be noise
            reasons.append(f"not scored, LLM error: {r['error'][:110]}…")
        elif lost:
            reasons.append(f"retrieved but not in answer (generation): {lost}")
        print(f"- Q{r['id']} ({r['type']}) {r['question']}\n  - " + "\n  - ".join(reasons))
    print("\nFull answers: eval/eval_results.json")


if __name__ == "__main__":
    main()
