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
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent",
                     "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebt",
                        "LongTermDebtAndCapitalLeaseObligations"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "shares": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
}

DURATION = {
    # The last three only fill gaps. ASC 606 moved most filers onto the
    # RevenueFromContractWithCustomer tags in 2018; before that many used
    # SalesRevenueGoodsNet, and regulated utilities still use their own
    # sector tag. Without these, whole years of history simply vanish.
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueGoodsNet", "SalesRevenueServicesNet",
                "RegulatedAndUnregulatedOperatingRevenue"],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold",
             "CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization",
             "CostOfServicesExcludingDepreciationDepletionAndAmortization",
             "CostOfGoodsAndServicesSoldExcludingDepreciationDepletionAndAmortization"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss",
                         "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    # NetIncomeLoss is profit attributable to the parent and is the right
    # numerator against StockholdersEquity. ProfitLoss (which includes
    # noncontrolling interest) only fills gaps -- Ford switched to it in 2025
    # and stopped tagging NetIncomeLoss entirely.
    "net_income": ["NetIncomeLoss", "ProfitLoss",
                   "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating",
                         "InterestAndDebtExpense", "InterestExpenseDebt",
                         "InterestIncomeExpenseNonoperatingNet",
                         "InterestIncomeExpenseNet"],
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


def quarterly_flows(facts, chain, asof=None):
    """{end_date: quarterly value} for a flow concept.

    Two shapes have to be unwound. A 10-Q reports cash-flow items
    year-to-date, so Q2/Q3 arrive as 6- and 9-month cumulatives; and a 10-K
    reports the fiscal year only, so the final quarter never appears
    directly. Both are recovered by subtracting the shorter period that
    shares the same start date.
    """
    periods = _periods(facts, chain, asof)
    out = {}
    for (s, e), v in periods.items():
        if 60 <= _days(s, e) <= 110:
            out[e] = v

    by_start = defaultdict(list)
    for (s, e) in periods:
        by_start[s].append(e)
    for s, ends in by_start.items():
        ends.sort()
        for prev, cur in zip(ends, ends[1:]):
            if cur in out or not 60 <= _days(prev, cur) <= 110:
                continue
            out[cur] = periods[(s, cur)] - periods[(s, prev)]

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


def share_counts(facts, asof=None):
    """{period_end: shares} from the first fresh source in SHARE_CHAIN.

    Only 10-K/10-Q values filed by `asof` count, and a source whose latest
    value is more than SHARE_MAX_AGE_DAYS before `asof` (today when None) is
    skipped. Empty when no source qualifies -- never a stale count.
    """
    from datetime import date
    ref = asof or date.today().isoformat()
    for taxonomy, tag in SHARE_CHAIN:
        node = facts["facts"].get(taxonomy, {}).get(tag)
        if not node:
            continue
        out = {}
        for e in node["units"].get("shares", []):
            if e.get("form") not in ("10-K", "10-Q") or not e.get("val"):
                continue
            if asof is not None and e.get("filed", "9999") > asof:
                continue
            out[e["end"]] = e["val"]
        if out and _days(max(out), ref) <= SHARE_MAX_AGE_DAYS:
            return out
    return {}


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
    return dict(sorted(rows.items()))


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
    if 6000 <= s <= 6499 or 6700 <= s <= 6799:
        return "financial"
    if 6500 <= s <= 6599:
        return "real_estate"
    if 4900 <= s <= 4999:
        return "utility"
    if 1000 <= s <= 1499 or 2900 <= s <= 2999:
        return "energy"
    if 2000 <= s <= 3999:
        return "manufacturing"
    if 5000 <= s <= 5999:
        return "retail"
    return "other"
