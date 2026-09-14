import os
from pathlib import Path

import yfinance as yf
import httpx
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── CONFIG ────────────────────────────────────────────────────────────────────
TICKERS_FILE = "fundamentals_tickers.txt"
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# Gate 1 — Quality thresholds
MIN_GROSS_MARGIN = 0.40   # 40% gross margin (lowered from 60% — most great companies hit this)
MIN_FCF_MARGIN   = 0.15   # 15% free cash flow margin
MIN_NET_MARGIN   = 0.10   # 10% net profit margin

# Gate 3 — Valuation thresholds
MIN_FCF_YIELD    = 0.01   # 1% FCF yield (FCF / market cap)
MIN_REV_GROWTH   = 0.10   # 10% annual revenue growth
# ─────────────────────────────────────────────────────────────────────────────

RISK_KEYWORDS = [
    "investigation", "lawsuit", "fraud", "bankrupt", "collapse",
    "regulatory", "antitrust", "sec probe", "criminal", "scandal",
    "revenue miss", "guidance cut", "layoffs massive", "debt crisis"
]


def load_tickers():
    with open(TICKERS_FILE) as f:
        return [line.strip().upper() for line in f if line.strip()]


def get_fundamentals(ticker):
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        fast  = stock.fast_info

        company      = info.get("longName", ticker)
        price        = round(fast.last_price, 2)
        market_cap   = fast.market_cap

        gross_margin = info.get("grossMargins")
        net_margin   = info.get("profitMargins")
        revenue      = info.get("totalRevenue")
        rev_growth   = info.get("revenueGrowth")
        pe           = info.get("trailingPE")
        sector       = info.get("sector", "N/A")
        industry     = info.get("industry", "N/A")

        # Calculate TTM FCF from cash flow statement (more accurate than info field)
        fcf = None
        try:
            cf = stock.cashflow  # annual cash flow statement
            if cf is not None and not cf.empty:
                op_cf  = cf.loc["Operating Cash Flow"].iloc[0]  if "Operating Cash Flow"  in cf.index else None
                capex  = cf.loc["Capital Expenditure"].iloc[0]  if "Capital Expenditure"  in cf.index else 0
                if op_cf is not None:
                    fcf = float(op_cf) + float(capex)  # capex is negative, so adding reduces
        except Exception:
            fcf = info.get("freeCashflow")

        fcf_margin = (fcf / revenue)    if fcf and revenue    else None
        fcf_yield  = (fcf / market_cap) if fcf and market_cap else None

        return {
            "ticker":       ticker,
            "company":      company,
            "sector":       sector,
            "industry":     industry,
            "price":        price,
            "market_cap_b": round(market_cap / 1e9, 1) if market_cap else None,
            "gross_margin": gross_margin,
            "net_margin":   net_margin,
            "fcf_margin":   fcf_margin,
            "fcf_yield":    fcf_yield,
            "rev_growth":   rev_growth,
            "pe":           round(pe, 1) if pe else None,
            "revenue_b":    round(revenue / 1e9, 2) if revenue else None,
            "fcf_b":        round(fcf / 1e9, 2) if fcf else None,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def check_risk_headlines(ticker, company):
    """Pull latest news and flag if a risk keyword appears in an article that is actually about this company."""
    if not NEWS_API_KEY:
        return {"ticker": ticker, "skipped": "NEWS_API_KEY not set"}
    try:
        # Search specifically for this ticker/company + risk terms
        short_name = company.split()[0]  # e.g. "Apple" from "Apple Inc."
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": f'"{ticker}" OR "{short_name}" investigation OR lawsuit OR fraud OR probe OR bankrupt',
            "sortBy": "publishedAt",
            "pageSize": 15,
            "language": "en",
            "apiKey": NEWS_API_KEY
        }
        resp = httpx.get(url, params=params, timeout=10)
        articles = resp.json().get("articles", [])

        flags = []
        for a in articles:
            title = (a.get("title") or "").lower()
            desc  = (a.get("description") or "").lower()
            combined = title + " " + desc

            # Must mention the ticker or company name to count
            ticker_mentioned  = ticker.lower() in combined
            company_mentioned = short_name.lower() in combined

            if not (ticker_mentioned or company_mentioned):
                continue

            for kw in RISK_KEYWORDS:
                if kw in combined:
                    flags.append(a["title"])
                    break

        return flags[:3]
    except Exception:
        return []


def pct(val):
    if val is None:
        return "N/A"
    return f"{round(val * 100, 1)}%"


