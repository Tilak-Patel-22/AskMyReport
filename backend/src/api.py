"""FastAPI app: /health, /companies, /ask (answer + sources + optional chart) for the React frontend."""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# uvicorn imports this file as "src.api"; every module here uses flat imports ("from retrieve import ..."), so put src/ on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from groq import APIError
from pydantic import BaseModel

from charts import maybe_extract_chart_data
from generate import TOP_K, generate_answer, name
from retrieve import YEARS, retrieve
from vectorstore import get_collection

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app):
    # fail at startup, not on the first request: get_or_create makes an empty collection if backend/vectorstore is gone
    count = get_collection().count()
    if count == 0:
        raise RuntimeError("ChromaDB collection 'askmyreport' is empty or missing - run: python src/vectorstore.py")
    log.info(f"ChromaDB collection 'askmyreport' reachable: {count} chunks")
    yield


app = FastAPI(title="AskMyReport", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"]
)


class AskRequest(BaseModel):
    query: str | None = None  # optional here so a missing query gets our clear 400, not a generic 422
    company: str | None = None  # folder id from /companies, e.g. "hdfc_bank"
    year: str | None = None  # fiscal year end, e.g. "2024"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/companies")
def companies():
    # YEARS is retrieve.py's scan of data/chunks/<company>/<year>.json; "company" is the id /ask expects
    return [{"company": c, "name": name(c), "years": sorted(YEARS[c])} for c in sorted(YEARS)]


@app.post("/ask")
def ask(req: AskRequest):  # plain def: models + Groq calls block, so FastAPI runs this in a worker thread
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(400, "query is required and must not be empty")
    if req.company and req.company not in YEARS:
        raise HTTPException(400, f"unknown company '{req.company}'; see GET /companies")
    if req.year and req.year not in YEARS.get(req.company, set().union(*YEARS.values())):
        raise HTTPException(400, f"no report for year '{req.year}'; see GET /companies")

    chunks = retrieve(query, req.company, req.year, top_k=TOP_K)
    try:
        result = generate_answer(query, chunks)
        chart = maybe_extract_chart_data(query, chunks)
    except APIError as e:  # Groq down / rate-limited / bad key
        raise HTTPException(502, f"LLM call failed: {e}") from e
    return {"answer": result["answer"], "sources": result["sources"], "chart": chart}


# Run (from inside /backend/):  uvicorn src.api:app --reload --port 8000
