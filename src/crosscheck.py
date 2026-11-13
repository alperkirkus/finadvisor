"""Cross-check of the price backtest's universe against an outside dataset.

`strategy.py` can only hold the S&P 500 members Yahoo still serves. This
compares that universe, month by month, with github.com/Johnbrick123/sp500-data
(every member since 1970 with a price, dead companies included) and with RSP,
the equal-weight S&P 500 fund, as a yardstick neither side built.

Not on the product path and not stdlib-only: it needs duckdb and the
dataset's release files, both kept outside the repository.

    uv venv /tmp/xcheck && uv pip install --python /tmp/xcheck/bin/python duckdb
    # prices.parquet and membership_intervals.parquet from the dataset's
    # latest release, into an empty directory
    /tmp/xcheck/bin/python -I src/crosscheck.py <that directory>

The dataset carries no licence and part of it derives from CRSP, so it is
read here as a check and none of it is stored in this repository.
"""
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy as S          # noqa: E402
import universe as U          # noqa: E402

THEIRS = sys.argv[1]
RSP_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/RSP"
           "?period1=1104537600&period2=%d&interval=1mo&events=div")

WINDOWS = [("2006-2012", "2006-01", "2012-12"), ("2013-2019", "2013-01", "2019-12"),
           ("2020-2025", "2020-01", "2025-12"), ("2006-2025", "2006-01", "2025-12")]


def ours():
    """{month: {symbol: next-month return}} with strategy.run's own universe rule."""
    members = S.members_since()
    series = {}
    for sym in list(members) + [S.ETF]:
        if os.path.exists(S._path(sym)):
            series[sym] = S.Series(json.load(open(S._path(sym))))
    ends = S.month_ends(series[S.ETF])
    out, listed = {}, {}
    for d0, d1 in zip(ends, ends[1:]):
        rets, named = {}, set()
        for sym, iv in members.items():
            if not U.is_member(iv, d0):
                continue
            named.add(sym)
            s = series.get(sym)
            if s is None:
                continue
            i0, i1 = s.at_or_before(d0), s.at_or_before(d1)
            if i0 is None or i1 is None or s.date[i0][:7] != d0[:7]:
                continue
            if s.features(i0) is None:
                continue
            rets[sym] = s.adj[i1] / s.adj[i0] - 1
        out[d1[:7]] = rets
        listed[d1[:7]] = named
    return ends, out, listed, set(series)


def theirs(ends):
    """{month: {label: next-month return}} for every member with a price at
    the month end and a year of history, the same rule as ours."""
    c = duckdb.connect()
    c.execute("create table ends as select unnest($1)::timestamp d0, unnest($2)::timestamp d1",
              [ends[:-1], ends[1:]])
    c.execute("""create table px as
        select ticker, date, adj_close,
               row_number() over (partition by ticker order by date) n
        from read_parquet($1) where adj_close > 0 and date >= '2003-01-01'""",
              [os.path.join(THEIRS, "prices.parquet")])
    c.execute("""create table mem as
        select e.d0, e.d1, m.ticker
        from ends e join read_parquet($1) m
          on m.start <= e.d0 and (m."end" is null or m."end" > e.d0)""",
              [os.path.join(THEIRS, "membership_intervals.parquet")])
    rows = c.execute("""
        select strftime(m.d1, '%Y-%m') mon, m.ticker, p0.adj_close a0, p0.date t0, p0.n n0,
               p1.adj_close a1
        from mem m
        asof left join px p0 on p0.ticker = m.ticker and p0.date <= m.d0
        asof left join px p1 on p1.ticker = m.ticker and p1.date <= m.d1""").fetchall()
    members = c.execute("select strftime(d1, '%Y-%m'), count(*) from mem group by 1").fetchall()
    out, unpriced = defaultdict(dict), defaultdict(list)
    d0_of = {d1[:7]: d0 for d0, d1 in zip(ends, ends[1:])}
    for mon, label, a0, t0, n0, a1 in rows:
        if a0 is None or t0.strftime("%Y-%m") != d0_of[mon][:7]:
            unpriced[mon].append(label)
            continue
        if n0 <= S.YEAR:
            continue
        out[mon][label] = a1 / a0 - 1
    return out, dict(members), unpriced


def stats(series, start, end):
    rows = [r for m, r in sorted(series.items()) if start <= m <= end]
    if len(rows) < 12:
        return None
    level, peak, mdd = 1.0, 1.0, 0.0
    for r in rows:
        level *= 1 + r
        peak = max(peak, level)
        mdd = min(mdd, level / peak - 1)
    mean = sum(rows) / len(rows)
    vol = math.sqrt(sum((r - mean) ** 2 for r in rows) / (len(rows) - 1)) * math.sqrt(12)
    return level ** (12 / len(rows)) - 1, vol, mdd


