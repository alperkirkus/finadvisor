"""Reads the quarter's diluted EPS out of earnings press releases.

The edgartools half of release_eps.py. It runs in its own environment and
isolated, because edgartools installs as `edgar`, the name of this
project's own SEC module:

    uv venv /tmp/release && uv pip install --python /tmp/release/bin/python edgartools
    /tmp/release/bin/python -I src/release_extract.py data/release_sample.json

Writes release_extract*.json beside the sample, one row per event, and can
be re-run: events already read are kept.
"""
import calendar
import json
import math
import os
import re
import sys

import edgar
from edgar.earnings import EarningsRelease

# SEC asks automated clients to name themselves. This goes out through a
# third-party library, so it names the program and carries no contact.
edgar.set_identity("FinAdvisor research script")

QUARTER = re.compile(r"three months|quarter|\bq[1-4]\b|[1-4]q\b|"
                     r"(1[2-6]|twelve|thirteen|fourteen|sixteen) weeks", re.I)
LONGER = re.compile(r"(six|nine|twelve) months|year|ytd|(2[4-9]|[3-5]\d) weeks", re.I)
NOT_A_PERIOD = re.compile(r"change|%|inc/|impact|growth|variance|b/\(w\)", re.I)
# A release prints several "diluted" lines; only the GAAP net one is the
# number XBRL will carry.
PER_SHARE = re.compile(r"per (common |diluted |ordinary )?share|\beps\b|"
                       r"^diluted( net)? (earnings|income|\(?loss)", re.I)
NOT_GAAP_EPS = re.compile(r"adjust|non-gaap|core|operating|special|exclud|normaliz|comparable|"
                          r"book value|ffo|project|guidance|outlook|impact|effect|shares|"
                          r"average|weighted|calculation|dilution|dividend", re.I)
PART = re.compile(r"continuing|discontinued", re.I)


def _flat(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def _dated(label, end):
    """Does the column label carry the quarter's own end date?"""
    year, month, day = end[:4], int(end[5:7]), int(end[8:])
    if re.search(r"\b0?%d/0?%d/(%s|%s)\b" % (month, day, year, year[2:]), label):
        return True
    names = (calendar.month_name[month], calendar.month_abbr[month])
    return year in label and any(n.lower() in label.lower() for n in names)


def _column(columns, end):
    """(column position, how it was chosen) for the quarter ending on `end`.

    The column carrying that date when one does. Otherwise the leftmost
    three-month column: a release leads with the quarter it reports, and a
    bare year in a header is as often the fiscal year as the calendar one.
    """
    usable = [(i, _flat(c)) for i, c in enumerate(columns)
              if not NOT_A_PERIOD.search(_flat(c)) and not LONGER.search(_flat(c))]
    for i, label in usable:
        if _dated(label, end) and not re.search(r"\b(19|20)\d\d\b.*\b(19|20)\d\d\b", label):
            return i, "dated"
    for i, label in usable:
        if QUARTER.search(label):
            return i, "leftmost_quarter"
    return (usable[0][0], "leftmost") if usable else (None, None)


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _candidates(table, end):
    """Diluted GAAP EPS readings in one table:
    (value, label, column, method, row position)."""
    frame = table.dataframe
    position, method = _column(list(frame.columns), end)
    if position is None:
        return []
    column = _flat(frame.columns[position])
    labels = [_flat(i) for i in frame.index]
    values = [_number(row[position]) for row in frame.itertuples(index=False)]
    per_share = table.per_share_rows
    trusted = set() if per_share is None else {_flat(i) for i in per_share.index}
    out = []
    for n, (label, number) in enumerate(zip(labels, values)):
        if number is None or abs(number) >= 1000:
            continue
        if "dilut" not in label.lower() or NOT_GAAP_EPS.search(label):
            continue
        # A bare "Diluted" also labels the share count. It is an EPS line
        # where the library classed it per-share, or where it follows a
        # "Basic" line and is not a whole number, as share counts print.
        bare = not PER_SHARE.search(label)
        paired = n > 0 and labels[n - 1].lower().startswith("basic") and number != int(number)
        if bare and label not in trusted and not (paired and abs(number) < 100):
            continue
        out.append((number, label, column, method, n))
    # Under bare labels a share count in millions can pass for a per-share
    # line; it stands out by being far larger than the EPS beside it.
    bare = [abs(c[0]) for c in out if not PER_SHARE.search(c[1]) and c[0]]
    if bare:
        out = [c for c in out if PER_SHARE.search(c[1]) or abs(c[0]) <= 20 * min(bare)]
    if out or any("dilut" in label.lower() for label in labels):
        return out
    # Some statements lose their "Basic" and "Diluted" header lines in
    # parsing and keep two rows under one per-share label; the second is
    # the diluted one.
    for n in range(1, len(labels)):
        back = [m for m in range(max(0, n - 3), n) if labels[m] == labels[n]]
        if (back and values[n] is not None and abs(values[n]) < 1000
                and PER_SHARE.search(labels[n]) and not NOT_GAAP_EPS.search(labels[n])):
            out.append((values[n], labels[n], column, method, n))
    return out


def read(event):
    filing = edgar.find(event["accession"])
    if filing is None:
        return {"status": "no_filing"}
    release = EarningsRelease.from_filing(filing)
    if release is None:
        return {"status": "no_release"}
    found = []
    for k, table in enumerate(release.financial_tables):
        try:
            found.extend(c + (k,) for c in _candidates(table, event["end"]))
        except Exception:
            continue    # one unreadable table does not hide the others
    if not found:
        return {"status": "no_eps", "tables": len(release.financial_tables)}
    # Readings from a dated column outrank positional ones, the net figure
    # outranks a part of it, then the value most tables agree on; among
    # equals the earliest table, and in it the lowest line, where a
    # statement puts net earnings after its parts.
    dated = [f for f in found if f[3] == "dated"] or found
    whole = [f for f in dated if not PART.search(f[1])] or dated
    counts = {}
    for f in whole:
        counts[f[0]] = counts.get(f[0], 0) + 1
    best = max(whole, key=lambda f: (counts[f[0]], -f[5], f[4]))
    return {"status": "ok", "eps": best[0], "label": best[1], "column": best[2],
            "method": best[3], "readings": len(found),
            "agreeing": counts[best[0]], "distinct": len(counts)}


def main(path):
    events = json.load(open(path))
    if not events:
        raise ValueError("no events in %s" % path)
    out_path = path.replace("release_sample", "release_extract")
    done = {}
    if os.path.exists(out_path):
        done = {(r["ticker"], r["end"]): r for r in json.load(open(out_path))}
    for i, event in enumerate(events, 1):
        key = (event["ticker"], event["end"])
        if key in done:
            continue
        try:
            row = read(event)
        except Exception as exc:
            row = {"status": "error", "error": "%s: %s" % (type(exc).__name__, str(exc)[:120])}
        done[key] = {"ticker": event["ticker"], "end": event["end"], **row}
        if i % 20 == 0 or i == len(events):
            json.dump(list(done.values()), open(out_path, "w"), indent=1)
            print("%d/%d" % (i, len(events)), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
