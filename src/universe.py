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
    """Rows of the table with id="constituents"."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.inside = [], None, None, False

    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "constituents":
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


def prefetch(universe, price_fn):
    """Downloads missing companyfacts and price histories, politely.

    SEC allows ten requests a second; Yahoo publishes no limit, so it gets a
    pause too. Failures are returned, not raised: one missing name must not
    stop a 600-name run.
    """
    _sec_contact()
    failures = {}
    for i, (ticker, rec) in enumerate(sorted(universe.items()), 1):
        facts_path = os.path.join(edgar.CACHE, "facts_%010d.json" % rec["cik"])
        sub_path = os.path.join(edgar.CACHE, "sub_%010d.json" % rec["cik"])
        try:
            if not os.path.exists(facts_path):
                edgar.companyfacts(rec["cik"])
                time.sleep(0.15)
            if not os.path.exists(sub_path):
                edgar.profile(rec["cik"])
                time.sleep(0.15)
        except Exception as exc:
            failures[ticker] = "facts: %s" % exc
            continue
        try:
            price_fn(yahoo_symbol(ticker), need_raw=True)
            time.sleep(0.3)
        except Exception as exc:
            failures[ticker] = "prices: %s" % exc
        if i % 50 == 0:
            print("  prefetch %d/%d (%d hata)" % (i, len(universe), len(failures)))
    return failures


if __name__ == "__main__":
    import backtest
    uni, unresolved = backtest_universe()
    print("%d uye, %d CIK cozulemedi" % (len(uni), len(unresolved)))
    failures = prefetch(uni, backtest.prices)
    json.dump({"unresolved": unresolved, "failures": failures},
              open(os.path.join(DATA, "prefetch_report.json"), "w"), indent=1)
    print("hatalar: %d" % len(failures))