def run_fundamentals_screener():
    tickers = load_tickers()

    print("=" * 70)
    print(f"  FUNDAMENTALS SCREENER  —  {datetime.now().strftime('%B %d, %Y  %I:%M %p')}")
    print("=" * 70)
    print(f"  Scanning {len(tickers)} companies through 3 gates...\n")
    print(f"  Gate 1 — Quality:   Gross >{int(MIN_GROSS_MARGIN*100)}%  FCF margin >{int(MIN_FCF_MARGIN*100)}%  Net margin >{int(MIN_NET_MARGIN*100)}%")
    print(f"  Gate 2 — Risk:      No headline risk that could cut revenue 30%+")
    print(f"  Gate 3 — Valuation: FCF yield >{int(MIN_FCF_YIELD*100)}%  OR  Revenue growth >{int(MIN_REV_GROWTH*100)}%")
    print("=" * 70)

    full_pass    = []
    failed_g1    = []
    failed_g2    = []
    failed_g3    = []
    errors       = []

    for ticker in tickers:
        f = get_fundamentals(ticker)

        if "error" in f:
            errors.append(ticker)
            print(f"\n  [ERROR]  {ticker} — {f['error']}")
            continue

        cap = f"${f['market_cap_b']}B" if f['market_cap_b'] else "N/A"
        print(f"\n  ── {ticker}  {f['company']}  ({cap}) ──")

        # ── GATE 1: QUALITY ──────────────────────────────────────────────────
        g1_failures = []

        gm = f["gross_margin"]
        fm = f["fcf_margin"]
        nm = f["net_margin"]

        print(f"     Gate 1 | Gross: {pct(gm)}  FCF margin: {pct(fm)}  Net: {pct(nm)}")

        if gm is None or gm < MIN_GROSS_MARGIN:
            g1_failures.append(f"Gross margin {pct(gm)} < {int(MIN_GROSS_MARGIN*100)}%")
        if fm is None or fm < MIN_FCF_MARGIN:
            g1_failures.append(f"FCF margin {pct(fm)} < {int(MIN_FCF_MARGIN*100)}%")
        if nm is None or nm < MIN_NET_MARGIN:
            g1_failures.append(f"Net margin {pct(nm)} < {int(MIN_NET_MARGIN*100)}%")

        if g1_failures:
            reason = " | ".join(g1_failures)
            failed_g1.append({"ticker": ticker, "company": f["company"], "reason": reason})
            print(f"     Gate 1 FAILED — {reason}")
            continue

        print(f"     Gate 1 PASSED ✓")

        # ── GATE 2: RISK ──────────────────────────────────────────────────────
        risk_flags = check_risk_headlines(ticker, f["company"])
        print(f"     Gate 2 | Checking news for existential risk signals...")

        if risk_flags:
            reason = risk_flags[0]
            failed_g2.append({"ticker": ticker, "company": f["company"], "reason": reason, "flags": risk_flags})
            print(f"     Gate 2 FAILED — Risk headline: {reason}")
            continue

        print(f"     Gate 2 PASSED ✓  (no existential risk signals in recent news)")

        # ── GATE 3: VALUATION ─────────────────────────────────────────────────
        fy  = f["fcf_yield"]
        rg  = f["rev_growth"]

        print(f"     Gate 3 | FCF yield: {pct(fy)}  Revenue growth: {pct(rg)}")

        g3_pass = (fy and fy >= MIN_FCF_YIELD) or (rg and rg >= MIN_REV_GROWTH)

        if not g3_pass:
            reason = f"FCF yield {pct(fy)} and revenue growth {pct(rg)} — neither meets threshold"
            failed_g3.append({"ticker": ticker, "company": f["company"], "reason": reason})
            print(f"     Gate 3 FAILED — {reason} → Add to watchlist")
            continue

        print(f"     Gate 3 PASSED ✓")
        print(f"     ★  ALL GATES PASSED — research now")
        full_pass.append(f)

    # ── FINAL REPORT ──────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print(f"  SCREENING REPORT  —  {datetime.now().strftime('%B %d, %Y')}")
    print("=" * 70)
    print(f"  Companies screened:          {len(tickers)}")
    print(f"  Full pass — research now:    {len(full_pass)}")
    print(f"  Failed Gate 1 (quality):     {len(failed_g1)}")
    print(f"  Failed Gate 2 (risk):        {len(failed_g2)}")
    print(f"  Failed Gate 3 (valuation):   {len(failed_g3)}")
    print("=" * 70)

    if full_pass:
        print(f"\n  ★ FULL PASS — RESEARCH NOW:")
        for s in full_pass:
            print(f"\n  {s['ticker']}  —  {s['company']}")
            print(f"    Sector: {s['sector']}  |  Market cap: ${s['market_cap_b']}B  |  PE: {s['pe']}")
            print(f"    Revenue: ${s['revenue_b']}B  |  FCF: ${s['fcf_b']}B")
            print(f"    Gross margin: {pct(s['gross_margin'])}  |  FCF margin: {pct(s['fcf_margin'])}  |  Net margin: {pct(s['net_margin'])}")
            print(f"    FCF yield: {pct(s['fcf_yield'])}  |  Revenue growth: {pct(s['rev_growth'])}")

    if failed_g1:
        print(f"\n  FAILED GATE 1 — Quality:")
        for s in failed_g1:
            print(f"    {s['ticker']}  —  {s['reason']}")

    if failed_g2:
        print(f"\n  FAILED GATE 2 — Risk:")
        for s in failed_g2:
            print(f"    {s['ticker']}  —  {s['reason']}")

    if failed_g3:
        print(f"\n  FAILED GATE 3 — Valuation (add to watchlist):")
        for s in failed_g3:
            print(f"    {s['ticker']}  —  {s['reason']}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    run_fundamentals_screener()
