"""Daily bars of every S&P 500 member as date x company arrays.

    <research venv>/python -I indicators/lab/panel.py <dataset directory>
    <research venv>/python -I indicators/lab/panel.py midsmall
    <research venv>/python -I indicators/lab/panel.py etf
    <research venv>/python -I indicators/lab/panel.py bist

Writes data/indicators/panel.npz: open, high, low, close (adjusted for
splits and dividends), volume, and `member` (in the index that day), with
the dates and labels. Built once; the lab reads only this file.

`midsmall` builds panel_midsmall.npz for S&P 400 and 600 members from
Yahoo. Two limits make it a second opinion and not an equal: membership is
known from 2012 (S&P 400) and late 2019 (S&P 600) only, and Yahoo serves
only the companies still trading, so every result on it is a survivor's --
least trustworthy exactly where a hypothesis is about losers.

`etf` and `bist` build panel_etf.npz and panel_bist.npz from the fixed
lists below, every instrument a "member" on any day it has a bar. The ETF
list is index, sector, country, bond, commodity and currency funds; the
BIST list is large Borsa Istanbul companies as of 2026, so it too holds
survivors only, and its prices are in lira, whose inflation alone makes
almost any purchase profitable in nominal terms.
"""
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "indicators")
START = "2004-01-01"


YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
         "?period1=%d&period2=%d&interval=1d&events=div%%2Csplits")
FROM_2010, FROM_2004 = 1262304000, 1072915200
ETFS = ("SPY QQQ IWM DIA MDY EFA EEM EWJ EWZ FXI EWG EWU EWW XLK XLF XLE XLV XLI XLP XLY "
        "XLU XLB VNQ TLT IEF LQD HYG TIP GLD SLV USO DBC UNG UUP FXE FXY").split()
BIST = ("AKBNK GARAN ISCTR YKBNK VAKBN HALKB TSKB KCHOL SAHOL DOHOL ALARK THYAO PGSUS TAVHL "
        "TUPRS PETKM SASA AKSA EREGL KRDMD ASELS OTKAR BIMAS MGROS SOKM MAVI SISE TCELL TTKOM "
        "FROTO TOASO TTRAK DOAS ARCLK VESTL ENKAI TKFEN EKGYO ISGYO KOZAL KOZAA ULKER AEFES "
        "CCOLA GUBRF HEKTS AKSEN ENJSA ODAS BRISA CIMSA OYAKC EGEEN").split()


def _yahoo(symbol, start=FROM_2010):
    req = urllib.request.Request(YAHOO % (symbol, start, int(time.time())),
                                 headers={"User-Agent": "Mozilla/5.0 (FinAdvisor research)"})
    result = json.loads(urllib.request.urlopen(req, timeout=60).read())["chart"]["result"][0]
    q, adj = result["indicators"]["quote"][0], result["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, t in enumerate(result["timestamp"]):
        o, h, low, c, v, a = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i], adj[i]
        if None in (o, h, low, c, v, a) or min(o, h, low, c, a) <= 0:
            continue
        f = a / c
        rows.append((time.strftime("%Y-%m-%d", time.gmtime(t)), o * f, h * f, low * f, a, v))
    return rows


def build_list(name, symbols, suffix=""):
    """A panel of a fixed list of instruments, each a member wherever it has a bar."""
    def one(symbol):
        try:
            rows = _yahoo(symbol + suffix, FROM_2004)
            return symbol, rows if len(rows) >= 300 else None
        except Exception:
            return symbol, None
    with ThreadPoolExecutor(4) as pool:
        got = {s: r for s, r in pool.map(one, symbols) if r}
    missing = sorted(set(symbols) - set(got))
    if len(got) < 0.8 * len(symbols):
        raise ValueError("only %d of %d %s instruments have daily bars" % (len(got), len(symbols), name))
    dates = sorted({r[0] for rows in got.values() for r in rows})
    at = {d: i for i, d in enumerate(dates)}
    shape = (len(dates), len(got))
    fields = {k: np.full(shape, np.nan, dtype=np.float32) for k in ("open", "high", "low", "close", "volume")}
    for j, symbol in enumerate(sorted(got)):
        idx = np.array([at[r[0]] for r in got[symbol]])
        for k, field in enumerate(("open", "high", "low", "close", "volume"), 1):
            fields[field][idx, j] = [r[k] for r in got[symbol]]
    os.makedirs(OUT, exist_ok=True)
    np.savez(os.path.join(OUT, "panel_%s.npz" % name), dates=np.array(dates),
             labels=np.array(sorted(got)), member=np.isfinite(fields["close"]), **fields)
    print("%s: %d gun x %d enstruman (%s .. %s)%s"
          % (name, shape[0], shape[1], dates[0], dates[-1],
             "; alinamayan: %s" % " ".join(missing) if missing else ""))


