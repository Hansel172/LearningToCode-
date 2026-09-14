import os
import sys
import time
import yfinance as yf
import httpx
import random
from dotenv import load_dotenv
from datetime import datetime
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
TO_EMAIL         = os.getenv("TO_EMAIL")
FROM_EMAIL       = os.getenv("FROM_EMAIL")
NEWS_API_KEY     = os.getenv("NEWS_API_KEY")

WATCHLIST = ["MSFT", "GOOGL", "META", "PLTR", "NVDA", "AMD", "AAPL"]
INDEXES   = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IBIT": "Bitcoin ETF"}
MACRO     = {"GC=F": "Gold", "CL=F": "Crude oil", "DX-Y.NYB": "US dollar", "BTC-USD": "Bitcoin"}
SECTORS   = {
    "XLK":  "Technology",      "XLC":  "Communication",   "XLY":  "Consumer disc.",
    "XLF":  "Financials",      "XLI":  "Industrials",     "XLV":  "Health care",
    "XLP":  "Consumer staples", "XLB": "Materials",       "XLRE": "Real estate",
    "XLU":  "Utilities",       "XLE":  "Energy",
}

# ── DESIGN TOKENS ─────────────────────────────────────────────────────────────
# Dark surface. Status colors reserved for direction only — the masthead accent
# is kept away from the data so no two reds compete for meaning.
PAGE      = "#0d0d0d"   # page plane
CARD      = "#161615"   # chart / card surface
INK       = "#ffffff"   # primary
INK2      = "#c3c2b7"   # secondary
MUTED     = "#898781"   # axis / labels
HAIRLINE  = "#2c2c2a"   # gridline
BASELINE  = "#383835"   # axis / divider
UP        = "#0ca30c"   # status: good
DOWN      = "#d03b3b"   # status: critical
ACCENT    = "#cc0000"   # masthead only — never adjacent to UP/DOWN
SANS      = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
TNUM      = "font-variant-numeric:tabular-nums;"

QUOTES = [
    ("The stock market is a device for transferring money from the impatient to the patient.", "Warren Buffett"),
    ("In investing, what is comfortable is rarely profitable.", "Robert Arnott"),
    ("The four most dangerous words in investing are: 'This time it's different.'", "Sir John Templeton"),
    ("Risk comes from not knowing what you're doing.", "Warren Buffett"),
    ("The market is filled with individuals who know the price of everything, but the value of nothing.", "Philip Fisher"),
    ("Be fearful when others are greedy, and greedy when others are fearful.", "Warren Buffett"),
    ("An investment in knowledge pays the best interest.", "Benjamin Franklin"),
    ("The individual investor should act consistently as an investor and not as a speculator.", "Ben Graham"),
    ("Wide diversification is only required when investors do not understand what they are doing.", "Warren Buffett"),
    ("Opportunities come infrequently. When it rains gold, put out the bucket, not the thimble.", "Warren Buffett"),
    ("The best investment you can make is in yourself.", "Warren Buffett"),
    ("It's not whether you're right or wrong, but how much money you make when you're right.", "George Soros"),
    ("The most contrarian thing of all is not to oppose the crowd but to think for yourself.", "Peter Thiel"),
    ("Bulls make money, bears make money, pigs get slaughtered.", "Wall Street proverb"),
]


# Company names are hardcoded rather than pulled from yf.Ticker().info — that
# call is expensive and Yahoo rate-limits hard from datacenter IPs.
COMPANY = {
    "MSFT": "Microsoft Corporation",      "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.",       "PLTR":  "Palantir Technologies Inc.",
    "NVDA": "NVIDIA Corporation",         "AMD":   "Advanced Micro Devices, Inc.",
    "AAPL": "Apple Inc.",
}

# Every ticker the briefing needs, pulled in one pass up front.
ALL_TICKERS = (list(INDEXES) + ["^VIX", "^TNX"] + list(MACRO)
               + list(SECTORS) + WATCHLIST)

_prices = {}   # ticker -> {"price", "prev", "year_high"}


