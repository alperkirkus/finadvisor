"""Backtests hypotheses written as formulas over the components.

    engine.py catalog                     # what a hypothesis may be written with
    engine.py discover <hypotheses.json>  # search: 2006-2016, as many as you like
    engine.py validate                    # 2017-2021, only what discovery promoted
    engine.py sealed                      # 2022-2025, only what validation passed; logged
    engine.py ledger                      # every trial so far

Any command takes `--universe midsmall` to run on S&P 400/600 members
instead (see panel.py for why that universe is a second opinion). Its
trials and stages are kept apart from the S&P 500's.

A hypothesis is {"id", "type": "rank" | "event" | "risk", "expr", "horizon",
"rationale"}. A `rank` expression gives every company a number and is
scored as a ranking; an `event` expression is true or false and is scored
by what the flagged companies did next; both at 5, 20 or 60 days. A `risk`
expression gives every company a number that is higher the likelier it is
to fall hard, and is scored at 250 days by how much better it separates the
companies that fell than the daily range alone does. Every trial is written
to the ledger, so the number of things tried is always known.

Searching is free on the discovery years. What is found there is believed
only if it holds on years the search never saw.
"""
import ast
import hashlib
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import components as C        # noqa: E402
import panel as P             # noqa: E402

LEDGER = os.path.join(P.OUT, "ledger.jsonl")
STAGES = {"discover": ("2006-01-01", "2016-12-31"),
          "validate": ("2017-01-01", "2021-12-31"),
          "sealed": ("2022-01-01", "2025-12-31")}
HORIZONS = (5, 20, 60)
RISK_HORIZON, RISK_FALL, RISK_STEP = 250, -0.25, 21
RISK_BENCHMARK = "range14"    # what a risk hypothesis has to beat
STEP = 5                      # a signal is read every fifth trading day
# The panel a universe is read from, and its cost per side on traded weight.
UNIVERSES = {"sp500": ("panel.npz", 0.001), "midsmall": ("panel_midsmall.npz", 0.002),
             "etf": ("panel_etf.npz", 0.0005), "bist": ("panel_bist.npz", 0.002)}
PROMOTE_T, CONFIRM_T = 3.0, 2.0
MIN_NAMES, MIN_EVENTS = 50, 5


# ---------------------------------------------------------------- formulas

def _rank(x, member):
    """Cross-sectional percentile among the day's members, 0..1."""
    out = np.full(x.shape, np.nan, dtype=np.float32)
    for t in range(x.shape[0]):
        ok = member[t] & np.isfinite(x[t])
        n = ok.sum()
        if n >= MIN_NAMES:
            order = x[t, ok].argsort().argsort()
            out[t, ok] = (order + 0.5) / n
    return out


def _lag(x, n):
    out = np.full(x.shape, np.nan, dtype=np.float32)
    out[n:] = x[:-n]
    return out


def _ts(x, n, how):
    stack = np.stack([_lag(x, k) if k else x for k in range(int(n))])
    with np.errstate(all="ignore"):
        return getattr(np, how)(stack, axis=0)


def functions(member):
    return {
        "rank": lambda x: _rank(np.asarray(x, dtype=np.float32), member),
        "lag": lambda x, n: _lag(np.asarray(x, dtype=np.float32), int(n)),
        "delta": lambda x, n: x - _lag(np.asarray(x, dtype=np.float32), int(n)),
        "ts_mean": lambda x, n: _ts(x, n, "nanmean"),
        "ts_max": lambda x, n: _ts(x, n, "nanmax"),
        "ts_min": lambda x, n: _ts(x, n, "nanmin"),
        "ts_z": lambda x, n: (x - _ts(x, n, "nanmean")) / _ts(x, n, "nanstd"),
        "cross_up": lambda a, b: (a > b) & (_lag(np.asarray(a, dtype=np.float32), 1)
                                           <= _lag(np.broadcast_to(np.asarray(b, dtype=np.float32),
                                                                   np.shape(a)), 1)),
        "cross_down": lambda a, b: (a < b) & (_lag(np.asarray(a, dtype=np.float32), 1)
                                             >= _lag(np.broadcast_to(np.asarray(b, dtype=np.float32),
                                                                     np.shape(a)), 1)),
        "where": np.where, "abs": np.abs, "sign": np.sign, "log": np.log,
        "minimum": np.minimum, "maximum": np.maximum, "clip": np.clip,
    }


ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare, ast.Call, ast.Name, ast.Load,
           ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.Invert,
           ast.BitAnd, ast.BitOr, ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq)


