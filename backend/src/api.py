"""FastAPI app for the React frontend.

/health, /companies, /ask (answer + sources + optional chart, from the report library or one uploaded PDF),
/upload (index a user's PDF), /history/{session_id} (restore a browser's earlier chat; stored in SQLite).
"""
import json
import logging
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing
from pathlib import Path

# uvicorn imports this file as "src.api"; every module here uses flat imports ("from retrieve import ..."), so put src/ on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from groq import APIError
from pydantic import BaseModel

import uploads
from charts import maybe_extract_chart_data
from generate import TOP_K, generate_answer, name
from retrieve import YEARS, retrieve
from vectorstore import BACKEND, get_collection

log = logging.getLogger("uvicorn.error")
HISTORY_DB = BACKEND / "data" / "history.db"
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")  # the frontend sends crypto.randomUUID()
llm_pool = ThreadPoolExecutor(max_workers=8)


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


def history_db():
    con = sqlite3.connect(HISTORY_DB)  # a short-lived connection per call: safe across FastAPI's worker threads
    con.execute(
        "CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, created REAL,"
        " query TEXT, answer TEXT, sources TEXT, chart TEXT)"
    )
    con.execute("CREATE INDEX IF NOT EXISTS turns_session ON turns (session_id)")
    return con


def check_session(session_id):
    if not SESSION_ID.match(session_id):
        raise HTTPException(400, "invalid session_id")


class AskRequest(BaseModel):
    query: str | None = None  # optional here so a missing query gets our clear 400, not a generic 422
    session_id: str | None = None  # when set, the turn is saved for /history
    upload_id: str | None = None  # from /upload: answer only from that PDF (company/year are then ignored)
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
    if req.session_id:
        check_session(req.session_id)
    if req.upload_id:
        if not uploads.exists(req.upload_id):
            raise HTTPException(400, "unknown upload_id; please upload the PDF again")
        chunks = retrieve(query, top_k=TOP_K, upload_id=req.upload_id)
    else:
        if req.company and req.company not in YEARS:
            raise HTTPException(400, f"unknown company '{req.company}'; see GET /companies")
        if req.year and req.year not in YEARS.get(req.company, set().union(*YEARS.values())):
            raise HTTPException(400, f"no report for year '{req.year}'; see GET /companies")
        chunks = retrieve(query, req.company, req.year, top_k=TOP_K)

    try:
        # the answer and the chart are independent LLM calls on the same chunks: run them side by side
        answer_job = llm_pool.submit(generate_answer, query, chunks)
        chart = maybe_extract_chart_data(query, chunks)
        result = answer_job.result()
    except APIError as e:  # Groq down / rate-limited / bad key
        raise HTTPException(502, f"LLM call failed: {e}") from e
    response = {"answer": result["answer"], "sources": result["sources"], "chart": chart}

    if req.session_id:
        with closing(history_db()) as con, con:
            con.execute(
                "INSERT INTO turns (session_id, created, query, answer, sources, chart) VALUES (?, ?, ?, ?, ?, ?)",
                (req.session_id, time.time(), query, response["answer"], json.dumps(response["sources"]), json.dumps(chart)),
            )
    return response


@app.post("/upload")
def upload(file: UploadFile = File(...)):  # parse + chunk + embed: ~1-3 min for a 300-page report on CPU
    data = file.file.read(uploads.MAX_BYTES + 1)  # one byte over the limit is enough to reject it
    try:
        return uploads.index_pdf(data, file.filename)
    except uploads.UploadError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/history/{session_id}")
def history(session_id: str):
    """This browser's last 50 turns, oldest first, in the shape the frontend restores: {query, answer, sources, chart}."""
    check_session(session_id)
    with closing(history_db()) as con:
        rows = con.execute(
            "SELECT query, answer, sources, chart FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT 50", (session_id,)
        ).fetchall()
    return [{"query": q, "answer": a, "sources": json.loads(s), "chart": json.loads(c)} for q, a, s, c in reversed(rows)]


# Run (from inside /backend/):  uvicorn src.api:app --reload --port 8000
