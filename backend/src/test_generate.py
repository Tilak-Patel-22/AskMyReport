"""Self-check for generate_answer's follow-up search, with a fake LLM and fake search. Run: python src/test_generate.py"""
from types import SimpleNamespace as NS

import generate


def chunk(text, page):
    return {"chunk_id": text, "company": "a.pdf", "year": "", "page_number": page, "text": text}


def reply(text):
    return NS(choices=[NS(message=NS(content=text))])


prompts = []


def fake_llm(messages, **kwargs):
    prompts.append(messages[1]["content"])
    if messages[0]["content"] == generate.MISSING:  # step 1: the LLM names what the excerpts lack
        return reply("1. reason income tax rose 2024\nNONE")
    return reply("Tax rose on a one-time charge.\nSources: [3]")


generate.call_llm = fake_llm
generate.retrieve = lambda q, *a, **k: [chunk("Tax was 29,749.", 27), chunk("One-time $10.2 billion State Aid charge.", 43)]
first = [chunk("Net income 93,736.", 32), chunk("Tax was 29,749.", 27)]
out = generate.generate_answer("Why did profit fall?", first, upload_id="u")
assert out["searches"] == ["reason income tax rose 2024"], out["searches"]
assert "State Aid" in prompts[-1] and prompts[-1].count("Tax was 29,749.") == 1, "new chunk added once, no duplicate"
assert out["sources"] == [{"company": "a.pdf", "year": "", "page_number": 43}], "citation [3] maps to the new chunk"

prompts.clear()
out = generate.generate_answer("What was net income?", first, upload_id="u")  # not causal: one call, no follow-up
assert len(prompts) == 1 and out["searches"] == []
print("generate checks passed")
