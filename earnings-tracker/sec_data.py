"""Pulls company financials and the earnings calendar from free, keyless
government and exchange sources.

Why not a paid API: the original design called for Financial Modeling Prep,
but testing showed its free/legacy endpoints were retired, and even the
current plan caps history at 5 quarters. Everything here comes straight from
SEC EDGAR (the primary filings themselves) and Nasdaq's public calendar,
with no subscription and no cap on history.

The one real cost of using raw SEC data instead of a packaged API: companies
don't all use the same XBRL tag for the same concept, and each filing can
report the same quarter more than once (a quarter's own number, plus a
year-to-date cumulative number, both tagged under the same concept). Both
problems are handled below rather than assumed away.
"""

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

# SEC requires a real identifying User-Agent on every request, or it will
# reject you. This is their policy, not a formality — an anonymous or fake
# UA gets blocked. See https://www.sec.gov/os/webmaster-faq#developers
SEC_HEADERS = {"User-Agent": "Personal earnings tracker research@example.com"}
NASDAQ_HEADERS = {"User-Agent": "Mozilla/5.0"}

_CIK_CACHE = Path(__file__).parent / "watchlist_data" / ".cik_cache.json"


def _load_cik_map():
    """The ticker->CIK lookup is one ~800KB file that never needs refetching
    more than occasionally, so it's cached locally after the first pull."""
    if _CIK_CACHE.exists():
        return json.loads(_CIK_CACHE.read_text())

    r = httpx.get("https://www.sec.gov/files/company_tickers.json",
                  headers=SEC_HEADERS, timeout=30)
    r.raise_for_status()
    raw = r.json()

    mapping = {e["ticker"].upper(): str(e["cik_str"]).zfill(10) for e in raw.values()}
    _CIK_CACHE.write_text(json.dumps(mapping))
    return mapping


def get_cik(ticker):
    """Returns the 10-digit CIK for a ticker, or None if not found."""
    return _load_cik_map().get(ticker.upper())


