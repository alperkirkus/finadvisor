"""HTTP layer over the analysis engine.

Thin by design: it caches, validates input and translates exceptions into
status codes. Every number still comes from `report.build`, and the only
route that costs money is the explicit analyze call.
"""
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import analyst
import edgar
import interpret
import report
import ranking as ranking_mod
import regime
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


def _wait_order(key):
    return (0, 0) if key == "near" else (2, 0) if key == "long" else (1, int(key))


RISK_LABELS = {"q1": "Çok düşük", "q2": "Düşük", "q3": "Orta", "q4": "Yüksek",
               "q5": "Çok yüksek"}


@app.get("/api/ranking")
def ranking(limit: int = 10, offset: int = 0, wait: Optional[str] = None,
            risk: Optional[str] = None):
    """The precomputed screen: its order, and what an earlier run said.

    The order is built offline by `ranking.py` because scoring a universe
    means a live quote and a beta regression per company. The file's prices
    are those of the run, so they are served as a dated record
    (`previous`), never as today's: the list reads today's from `/api/live`.
    `wait` keeps the rows whose fair-value target has taken that long,
    `risk` those in that fall-risk group.
    """
    payload = ranking_mod.load()
    if not payload:
        return {"rows": [], "generated_at": None,
                "note": "siralama henuz olusturulmadi: python src/ranking.py"}
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    rows = [dict(r, rank=i + 1) for i, r in enumerate(payload["rows"])]
    counts = Counter(r["wait"] for r in rows if r.get("wait"))
    risks = Counter(r["risk"] for r in rows if r.get("risk"))
    if wait is not None:
        if wait not in counts:
            raise HTTPException(400, "gecersiz bekleme filtresi: %s" % wait)
        rows = [r for r in rows if r.get("wait") == wait]
    if risk is not None:
        if risk not in risks:
            raise HTTPException(400, "gecersiz risk filtresi: %s" % risk)
        rows = [r for r in rows if r.get("risk") == risk]
    # The run a row is compared with is the latest one at least a day old:
    # this run once it has aged, the one before it until then.
    previous = (ranking_mod.baseline(payload) or payload.get("previous")
                or {"generated_at": None, "rows": {}})
    page = rows[offset:offset + limit]
    for r in page:
        r["previous"] = previous["rows"].get(r["ticker"])
    return {"generated_at": payload["generated_at"],
            "previous_generated_at": previous["generated_at"],
            "universe_size": payload["universe_size"],
            "total": len(rows),
            "offset": offset,
            "wait_options": [{"key": k, "label": verdict_mod.wait_label(k),
                              "count": counts[k]}
                             for k in sorted(counts, key=_wait_order)],
            "risk_options": [{"key": k, "label": RISK_LABELS[k], "count": risks[k]}
                             for k in RISK_LABELS if k in risks],
            "rows": page}


@app.get("/api/market")
def market():
    """S&P 500 against its 200-day average, with the backtest behind the rule."""
    try:
        return regime.read()
    except Exception as exc:
        raise HTTPException(503, "piyasa verisi alinamadi: %s" % exc)


@app.get("/api/valuation/{ticker}")
def valuation(ticker: str, quarters: int = 40):
    """Priced view: multiples, DCF, reverse DCF, verdict, quarter projection.

    Ten years by default rather than five: the normalised cash-flow margin
    and the growth estimate both need a full cycle, and a five-year window
    on a cyclical business measures the cycle instead of the business.
    """
    ticker = _clean(ticker)
    pkg, val, price_error = _priced(ticker, quarters)
    out = {"company": pkg["company"], "as_of": pkg["as_of"],
           "valuation": val,
           "verdict": verdict_mod.assess(pkg, val, _prior(ticker), _risk_cuts())}
    if price_error:
        out["price_error"] = price_error
    return out


_RUN = {"mtime": None, "prior": {}, "cuts": None}


def _last_run():
    """What the verdict reads from the latest screen run, reloaded when the
    file changes: each ticker's previous reading and the daily-range fifths."""
    try:
        mtime = os.path.getmtime(ranking_mod.OUTPUT)
    except OSError:
        return {"prior": {}, "cuts": None}
    if _RUN["mtime"] != mtime:
        payload = ranking_mod.load()
        _RUN.update(mtime=mtime, prior=ranking_mod.prior_state(payload),
                    cuts=ranking_mod.risk_cuts(payload))
    return _RUN


def _prior(ticker):
    return _last_run()["prior"].get(ticker)


def _risk_cuts():
    return _last_run()["cuts"]