def compile_formula(expr, names):
    """Code for a formula, after checking it is nothing but arithmetic on
    known components and functions. A formula comes from outside, possibly
    from a model; it is never executed as free Python."""
    tree = ast.parse(expr.replace(" and ", " & ").replace(" or ", " | "), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED):
            raise ValueError("not allowed in a formula: %s" % type(node).__name__)
        if isinstance(node, ast.Name) and node.id not in names:
            raise ValueError("unknown name: %s" % node.id)
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and not node.keywords):
            raise ValueError("only plain function calls are allowed")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError("only numbers are allowed as constants")
    return compile(tree, "<formula>", "eval")


# ------------------------------------------------------------------- data

class Market:
    def __init__(self, universe="sp500"):
        name, self.cost = UNIVERSES[universe]
        self.universe = universe
        p = P.load(name)
        self.dates = [str(d) for d in p["dates"]]
        self.labels = [str(x) for x in p["labels"]]
        self.member = p["member"]
        self.bars = {k: p[k] for k in ("open", "high", "low", "close")}
        self.parts = C.compute(p)
        close = p["close"].copy()
        # A company that stops trading is held at its last price.
        for j in range(close.shape[1]):
            ok = np.where(np.isfinite(close[:, j]))[0]
            if len(ok):
                close[ok[-1] + 1:, j] = close[ok[-1], j]
        entry = np.full(close.shape, np.nan, dtype=np.float32)
        entry[:-1] = p["open"][1:]
        still = ~np.isfinite(entry) & np.isfinite(close)      # no next open: last price
        entry[still] = close[still]
        self.forward = {}
        for h in HORIZONS + (RISK_HORIZON,):
            out = np.full(close.shape, np.nan, dtype=np.float32)
            with np.errstate(all="ignore"):
                out[:-h] = close[h:] / entry[:-h] - 1
            self.forward[h] = out
        self.env = {**self.parts, **functions(self.member)}

    def grid(self, stage, every, embargo=0):
        """Signal dates of a stage. With `embargo`, the last that many
        trading days are left out, so an outcome measured that far ahead
        ends inside the stage and never in the next one."""
        first, last = STAGES[stage]
        idx = [i for i, d in enumerate(self.dates) if first <= d <= last]
        if embargo:
            idx = idx[:-embargo]
        return idx[::every]


def newey_west(series, lag):
    x = np.asarray(series, dtype=float)
    n = len(x)
    if n < 12:
        return None
    dev = x - x.mean()
    var = float(dev @ dev) / n
    for k in range(1, lag + 1):
        var += 2 * (1 - k / (lag + 1)) * float(dev[k:] @ dev[:-k]) / n
    se = math.sqrt(max(var, 0) / n)
    return float(x.mean() / se) if se > 0 else None


def _spearman(a, b):
    ra, rb = a.argsort().argsort().astype(float), b.argsort().argsort().astype(float)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    den = math.sqrt(float(ra @ ra) * float(rb @ rb))
    return float(ra @ rb) / den if den else None


# ------------------------------------------------------------------ scoring

