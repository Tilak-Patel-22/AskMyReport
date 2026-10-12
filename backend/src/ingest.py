"""Parse data/raw_pdfs/<company>/<year>.pdf -> data/parsed/<company>/<year>.json.

Text comes from PyMuPDF, tables from pdfplumber, section headings from font size. Bad pages are logged and skipped.
Run: python src/ingest.py
"""
import json
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pdfplumber
import pymupdf

DATA = Path(__file__).resolve().parent.parent / "data"
RAW, PARSED = DATA / "raw_pdfs", DATA / "parsed"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
errors = []


def warn(msg):
    errors.append(msg)
    logging.warning(msg)


def clean(s):
    # NFKC turns ligatures like "ﬁ" into "fi" and odd spaces into normal ones, so search/embeddings match.
    return unicodedata.normalize("NFKC", s or "").strip()


# Indian reports draw ₹ with special fonts (Rupee, RupeeForadian, ITFRupee) that map the glyph
# to a plain key: ` ‘ H C K I J D L. Any letter/backtick in such a font is really ₹.
RUPEE_KEYS = re.compile(r"[A-Za-z`‘]")


def fix_rupee(font, text):
    return RUPEE_KEYS.sub("₹", text) if "rupee" in font.lower() else text


def page_blocks(page):
    """[(text, font size)] per PyMuPDF block (≈ one paragraph); size = the rounded size most of its characters use.
    Text is rebuilt from spans so rupee-font characters can be fixed."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        lines = block.get("lines", [])
        sizes = Counter()
        for s in (s for line in lines for s in line["spans"]):
            sizes[round(s["size"])] += len(s["text"].strip())
        if sizes.total():
            text = "\n".join("".join(fix_rupee(s["font"], s["text"]) for s in line["spans"]) for line in lines)
            out.append((text, sizes.most_common(1)[0][0]))
    return out


def mark_headings(pages):
    """Headings = blocks in a bigger font than the body text (the size most characters use), running headers included.
    Saved per page; chunk.py carries the last one onto later pages that have none."""
    sizes = Counter()
    for p in pages:
        for t, s in p["blocks"]:
            sizes[s] += len(t)
    body = max(sizes, key=sizes.get, default=0)
    for p in pages:
        p["headings"] = [" ".join(clean(t).split()) for t, s in p.pop("blocks") if s > body]


def parse_pdf(pdf):
    name = f"{pdf.parent.name}/{pdf.name}"
    pages = []
    with pymupdf.open(pdf) as doc, pdfplumber.open(pdf) as plumb:
        for i, page in enumerate(doc):
            n = i + 1
            try:
                blocks = page_blocks(page)
                text = clean("\n\n".join(t for t, _ in blocks))  # blank line between blocks = paragraph break
            except Exception as e:
                warn(f"{name} page {n}: text extraction failed ({e})")
                continue
            if not text:
                warn(f"{name} page {n}: no text layer (scanned/image-only)")
                continue
            try:
                p = plumb.pages[i]
                for c in p.chars:
                    c["text"] = fix_rupee(c["fontname"], c["text"])
                tables = [[[clean(c) for c in row] for row in t] for t in p.extract_tables()]
                # drop empty rows, then tables left empty (decorative boxes pdfplumber mistakes for tables)
                tables = [t for t in ([r for r in t if any(r)] for t in tables) if t]
                p.close()  # frees pdfplumber's per-page cache; without it memory grows over 500+ page reports
            except Exception as e:
                tables = []
                warn(f"{name} page {n}: table extraction failed, text kept ({e})")
            pages.append({"page_number": n, "text": text, "tables": tables, "blocks": blocks})
    mark_headings(pages)
    return {"company": pdf.parent.name, "year": pdf.stem, "pages": pages}


def main():
    pdfs = sorted(RAW.glob("*/*.pdf"))
    done, n_pages, n_tables = 0, 0, 0
    for pdf in pdfs:
        logging.info(f"Parsing {pdf.parent.name}/{pdf.name}")
        try:
            result = parse_pdf(pdf)
        except Exception as e:  # corrupted / unreadable file
            warn(f"{pdf.parent.name}/{pdf.name}: could not open ({e})")
            continue
        out = PARSED / pdf.parent.name / f"{pdf.stem}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        done += 1
        n_pages += len(result["pages"])
        n_tables += sum(len(p["tables"]) for p in result["pages"])

    print("\n===== SUMMARY =====")
    print(f"PDFs processed : {done}/{len(pdfs)}")
    print(f"Pages extracted: {n_pages}")
    print(f"Tables found   : {n_tables}")
    print(f"Errors/skipped : {len(errors)}")
    for e in errors:
        print(f"  - {e}")


if __name__ == "__main__":
    main()