def load_prices(retries=3):
    """Fetch every ticker once, up front, and serve the rest of the briefing
    from the cache.

    Note: yfinance issues one HTTP request per symbol (multi.py loops over
    tickers) — there is no true bulk endpoint. What this buys us is not a
    single request but no *redundant* ones: previously the watchlist was
    fetched twice per ticker and each news item spent a yf.Ticker().info call,
    which hits a separate, more aggressively throttled endpoint. Yahoo returns
    429 to datacenter IPs readily, so the retry/backoff below matters."""
    global _prices
    for attempt in range(retries):
        try:
            df = yf.download(
                ALL_TICKERS, period="1y", interval="1d",
                group_by="ticker", auto_adjust=False,
                progress=False, threads=True,
            )
            if df is None or df.empty:
                raise ValueError("empty frame")

            for ticker in ALL_TICKERS:
                try:
                    sub   = df[ticker] if ticker in df.columns.get_level_values(0) else df
                    close = sub["Close"].dropna()
                    if len(close) < 2:
                        continue
                    _prices[ticker] = {
                        "price":     float(close.iloc[-1]),
                        "prev":      float(close.iloc[-2]),
                        "year_high": float(sub["High"].dropna().max()),
                    }
                except Exception:
                    continue

            if _prices:
                print(f"  loaded {len(_prices)}/{len(ALL_TICKERS)} tickers")
                return
            raise ValueError("no tickers parsed")

        except Exception as e:
            wait = 2 ** attempt * 5
            print(f"  attempt {attempt + 1} failed ({e})")
            if attempt < retries - 1:
                print(f"  retrying in {wait}s...")
                time.sleep(wait)

    print("  WARNING: price data unavailable — sections will be sparse")


def fetch(ticker):
    """Price, absolute change, percent change — served from the bulk load."""
    d = _prices.get(ticker)
    if not d:
        return None, None, None
    chg = d["price"] - d["prev"]
    return d["price"], chg, (chg / d["prev"]) * 100


def year_high(ticker):
    d = _prices.get(ticker)
    return d["year_high"] if d else None


def get_news(ticker):
    company_name = COMPANY.get(ticker.upper(), ticker)
    try:
        params = {
            "q": f"{ticker.upper()} stock OR {company_name} stock",
            "sortBy": "publishedAt", "pageSize": 5,
            "language": "en", "apiKey": NEWS_API_KEY,
        }
        resp = httpx.get("https://newsapi.org/v2/everything", params=params, timeout=10)
        articles = resp.json().get("articles", [])
        return company_name, [
            {"title": a["title"], "source": a["source"]["name"], "published": a["publishedAt"][:10]}
            for a in articles[:3]
        ]
    except Exception:
        return company_name, []


# ── BUILDING BLOCKS ───────────────────────────────────────────────────────────
def delta(pct):
    """Signed change with an arrow — direction never rides on color alone."""
    if pct is None:
        return f'<span style="color:{MUTED};">&mdash;</span>'
    color = UP if pct >= 0 else DOWN
    arrow = "&#9650;" if pct >= 0 else "&#9660;"
    return f'<span style="color:{color};{TNUM}white-space:nowrap;">{arrow}&nbsp;{abs(pct):.2f}%</span>'


def section(number, title, inner, note=None):
    note_html = f'<div style="color:{MUTED};font-size:12px;line-height:1.5;margin:0 0 14px;">{note}</div>' if note else ""
    return f"""
    <tr><td style="padding:0 0 40px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="padding:0 0 6px;">
            <span style="color:{MUTED};font-size:11px;letter-spacing:2px;{TNUM}">{number}</span>
            <span style="color:{INK};font-size:11px;letter-spacing:2px;font-weight:600;text-transform:uppercase;padding-left:10px;">{title}</span>
          </td>
        </tr>
        <tr><td style="border-bottom:1px solid {BASELINE};font-size:0;line-height:0;padding:0 0 12px;">&nbsp;</td></tr>
        <tr><td style="padding:14px 0 0;">{note_html}{inner}</td></tr>
      </table>
    </td></tr>"""


