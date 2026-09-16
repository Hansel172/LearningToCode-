"""The comparison logic shared by the terminal report and the web app.

Kept separate from earnings_tracker.py so both the CLI and the public page
(built by build_public.py) call the exact same computation — otherwise the
two could quietly drift apart as one gets edited and the other doesn't.
This function only computes; nothing here prints or writes a file.
"""

from datetime import date

from red_flag_detector import detect_red_flags


def _pct_change(new, old):
    if old in (None, 0) or new is None:
        return None
    return (new - old) / abs(old) * 100


def _classify_metric(name, change, good_is_positive=True, ugly_threshold=None):
    """Sorts one metric's change into good / bad / ugly. `ugly_threshold` is
    the magnitude past which a bad number becomes an alarming one."""
    if change is None:
        return None
    is_good = (change > 0) if good_is_positive else (change < 0)
    if is_good:
        return ("good", name, change)
    if ugly_threshold is not None and abs(change) >= ugly_threshold:
        return ("ugly", name, change)
    return ("bad", name, change)


def _streak(quarters, getter, better):
    """How many consecutive quarters, walking backward from the most recent,
    kept moving in the `better` direction versus the quarter before them.
    Stops at the first break or the first missing value — a derived Q4's
    blank EPS (see sec_data.py) should halt an EPS streak, not silently
    skip over the gap and keep counting past it."""
    count = 0
    for i in range(len(quarters) - 1):
        cur_v, prev_v = getter(quarters[i]), getter(quarters[i + 1])
        if cur_v is None or prev_v is None:
            break
        if better(cur_v, prev_v):
            count += 1
        else:
            break
    return count


def build_trend(quarters):
    """Revenue history across every stored quarter (not just the latest
    two), plus simple streak counts computed the same way. This is what
    lets a card say "revenue has grown for 5 straight quarters" instead of
    only ever comparing one quarter to the one before it."""
    chronological = list(reversed(quarters))  # oldest -> newest, for a left-to-right sparkline
    points = [
        {"period_end": q["period_end"], "revenue": q["revenue"]}
        for q in chronological if q.get("revenue") is not None
    ]

    return {
        "revenue_points": points,
        "revenue_growth_streak": _streak(
            quarters, lambda q: q.get("revenue"), lambda c, p: c > p),
        "margin_expansion_streak": _streak(
            quarters, lambda q: q.get("gross_margin_pct"), lambda c, p: c > p),
        "quarters_table": [
            {
                "period_end": q["period_end"],
                "revenue": q.get("revenue"),
                "gross_margin_pct": q.get("gross_margin_pct"),
                "eps_diluted": q.get("eps_diluted"),
            }
            for q in quarters
        ],
    }


def _ttm_sum(quarters, key):
    """Trailing-twelve-month total for an additive dollar figure, from the
    4 most recent quarters. None if fewer than 4 are available or any of
    the 4 is missing the figure — a partial-year sum would understate the
    real trailing total, which is worse than not showing one at all."""
    latest_four = quarters[:4]
    if len(latest_four) < 4:
        return None
    values = [q.get(key) for q in latest_four]
    if any(v is None for v in values):
        return None
    return sum(values)


def build_valuation(market_cap, quarters):
    """Real valuation multiples for the Company Story section — never asked
    of Claude, since these are exact arithmetic on numbers already fetched
    (market_cap from Nasdaq, everything else from SEC XBRL). A multiple is
    only returned when every input for it is actually known; otherwise the
    field is None and the caller labels it as unavailable rather than
    guessing at a number this function couldn't actually compute.
    """
    if market_cap is None or not quarters:
        return {"market_cap": market_cap, "pe_ttm": None, "ev_ebitda_ttm": None}

    ttm_net_income = _ttm_sum(quarters, "net_income")
    pe_ttm = (round(market_cap / ttm_net_income, 1)
              if ttm_net_income and ttm_net_income > 0 else None)

    latest = quarters[0]
    debt, cash = latest.get("debt"), latest.get("cash")
    ev = (market_cap + debt - cash) if debt is not None and cash is not None else None

    ttm_ebitda = _ttm_sum(quarters, "ebitda")
    ev_ebitda_ttm = (round(ev / ttm_ebitda, 1)
                     if ev is not None and ttm_ebitda and ttm_ebitda > 0 else None)

    return {"market_cap": market_cap, "pe_ttm": pe_ttm, "ev_ebitda_ttm": ev_ebitda_ttm}


def build_analysis(ticker, quarters):
    """One ticker's latest-quarter-vs-baseline comparison, plus the full-
    history trend from build_trend(). Returns a dict with
    `insufficient_data: True` if there's nothing to compare yet (fewer than
    2 stored quarters) — the caller decides how to present that, this
    function never assumes a particular output format.
    """
    if len(quarters) < 2:
        return {"ticker": ticker, "insufficient_data": True,
                "quarters_available": len(quarters)}

    cur, prev = quarters[0], quarters[1]
    gap_days = (date.fromisoformat(cur["period_end"]) - date.fromisoformat(prev["period_end"])).days
    is_quarterly = gap_days <= 100

    good, bad, ugly = [], [], []

    def _bucket(item):
        if item is None:
            return
        kind, name, change = item
        (good if kind == "good" else bad if kind == "bad" else ugly).append(
            {"metric": name, "change_pct": round(change, 1)})

    for label, key, ugly_at in [
        ("Revenue growth", "revenue", 10),
        ("Net income",     "net_income", 20),
        ("EPS (diluted)",  "eps_diluted", 20),
        ("Free cash flow", "free_cash_flow", None),
        ("Cash on hand",   "cash", 20),
    ]:
        chg = _pct_change(cur.get(key), prev.get(key))
        label_out = label
        # A shrinking loss is a real improvement, but "+46%" alone reads as
        # unambiguous success — so a still-negative figure is called out
        # even when the direction of change is favorable.
        if key in ("net_income", "free_cash_flow") and cur.get(key) is not None and cur[key] < 0:
            label_out = f"{label} (still negative, but improving)" if chg and chg > 0 else f"{label} (still negative)"
        _bucket(_classify_metric(label_out, chg, good_is_positive=True, ugly_threshold=ugly_at))

    # Debt: shrinking or flat is good; growing is bad. >15% matches the
    # red-flag detector's own threshold, so it lands in the same bucket here.
    debt_chg = _pct_change(cur.get("debt"), prev.get("debt"))
    _bucket(_classify_metric("Debt", debt_chg, good_is_positive=False, ugly_threshold=15))

    # Gross margin: percentage-point change, not percent change of a percent.
    gm_cur, gm_prev = cur.get("gross_margin_pct"), prev.get("gross_margin_pct")
    if gm_cur is not None and gm_prev is not None:
        pts = round(gm_cur - gm_prev, 1)
        entry = {"metric": "Gross margin", "change_pts": pts,
                 "from_pct": gm_prev, "to_pct": gm_cur}
        (good if pts > 0 else ugly if pts <= -2 else bad).append(entry)

    return {
        "ticker": ticker,
        "insufficient_data": False,
        "period_end": cur["period_end"],
        "compared_to": prev["period_end"],
        "gap_days": gap_days,
        "is_quarterly_comparison": is_quarterly,
        "good": good,
        "bad": bad,
        "ugly": ugly,
        "red_flags": detect_red_flags(quarters),
        "trend": build_trend(quarters),
    }
