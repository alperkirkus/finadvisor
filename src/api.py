"""HTTP layer over the analysis engine.

Thin by design: it caches, validates input and translates exceptions into
status codes. Every number still comes from `report.build`, and the only
route that costs money is the explicit analyze call.
"""
import os
import re
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import analyst
import edgar
import interpret
import report
import ranking as ranking_mod
import valuation as valuation_mod
import verdict as verdict_mod

app = FastAPI(title="FinAdvisor API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z.\-]{0,9}$")

# Building a package parses a multi-megabyte filing set, so the result is
# held briefly. Filings only change quarterly; the window just protects
# against a user hammering the same ticker.
_CACHE = {}
_TTL = 900

# Quotes move during the session, so the priced view is cached far more
# briefly than the filing-derived package it builds on.
_PRICE_CACHE = {}
_PRICE_TTL = 60


def _clean(ticker):
    if not TICKER_RE.match(ticker or ""):
        raise HTTPException(400, "gecersiz ticker")
    return ticker.upper()


def _package(ticker, quarters):
    key = (ticker, quarters)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    try:
        pkg = report.build(ticker, quarters)
    except KeyError:
        raise HTTPException(404, "ticker SEC kayitlarinda bulunamadi: %s" % ticker)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    _CACHE[key] = (time.time(), pkg)
    return pkg


def _llm_ready():
    analyst._load_env()
    return analyst._is_real_key(os.environ.get("ANTHROPIC_API_KEY") or "")


@app.get("/api/health")
def health():
    return {"ok": True, "llm_configured": _llm_ready()}


@app.get("/api/company/{ticker}")
def company(ticker: str, quarters: int = 20):
    ticker = _clean(ticker)
    if not 4 <= quarters <= 60:
        raise HTTPException(400, "quarters 4 ile 60 arasinda olmali")
    return _package(ticker, quarters)


def _filers():
    """The SEC ticker file, cached in memory. Ordered largest first."""
    if not hasattr(_filers, "rows"):
        edgar.resolve_cik("AAPL")   # ensures the file is on disk
        import json
        table = json.load(open(os.path.join(edgar.CACHE, "tickers.json")))
        _filers.rows = [{"ticker": r["ticker"], "name": r["title"],
                         "cik": r["cik_str"]} for r in table.values()]
    return _filers.rows


@app.get("/api/search")
def search(q: str = "", limit: int = 40):
    """Search the SEC filer list, or browse it when no query is given.

    An empty query returns the head of the list rather than nothing: the
    file is ordered by size, so that is a useful "what can I look at"
    answer, and `total` lets the caller say how much else is reachable.
    """
    rows = _filers()
    limit = max(1, min(limit, 200))
    if not q.strip():
        return {"results": rows[:limit], "total": len(rows), "browsing": True}

    ql = q.strip().lower()
    exact, prefix, partial = [], [], []
    for r in rows:
        tick, name = r["ticker"].lower(), r["name"].lower()
        if tick == ql:
            exact.append(r)
        elif tick.startswith(ql) or name.startswith(ql):
            prefix.append(r)
        elif ql in name or ql in tick:
            partial.append(r)
    hits = exact + prefix + partial
    return {"results": hits[:limit], "total": len(hits), "browsing": False}


@app.get("/api/interpret/{ticker}")
def interpretation(ticker: str, quarters: int = 20):
    """Rule-based read. No model call, no cost, no key required."""
    ticker = _clean(ticker)
    pkg = _package(ticker, quarters)
    return {"company": pkg["company"], "as_of": pkg["as_of"],
            "interpretation": interpret.interpret(pkg)}


@app.get("/api/ranking")
def ranking(limit: int = 10):
    """Best-scoring companies from the precomputed screen.

    The ranking is built offline by `ranking.py` because scoring a universe
    means a live quote and a beta regression per company; serving it from a
    file keeps the endpoint instant and the numbers consistent between the
    list and the company page.
    """
    payload = ranking_mod.load()
    if not payload:
        return {"rows": [], "generated_at": None,
                "note": "siralama henuz olusturulmadi: python src/ranking.py"}
    limit = max(1, min(limit, 50))
    return {"generated_at": payload["generated_at"],
            "universe_size": payload["universe_size"],
            "rows": payload["rows"][:limit]}


@app.get("/api/valuation/{ticker}")
def valuation(ticker: str, quarters: int = 40):
    """Priced view: multiples, DCF, reverse DCF, verdict, quarter projection.

    Ten years by default rather than five: the normalised cash-flow margin
    and the growth estimate both need a full cycle, and a five-year window
    on a cyclical business measures the cycle instead of the business.
    """
    ticker = _clean(ticker)
    pkg = _package(ticker, quarters)

    hit = _PRICE_CACHE.get(ticker)
    if hit and time.time() - hit[0] < _PRICE_TTL:
        val = hit[1]
    else:
        try:
            val = valuation_mod.value(pkg)
        except RuntimeError as exc:
            # The business assessment stands on its own without a price, so a
            # quote failure degrades the response instead of failing it.
            return {"company": pkg["company"], "as_of": pkg["as_of"],
                    "valuation": None, "price_error": str(exc),
                    "verdict": verdict_mod.assess(pkg, None)}
        _PRICE_CACHE[ticker] = (time.time(), val)

    return {"company": pkg["company"], "as_of": pkg["as_of"],
            "valuation": val, "verdict": verdict_mod.assess(pkg, val)}


@app.post("/api/analyze/{ticker}")
def analyze(ticker: str, quarters: int = 20, effort: str = "high"):
    ticker = _clean(ticker)
    pkg = _package(ticker, quarters)
    if not _llm_ready():
        raise HTTPException(503, "Gecerli bir ANTHROPIC_API_KEY yok. .env "
                                 "dosyasindaki ornek deger degistirilmemis "
                                 "olabilir -- console.anthropic.com/settings/keys")
    try:
        parsed, usage = analyst.analyze(pkg, effort)
    except Exception as exc:
        raise HTTPException(502, "analiz basarisiz: %s" % exc)
    return {"company": pkg["company"], "as_of": pkg["as_of"],
            "analysis": parsed.model_dump(),
            "usage": {"input_tokens": usage.input_tokens,
                      "output_tokens": usage.output_tokens,
                      "cache_read": usage.cache_read_input_tokens}}
