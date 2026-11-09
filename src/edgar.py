"""SEC EDGAR XBRL ingest + normalization layer.

Turns a company's raw XBRL companyfacts into a canonical quarterly panel.
The hard part is that tag usage varies by company and by era, so every
canonical concept resolves through an ordered fallback chain.
"""
import json
import os
import urllib.request
from collections import defaultdict

# The SEC requires a contact address in the User-Agent and rate-limits
# anonymous traffic. Set SEC_CONTACT to your own address; the placeholder
# works but is bad manners toward a free public service.
UA = "FinAdvisor Research %s" % os.environ.get("SEC_CONTACT", "contact@example.com")
CACHE = os.path.join(os.path.dirname(__file__), "..", "data")

# Ordered fallback chains: first tag that has data for a period wins.
INSTANT = {
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "short_term_investments": ["ShortTermInvestments",
                              "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                              "MarketableSecuritiesCurrent"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent",
                    "ReceivablesNetCurrent"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsNetExcludingGoodwill",
                    "FiniteLivedIntangibleAssetsNet"],
    # Debt comes in overlapping shapes, kept apart so metrics.snapshot can
    # add them without double counting: the current portion of long-term
    # debt; current debt including short-term borrowings; the non-current
    # portion; totals that already include the current portion; notes-style
    # debt (REITs, some industrials); and short-term borrowings. Realty
    # Income reports only NotesPayable, which the old chain lacked, so its
    # $26B of debt read as zero.
    "debt_current_ltd": ["LongTermDebtCurrent",
                         "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "debt_current_all": ["DebtCurrent"],
    "debt_noncurrent": ["LongTermDebtNoncurrent",
                        "LongTermDebtAndCapitalLeaseObligations"],
    "debt_total": ["LongTermDebt",
                   "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
                   "DebtAndCapitalLeaseObligations",
                   "DebtLongtermAndShorttermCombinedAmount"],
    "debt_notes": ["NotesPayable", "SeniorNotes", "UnsecuredDebt", "SecuredDebt",
                   "LongTermNotesPayable", "ConvertibleNotesPayable",
                   "ConvertibleDebtNoncurrent", "ConvertibleSeniorNotesNoncurrent",
                   "ConvertibleDebt", "NonRecourseDebt"],
    "debt_short": ["ShortTermBorrowings", "CommercialPaper",
                   "OtherShortTermBorrowings"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "shares": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
}

DURATION = {
    # The last three only fill gaps. ASC 606 moved most filers onto the
    # RevenueFromContractWithCustomer tags in 2018; before that many used
    # SalesRevenueGoodsNet, and regulated utilities still use their own
    # sector tag. Without these, whole years of history simply vanish.
    # Banks and brokers report total net revenue as RevenuesNetOfInterestExpense
    # and tag RevenueFromContract... for fee income only, so the bank tag
    # leads; without it JPM's latest usable quarter was 2014.
    # Total revenue before its contract-revenue subset: RevenueFromContract...
    # excludes premiums, rent and interest, and was 3% of MetLife's revenue
    # and 9% of American Tower's when it led the chain.
    "revenue": ["RevenuesNetOfInterestExpense",
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueGoodsNet", "SalesRevenueServicesNet",
                "RegulatedAndUnregulatedOperatingRevenue"],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold",
             "CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization",
             "CostOfServicesExcludingDepreciationDepletionAndAmortization",
             "CostOfGoodsAndServicesSoldExcludingDepreciationDepletionAndAmortization"],
    "gross_profit": ["GrossProfit"],
    # Operating income only. Pretax income used to stand in for it, which
    # is EBIT less interest: it read Pfizer's interest coverage as 1.6
    # instead of 2.6. metrics.snapshot rebuilds EBIT from pretax + interest.
    "operating_income": ["OperatingIncomeLoss"],
    # NetIncomeLoss is profit attributable to the parent and is the right
    # numerator against StockholdersEquity. ProfitLoss (which includes
    # noncontrolling interest) only fills gaps -- Ford switched to it in 2025
    # and stopped tagging NetIncomeLoss entirely.
    "net_income": ["NetIncomeLoss", "ProfitLoss",
                   "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    # Expense tags only. The net interest tags (income minus expense) used to
    # sit at the end of this chain; abs() in metrics then turned net interest
    # income into an "expense" and corrupted interest coverage.
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating",
                         "InterestAndDebtExpense", "InterestExpenseDebt"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    # Some filers -- utilities especially -- tag capex only in their own
    # extension namespace, which companyfacts does not return at all. There
    # is no us-gaap fallback for those; the gap is reported, never estimated.
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements",
              "PaymentsToAcquireOilAndGasProperty"],
    "depreciation": ["DepreciationDepletionAndAmortization",
                     "DepreciationAndAmortization",
                     "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    "rnd": ["ResearchAndDevelopmentExpense"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "dividends": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "eps_diluted": ["EarningsPerShareDiluted"],
}


def _get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=60).read()
    if dest:
        with open(dest, "wb") as fh:
            fh.write(raw)
    return json.loads(raw)


def resolve_cik(ticker):
    if ticker.upper() in CIK_OVERRIDE:
        cik = CIK_OVERRIDE[ticker.upper()]
        return cik, profile(cik)["name"]
    path = os.path.join(CACHE, "tickers.json")
    if not os.path.exists(path):
        _get("https://www.sec.gov/files/company_tickers.json", path)
    table = json.load(open(path))
    for row in table.values():
        if row["ticker"].upper() == ticker.upper():
            return row["cik_str"], row["title"]
    raise KeyError("ticker bulunamadi: " + ticker)


def companyfacts(cik, refresh=False):
    path = os.path.join(CACHE, "facts_%010d.json" % cik)
    if os.path.exists(path) and not refresh:
        return json.load(open(path))
    return _get("https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik, path)


def _reconcile_equity(rows):
    """Corrects equity when a filer tags more than one value for a date.

    A tag can carry several values for the same instant -- an equity
    rollforward line alongside the balance-sheet total, say -- and picking
    the wrong one breaks every leverage and return ratio downstream. The
    balance sheet itself settles it: equity is total liabilities and equity
    minus total liabilities, both of which the filer reported.
    """
    for d, r in rows.items():
        total, liab, eq = (r.pop("_balance_total", None),
                           r.get("liabilities"), r.get("equity"))
        if total is None or liab is None or eq is None or not total:
            continue
        implied = total - liab
        if abs(implied - eq) / abs(total) > 0.01:
            r["equity"] = implied
            r["equity_reconciled"] = True


def _entries(facts, tag, asof=None):
    """Facts for a tag, optionally restricted to what had been filed by a date.

    The `asof` filter is what makes an honest backtest possible. It drops
    both biases at once: a signal cannot use a filing published after the
    decision date, and because later restatements are themselves later
    filings, the values returned are the ones that were on the record at the
    time rather than today's revised figures.
    """
    node = facts["facts"].get("us-gaap", {}).get(tag)
    if not node:
        return []
    for unit in ("USD", "USD/shares", "shares"):
        if unit in node["units"]:
            rows = node["units"][unit]
            if asof:
                rows = [e for e in rows if e.get("filed", "9999") <= asof]
            return rows
    return []


def instant_series(facts, chain, asof=None):
    """{date: value} for balance-sheet (point-in-time) concepts.

    Later filings restate earlier periods, so the last entry for a given
    date wins. Only 10-K/10-Q are trusted.
    """
    out = {}
    for tag in reversed(chain):          # earlier chain entries overwrite later
        for e in _entries(facts, tag, asof):
            if e.get("form") not in ("10-K", "10-Q"):
                continue
            out[e["end"]] = e["val"]
    return out


def _periods(facts, chain, asof=None):
    """{(start, end): value} for a flow concept, best tag per period."""
    out = {}
    for tag in reversed(chain):
        for e in _entries(facts, tag, asof):
            if e.get("form") not in ("10-K", "10-Q") or "start" not in e:
                continue
            out[(e["start"], e["end"])] = e["val"]
    return out


def _days(a, b):
    from datetime import date
    return (date(*map(int, b.split("-"))) - date(*map(int, a.split("-")))).days


QUARTER_DAYS = (60, 120)    # 52/53-week filers run a 16-week first quarter (112 days)


def quarterly_flows(facts, chain, asof=None):
    """{end_date: quarterly value} for a flow concept.

    Two shapes have to be unwound. A 10-Q reports cash-flow items
    year-to-date, so Q2/Q3 arrive as 6- and 9-month cumulatives; and a 10-K
    reports the fiscal year only, so the final quarter never appears
    directly. Both are recovered by subtracting the shorter period that
    shares the same start date.
    """
    from datetime import date, timedelta
    lo, hi = QUARTER_DAYS
    periods = _periods(facts, chain, asof)
    out, starts = {}, {}
    for (s, e), v in periods.items():
        if lo <= _days(s, e) <= hi:
            out[e] = v
            starts[e] = s

    def day_after(d):
        return (date.fromisoformat(d) + timedelta(days=1)).isoformat()

    by_start = defaultdict(list)
    for (s, e) in periods:
        by_start[s].append(e)
    for s, ends in by_start.items():
        ends.sort()
        for prev, cur in zip(ends, ends[1:]):
            if cur in out or not lo <= _days(prev, cur) <= hi:
                continue
            out[cur] = periods[(s, cur)] - periods[(s, prev)]
            starts[cur] = day_after(prev)

    # Some filers publish only discrete three-month periods in their 10-Qs
    # and never a year-to-date figure, so the subtraction above has nothing
    # to work with and the final quarter stays missing. Recover it from the
    # annual total minus the three quarters that are already known.
    for (s, e), annual in periods.items():
        if e in out or not 330 <= _days(s, e) <= 400:
            continue
        inner = [q for q in out if s < q < e and _days(s, q) >= 60]
        if len(inner) == 3:
            out[e] = annual - sum(out[q] for q in inner)

    # A quarter that was never reported on its own, but sits inside a
    # longer period whose other quarters are known (Con Ed's Q2: nine months
    # minus Q1 minus Q3), is that period less the known quarters.
    for (s, e), total in periods.items():
        if not 150 <= _days(s, e) <= 400:
            continue
        inner = sorted((starts[q], q) for q in out
                       if q in starts and starts[q] >= s and q <= e)
        if not inner or inner[0][0] != s or inner[-1][1] != e:
            continue
        gaps = [(day_after(a_end), b_start) for (_, a_end), (b_start, _)
                in zip(inner, inner[1:]) if day_after(a_end) != b_start]
        if len(gaps) != 1:
            continue
        g_start, g_next = gaps[0]
        g_end = (date.fromisoformat(g_next) - timedelta(days=1)).isoformat()
        if g_end in out or not lo <= _days(g_start, g_end) <= hi:
            continue
        out[g_end] = total - sum(out[q] for _, q in inner)
        starts[g_end] = g_start
    return out


# Share count sources, best first. The cover-page count is missing for some
# multi-class filers (Alphabet, Meta report none) and stops being tagged by
# others (Berkshire's ends in 2011), so a source is used only if its latest
# count is recent; the balance-sheet count and the diluted weighted average
# are undimensioned totals across classes.
SHARE_CHAIN = [("dei", "EntityCommonStockSharesOutstanding"),
               ("us-gaap", "CommonStockSharesOutstanding"),
               ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")]
SHARE_MAX_AGE_DAYS = 400


def share_count_detail(facts, asof=None):
    """{period_end: (shares, filed)} from the first fresh source in SHARE_CHAIN.

    Only 10-K/10-Q values filed by `asof` count; for a period reported more
    than once the latest filing wins (a later filing restates for splits).
    A source whose latest value is more than SHARE_MAX_AGE_DAYS before
    `asof` (today when None) is skipped. An isolated value more than 20x off
    both neighbours is an XBRL scale error (thousands or millions entered as
    units) and is dropped. Empty when no source qualifies.
    """
    from datetime import date
    ref = asof or date.today().isoformat()
    for taxonomy, tag in SHARE_CHAIN:
        node = facts["facts"].get(taxonomy, {}).get(tag)
        if not node:
            continue
        out, seen = {}, defaultdict(set)
        for e in node["units"].get("shares", []):
            if e.get("form") not in ("10-K", "10-Q") or not e.get("val"):
                continue
            filed = e.get("filed", "9999")
            if asof is not None and filed > asof:
                continue
            seen[(e["end"], filed)].add(e["val"])
            if e["end"] not in out or filed >= out[e["end"]][1]:
                out[e["end"]] = (e["val"], filed)
        # Multi-class filers (Visa) report one count per class for the same
        # date; their series jumps between classes by design, so the
        # scale-error test below would delete real values.
        multi = any(len(v) > 1 for v in seen.values())
        ends = [] if multi else sorted(out)
        spikes = [cur for prev, cur, nxt in zip(ends, ends[1:], ends[2:])
                  if (out[cur][0] > 20 * out[prev][0] and out[cur][0] > 20 * out[nxt][0])
                  or (20 * out[cur][0] < out[prev][0] and 20 * out[cur][0] < out[nxt][0])]
        for cur in spikes:
            del out[cur]
        if out and _days(max(out), ref) <= SHARE_MAX_AGE_DAYS:
            return out
    return {}


def share_counts(facts, asof=None):
    """{period_end: shares}; see share_count_detail."""
    return {e: v for e, (v, _) in share_count_detail(facts, asof).items()}


def is_split(factor):
    """A real split is a simple ratio (2, 3:2, 10, 1:10). Yahoo also logs
    spin-offs as "splits" with factors like 2.376 (eBay/PayPal); those do
    not change the share count and must not be applied to it."""
    if not factor or factor <= 0:
        return False
    for x in (factor, 1 / factor):
        if abs(x * 2 - round(x * 2)) < 0.02 and round(x * 2) >= 2:
            return True
    return False


def to_price_basis(count, filed, splits):
    """Puts a filed share count on the split basis of today's adjusted
    prices: only splits after the filing date, because a filing made after
    a split already reports post-split figures."""
    for sp in splits:
        if sp["date"] > filed and is_split(sp["factor"]):
            count *= sp["factor"]
    return count


def net_issuance(facts, asof, splits):
    """Log change in split-adjusted share count over about a year.

    Positive means new shares were issued (dilution), negative means a net
    buyback (Pontiff & Woodgate 2008). `splits` is [{"date", "factor"}] from
    the price history; counts are put on today's split basis before the
    comparison. Uses only counts filed by `asof` (today when None).
    """
    import math
    counts = share_count_detail(facts, asof)
    if not counts:
        return None
    now = max(counts)
    earlier = [d for d in counts if 330 <= _days(d, now) <= 400]
    if not earlier:
        return None
    then = max(earlier)
    a = to_price_basis(counts[now][0], counts[now][1], splits)
    b = to_price_basis(counts[then][0], counts[then][1], splits)
    return math.log(a / b)


def annual_flows(facts, chain, asof=None):
    return {e: v for (s, e), v in _periods(facts, chain, asof).items()
            if 330 <= _days(s, e) <= 400}


def panel(facts, asof=None):
    """Canonical quarterly panel: {date: {concept: value}}.

    Pass `asof` (a YYYY-MM-DD string) to reconstruct the panel as it stood
    on that date, using only filings published by then.
    """
    rows = defaultdict(dict)
    for name, chain in INSTANT.items():
        for d, v in instant_series(facts, chain, asof).items():
            rows[d][name] = v
    for d, v in instant_series(facts, ["LiabilitiesAndStockholdersEquity"], asof).items():
        rows[d]["_balance_total"] = v
    _reconcile_equity(rows)
    for name, chain in DURATION.items():
        for d, v in quarterly_flows(facts, chain, asof).items():
            rows[d][name] = v
        for d, v in annual_flows(facts, chain, asof).items():
            rows[d][name + "_fy"] = v
    _bank_revenue(facts, rows, asof)
    _carry_debt(rows)
    return dict(sorted(rows.items()))


DEBT_KEYS = ("debt_current_ltd", "debt_current_all", "debt_noncurrent",
             "debt_total", "debt_notes", "debt_short")


def _carry_debt(rows):
    """Debt that some filers tag only at fiscal year end (General Motors)
    is carried into the following quarters, for up to 400 days, so a 10-Q
    without the tag does not read as debt-free. `_debt_ever` marks every
    date after the first debt observation: a company that has reported debt
    and stops tagging it has unknown debt, not none."""
    last, material = {}, None
    for d in sorted(rows):
        row = rows[d]
        if any(k in row for k in DEBT_KEYS):
            for k in DEBT_KEYS:
                if k in row:
                    last[k] = (d, row[k])
            biggest = max(row[k] or 0 for k in DEBT_KEYS if k in row)
            if row.get("assets") and biggest > 0.01 * row["assets"]:
                material = d
        elif "assets" in row:
            for k, (when, v) in last.items():
                if _days(when, d) <= 400:
                    row[k] = v
        # Debt worth more than 1% of assets reported in the last six years:
        # if the tags then go quiet, the debt is unknown rather than zero.
        if material and _days(material, d) <= 6 * 365:
            row["_debt_ever"] = True


# Regional banks such as Regions, Truist and Synchrony tag no total revenue
# at all, only its two parts. A bank's net revenue is net interest income
# plus noninterest income, so where revenue is missing it is rebuilt from
# them; a period that has a revenue tag is never overwritten.
BANK_REVENUE_PARTS = {
    "net_interest_income": ["InterestIncomeExpenseNet", "InterestRevenueExpenseNet"],
    "noninterest_income": ["NoninterestIncome"],
}


def _bank_revenue(facts, rows, asof):
    parts = {}
    for name, chain in BANK_REVENUE_PARTS.items():
        parts[name] = (quarterly_flows(facts, chain, asof),
                       annual_flows(facts, chain, asof))
    (nii_q, nii_y), (non_q, non_y) = parts["net_interest_income"], parts["noninterest_income"]
    for d in set(nii_q) & set(non_q):
        if "revenue" not in rows[d]:
            rows[d]["revenue"] = nii_q[d] + non_q[d]
    for d in set(nii_y) & set(non_y):
        if "revenue_fy" not in rows[d]:
            rows[d]["revenue_fy"] = nii_y[d] + non_y[d]


# Reorganizations mint a fresh CIK, so the ticker file points at a holdco
# that only has filings since the restructure. These map back to the entity
# that carries the operating history.
CIK_OVERRIDE = {
    "XOM": 34088,      # ExxonMobil Holdings Corp -> Exxon Mobil Corp
}


def profile(cik):
    """Filer metadata: name, SIC industry code, former names."""
    path = os.path.join(CACHE, "sub_%010d.json" % cik)
    if os.path.exists(path):
        d = json.load(open(path))
    else:
        d = _get("https://data.sec.gov/submissions/CIK%010d.json" % cik, path)
    return {"name": d.get("name"), "sic": d.get("sic"),
            "industry": d.get("sicDescription"),
            "tickers": d.get("tickers", []),
            "former_names": [f["name"] for f in d.get("formerNames", [])]}


def sector(sic):
    """Coarse bucket. Drives which models are even applicable."""
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return "unknown"
    # REITs (6798) own property, they do not lend: valuing them on a bank's
    # justified P/B ranked them the wrong way in both backtest windows.
    if 6500 <= s <= 6599 or s == 6798:
        return "real_estate"
    if 6000 <= s <= 6499 or 6700 <= s <= 6799:
        return "financial"
    if 4900 <= s <= 4999:
        return "utility"
    if 1000 <= s <= 1499 or 2900 <= s <= 2999:
        return "energy"
    if 2000 <= s <= 3999:
        return "manufacturing"
    if 5000 <= s <= 5999:
        return "retail"
    return "other"