def _priced(ticker, quarters=40):
    """(package, valuation, price error) at the current quote.

    The company page and the live list both come through here and share
    its cache, which is what keeps a row and the page it opens identical.
    """
    pkg = _package(ticker, quarters)
    hit = _PRICE_CACHE.get((ticker, quarters))
    if hit and time.time() - hit[0] < _PRICE_TTL:
        return pkg, hit[1], None
    try:
        val = valuation_mod.value(pkg)
    except RuntimeError as exc:
        # The business assessment stands on its own without a price, so a
        # quote failure degrades the response instead of failing it.
        return pkg, None, str(exc)
    _PRICE_CACHE[(ticker, quarters)] = (time.time(), val)
    return pkg, val, None


LIVE_BATCH = 20


@app.get("/api/live")
def live(tickers: str):
    """Today's screen rows for a handful of tickers, priced now.

    Each row is the company page's own valuation and verdict cut down to
    the fields the list shows. A ticker that cannot be read comes back as
    {"error": ...} rather than dropping out or borrowing a stored value.
    """
    names = list(dict.fromkeys(_clean(t) for t in tickers.split(",") if t))
    if not names or len(names) > LIVE_BATCH:
        raise HTTPException(400, "1 ile %d arasinda ticker verin" % LIVE_BATCH)

    def one(ticker):
        try:
            pkg, val, price_error = _priced(ticker)
        except HTTPException as exc:
            return {"error": exc.detail}
        except Exception as exc:
            # One unreadable company must not blank the rest of the batch.
            return {"error": str(exc) or type(exc).__name__}
        row = ranking_mod.summarise(
            ticker, pkg, val,
            verdict_mod.assess(pkg, val, _prior(ticker), _risk_cuts()))
        if price_error:
            row["error"] = price_error
        return row

    with ThreadPoolExecutor(4) as pool:
        return {"rows": dict(zip(names, pool.map(one, names)))}


SIGNALS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "signals")
SIGNALS_JOB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "indicators", "lab",
                           "signals.py")
SIGNAL_MARKETS = {"sp500": "ABD hisseleri", "etf": "Endeks ve ETF", "bist": "BIST"}
INSTRUMENT_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{0,11}$")
_REFRESH = {"job": None}


def _signals_file(*parts):
    path = os.path.join(SIGNALS, *parts) + ".json"
    if not os.path.exists(path):
        raise HTTPException(404, "sinyal dosyasi yok: python indicators/lab/signals.py refresh")
    with open(path) as fh:
        return json.load(fh)


def _refreshing():
    job = _REFRESH["job"]
    return job is not None and job.poll() is None


@app.get("/api/signals")
def signals(market: str = "sp500"):
    """The systems shown for a market, their record, and the instruments in
    a position or about to enter one, as written by indicators/lab/signals.py.
    Nothing is computed here: the file is the dated output of that job."""
    if market not in SIGNAL_MARKETS:
        raise HTTPException(400, "gecersiz piyasa: %s" % market)
    return dict(_signals_file(market),
                markets=[{"key": k, "label": v} for k, v in SIGNAL_MARKETS.items()],
                refreshing=_refreshing())


@app.get("/api/signals/{market}/{instrument}")
def signal_journal(market: str, instrument: str):
    """Every trade each shown system made on one instrument."""
    if market not in SIGNAL_MARKETS:
        raise HTTPException(400, "gecersiz piyasa: %s" % market)
    instrument = instrument.upper()
    if not INSTRUMENT_RE.match(instrument):
        raise HTTPException(400, "gecersiz enstruman")
    return _signals_file(market, instrument)


@app.post("/api/signals/refresh")
def signals_refresh():
    """Starts the job that fetches today's bars and rebuilds the signal
    files. It needs numpy and TA-Lib beside the API; without them the
    files stay as they are and the reply says so."""
    if _refreshing():
        return {"refreshing": True, "started": False}
    try:
        import numpy  # noqa: F401
        import talib  # noqa: F401
    except ImportError:
        raise HTTPException(503, "numpy ve TA-Lib kurulu degil: "
                                 "<venv>/bin/python indicators/lab/signals.py refresh")
    os.makedirs(SIGNALS, exist_ok=True)
    log = open(os.path.join(SIGNALS, "refresh.log"), "w")
    _REFRESH["job"] = subprocess.Popen([sys.executable, SIGNALS_JOB, "refresh"],
                                       stdout=log, stderr=subprocess.STDOUT)
    return {"refreshing": True, "started": True}


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
