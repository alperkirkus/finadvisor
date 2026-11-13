"""Five-minute bars for the intraday study: fetch, store, load, aggregate.

Yahoo serves five-minute bars for the last 60 days only, so a history
longer than that exists only if it is collected as it goes by. `collect`
merges what Yahoo has now into what is already on disk; run weekly it
loses nothing.

    python intraday/bars.py collect      # fetch and merge every symbol
    python intraday/bars.py status       # what is on disk
"""
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data", "intraday", "equity")
UNIVERSE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe.json")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=60d&interval=5m"
UA = "Mozilla/5.0 (FinAdvisor research)"
FIELDS = ("o", "h", "l", "c", "v")
SIZE = 100


def universe():
    """The symbols under study: fixed once, on the day the study began."""
    if os.path.exists(UNIVERSE):
        return json.load(open(UNIVERSE))["symbols"]
    # The 100 largest S&P 500 members: the screen's universe in the order of
    # the SEC ticker file, which lists filers by market value.
    screen = {r["ticker"] for r in json.load(open(os.path.join(ROOT, "data", "ranking.json")))["rows"]}
    table = json.load(open(os.path.join(ROOT, "data", "tickers.json")))
    ordered = [table[k]["ticker"] for k in sorted(table, key=int)]
    symbols = [t for t in ordered if t in screen][:SIZE]
    if len(symbols) < SIZE:
        raise ValueError("only %d screen members found in the SEC ticker file" % len(symbols))
    json.dump({"fixed_on": time.strftime("%Y-%m-%d"), "symbols": symbols},
              open(UNIVERSE, "w"), indent=1)
    return symbols


def _path(symbol):
    return os.path.join(DATA, symbol + ".json")


def load(symbol):
    """{"t": [bar start, epoch seconds], "o", "h", "l", "c", "v"}, ascending."""
    return json.load(open(_path(symbol)))


def fetch(symbol):
    req = urllib.request.Request(URL % symbol, headers={"User-Agent": UA})
    result = json.loads(urllib.request.urlopen(req, timeout=60).read())["chart"]["result"][0]
    q = result["indicators"]["quote"][0]
    rows = {}
    for i, t in enumerate(result["timestamp"]):
        row = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        # A bar with no trade comes back as nulls; one still forming at the
        # moment of the request is dropped by the five-minute alignment.
        if any(x is None for x in row) or row[3] <= 0 or t % 300:
            continue
        rows[t] = row
    if not rows:
        raise ValueError("no usable bars for %s" % symbol)
    return rows


def collect_one(symbol):
    rows = fetch(symbol)
    if os.path.exists(_path(symbol)):
        old = load(symbol)
        for i, t in enumerate(old["t"]):
            rows.setdefault(t, [old[k][i] for k in FIELDS])
    ts = sorted(rows)
    out = {"t": ts, **{k: [rows[t][j] for t in ts] for j, k in enumerate(FIELDS)}}
    tmp = _path(symbol) + ".part"
    json.dump(out, open(tmp, "w"))
    os.replace(tmp, _path(symbol))
    return len(ts)


def collect(workers=4):
    os.makedirs(DATA, exist_ok=True)
    failed = {}

    def one(symbol):
        try:
            return symbol, collect_one(symbol), None
        except Exception as exc:
            return symbol, 0, "%s: %s" % (type(exc).__name__, str(exc)[:60])
    with ThreadPoolExecutor(workers) as pool:
        for symbol, n, err in pool.map(one, universe()):
            if err:
                failed[symbol] = err
    return failed


def day(t):
    """The session a bar belongs to. The regular session sits inside one UTC day."""
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def sessions(bars, every=1):
    """[(day, [bar, ...])] with `every` five-minute bars joined into one.

    A bar is {"o", "h", "l", "c", "v"}. Bars are joined inside a session
    only, from its first bar, and a tail shorter than `every` is dropped.
    """
    by_day = {}
    for i, t in enumerate(bars["t"]):
        by_day.setdefault(day(t), []).append(i)
    out = []
    for d in sorted(by_day):
        idx, joined = by_day[d], []
        for a in range(0, len(idx) - every + 1, every):
            part = idx[a:a + every]
            joined.append({"o": bars["o"][part[0]], "c": bars["c"][part[-1]],
                           "h": max(bars["h"][i] for i in part),
                           "l": min(bars["l"][i] for i in part),
                           "v": sum(bars["v"][i] for i in part)})
        if joined:
            out.append((d, joined))
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "collect":
        failed = collect()
        print("%d sembol, %d alinamadi %s" % (len(universe()), len(failed), failed or ""))
    have = [s for s in universe() if os.path.exists(_path(s))]
    if not have:
        raise SystemExit("diskte bar yok: python intraday/bars.py collect")
    spans = [(day(load(s)["t"][0]), day(load(s)["t"][-1]), len(load(s)["t"])) for s in have]
    print("%d sembol diskte; %s .. %s; sembol basina ortalama %d bar"
          % (len(have), min(a for a, _, _ in spans), max(b for _, b, _ in spans),
             sum(n for _, _, n in spans) / len(spans)))