def score_rank(m, signal, h, stage):
    """A ranking: its rank IC, and a top-minus-bottom fifth held h days."""
    fwd = m.forward[h]
    ics = []
    for t in m.grid(stage, STEP):
        ok = m.member[t] & np.isfinite(signal[t]) & np.isfinite(fwd[t])
        if ok.sum() >= MIN_NAMES:
            ic = _spearman(signal[t, ok], fwd[t, ok])
            if ic is not None:
                ics.append(ic)
    t_ic = newey_west(ics, h // STEP - 1) if ics else None
    if t_ic is None:
        return {"insufficient": True, "dates": len(ics)}
    side = 1 if t_ic >= 0 else -1          # which end is long is read off discovery
    gross, net, held = [], [], (set(), set())
    for t in m.grid(stage, h):
        ok = np.where(m.member[t] & np.isfinite(signal[t]) & np.isfinite(fwd[t]))[0]
        if len(ok) < MIN_NAMES:
            continue
        order = ok[np.argsort(side * signal[t, ok])]
        k = len(order) // 5
        short, long = set(order[:k].tolist()), set(order[-k:].tolist())
        r = float(fwd[t, list(long)].mean() - fwd[t, list(short)].mean())
        traded = sum(2 * len(now - was) / k for now, was in ((long, held[0]), (short, held[1])))
        gross.append(r)
        net.append(r - m.cost * traded)
        held = (long, short)
    if len(net) < 12:
        return {"insufficient": True, "dates": len(net)}
    per_year = 252 / h
    sd = float(np.std(net, ddof=1))
    return {"ic": float(np.mean(ics)), "t": t_ic, "side": side, "dates": len(ics),
            "gross_annual": float(np.mean(gross)) * per_year,
            "net_annual": float(np.mean(net)) * per_year,
            "net_sharpe": float(np.mean(net)) / sd * math.sqrt(per_year) if sd else None,
            "periods": len(net)}


def score_event(m, flag, h, stage):
    """An event: what flagged companies returned over the next h days,
    against the day's members, and after a round trip's cost."""
    fwd = m.forward[h]
    excess, share = [], []
    for t in m.grid(stage, STEP):
        ok = m.member[t] & np.isfinite(fwd[t])
        hit = ok & (flag[t] == True)       # noqa: E712  (flag may hold NaN)
        if ok.sum() < MIN_NAMES:
            continue
        share.append(hit.sum() / ok.sum())
        if hit.sum() >= MIN_EVENTS:
            excess.append(float(fwd[t, hit].mean() - fwd[t, ok].mean()))
    t = newey_west(excess, h // STEP - 1) if excess else None
    if t is None:
        return {"insufficient": True, "dates": len(excess),
                "flagged_share": float(np.mean(share)) if share else 0.0}
    mean = float(np.mean(excess))
    side = 1 if mean >= 0 else -1
    net = side * mean - 2 * m.cost
    return {"excess": mean, "t": t, "side": side, "dates": len(excess),
            "flagged_share": float(np.mean(share)),
            "gross_annual": side * mean * 252 / h, "net_annual": net * 252 / h}


def _auc(values, falls):
    """P(a company that fell had the higher value); 0.5 is no information."""
    order = values.argsort().argsort().astype(float) + 1
    pos = falls.sum()
    return float((order[falls].sum() - pos * (pos + 1) / 2) / (pos * (len(values) - pos)))


def score_risk(m, signal, stage):
    """A risk measure: its AUC for a fall of more than 25% in a year, and
    its gain over the daily range's AUC on the same companies and dates."""
    fwd, base = m.forward[RISK_HORIZON], m.parts[RISK_BENCHMARK]
    aucs, gains = [], []
    for t in m.grid(stage, RISK_STEP, embargo=RISK_HORIZON):
        ok = m.member[t] & np.isfinite(signal[t]) & np.isfinite(fwd[t]) & np.isfinite(base[t])
        fell = fwd[t, ok] < RISK_FALL
        if ok.sum() < MIN_NAMES or not 3 <= fell.sum() < ok.sum():
            continue
        mine = _auc(signal[t, ok], fell)
        aucs.append(mine)
        gains.append(mine - _auc(base[t, ok], fell))
    if len(gains) < 12:
        return {"insufficient": True, "dates": len(gains)}
    # No spread at all (the benchmark scored against itself) is a t of zero.
    t = newey_west(gains, RISK_HORIZON // RISK_STEP - 1) or 0.0
    gain = float(np.mean(gains))
    return {"auc": float(np.mean(aucs)), "benchmark": float(np.mean(aucs)) - gain,
            "gain": gain, "t": t, "side": 1 if gain >= 0 else -1, "dates": len(gains),
            # promoted() and confirmed() read these: a risk measure passes by
            # beating the benchmark, never by being reliably worse than it.
            "gross_annual": gain, "net_annual": gain}


def evaluate(m, hyp, stage):
    with np.errstate(all="ignore"):
        value = eval(compile_formula(hyp["expr"], m.env), {"__builtins__": {}}, m.env)
    value = np.broadcast_to(np.asarray(value), m.member.shape)
    if hyp["type"] == "event":
        return score_event(m, value, hyp["horizon"], stage)
    if hyp["type"] == "risk":
        return score_risk(m, value.astype(np.float32), stage)
    return score_rank(m, value.astype(np.float32), hyp["horizon"], stage)


# ------------------------------------------------------------------- ledger

def key(hyp):
    text = "%s|%d|%s" % (hyp["type"], hyp["horizon"], "".join(hyp["expr"].split()))
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def ledger(universe="sp500"):
    if not os.path.exists(LEDGER):
        return []
    rows = [json.loads(line) for line in open(LEDGER) if line.strip()]
    return [r for r in rows if r.get("universe", "sp500") == universe]


def record(hyp, stage, stats, verdict, universe, **extra):
    row = {"key": key(hyp), "universe": universe, **extra,
           "id": hyp["id"], "type": hyp["type"], "horizon": hyp["horizon"],
           "expr": hyp["expr"], "rationale": hyp.get("rationale", ""),
           "source": hyp.get("source", ""), "stage": stage, "stats": stats,
           "verdict": verdict, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(LEDGER, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def promoted(stats):
    return (not stats.get("insufficient") and abs(stats["t"]) >= PROMOTE_T
            and stats["net_annual"] > 0)


def confirmed(stats, found):
    return (not stats.get("insufficient") and stats["side"] == found["side"]
            and abs(stats["t"]) >= CONFIRM_T and stats["net_annual"] > 0)


def line(row):
    s = row["stats"]
    if s.get("insufficient"):
        return "  %-26s %-5s %3dg  yetersiz veri (%s tarih)" % (row["id"][:26], row["type"],
                                                                 row["horizon"], s.get("dates"))
    if row["type"] == "risk":
        return ("  %-26s risk  250g  AUC %.3f (aralik %.3f)  kazanc %+.3f  t %+5.1f  %s"
                % (row["id"][:26], s["auc"], s["benchmark"], s["gain"], s["t"], row["verdict"]))
    main = ("IC %+.3f" % s["ic"]) if row["type"] == "rank" else ("fark %+.2f%%" % (100 * s["excess"]))
    extra = "" if row["type"] == "rank" else "  isaretlenen %%%.1f" % (100 * s["flagged_share"])
    return ("  %-26s %-5s %3dg  %-12s t %+5.1f  brut %+6.1f%%  net %+6.1f%%/yil%s  %s"
            % (row["id"][:26], row["type"], row["horizon"], main, s["t"],
               100 * s["gross_annual"], 100 * s["net_annual"], extra, row["verdict"]))


def main(argv):
    universe = "sp500"
    if "--universe" in argv:
        i = argv.index("--universe")
        universe = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
        if universe not in UNIVERSES:
            raise SystemExit("bilinmeyen evren: %s" % universe)
    cmd = argv[1] if len(argv) > 1 else "ledger"
    if cmd == "catalog":
        print("Components (each a number per company per day, known at the close):")
        for name, family, formula in C.CATALOG:
            print("  %-12s [%s] %s" % (name, family, formula))
        print("Functions: rank(x) cross-sectional percentile 0..1 among the day's index members; "
              "lag(x, n); delta(x, n); ts_mean/ts_max/ts_min/ts_z(x, n) over a company's last n "
              "days (n <= 60); where(cond, a, b); abs; sign; log; minimum; maximum; clip.")
        print("Operators: + - * / ** and comparisons; combine conditions with & and |.")
        return
    rows = ledger(universe)
    if cmd == "ledger":
        by_stage = {s: [r for r in rows if r["stage"] == s] for s in STAGES}
        print("%d kesif denemesi, %d terfi; %d dogrulama, %d gecti; %d muhurlu bakis"
              % (len(by_stage["discover"]), sum(r["verdict"] == "terfi" for r in by_stage["discover"]),
                 len(by_stage["validate"]), sum(r["verdict"] == "gecti" for r in by_stage["validate"]),
                 len(by_stage["sealed"])))
        for r in rows:
            print(line(r))
        return
    m = Market(universe)
    done = {(r["key"], r["stage"]) for r in rows}
    if cmd == "discover":
        hyps = json.load(open(argv[2]))
        new = [h for h in hyps if (key(h), "discover") not in done]
        print("%d hipotez, %d yeni" % (len(hyps), len(new)))
        for h in new:
            if not ((h["type"] in ("rank", "event") and h["horizon"] in HORIZONS)
                    or (h["type"] == "risk" and h["horizon"] == RISK_HORIZON)):
                print("  %-26s gecersiz tur ya da ufuk" % h["id"][:26])
                continue
            try:
                stats = evaluate(m, h, "discover")
            except Exception as exc:
                print("  %-26s formul hatasi: %s" % (h["id"][:26], str(exc)[:70]))
                continue
            print(line(record(h, "discover", stats, "terfi" if promoted(stats) else "-", universe)))
        return
    source = "discover" if cmd == "validate" else "validate"
    passed = "terfi" if cmd == "validate" else "gecti"
    stage = cmd
    if stage not in ("validate", "sealed"):
        raise SystemExit("bilinmeyen komut: %s" % cmd)
    todo = [r for r in rows if r["stage"] == source and r["verdict"] == passed
            and (r["key"], stage) not in done]
    print("%s: %d aday" % (stage, len(todo)))
    for r in todo:
        found = next(x for x in rows if x["key"] == r["key"] and x["stage"] == "discover")["stats"]
        stats = evaluate(m, r, stage)
        print(line(record(r, stage, stats, "gecti" if confirmed(stats, found) else "kaldi", universe)))


if __name__ == "__main__":
    main(sys.argv)
