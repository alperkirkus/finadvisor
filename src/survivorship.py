"""What the missing S&P 500 members were, and how many can be recovered.

301 of 963 historical members have no Yahoo history under their membership
ticker, so every price-based result here is computed without them. This
module finds out why, with free sources only:

1. Wikipedia's "Historical components of the S&P 500" gives, for each
   removal, the security's name and the reason (acquired, bankrupt, market
   cap, spin-off...).
2. SEC's cik-lookup-data.txt maps every name a filer has ever used to its
   CIK; the filer's submissions then give its current ticker, if any.
3. A missing member whose company still trades under a new ticker (ABC is
   now COR, ANTM is ELV) is recovered: its history is fetched under the new
   ticker, which is the same company by CIK.

What remains is classified by the removal reason, and the bias of leaving
it out is bounded in `report`.

    python src/survivorship.py map        # names, CIKs, new tickers
    python src/survivorship.py recover    # fetch recovered histories
"""
import json
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime

import edgar
import strategy as S
import universe as U

DIR = os.path.join(os.path.dirname(__file__), "..", "data", "survivorship")
HIST_URL = ("https://en.wikipedia.org/w/index.php?title="
            "Historical_components_of_the_S%26P_500&action=raw")
LOOKUP_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
MAP = os.path.join(DIR, "map.json")

SUFFIXES = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD",
            "LIMITED", "PLC", "LLC", "LP", "THE", "HOLDINGS", "HOLDING", "GROUP",
            "NV", "SA", "AG", "DE", "NEW", "CL", "A", "B"}


def _norm(name):
    name = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", name)
    name = re.sub(r"\(.*?\)", " ", name).upper().replace("&", " AND ")
    words = re.sub(r"[^A-Z0-9 ]", " ", name).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    while words and words[0] == "THE":
        words.pop(0)
    return " ".join(words)


def _cell(text):
    text = text.strip().lstrip("|").strip()
    return re.sub(r"<ref.*?(</ref>|/>)", "", text).strip()


def _rows():
    """[(date, added ticker, added security, removed ticker, removed security, reason)]."""
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, "hist.txt")
    if not os.path.exists(path):
        U._download(HIST_URL, path)
    body = open(path, encoding="utf-8").read()
    table = body[body.index('id="changes"'):]
    out, last_date = [], None
    for block in table.split("\n|-")[1:]:
        lines = [l for l in block.strip().split("\n") if l.startswith("|") and not l.startswith("|}")]
        cells = []
        for l in lines:
            cells.extend(_cell(c) for c in re.split(r"\|\|", l.lstrip("|")))
        if not cells:
            continue
        try:
            when = datetime.strptime(cells[0].split("[")[0].strip(), "%B %d, %Y").date().isoformat()
            cells = cells[1:]
        except ValueError:
            when = last_date
        last_date = when
        if len(cells) < 5:
            continue
        out.append((when, cells[0].strip().upper(), cells[1], cells[2].strip().upper(),
                    cells[3], cells[4]))
    return out


def _additions():
    return [(w, a, asec, reason) for w, a, asec, _, _, reason in _rows() if a]


def removals():
    """[(date, ticker, security, reason)] from the Wikipedia changes table."""
    return [(w, r, rsec, reason) for w, _, _, r, rsec, reason in _rows() if r]


def _old_removals():
    """[(date, ticker, security, reason)] from the Wikipedia changes table."""
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, "hist.txt")
    if not os.path.exists(path):
        U._download(HIST_URL, path)
    body = open(path, encoding="utf-8").read()
    table = body[body.index('id="changes"'):]
    out, last_date = [], None
    for block in table.split("\n|-")[1:]:
        lines = [l for l in block.strip().split("\n") if l.startswith("|") and not l.startswith("|}")]
        cells = []
        for l in lines:
            cells.extend(_cell(c) for c in re.split(r"\|\|", l.lstrip("|")))
        if not cells:
            continue
        try:
            when = datetime.strptime(cells[0].split("[")[0].strip(), "%B %d, %Y").date().isoformat()
            cells = cells[1:]
        except ValueError:
            when = last_date
        last_date = when
        if len(cells) < 5:
            continue
        ticker, security, reason = cells[2].strip(), cells[3], cells[4]
        if ticker:
            out.append((when, ticker.upper(), security, reason))
    return out


