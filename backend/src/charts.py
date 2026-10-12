"""maybe_extract_chart_data(query, chunks) -> chart data for the frontend (Recharts), or None.

Only trend/compare-style questions reach the LLM, and every value must be printed in the chunks or no chart is returned.
Run: python src/charts.py   (manual test)
"""
import json
import re

from generate import call_llm, excerpts

CHART_WORDS = re.compile(
    r"\b(trend\w*|compar\w*|grow\w*|grew|over the years|year[- ]wise|year[- ]on[- ]year|yoy|chart|graph|plot|vs|versus)\b",
    re.I,
)

SYSTEM = """You turn annual-report excerpts into chart data. Reply with one JSON object and nothing else:
{"chart_type": "bar" or "line", "metric_name": "...", "labels": [...], "values": [...], "unit": "..."}
Rules:
- Use ONLY numbers printed in the excerpts. Never estimate, convert units or calculate new numbers.
- values: plain numbers copied from the excerpts with thousands separators removed (₹2,40,893 crore -> 240893).
- All values must be the same metric on the same basis (e.g. all consolidated) and unit; name the basis in metric_name.
- labels: the year (e.g. "FY2024") for a trend, or the company name when comparing companies; one label per value,
  years in time order.
- chart_type "line" for a trend over years, "bar" for comparing companies or categories.
- If the excerpts hold fewer than 2 data points for what was asked, reply exactly {"chart_type": null}."""


def needs_chart(query: str) -> bool:
    return CHART_WORDS.search(query) is not None


def plain(v):
    return str(int(v)) if v.is_integer() else str(v)  # 240893.0 -> "240893", 6.8 -> "6.8"


def maybe_extract_chart_data(query: str, retrieved_chunks: list) -> dict | None:
    if not needs_chart(query):
        return None  # plain factual question: no LLM call
    resp = call_llm(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Excerpts:\n\n{excerpts(retrieved_chunks)}\n\nQuestion: {query}"},
        ],
        temperature=0,
    )
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)  # skips ```json fences / text around it
    try:
        data = json.loads(m.group(0)) if m else {}
        values = [float(str(v).replace(",", "")) for v in data.get("values") or []]
    except (json.JSONDecodeError, ValueError):
        return None
    labels = [str(x) for x in data.get("labels") or []]
    if data.get("chart_type") not in ("bar", "line") or len(values) < 2 or len(values) != len(labels):
        return None
    # last guard against invented numbers: each value must literally appear in the chunks (commas ignored)
    text = "".join(c["text"] for c in retrieved_chunks).replace(",", "")
    if not all(plain(abs(v)) in text for v in values):
        return None
    if data["chart_type"] == "line":  # LLM sometimes lists years newest-first; a trend line must run oldest -> newest
        labels, values = map(list, zip(*sorted(zip(labels, values))))
    return {
        "chart_type": data["chart_type"],
        "metric_name": str(data.get("metric_name") or ""),
        "labels": labels,
        "values": [int(v) if v.is_integer() else v for v in values],
        "unit": str(data.get("unit") or ""),
    }


if __name__ == "__main__":
    from retrieve import retrieve

    assert needs_chart("Compare TCS revenue across the years") and needs_chart("TCS vs Infosys margin")
    assert needs_chart("How has HDFC Bank's NPA trended?") and not needs_chart("What was TCS revenue in FY2024")
    for q in ["Compare TCS revenue across the years in the report", "What was TCS revenue in FY2024"]:
        print(f"\nQ: {q}\n-> {maybe_extract_chart_data(q, retrieve(q, top_k=8))}")