def stat_tile(label, value, sub_html):
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:{CARD};border-radius:10px;">
      <tr><td style="padding:16px 14px;text-align:center;">
        <div style="color:{MUTED};font-size:11px;line-height:1.4;padding-bottom:8px;">{label}</div>
        <div style="color:{INK};font-size:21px;font-weight:600;line-height:1.2;">{value}</div>
        <div style="font-size:12px;line-height:1.4;padding-top:7px;">{sub_html}</div>
      </td></tr>
    </table>"""


def tile_row(tiles):
    """Lay tiles side by side with an 8px surface gap between them."""
    cells = ""
    for i, t in enumerate(tiles):
        if i:
            cells += '<td width="8" style="font-size:0;line-height:0;">&nbsp;</td>'
        cells += f'<td valign="top" width="{100 // len(tiles)}%">{t}</td>'
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{cells}</tr></table>'


def diverging_bar(pct, scale):
    """Bar growing left (down) or right (up) from a shared zero baseline.
    Rounded at the data end, square at the baseline."""
    width = min(abs(pct) / scale * 100, 100) if scale else 0
    if pct >= 0:
        left  = '<td width="50%" style="font-size:0;line-height:0;">&nbsp;</td>'
        right = (f'<td width="50%" style="font-size:0;line-height:0;"><table role="presentation" cellpadding="0" '
                 f'cellspacing="0" border="0" width="100%"><tr>'
                 f'<td width="{width:.0f}%" style="background:{UP};height:8px;border-radius:0 4px 4px 0;font-size:0;line-height:0;">&nbsp;</td>'
                 f'<td style="font-size:0;line-height:0;">&nbsp;</td></tr></table></td>')
    else:
        left  = (f'<td width="50%" style="font-size:0;line-height:0;"><table role="presentation" cellpadding="0" '
                 f'cellspacing="0" border="0" width="100%"><tr>'
                 f'<td style="font-size:0;line-height:0;">&nbsp;</td>'
                 f'<td width="{width:.0f}%" style="background:{DOWN};height:8px;border-radius:4px 0 0 4px;font-size:0;line-height:0;">&nbsp;</td>'
                 f'</tr></table></td>')
        right = '<td width="50%" style="font-size:0;line-height:0;">&nbsp;</td>'

    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{left}'
            f'<td width="1" style="background:{BASELINE};font-size:0;line-height:0;">&nbsp;</td>{right}</tr></table>')


def chip(text, tone):
    bg, fg = (("#0e2410", UP) if tone == "good" else ("#232322", MUTED))
    return (f'<span style="background:{bg};color:{fg};font-size:11px;font-weight:600;'
            f'padding:4px 9px;border-radius:20px;white-space:nowrap;">{text}</span>')


def th(text, align="left"):
    return (f'<th style="padding:0 12px 9px;text-align:{align};color:{MUTED};font-size:11px;'
            f'font-weight:500;letter-spacing:0.5px;text-transform:uppercase;">{text}</th>')


def td(html, align="left", color=None, weight=None, tnum=True):
    style = f'padding:11px 12px;text-align:{align};font-size:13px;border-top:1px solid {HAIRLINE};'
    style += f'color:{color or INK2};'
    if weight:
        style += f'font-weight:{weight};'
    if tnum:
        style += TNUM
    return f'<td style="{style}">{html}</td>'


def data_table(header_cells, rows):
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background:{CARD};border-radius:10px;">'
            f'<tr>{"".join(header_cells)}</tr>{rows}</table>')


# ── EMAIL ─────────────────────────────────────────────────────────────────────
def build_email():
    today    = datetime.now().strftime("%A, %B %-d, %Y")
    blocks   = []

    # ---- gather ----------------------------------------------------------
    print(f"Loading {len(ALL_TICKERS)} tickers...")
    load_prices()

    index_data = {t: fetch(t) for t in INDEXES}
    vix_price, _, _ = fetch("^VIX")
    tny_price, _, _ = fetch("^TNX")

    sector_data = []
    for ticker, label in SECTORS.items():
        _, _, pct = fetch(ticker)
        if pct is not None:
            sector_data.append((label, pct))
    sector_data.sort(key=lambda x: x[1], reverse=True)

    # ---- lede ------------------------------------------------------------
    spy_pct = index_data.get("SPY", (None, None, None))[2]
    green   = sum(1 for _, p in sector_data if p >= 0)
    bits    = []
    if spy_pct is not None:
        bits.append(f"S&amp;P 500 {'up' if spy_pct >= 0 else 'down'} {abs(spy_pct):.2f}%")
    if sector_data:
        bits.append(f"{green} of {len(sector_data)} sectors advancing")
    if vix_price is not None:
        bits.append(f"VIX at {vix_price:.1f} &mdash; {'elevated' if vix_price > 20 else 'calm'}")
    lede = ". ".join(bits) + "." if bits else "Markets closed &mdash; no live pricing available."

    # ---- 01 market pulse -------------------------------------------------
    idx_tiles = []
    for ticker, label in INDEXES.items():
        price, _, pct = index_data[ticker]
        idx_tiles.append(stat_tile(label, f"${price:,.2f}" if price else "&mdash;", delta(pct)))

    vix_tone  = DOWN if (vix_price and vix_price > 20) else UP
    vix_word  = "Elevated" if (vix_price and vix_price > 20) else "Calm"
    gauge = [
        stat_tile("VIX &middot; volatility", f"{vix_price:.1f}" if vix_price else "&mdash;",
                  f'<span style="color:{vix_tone};font-weight:600;">{vix_word}</span>'
                  if vix_price else f'<span style="color:{MUTED};">&mdash;</span>'),
        stat_tile("10-year Treasury", f"{tny_price:.2f}%" if tny_price else "&mdash;",
                  f'<span style="color:{MUTED};">Benchmark yield</span>'),
    ]

    blocks.append(section("01", "Market pulse",
                          tile_row(idx_tiles)
                          + '<div style="height:8px;line-height:8px;font-size:0;">&nbsp;</div>'
                          + tile_row(gauge)))

    # ---- 02 macro --------------------------------------------------------
    rows = ""
    for ticker, label in MACRO.items():
        price, chg, pct = fetch(ticker)
        if price is None:
            continue
        if   ticker == "BTC-USD":  value = f"${price:,.0f}"
        elif ticker == "DX-Y.NYB": value = f"{price:,.2f}"
        elif ticker == "GC=F":     value = f"${price:,.0f}"
        elif ticker == "CL=F":     value = f"${price:,.2f}"
        else:                      value = f"${price:,.2f}"
        rows += ("<tr>"
                 + td(label, color=INK2, tnum=False)
                 + td(value, align="right", color=INK, weight=600)
                 + td(delta(pct), align="right")
                 + "</tr>")

    blocks.append(section("02", "Macro", data_table(
        [th("Asset"), th("Price", "right"), th("Today", "right")], rows)))

    # ---- 03 sectors ------------------------------------------------------
    if sector_data:
        scale = max(abs(p) for _, p in sector_data) or 1
        rows  = ""
        for label, pct in sector_data:
            rows += ("<tr>"
                     + td(label, color=INK2, tnum=False)
                     + td(delta(pct), align="right")
                     + f'<td style="padding:11px 12px;border-top:1px solid {HAIRLINE};width:44%;">{diverging_bar(pct, scale)}</td>'
                     + "</tr>")
        blocks.append(section("03", "Sectors", data_table(
            [th("Sector"), th("Today", "right"), th("")], rows),
            note=f"All 11 S&amp;P sectors, strongest first. Bars diverge from a zero baseline &mdash; "
                 f"widest move today is {scale:.2f}%."))

    # ---- 04 watchlist ----------------------------------------------------
    rows = ""
    in_zone = 0
    for ticker in WATCHLIST:
        price, _, day_pct = fetch(ticker)
        high = year_high(ticker)
        if price is None or not high:
            continue

        from_high = ((price - high) / high) * 100
        zone = -35 <= from_high <= -18
        if zone:
            in_zone += 1

        rows += ("<tr>"
                 + td(ticker, color=INK, weight=600)
                 + td(f"${price:,.2f}", align="right")
                 + td(delta(day_pct), align="right")
                 + td(f"${high:,.2f}", align="right", color=MUTED)
                 + td(f"{from_high:.1f}%", align="right", color=MUTED)
                 + td(chip("In zone", "good") if zone else chip("Watch", "muted"),
                      align="right", tnum=False)
                 + "</tr>")

    zone_line = (f'<span style="color:{UP};font-weight:600;">{in_zone} in the entry zone today.</span>'
                 if in_zone else f'<span style="color:{MUTED};">Nothing in the entry zone today.</span>')

    blocks.append(section("04", "Watchlist", data_table(
        [th("Ticker"), th("Price", "right"), th("Today", "right"),
         th("52w high", "right"), th("From high", "right"), th("Signal", "right")], rows),
        note=f"Entry zone = 18&ndash;35% below the 52-week high. {zone_line}"))

    # ---- 05 news ---------------------------------------------------------
    print("Fetching news...")
    cards = ""
    for ticker in WATCHLIST:
        company, headlines = get_news(ticker)
        if not headlines:
            continue
        items = ""
        for h in headlines:
            items += (f'<div style="padding:9px 0;border-top:1px solid {HAIRLINE};">'
                      f'<div style="color:{MUTED};font-size:11px;padding-bottom:3px;">{h["source"]} &middot; {h["published"]}</div>'
                      f'<div style="color:{INK2};font-size:13px;line-height:1.5;">{h["title"]}</div></div>')
        cards += (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
                  f'style="background:{CARD};border-radius:10px;margin-bottom:10px;">'
                  f'<tr><td style="padding:14px 16px 16px;">'
                  f'<div style="padding-bottom:4px;">'
                  f'<span style="color:{INK};font-size:13px;font-weight:600;">{ticker}</span>'
                  f'<span style="color:{MUTED};font-size:12px;padding-left:8px;">{company}</span></div>'
                  f'{items}</td></tr></table>')

    if cards:
        blocks.append(section("05", "Watchlist news", cards))

    # ---- 06 quote --------------------------------------------------------
    quote, author = random.choice(QUOTES)
    blocks.append(section("06", "Closing thought",
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{CARD};border-radius:10px;"><tr><td style="padding:22px 24px;">'
        f'<div style="color:{INK2};font-size:15px;line-height:1.65;font-style:italic;">&ldquo;{quote}&rdquo;</div>'
        f'<div style="color:{MUTED};font-size:12px;padding-top:12px;">&mdash; {author}</div>'
        f'</td></tr></table>'))

    # ---- assemble --------------------------------------------------------
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:{PAGE};margin:0;padding:0;">
  <tr><td align="center" style="padding:32px 16px 48px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="max-width:620px;font-family:{SANS};">

      <tr><td style="padding:0 0 32px;">
        <div style="color:{ACCENT};font-size:10px;letter-spacing:3px;font-weight:600;text-transform:uppercase;padding-bottom:10px;">Daily intelligence</div>
        <div style="color:{INK};font-size:30px;font-weight:700;letter-spacing:-0.5px;line-height:1.15;">Morning Briefing</div>
        <div style="color:{MUTED};font-size:13px;padding-top:8px;">{today}</div>
        <div style="border-top:2px solid {ACCENT};width:44px;margin:20px 0 0;font-size:0;line-height:0;">&nbsp;</div>
        <div style="color:{INK2};font-size:15px;line-height:1.6;padding-top:20px;">{lede}</div>
      </td></tr>

      {"".join(blocks)}

      <tr><td style="border-top:1px solid {HAIRLINE};padding:20px 0 0;text-align:center;">
        <div style="color:{MUTED};font-size:11px;line-height:1.8;">
          Automated &middot; Yahoo Finance &middot; NewsAPI<br>
          Not financial advice. Do your own research.
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>"""


def send_briefing():
    print(f"Building morning briefing for {TO_EMAIL}...")
    html = build_email()

    message = Mail(
        from_email   = FROM_EMAIL,
        to_emails    = TO_EMAIL,
        subject      = f"Morning Briefing — {datetime.now().strftime('%B %-d, %Y')}",
        html_content = html,
    )

    try:
        response = SendGridAPIClient(SENDGRID_API_KEY).send(message)
        if response.status_code in (200, 202):
            print(f"✓ Briefing sent to {TO_EMAIL}")
        else:
            print(f"SendGrid response: {response.status_code}")
    except Exception as e:
        print(f"Error sending email: {e}")


if __name__ == "__main__":
    if "--preview" in sys.argv:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview.html")
        with open(out, "w") as f:
            f.write(f'<body style="margin:0;background:{PAGE};">{build_email()}</body>')
        print(f"✓ Preview written to {out}")
    else:
        send_briefing()