def their_universe():
    """Their members and daily series in the shapes strategy.run takes."""
    c = duckdb.connect()
    day = lambda t: t.strftime("%Y-%m-%d")
    members = defaultdict(list)
    for label, start, end in c.execute(
            'select ticker, start, "end" - interval 1 day from read_parquet($1)',
            [os.path.join(THEIRS, "membership_intervals.parquet")]).fetchall():
        if day(start) <= "2025-12-31" and (end is None or day(end) >= "2005-01-01"):
            members[label].append((day(start), day(end) if end else None))
    rows = c.execute("""
        select ticker, list(strftime(date, '%Y-%m-%d') order by date), list(adj_close order by date)
        from read_parquet($1) where adj_close > 0 and date >= '2004-01-01' and ticker in $2
        group by ticker""", [os.path.join(THEIRS, "prices.parquet"), list(members)]).fetchall()
    if len(rows) < 500:
        raise ValueError("only %d of %d members have prices in %s" % (len(rows), len(members), THEIRS))
    series = {label: S.Series({"date": dates, "adj": adj, "vol": []}) for label, dates, adj in rows}
    series.update(S.load_series([S.INDEX, S.ETF]))
    return dict(members), series


def strategies():
    """Strategy A, B and the regime rule on the full universe, beside ours."""
    members, series = their_universe()
    full, _, counts = S.run(members, series,
                            lambda label: None if re.search(r"-\d{6}$", label) else label)
    mine, _, mine_counts = S.run()
    names = [("A", "A: trend+momentum+rejim"), ("B", "B: A + kalite"),
             ("A_no_regime", "A, rejim filtresiz"), ("EW", "eşit ağırlıklı evren"),
             ("SPY", "SPY"), ("SPY_regime", "SPY + rejim")]
    print("\n== 6. Stratejiler tam evrende: yıllık getiri / Sharpe / en büyük düşüş (bizim evren → tam evren)")
    for label, a, b in WINDOWS:
        print("  %s" % label)
        for key, name in names:
            x, y = S.stats(mine[key], a, b), S.stats(full[key], a, b)
            cell = lambda s: ("%5.1f%% / %4.2f / %4.0f%%" % (s["cagr"] * 100, s["sharpe"] or 0, s["maxdd"] * 100)
                              if s else "      -")
            print("    %-26s %s  →  %s" % (name, cell(x), cell(y)))
    for key in ("A", "B"):
        print("  %s ortalama hisse: bizim %.0f, tam %.0f"
              % (key, mean(mine_counts[key]), mean(counts[key])))
    print("  Ön kayıtlı ölçüt (Sharpe evrenden yüksek VE düşüş daha küçük, 2006-2012 ve 2013-2019):")
    for key in ("A", "B"):
        verdicts = []
        for label, a, b in WINDOWS[:2]:
            s, ew = S.stats(full[key], a, b), S.stats(full["EW"], a, b)
            verdicts.append("%s %s" % (label, "-" if not s else
                                       "geçti" if s["sharpe"] > ew["sharpe"] and s["maxdd"] > ew["maxdd"]
                                       else "kaldı"))
        print("    %s: %s" % (key, ", ".join(verdicts)))


