"""The backtest universe: S&P 500 membership as it stood on each date.

Testing on the companies in the index today selects winners twice: a name
that rose into the index after 2013 is scored on dates when no index-based
screen would have held it. Membership intervals come from the public
historical-components dataset at github.com/fja05680/sp500 (MIT); a ticker is
scored only on dates inside one of its intervals.

What cannot be fixed with free data is the other half of survivorship:
members later acquired or delisted usually have neither a CIK in the SEC
ticker map nor a Yahoo price history any more. They are counted, not filled.
"""
import csv
import json
import os
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

import edgar

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "universe")
MEMBERSHIP_URL = ("https://raw.githubusercontent.com/fja05680/sp500/master/"
                  "sp500_ticker_start_end.csv")
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
UA = "FinAdvisor research script"
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    body = urllib.request.urlopen(req, timeout=60).read()
    if not body:
        raise ValueError("empty response from %s" % url)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(body)
    os.replace(tmp, path)


def yahoo_symbol(ticker):
    """BRK.B in the membership file is BRK-B on Yahoo and in the SEC map."""
    return ticker.replace(".", "-")


def membership(refresh=False):
    """{ticker: [(start, end_or_None), ...]} with ISO dates."""
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "sp500_ticker_start_end.csv")
    if refresh or not os.path.exists(path):
        _download(MEMBERSHIP_URL, path)
    out = {}
    with open(path) as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["ticker"], []).append(
                (row["start_date"], row["end_date"] or None))
    if len(out) < 500:
        raise ValueError("membership file has only %d tickers" % len(out))
    return out


def is_member(intervals, date):
    return any(start <= date and (end is None or date <= end)
               for start, end in intervals)


class _Table(HTMLParser):
    """Rows of the Wikipedia table with the given id."""

    def __init__(self, table_id="constituents"):
        super().__init__()
        self.table_id = table_id
        self.rows, self.row, self.cell, self.inside = [], None, None, False

    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == self.table_id:
            self.inside = True
        elif self.inside and tag == "tr":
            self.row = []
            self.rows.append(self.row)
        elif self.inside and tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self.inside:
            self.inside = False
        elif self.inside and tag in ("td", "th") and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def wikipedia_ciks(refresh=False):
    """{ticker: cik} for current members, from the Wikipedia constituents table.

    The SEC ticker map omits some live members (BK, AVB among them); the
    constituents table carries the CIK directly.
    """
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "sp500_wikipedia.html")
    if refresh or not os.path.exists(path):
        _download(WIKI_URL, path)
    parser = _Table()
    parser.feed(open(path, encoding="utf-8").read())
    header, out = None, {}
    for row in parser.rows:
        if header is None:
            header = row
            continue
        rec = dict(zip(header, row))
        if rec.get("Symbol") and rec.get("CIK", "").isdigit():
            out[rec["Symbol"]] = int(rec["CIK"])
    if len(out) < 400:
        raise ValueError("constituents table parsed to %d rows" % len(out))
    return out


# Mid and small caps. Wikipedia carries each index's current constituents
# and a dated table of additions and removals; walking the changes backwards
# from today rebuilds who was in the index on any date the table covers.
# Before its first change the membership is unknown, so a name is never
# placed in the index earlier than that.
INDEX_PAGES = {
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}


def index_membership(index, refresh=False):
    """({ticker: [(start, end_or_None)]}, {ticker: cik}, coverage_start)."""
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "%s_wikipedia.html" % index)
    if refresh or not os.path.exists(path):
        _download(INDEX_PAGES[index], path)
    html = open(path, encoding="utf-8").read()

    cons = _Table("constituents")
    cons.feed(html)
    header, current, ciks = None, set(), {}
    for row in cons.rows:
        if header is None:
            header = row
            continue
        rec = dict(zip(header, row))
        if rec.get("Symbol"):
            current.add(rec["Symbol"])
            if rec.get("CIK", "").isdigit():
                ciks[rec["Symbol"]] = int(rec["CIK"])
    if len(current) < 300:
        raise ValueError("%s constituents parsed to %d rows" % (index, len(current)))

    changes = _Table("changes")
    changes.feed(html)
    events, last_date = [], None
    for row in changes.rows[2:]:
        try:
            when = datetime.strptime(row[0].split("[")[0].strip(), "%B %d, %Y").date().isoformat()
            cells = row[1:]
        except (ValueError, IndexError):
            when, cells = last_date, row       # rows sharing a rowspan date cell
        if when is None:
            continue
        last_date = when
        added = cells[0].strip() if len(cells) > 0 else ""
        removed = cells[2].strip() if len(cells) > 2 else ""
        events.append((when, added, removed))
    if not events:
        raise ValueError("%s changes table is empty" % index)
    coverage = min(e[0] for e in events)

    # Walk backwards: an addition on d opens the interval at d, a removal on
    # d means the name was in until d.
    open_end = {t: None for t in current}
    intervals = {}
    for when, added, removed in sorted(events, reverse=True):
        if added and added in open_end:
            intervals.setdefault(added, []).append((when, open_end.pop(added)))
        if removed and removed not in open_end:
            open_end[removed] = when
    for t, end in open_end.items():
        intervals.setdefault(t, []).append((coverage, end))
    return intervals, ciks, coverage