# Concept fallback lists. Companies tag the same line item differently, so
# each concept lists every common tag in priority order — the first one a
# company actually reports wins. GrossProfit is deliberately absent from the
# fallback chain: when a company doesn't report it directly, it's derived
# from Revenue minus CostOfRevenue instead of guessing at a substitute tag.
# Each concept maps to (fallback tag list, XBRL unit key, can_derive_q4).
# Nearly everything is a dollar FLOW figure, so quarters sum into the annual
# total and a missing Q4 can be derived as FullYear - Q1 - Q2 - Q3.
#
# EPS cannot use that trick. It's a per-share RATIO (net income / diluted
# share count), and share counts differ quarter to quarter — ratios from
# different periods don't subtract into a meaningful result the way dollar
# totals do. Deriving Q4 EPS this way produced -$0.25 for a real NVIDIA
# quarter that was solidly profitable, caught by checking output against
# what was actually known to be true rather than trusting the arithmetic.
# EPS is marked non-derivable; a missing Q4 EPS is preferable to a wrong one.
CONCEPTS = {
    "revenue":            (["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                             "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"], "USD", True),
    "cost_of_revenue":    (["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"], "USD", True),
    "gross_profit":       (["GrossProfit"], "USD", True),
    "net_income":         (["NetIncomeLoss", "ProfitLoss"], "USD", True),
    "eps_diluted":        (["EarningsPerShareDiluted"], "USD/shares", False),
    "operating_expenses": (["OperatingExpenses", "CostsAndExpenses"], "USD", True),
    "operating_cash_flow": (["NetCashProvidedByUsedInOperatingActivities",
                              "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"], "USD", True),
    "capex":              (["PaymentsToAcquirePropertyPlantAndEquipment",
                             "PaymentsForCapitalImprovements", "PaymentsToAcquireProductiveAssets"], "USD", True),
    # Only fetched to build a real EBITDA for the valuation multiple in the
    # Company Story section (see build_valuation() in analyzer.py) — nothing
    # else here needs operating income or D&A separately from net income.
    "operating_income":  (["OperatingIncomeLoss"], "USD", True),
    "depreciation_amortization": (["DepreciationDepletionAndAmortization",
                                    "DepreciationAmortizationAndAccretionNet",
                                    "DepreciationAndAmortization"], "USD", True),
}

# Instant (point-in-time) concepts — balance sheet items with no duration,
# unlike everything above which covers a span of time.
INSTANT_CONCEPTS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
}


def _fetch_concept(cik, tag, unit):
    """One XBRL concept's full reporting history, or None if this company
    doesn't use that tag, or doesn't report it in the expected unit."""
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    r = httpx.get(url, headers=SEC_HEADERS, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("units", {}).get(unit, [])


def _dedupe_by_end(entries):
    """When the same end date appears more than once — a restatement or
    amendment reporting an identical period again — the most recently
    filed version wins."""
    by_end = {}
    for u in entries:
        end = u.get("end")
        if not end:
            continue
        existing = by_end.get(end)
        if existing is None or u.get("filed", "") >= existing.get("filed", ""):
            by_end[end] = u
    return by_end


def _quarterly_series(cik, tags, unit="USD", derive_q4=True):
    """Clean quarterly values merged across every tag in `tags`, with Q4
    filled in where it's missing (dollar figures only — see the comment on
    CONCEPTS for why EPS is excluded).

    Four problems get fixed here:
      1. Duration filter (80-100 days) — SEC filings report both a quarter's
         own figure AND a year-to-date cumulative figure under the SAME tag.
         A 90-day span is a true quarter; 180 or 270 days is 2- or 3-quarter
         cumulative. Keeping only ~90-day spans throws out the cumulative
         duplicates.
      2. Same period filed twice — a restatement or amendment can report an
         identical end date again later. The latest `filed` date wins.
      3. Companies switch tags over time — e.g. Microsoft reported under
         "Revenues" only through 2010, then "RevenueFromContractWith-
         CustomerExcludingAssessedTax" from 2016 onward (the 2010-2016
         transition period isn't in either tag's SEC data at all). Taking
         only the first fallback tag with any data would silently return
         a decade-stale slice and never reach the current one — caught by
         testing MSFT specifically, where "Revenues" had data but all of it
         predated 2011. Every tag is fetched and merged so whichever one a
         company is CURRENTLY using is what actually shows up.
      4. Q4 is usually never filed as its own ~90-day figure at all — only
         the 10-K's full-year total exists in XBRL. For additive dollar
         figures it's derived as FullYear - Q1 - Q2 - Q3 whenever exactly
         three quarters inside that fiscal year are already known.
    """
    by_end = {}
    annual_all = []

    for tag in tags:
        entries = _fetch_concept(cik, tag, unit)
        if not entries:
            continue
        quarterly = [u for u in entries if u.get("start") and u.get("end")
                     and 80 <= (date.fromisoformat(u["end"]) - date.fromisoformat(u["start"])).days <= 100]
        for u in quarterly:
            end = u["end"]
            existing = by_end.get(end)
            if existing is None or u.get("filed", "") >= existing.get("filed", ""):
                by_end[end] = u
        if derive_q4:
            annual_all.extend(u for u in entries if u.get("start") and u.get("end")
                               and 350 <= (date.fromisoformat(u["end"]) - date.fromisoformat(u["start"])).days <= 380)

    if derive_q4:
        for fy in _dedupe_by_end(annual_all).values():
            fy_end = fy["end"]
            if fy_end in by_end:
                continue  # Q4 already filed as its own discrete figure
            fy_start = fy["start"]
            inside = [v for e, v in by_end.items() if fy_start < e <= fy_end]
            if len(inside) == 3:
                q4_val = fy["val"] - sum(v["val"] for v in inside)
                by_end[fy_end] = {"val": q4_val, "end": fy_end, "filed": fy.get("filed"),
                                   "fp": "Q4", "form": f"{fy.get('form')} (derived)"}

    return by_end  # {end_date: {val, filed, fp, form, ...}}


def _instant_series(cik, tags):
    """Same merge-across-tags approach as _quarterly_series, for point-in-
    time facts (cash, debt) which have an `end` date and no `start` — no
    duration to filter on, just the same-period-filed-twice and
    company-switched-tags cases."""
    by_end = {}
    for tag in tags:
        entries = _fetch_concept(cik, tag, "USD")
        if not entries:
            continue
        for u in entries:
            end = u.get("end")
            if not end:
                continue
            existing = by_end.get(end)
            if existing is None or u.get("filed", "") >= existing.get("filed", ""):
                by_end[end] = u
    return by_end


def get_quarterly_financials(ticker, num_quarters=12):
    """Returns up to `num_quarters` of clean quarterly data for a ticker,
    most recent first. Each entry is a dict of the raw line items plus the
    derived ratios (margins, free cash flow) the red-flag detector needs.

    Returns None if the ticker has no CIK on file (not SEC-registered, or a
    typo). Returns an empty list if the CIK exists but no revenue data could
    be found under any known tag — rare, but some ETFs and non-GAAP filers
    show up in the ticker list without reporting financials this way.
    """
    cik = get_cik(ticker)
    if not cik:
        return None

    series = {name: _quarterly_series(cik, tags, unit, derive_q4)
              for name, (tags, unit, derive_q4) in CONCEPTS.items()}
    instants = {name: _instant_series(cik, tags) for name, tags in INSTANT_CONCEPTS.items()}

    if not series["revenue"]:
        return []

    end_dates = sorted(series["revenue"].keys(), reverse=True)[:num_quarters]

    # Instant facts (cash, debt) are point-in-time and rarely land on the
    # exact same date as the quarter's own end date — find the closest
    # instant snapshot at or before each quarter end instead of an exact match.
    def nearest_instant(concept_dates, target):
        candidates = [d for d in concept_dates if d <= target]
        return max(candidates) if candidates else None

    quarters = []
    for end in end_dates:
        rev = series["revenue"][end]["val"]
        cor = series["cost_of_revenue"].get(end, {}).get("val")
        gp  = series["gross_profit"].get(end, {}).get("val")
        if gp is None and cor is not None:
            gp = rev - cor  # derive when the company doesn't tag GrossProfit directly

        ni    = series["net_income"].get(end, {}).get("val")
        eps   = series["eps_diluted"].get(end, {}).get("val")
        opex  = series["operating_expenses"].get(end, {}).get("val")
        ocf   = series["operating_cash_flow"].get(end, {}).get("val")
        capex = series["capex"].get(end, {}).get("val")
        op_income = series["operating_income"].get(end, {}).get("val")
        d_and_a   = series["depreciation_amortization"].get(end, {}).get("val")

        cash_d = nearest_instant(instants["cash"].keys(), end)
        debt_d = nearest_instant(instants["debt"].keys(), end)
        cash = instants["cash"][cash_d]["val"] if cash_d else None
        debt = instants["debt"][debt_d]["val"] if debt_d else None

        fcf = (ocf - capex) if (ocf is not None and capex is not None) else None

        quarters.append({
            "period_end": end,
            "filed": series["revenue"][end].get("filed"),
            "fiscal_period": series["revenue"][end].get("fp"),
            "fiscal_year": series["revenue"][end].get("fy"),
            "revenue": rev,
            "gross_profit": gp,
            "net_income": ni,
            "eps_diluted": eps,
            "operating_expenses": opex,
            "operating_cash_flow": ocf,
            "capex": capex,
            "free_cash_flow": fcf,
            "cash": cash,
            "debt": debt,
            "ebitda": (op_income + d_and_a) if (op_income is not None and d_and_a is not None) else None,
            "gross_margin_pct": round(gp / rev * 100, 2) if gp is not None and rev else None,
            "net_margin_pct": round(ni / rev * 100, 2) if ni is not None and rev else None,
        })

    return quarters


def get_market_cap(ticker):
    """Today's market cap from Nasdaq's public quote-summary endpoint — no
    key, same trust tier as the earnings calendar calls above. Deliberately
    the only "live price" data this app touches, and even then only to
    report the business's total value, never a per-share number. Returns
    None if the ticker isn't found or the field is missing/unparseable,
    rather than guessing."""
    try:
        r = httpx.get(f"https://api.nasdaq.com/api/quote/{ticker.upper()}/summary",
                      params={"assetclass": "stocks"}, headers=NASDAQ_HEADERS, timeout=20)
        r.raise_for_status()
        raw = r.json().get("data", {}).get("summaryData", {}).get("MarketCap", {}).get("value")
        if not raw or raw == "N/A":
            return None
        return float(raw.replace(",", ""))
    except Exception:
        return None


def get_earnings_calendar(days_ahead=14):
    """Every company reporting earnings in the next `days_ahead` days.
    Nasdaq's calendar endpoint takes one date per request — there is no
    range parameter, confirmed by testing before this was written — so this
    makes one call per day rather than assuming a range works."""
    results = {}
    today = date.today()
    for offset in range(days_ahead + 1):
        d = today + timedelta(days=offset)
        try:
            r = httpx.get("https://api.nasdaq.com/api/calendar/earnings",
                          params={"date": d.isoformat()}, headers=NASDAQ_HEADERS, timeout=20)
            r.raise_for_status()
            rows = r.json().get("data", {}).get("rows") or []
            if rows:
                results[d.isoformat()] = rows
        except Exception:
            continue  # one bad day shouldn't kill the whole calendar
        time.sleep(0.2)  # light throttle — this is a public, unauthenticated endpoint
    return results


def get_recent_reports(tickers, days_back=7):
    """Which of `tickers` appears in Nasdaq's calendar as having reported in
    the last `days_back` days. Same one-request-per-day approach as
    get_earnings_calendar, just looking backward instead of forward."""
    tickers = {t.upper() for t in tickers}
    found = {}
    today = date.today()
    for offset in range(1, days_back + 1):
        d = today - timedelta(days=offset)
        try:
            r = httpx.get("https://api.nasdaq.com/api/calendar/earnings",
                          params={"date": d.isoformat()}, headers=NASDAQ_HEADERS, timeout=20)
            r.raise_for_status()
            rows = r.json().get("data", {}).get("rows") or []
            for row in rows:
                sym = row.get("symbol", "").upper()
                if sym in tickers:
                    found[sym] = {"date": d.isoformat(), **row}
        except Exception:
            continue
        time.sleep(0.2)
    return found


def get_earnings_surprise(ticker, target_date):
    """EPS actual vs. consensus estimate for one ticker on one report date,
    pulled from the same Nasdaq calendar the monitor command already uses.
    Returns None if that date has no data for this ticker (calendar dates
    can shift as companies confirm their actual report date)."""
    try:
        r = httpx.get("https://api.nasdaq.com/api/calendar/earnings",
                      params={"date": target_date}, headers=NASDAQ_HEADERS, timeout=20)
        r.raise_for_status()
        rows = r.json().get("data", {}).get("rows") or []
        for row in rows:
            if row.get("symbol", "").upper() == ticker.upper():
                return row
    except Exception:
        pass
    return None