def build_midsmall():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
    import universe as U
    spans = {}
    for index in ("sp400", "sp600"):
        for ticker, iv in U.index_membership(index)[0].items():
            spans.setdefault(U.yahoo_symbol(ticker), []).extend(iv)

    def one(symbol):
        try:
            rows = _yahoo(symbol)
            return symbol, rows if len(rows) >= 300 else None
        except Exception:
            return symbol, None
    with ThreadPoolExecutor(4) as pool:
        got = {s: r for s, r in pool.map(one, sorted(spans)) if r}
    if len(got) < 500:
        raise ValueError("only %d of %d mid/small members have daily bars" % (len(got), len(spans)))
    dates = sorted({r[0] for rows in got.values() for r in rows})
    at = {d: i for i, d in enumerate(dates)}
    shape = (len(dates), len(got))
    fields = {k: np.full(shape, np.nan, dtype=np.float32) for k in ("open", "high", "low", "close", "volume")}
    member = np.zeros(shape, dtype=bool)
    for j, symbol in enumerate(sorted(got)):
        rows = got[symbol]
        idx = np.array([at[r[0]] for r in rows])
        for k, name in enumerate(("open", "high", "low", "close", "volume"), 1):
            fields[name][idx, j] = [r[k] for r in rows]
        for s, e in spans[symbol]:
            a = np.searchsorted(dates, s)
            b = np.searchsorted(dates, e) if e else len(dates)
            member[a:b, j] = True
    member &= np.isfinite(fields["close"])
    os.makedirs(OUT, exist_ok=True)
    np.savez(os.path.join(OUT, "panel_midsmall.npz"), dates=np.array(dates),
             labels=np.array(sorted(got)), member=member, **fields)
    print("%d gun x %d sirket (%d uyeden; %s .. %s); gunluk ortalama uye %.0f (2013: %.0f, 2021: %.0f)"
          % (shape[0], shape[1], len(spans), dates[0], dates[-1], member.sum(axis=1).mean(),
             member[[i for i, d in enumerate(dates) if d[:4] == "2013"]].sum(axis=1).mean(),
             member[[i for i, d in enumerate(dates) if d[:4] == "2021"]].sum(axis=1).mean()))


def build(theirs):
    import duckdb
    c = duckdb.connect()
    spans = {}
    for label, start, end in c.execute(
            'select ticker, strftime(start, \'%Y-%m-%d\'), strftime("end", \'%Y-%m-%d\') '
            "from read_parquet($1)", [os.path.join(theirs, "membership_intervals.parquet")]).fetchall():
        if end is None or end >= START:
            spans.setdefault(label, []).append((start, end))
    rows = c.execute("""
        select ticker, list(strftime(date, '%Y-%m-%d') order by date),
               list(open order by date), list(high order by date), list(low order by date),
               list(close order by date), list(volume order by date), list(adj_close order by date)
        from read_parquet($1)
        where date >= $3 and close > 0 and adj_close > 0 and open > 0 and high > 0 and low > 0
              and volume is not null and ticker in $2
        group by ticker order by ticker""",
                     [os.path.join(theirs, "prices.parquet"), list(spans), START]).fetchall()
    rows = [r for r in rows if len(r[1]) >= 300]
    if len(rows) < 500:
        raise ValueError("only %d members with daily bars in %s" % (len(rows), theirs))
    dates = sorted({d for r in rows for d in r[1]})
    at = {d: i for i, d in enumerate(dates)}
    shape = (len(dates), len(rows))
    fields = {k: np.full(shape, np.nan, dtype=np.float32) for k in ("open", "high", "low", "close", "volume")}
    member = np.zeros(shape, dtype=bool)
    labels = []
    for j, (label, ds, o, h, low, close, vol, adj) in enumerate(rows):
        labels.append(label)
        idx = np.array([at[d] for d in ds])
        factor = np.asarray(adj, dtype=float) / np.asarray(close, dtype=float)
        fields["open"][idx, j] = np.asarray(o) * factor
        fields["high"][idx, j] = np.asarray(h) * factor
        fields["low"][idx, j] = np.asarray(low) * factor
        fields["close"][idx, j] = np.asarray(adj)
        fields["volume"][idx, j] = np.asarray(vol)
        for s, e in spans[label]:
            a = np.searchsorted(dates, s)
            b = np.searchsorted(dates, e) if e else len(dates)
            member[a:b, j] = True
    member &= np.isfinite(fields["close"])
    os.makedirs(OUT, exist_ok=True)
    np.savez(os.path.join(OUT, "panel.npz"), dates=np.array(dates), labels=np.array(labels),
             member=member, **fields)
    print("%d gun x %d sirket (%s .. %s); gunluk ortalama uye %.0f"
          % (shape[0], shape[1], dates[0], dates[-1], member.sum(axis=1).mean()))


def load(name="panel.npz"):
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        raise SystemExit("%s yok: python indicators/lab/panel.py <dataset directory | midsmall>" % name)
    z = np.load(path)
    return {k: z[k] for k in z.files}


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "midsmall":
        build_midsmall()
    elif what == "etf":
        build_list("etf", ETFS)
    elif what == "bist":
        build_list("bist", BIST, ".IS")
    else:
        build(what)
