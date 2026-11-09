"""Officer and director open-market trades from the SEC insider data sets.

Executives buying their own company's stock in the open market is the one
piece of forward-looking information a financial statement does not carry,
and it is in the public record (Lakonishok & Lee 2001; Cohen, Malloy &
Pomorski 2012). Sales are noisier -- diversification, taxes, scheduled
plans -- so purchases carry most of the signal.

Source: SEC Form 3/4/5 "insider transactions data sets", one zip a quarter
(www.sec.gov/dera/data/form-345). Only Form 4 non-derivative transactions
coded P (open-market purchase) or S (open-market sale) by an officer or a
director are kept, with their filing date so a backtest can see a trade only
once it was public.
"""
import csv
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta

import edgar
import universe as U

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "insider")
URL = ("https://www.sec.gov/files/structureddata/data/"
       "insider-transactions-data-sets/%dq%d_form345.zip")
FIRST = (2012, 1)


def _quarters(today=None):
    today = today or date.today()
    y, q = FIRST
    while (y, q) <= (today.year, (today.month - 1) // 3 + 1):
        yield y, q
        y, q = (y, q + 1) if q < 4 else (y + 1, 1)


def download():
    """Fetches every quarter not yet on disk. A quarter SEC has not
    published yet answers 404 and is skipped, not treated as an error."""
    U._sec_contact()
    os.makedirs(DATA, exist_ok=True)
    got, missing = [], []
    for y, q in _quarters():
        path = os.path.join(DATA, "%dq%d_form345.zip" % (y, q))
        if os.path.exists(path):
            got.append(path)
            continue
        try:
            req = urllib.request.Request(URL % (y, q), headers={"User-Agent": edgar.UA})
            body = urllib.request.urlopen(req, timeout=180).read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                missing.append("%dq%d" % (y, q))
                continue
            raise
        if not body:
            raise ValueError("empty response for %dq%d" % (y, q))
        with open(path + ".part", "wb") as fh:
            fh.write(body)
        os.replace(path + ".part", path)
        got.append(path)
        time.sleep(0.5)
    return got, missing


def _date(s):
    return datetime.strptime(s, "%d-%b-%Y").date().isoformat() if s else None


def _rows(zf, name):
    with zf.open(name) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace"),
                                  delimiter="\t", quoting=csv.QUOTE_NONE)


def build(ciks, out_path=None):
    """{issuer_cik: [[filed, traded, code, shares, price, owner_cik], ...]}
    for the given issuers, from every downloaded quarter."""
    ciks = {int(c) for c in ciks}
    trades = {}
    for y, q in _quarters():
        path = os.path.join(DATA, "%dq%d_form345.zip" % (y, q))
        if not os.path.exists(path):
            continue
        with zipfile.ZipFile(path) as zf:
            subs = {}
            for r in _rows(zf, "SUBMISSION.tsv"):
                if r["DOCUMENT_TYPE"] not in ("4", "4/A"):
                    continue
                try:
                    cik = int(r["ISSUERCIK"])
                except ValueError:
                    continue
                if cik in ciks:
                    subs[r["ACCESSION_NUMBER"]] = (cik, _date(r["FILING_DATE"]))
            owners = {}
            for r in _rows(zf, "REPORTINGOWNER.tsv"):
                acc = r["ACCESSION_NUMBER"]
                rel = r["RPTOWNER_RELATIONSHIP"] or ""
                if acc in subs and ("Officer" in rel or "Director" in rel):
                    owners.setdefault(acc, r["RPTOWNERCIK"])
            for r in _rows(zf, "NONDERIV_TRANS.tsv"):
                acc = r["ACCESSION_NUMBER"]
                code = r["TRANS_CODE"]
                if acc not in owners or code not in ("P", "S"):
                    continue
                try:
                    shares = float(r["TRANS_SHARES"] or 0)
                    price = float(r["TRANS_PRICEPERSHARE"] or 0)
                except ValueError:
                    continue
                if shares <= 0:
                    continue
                cik, filed = subs[acc]
                trades.setdefault(str(cik), []).append(
                    [filed, _date(r["TRANS_DATE"]), code, shares, price, owners[acc]])
    for v in trades.values():
        v.sort()
    if out_path:
        json.dump(trades, open(out_path, "w"))
    return trades


def signal(trades, asof):
    """Insider read on `asof` from trades filed by then.

    insider_buyers_6m: distinct officers/directors with an open-market
    purchase traded in the last six months. insider_npr_12m: (purchase $ -
    sale $) / (purchase $ + sale $) over twelve months, None without trades.
    """
    end = date.fromisoformat(asof)
    start6, start12 = (end - timedelta(days=182)).isoformat(), (end - timedelta(days=365)).isoformat()
    buyers, buy, sell = set(), 0.0, 0.0
    for filed, traded, code, shares, price, owner in trades or []:
        if filed is None or filed > asof or traded is None or traded > asof:
            continue
        if traded > start12:
            value = shares * price
            if code == "P":
                buy += value
            else:
                sell += value
        if code == "P" and traded > start6:
            buyers.add(owner)
    total = buy + sell
    return {"insider_buyers_6m": len(buyers),
            "insider_npr_12m": (buy - sell) / total if total > 0 else None}


if __name__ == "__main__":
    got, missing = download()
    print("%d ceyrek indirildi, yayimlanmamis: %s" % (len(got), missing))
    uni, _ = U.backtest_universe()
    t = build([r["cik"] for r in uni.values()], os.path.join(DATA, "trades_sp500.json"))
    print("%d sirket, %d islem" % (len(t), sum(len(v) for v in t.values())))