def midsmall_universe(start="2013-01-01", end="2025-12-31"):
    """S&P 400 and S&P 600 members over the window, resolved to CIKs.

    A name in both indices at different times keeps both intervals; one that
    moved up into the S&P 500 is scored here only while it was mid or small.
    """
    wiki = wikipedia_ciks()
    merged, ciks, coverage = {}, dict(wiki), {}
    for index in ("sp400", "sp600"):
        iv, c, cov = index_membership(index)
        coverage[index] = cov
        ciks.update(c)
        for t, spans in iv.items():
            merged.setdefault(t, []).extend(spans)
    out, unresolved = {}, []
    for ticker, spans in sorted(merged.items()):
        if not any(s <= end and (e is None or e >= start) for s, e in spans):
            continue
        cik = resolve(ticker, ciks)
        if cik is None:
            unresolved.append(ticker)
            continue
        out[ticker] = {"cik": cik, "intervals": spans}
    return out, unresolved, coverage


def resolve(ticker, wiki):
    """CIK for a membership ticker, or None. Never guesses from a name."""
    if ticker in wiki:
        return wiki[ticker]
    try:
        cik, _ = edgar.resolve_cik(yahoo_symbol(ticker))
        return cik
    except KeyError:
        return None


def backtest_universe(start="2013-01-01", end="2025-12-31"):
    """Members at any point in [start, end], resolved to CIKs.

    Returns ({ticker: {"cik", "intervals"}}, unresolved tickers).
    """
    members = membership()
    wiki = wikipedia_ciks()
    out, unresolved = {}, []
    for ticker, intervals in sorted(members.items()):
        if not any(s <= end and (e is None or e >= start) for s, e in intervals):
            continue
        cik = resolve(ticker, wiki)
        if cik is None:
            unresolved.append(ticker)
            continue
        out[ticker] = {"cik": cik, "intervals": intervals}
    return out, unresolved


def _sec_contact():
    """SEC asks for a contact address; read SEC_CONTACT from .env if unset."""
    if os.environ.get("SEC_CONTACT") or not os.path.exists(ENV_FILE):
        return
    for line in open(ENV_FILE, encoding="utf-8"):
        key, _, val = line.strip().partition("=")
        if key.strip() == "SEC_CONTACT" and val.strip():
            os.environ["SEC_CONTACT"] = val.strip().strip("\"'")
            edgar.UA = "FinAdvisor Research %s" % os.environ["SEC_CONTACT"]
            return


class _RateLimit:
    """At most `per_second` calls across all threads."""

    def __init__(self, per_second):
        import threading
        self.gap, self.lock, self.next = 1.0 / per_second, threading.Lock(), 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next)
            self.next = slot + self.gap
        time.sleep(max(0.0, slot - now))


def prefetch(universe, price_fn, workers=6):
    """Downloads missing companyfacts, submissions and price histories.

    Runs `workers` companies at a time. SEC allows ten requests a second, so
    SEC calls share a limiter set below that; Yahoo gets its own, gentler
    one. Already-cached files are skipped, so an interrupted run resumes.
    Failures are returned, not raised: one missing name must not stop a
    thousand-name run.
    """
    from concurrent.futures import ThreadPoolExecutor
    _sec_contact()
    sec, yahoo = _RateLimit(8), _RateLimit(4)

    def one(item):
        ticker, rec = item
        facts_path = os.path.join(edgar.CACHE, "facts_%010d.json" % rec["cik"])
        sub_path = os.path.join(edgar.CACHE, "sub_%010d.json" % rec["cik"])
        try:
            if not os.path.exists(facts_path):
                sec.wait()
                edgar.companyfacts(rec["cik"])
            if not os.path.exists(sub_path):
                sec.wait()
                edgar.profile(rec["cik"])
        except Exception as exc:
            return ticker, "facts: %s" % exc
        try:
            yahoo.wait()
            price_fn(yahoo_symbol(ticker), need_raw=True)
        except Exception as exc:
            return ticker, "prices: %s" % exc
        return ticker, None

    failures, done = {}, 0
    with ThreadPoolExecutor(workers) as pool:
        for ticker, err in pool.map(one, sorted(universe.items())):
            done += 1
            if err:
                failures[ticker] = err
            if done % 100 == 0:
                print("  prefetch %d/%d (%d hata)" % (done, len(universe), len(failures)),
                      flush=True)
    return failures


if __name__ == "__main__":
    import sys
    import backtest
    if "--midsmall" in sys.argv:
        uni, unresolved, cov = midsmall_universe()
        print("kapsam baslangici: %s" % cov)
    else:
        uni, unresolved = backtest_universe()
    print("%d uye, %d CIK cozulemedi" % (len(uni), len(unresolved)))
    failures = prefetch(uni, backtest.prices)
    json.dump({"unresolved": unresolved, "failures": failures},
              open(os.path.join(DATA, "prefetch_report.json"), "w"), indent=1)
    print("hatalar: %d" % len(failures))