def rsp():
    """{month: RSP's total-return level at the month end}."""
    req = urllib.request.Request(RSP_URL % int(time.time()), headers={"User-Agent": S.UA})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())["chart"]["result"][0]
    return {time.strftime("%Y-%m", time.gmtime(t)): a
            for t, a in zip(d["timestamp"], d["indicators"]["adjclose"][0]["adjclose"]) if a}


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ends, mine, listed, have_series = ours()
    their, their_members, unpriced = theirs(ends)
    aliases = json.load(open(S.ALIASES)) if os.path.exists(S.ALIASES) else {}
    base = lambda label: re.sub(r"-\d{6}$", "", label)
    sym_of = lambda label: aliases.get(base(label), base(label))
    months = [m for m in sorted(mine) if "2006-01" <= m <= "2025-12"]

    print("== 1. Evren büyüklüğü (ay sonu ortalaması)")
    for name, a, b in WINDOWS:
        ms = [m for m in months if a <= m <= b]
        print("  %s  fja üye %5.0f | bizde getirisi olan %5.0f | onlarda üye %5.0f | onlarda getirisi olan %5.0f | onlarda fiyatsız %4.1f"
              % (name, mean(len(listed[m]) for m in ms), mean(len(mine[m]) for m in ms),
                 mean(their_members.get(m, 0) for m in ms), mean(len(their[m]) for m in ms),
                 mean(len(unpriced.get(m, [])) for m in ms)))

    # Their members by whether our universe held the same company that month.
    matched, missing = defaultdict(dict), defaultdict(dict)
    # A dead label is the same company as our symbol only when no living
    # label claims that symbol in the month (TT was Trane before it was
    # Ingersoll-Rand's ticker).
    for m in months:
        living = {sym_of(label) for label in their[m] if base(label) == label}
        for label, r in their[m].items():
            sym = sym_of(label)
            ours_too = sym in mine[m] and (base(label) == label or sym not in living)
            (matched if ours_too else missing)[m][label] = r

    print("\n== 2. Ortak isimlerde aylık getiri uyumu (bizim Yahoo önbelleği vs onların adj_close)")
    diffs = []
    for m in months:
        for label, r in matched[m].items():
            diffs.append((abs(mine[m][sym_of(label)] - r), m, label, mine[m][sym_of(label)], r))
    n = len(diffs)
    for cut in (0.005, 0.02, 0.05):
        print("  |fark| > %.1f puan: %6d / %d (%.2f%%)" % (cut * 100, sum(d[0] > cut for d in diffs), n,
                                                           100 * sum(d[0] > cut for d in diffs) / n))
    by_label = defaultdict(list)
    for d in diffs:
        if d[0] > 0.05:
            by_label[d[2]].append(d)
    print("  >5 puan farkı olan isimler (ay sayısı, ilk-son ay, en büyük fark: biz / onlar):")
    for label, ds in sorted(by_label.items(), key=lambda kv: -len(kv[1]))[:25]:
        worst = max(ds)
        print("    %-14s %3d ay  %s..%s  %s: %+.1f%% / %+.1f%%"
              % (label, len(ds), min(d[1] for d in ds), max(d[1] for d in ds), worst[1],
                 worst[3] * 100, worst[4] * 100))
    print("    toplam %d isim" % len(by_label))

    print("\n== 3. Bizde olmayan üyeler (onlarda fiyatı var)")
    labels = defaultdict(int)
    for m in months:
        for label in missing[m]:
            labels[label] += 1
    dead = [l for l in labels if base(l) != l]
    print("  farklı isim: %d (ölü etiketli %d, yaşayan etiketli %d); üye-ay: %d"
          % (len(labels), len(dead), len(labels) - len(dead), sum(labels.values())))
    alive = sorted(((n, l) for l, n in labels.items() if base(l) == l), reverse=True)[:25]
    print("  yaşayan etiketli, bizde eksik (ay): %s" % ", ".join("%s %d" % (l, n) for n, l in alive))
    print("  bizde serisi var ama o ay evrende yok: %d isim"
          % len({l for l in labels if sym_of(l) in have_series}))

    print("\n== 4. Eşit ağırlıklı evren: yıllık getiri / oynaklık / en büyük düşüş")
    ew = {
        "bizim (strategy.py EW)": {m: mean(mine[m].values()) for m in months if mine[m]},
        "onlar, ortak isimler": {m: mean(matched[m].values()) for m in months if matched[m]},
        "onlar, tüm üyeler": {m: mean(their[m].values()) for m in months if their[m]},
        "onlar, bizde eksikler": {m: mean(missing[m].values()) for m in months if missing[m]},
    }
    for label, series in ew.items():
        cells = []
        for name, a, b in WINDOWS:
            s = stats(series, a, b)
            cells.append("%s %5.1f%% / %4.1f%% / %4.0f%%" % (name, s[0] * 100, s[1] * 100, s[2] * 100)
                         if s else "%s -" % name)
        print("  %-24s %s" % (label, " | ".join(cells)))

    level = rsp()
    cells = []
    for name, a, b in WINDOWS:
        before = "%04d-12" % (int(a[:4]) - 1)
        n = (int(b[:4]) - int(a[:4])) * 12 + int(b[5:]) - int(a[5:]) + 1
        cells.append("%s %5.1f%%" % (name, ((level[b] / level[before]) ** (12 / n) - 1) * 100))
    print("  %-24s %s" % ("RSP (fon, masraf sonrası)", " | ".join(cells)))

    print("\n== 5. strategy.run() ile tutarlılık")
    rets, _, _ = S.run()
    ref = {m: r for m, r, _ in rets["EW"]}
    worst = max(abs(ref[m] - ew["bizim (strategy.py EW)"][m]) for m in months if m in ref)
    print("  bu betiğin EW serisi ile strategy.run EW arasındaki en büyük aylık fark: %.2e" % worst)


main()
strategies()