def _lookup():
    """{normalized name: {cik}} from SEC's every-name-ever file."""
    path = os.path.join(DIR, "cik-lookup-data.txt")
    if not os.path.exists(path):
        U._sec_contact()
        req = urllib.request.Request(LOOKUP_URL, headers={"User-Agent": edgar.UA})
        open(path, "wb").write(urllib.request.urlopen(req, timeout=120).read())
    out = defaultdict(set)
    for line in open(path, encoding="latin-1"):
        parts = line.rstrip("\n").rsplit(":", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[0]:
            out[_norm(parts[0])].add(int(parts[1]))
    return out


def _current_added():
    """{ticker: date added} for current members, from the constituents table."""
    path = os.path.join(DIR, "sp500_page.html")
    if not os.path.exists(path):
        U._download(U.WIKI_URL, path)
    t = U._Table("constituents")
    t.feed(open(path, encoding="utf-8").read())
    header, out = t.rows[0], {}
    for row in t.rows[1:]:
        rec = dict(zip(header, row))
        if rec.get("Symbol") and re.match(r"\d{4}-\d{2}-\d{2}", rec.get("Date added", "")):
            out[rec["Symbol"]] = rec["Date added"][:10]
    return out


def classify(reason):
    r = reason.lower()
    if "bankrupt" in r or "chapter 11" in r:
        return "bankruptcy"
    if any(k in r for k in ("acquir", "acquisition", "merg", "bought", "purchase", "buyout",
                            "taken private", "privat", "takeover")):
        return "acquired"
    if "spin" in r or "split" in r:
        return "spin-off/split"
    if "market cap" in r or "capitalization" in r or "float" in r or "size" in r:
        return "market cap"
    if "renam" in r or "ticker" in r or "symbol" in r or "reorgan" in r:
        return "renamed"
    return "other"


def build_map():
    missing = json.load(open(os.path.join(S.DAILY, "failed.json")))
    rem = defaultdict(list)
    for when, t, sec, reason in removals():
        rem[t].append((when, sec, reason))
    names = _lookup()
    members = U.membership()
    added_on = defaultdict(set)
    for when, t, sec, reason in _additions():
        added_on[when].add(t)
    starts = defaultdict(list)
    for t, iv in members.items():
        for a, _ in iv:
            starts[a].append(t)
    added_date = _current_added()
    out = {}
    for sym in sorted(missing):
        ticker = sym.replace("-", ".")
        iv = members.get(ticker) or members.get(sym) or []
        last_end = max((e or "9999-12-31") for _, e in iv) if iv else None
        # The removal row nearest the membership end belongs to this ticker's
        # member; a ticker reused by another company has other rows.
        cands = rem.get(ticker) or rem.get(sym) or []
        row = None
        if cands and last_end:
            row = min(cands, key=lambda c: abs((datetime.fromisoformat(c[0]) -
                                                datetime.fromisoformat(last_end[:10])).days))
        rec = {"membership_end": last_end, "error": missing[sym][:40]}
        if row:
            rec.update({"removed": row[0], "security": re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]",
                                                              r"\1", row[1]),
                        "reason": re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", row[2])[:200],
                        "class": classify(row[2])})
            ciks = names.get(_norm(row[1]), set())
            if len(ciks) == 1:
                rec["cik"] = next(iter(ciks))
            elif ciks:
                rec["cik_candidates"] = sorted(ciks)[:6]
        # A ticker change: the old ticker ends the day a new one starts, and
        # neither appears in the changes table (nobody left the index).
        if not row and last_end and last_end != "9999-12-31":
            day = datetime.fromisoformat(last_end[:10])
            near = [t for d, ts in starts.items() if abs((datetime.fromisoformat(d) - day).days) <= 3
                    for t in ts if t != ticker]
            listed = {t for d, ts in added_on.items()
                      if abs((datetime.fromisoformat(d) - day).days) <= 7 for t in ts}
            near = [t for t in near if t not in listed]
            # Confirmed only when the new ticker is a current member whose
            # "date added" predates the switch: a rename keeps the original
            # date, a replacement gets the switch date.
            near = [t for t in near if t in added_date and added_date[t] < (day.date().isoformat())
                    and (day - datetime.fromisoformat(added_date[t])).days > 30]
            if len(near) == 1:
                rec.update({"class": "renamed", "renamed_to": U.yahoo_symbol(near[0])})
        out[sym] = rec
    json.dump(out, open(MAP, "w"), indent=1)
    return out


def current_tickers(cik, sec):
    path = os.path.join(edgar.CACHE, "sub_%010d.json" % cik)
    if not os.path.exists(path):
        sec.wait()
        edgar.profile(cik)
    d = json.load(open(path))
    return d.get("tickers") or [], d.get("name")


def recover():
    """Fetch history under the company's current ticker, same CIK."""
    U._sec_contact()
    sec = U._RateLimit(8)
    m = json.load(open(MAP))
    recovered = {}
    for sym, rec in m.items():
        if rec["error"].startswith(("'close'", "too little")):
            rec["retry"] = True
            new = [sym] + ([rec["renamed_to"]] if rec.get("renamed_to") else [])
        elif rec.get("renamed_to"):
            new = [rec["renamed_to"]]
        elif "cik" in rec:
            try:
                tickers, name = current_tickers(rec["cik"], sec)
            except Exception:
                continue
            rec["current_tickers"], rec["current_name"] = tickers, name
            new = [t.replace(".", "-") for t in tickers if t.replace(".", "-") != sym]
        else:
            continue
        rec.pop("recover_errors", None)
        for t in new[:2]:
            path = S._path(t)
            try:
                if os.path.exists(path):
                    d = json.load(open(path))
                else:
                    d = S.fetch_one(t)
            except Exception as exc:
                rec.setdefault("recover_errors", []).append("%s: %s" % (t, str(exc)[:40]))
                continue
            # The new ticker's history must cover the old membership; a
            # company listed only after it left the index adds nothing.
            if rec["membership_end"] and d["date"][0] > rec["membership_end"][:10]:
                continue
            rec["recovered_as"] = t
            recovered[sym] = t
            break
    json.dump(m, open(MAP, "w"), indent=1)
    json.dump(recovered, open(os.path.join(DIR, "aliases.json"), "w"), indent=1)
    return m, recovered


def report(m=None):
    m = m or json.load(open(MAP))
    gone = {s: r for s, r in m.items() if "recovered_as" not in r}
    print("eksik %d, kurtarilan %d, kalan %d" % (len(m), len(m) - len(gone), len(gone)))
    print("kalanlarin cikis nedeni:", dict(Counter(r.get("class", "kayit yok") for r in gone.values())))
    return gone


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "map":
        m = build_map()
        print("%d eksik; nedeni bulunan %d; tek CIK %d"
              % (len(m), sum("class" in r for r in m.values()),
                 sum("cik" in r for r in m.values())))
        print(dict(Counter(r.get("class", "kayit yok") for r in m.values())))
    elif cmd == "recover":
        m, rec = recover()
        report(m)
    else:
        report()
