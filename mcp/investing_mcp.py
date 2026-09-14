import yfinance as yf
import httpx
import json
import os
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")


def _rh_login():
    import robin_stocks.robinhood as r
    r.login(
        os.getenv("ROBINHOOD_USERNAME"),
        os.getenv("ROBINHOOD_PASSWORD"),
        store_session=True,
        expiresIn=86400
    )
    return r


def get_portfolio_summary(tickers: str) -> dict:
    """Get current prices and daily change for a list of tickers.
    Pass tickers as a comma separated string like 'AAPL, TSLA, NVDA'
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",")]
    results = []

    for ticker in ticker_list:
        stock = yf.Ticker(ticker)
        info = stock.fast_info

        try:
            price = round(info.last_price, 2)
            prev_close = round(info.previous_close, 2)
            change = round(price - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2)

            results.append({
                "ticker": ticker,
                "price": f"${price}",
                "change": f"${change}",
                "change_percent": f"{change_pct}%",
                "trend": "UP" if change >= 0 else "DOWN"
            })
        except Exception:
            results.append({"ticker": ticker, "error": "Could not fetch data"})

    return {"portfolio": results}


def get_stock_news(ticker: str) -> dict:
    """Get the latest news headlines for a stock ticker."""
    stock = yf.Ticker(ticker.upper())
    company_name = stock.info.get("longName", ticker)

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": f"{ticker.upper()} stock OR {company_name} stock OR {ticker.upper()} shares",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "language": "en",
        "apiKey": NEWS_API_KEY
    }

    response = httpx.get(url, params=params)
    data = response.json()

    articles = data.get("articles", [])
    headlines = [
        {
            "title": a["title"],
            "source": a["source"]["name"],
            "published": a["publishedAt"][:10]
        }
        for a in articles
    ]

    return {
        "ticker": ticker.upper(),
        "company": company_name,
        "headlines": headlines
    }


def get_earnings(ticker: str) -> dict:
    """Get the last 4 quarters of earnings for a company."""
    stock = yf.Ticker(ticker.upper())
    company_name = stock.info.get("longName", ticker)

    income = stock.quarterly_income_stmt
    if income is None or income.empty:
        return {"ticker": ticker.upper(), "error": "No earnings data found"}

    results = []
    for date in income.columns[:4]:
        net_income = income.loc["Net Income", date] if "Net Income" in income.index else None
        revenue = income.loc["Total Revenue", date] if "Total Revenue" in income.index else None
        results.append({
            "quarter": str(date)[:10],
            "net_income": f"${round(float(net_income) / 1_000_000_000, 2)}B" if net_income else "N/A",
            "revenue": f"${round(float(revenue) / 1_000_000_000, 2)}B" if revenue else "N/A"
        })

    return {
        "ticker": ticker.upper(),
        "company": company_name,
        "last_4_quarters": results
    }


def compare_stocks(ticker1: str, ticker2: str) -> dict:
    """Compare two stocks side by side — price, change, PE ratio, market cap."""
    results = {}

    for ticker in [ticker1.upper(), ticker2.upper()]:
        stock = yf.Ticker(ticker)
        info = stock.info
        fast = stock.fast_info

        try:
            price = round(fast.last_price, 2)
            prev_close = round(fast.previous_close, 2)
            change_pct = round(((price - prev_close) / prev_close) * 100, 2)
            market_cap = fast.market_cap
            pe_ratio = info.get("trailingPE", "N/A")

            results[ticker] = {
                "price": f"${price}",
                "change_today": f"{change_pct}%",
                "market_cap": f"${round(market_cap / 1_000_000_000, 2)}B" if market_cap else "N/A",
                "pe_ratio": round(pe_ratio, 2) if isinstance(pe_ratio, float) else "N/A",
                "52w_high": f"${round(fast.year_high, 2)}",
                "52w_low": f"${round(fast.year_low, 2)}"
            }
        except Exception as e:
            results[ticker] = {"error": str(e)}

    return {"comparison": results}


def get_watchlist_summary(tickers: str) -> dict:
    """Check your entire watchlist at once — prices, change, and a signal."""
    ticker_list = [t.strip().upper() for t in tickers.split(",")]
    watchlist = []

    for ticker in ticker_list:
        stock = yf.Ticker(ticker)
        fast = stock.fast_info
        info = stock.info

        try:
            price = round(fast.last_price, 2)
            prev_close = round(fast.previous_close, 2)
            change_pct = round(((price - prev_close) / prev_close) * 100, 2)
            year_high = round(fast.year_high, 2)
            year_low = round(fast.year_low, 2)
            pct_from_high = round(((price - year_high) / year_high) * 100, 2)

            if change_pct > 2:
                signal = "STRONG MOVE UP"
            elif change_pct < -2:
                signal = "STRONG MOVE DOWN"
            elif pct_from_high > -5:
                signal = "NEAR 52W HIGH"
            else:
                signal = "NEUTRAL"

            watchlist.append({
                "ticker": ticker,
                "company": info.get("shortName", ticker),
                "price": f"${price}",
                "change_today": f"{change_pct}%",
                "pct_from_52w_high": f"{pct_from_high}%",
                "signal": signal
            })
        except Exception:
            watchlist.append({"ticker": ticker, "error": "Could not fetch"})

    return {"watchlist": watchlist}


def get_sec_filings(ticker: str) -> dict:
    """Get the latest SEC filings for a company from EDGAR."""
    stock = yf.Ticker(ticker.upper())
    company_name = stock.info.get("longName", ticker)
    headers = {"User-Agent": "InvestingMCP research@example.com"}

    try:
        # Step 1: get CIK from EDGAR ticker lookup
        tickers_resp = httpx.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=headers, timeout=10
        )
        tickers_data = tickers_resp.json()
        cik = None
        for entry in tickers_data.values():
            if entry["ticker"].upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                break

        if not cik:
            return {"ticker": ticker.upper(), "error": "CIK not found"}

        # Step 2: get filings for that CIK
        filings_resp = httpx.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=headers, timeout=10
        )
        data = filings_resp.json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        descriptions = recent.get("primaryDocument", [])

        filings = []
        for form, date, desc in zip(forms, dates, descriptions):
            if form in ["10-K", "10-Q", "8-K"]:
                filings.append({"form": form, "filed": date, "document": desc})
            if len(filings) == 5:
                break

        return {
            "ticker": ticker.upper(),
            "company": company_name,
            "recent_filings": filings
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def research_company(ticker: str) -> dict:
    """Full company breakdown — price, news, earnings, and SEC filings in one call."""
    stock = yf.Ticker(ticker.upper())
    info = stock.info
    fast = stock.fast_info

    try:
        price = round(fast.last_price, 2)
        prev_close = round(fast.previous_close, 2)
        change_pct = round(((price - prev_close) / prev_close) * 100, 2)
        market_cap = fast.market_cap
        pe_ratio = info.get("trailingPE", "N/A")
        year_high = round(fast.year_high, 2)
        year_low = round(fast.year_low, 2)

        overview = {
            "ticker": ticker.upper(),
            "company": info.get("longName", ticker),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "description": info.get("longBusinessSummary", "N/A")[:300] + "...",
            "price": f"${price}",
            "change_today": f"{change_pct}%",
            "market_cap": f"${round(market_cap / 1_000_000_000, 2)}B" if market_cap else "N/A",
            "pe_ratio": round(pe_ratio, 2) if isinstance(pe_ratio, float) else "N/A",
            "52w_high": f"${year_high}",
            "52w_low": f"${year_low}",
            "dividend_yield": info.get("dividendYield", "None")
        }
    except Exception as e:
        overview = {"ticker": ticker.upper(), "error": str(e)}

    news = get_stock_news(ticker)
    earnings = get_earnings(ticker)
    filings = get_sec_filings(ticker)

    return {
        "overview": overview,
        "latest_news": news.get("headlines", [])[:3],
        "earnings": earnings.get("last_4_quarters", [])[:2],
        "sec_filings": filings.get("recent_filings", [])[:3]
    }


def get_insider_trades(ticker: str) -> dict:
    """Track insider buying and selling — Form 4 filings from SEC EDGAR.
    When executives buy their own stock with their own money, that's a bullish signal.
    When they sell large amounts, that can be a warning sign.
    """
    headers = {"User-Agent": "InvestingMCP research@example.com"}
    stock = yf.Ticker(ticker.upper())
    company_name = stock.info.get("longName", ticker)

    try:
        # Step 1: get CIK
        tickers_resp = httpx.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=headers, timeout=10
        )
        tickers_data = tickers_resp.json()
        cik = None
        for entry in tickers_data.values():
            if entry["ticker"].upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                break

        if not cik:
            return {"ticker": ticker.upper(), "error": "CIK not found"}

        # Step 2: get Form 4 filings (insider trades)
        filings_resp = httpx.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=headers, timeout=10
        )
        data = filings_resp.json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        reporters = recent.get("primaryDocument", [])

        # Step 3: find all Form 4 entries
        insider_filings = []
        for form, date, doc in zip(forms, dates, reporters):
            if form == "4":
                insider_filings.append({"filed": date, "document": doc})
            if len(insider_filings) == 10:
                break

        if not insider_filings:
            return {
                "ticker": ticker.upper(),
                "company": company_name,
                "message": "No recent insider trades found"
            }

        # Step 4: parse each Form 4 for transaction details
        trades = []
        for filing in insider_filings[:5]:
            try:
                doc_parts = filing["document"].replace(".htm", "").replace(".xml", "")
                xml_url = (
                    f"https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10&output=atom"
                )
                trades.append({
                    "filed": filing["filed"],
                    "form": "Form 4 (Insider Trade)",
                    "sec_link": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10"
                })
            except Exception:
                continue

        # Step 5: also get summary from yfinance insider data
        insider_summary = []
        try:
            insider_df = stock.insider_transactions
            if insider_df is not None and not insider_df.empty:
                for _, row in insider_df.head(8).iterrows():
                    shares = row.get("Shares", 0)
                    action = "BOUGHT" if shares > 0 else "SOLD"
                    insider_summary.append({
                        "insider": row.get("Insider", "Unknown"),
                        "position": row.get("Position", "N/A"),
                        "action": action,
                        "shares": f"{abs(int(shares)):,}",
                        "value": f"${abs(int(row.get('Value', 0))):,}",
                        "date": str(row.get("Start Date", "N/A"))[:10]
                    })
        except Exception:
            pass

        return {
            "ticker": ticker.upper(),
            "company": company_name,
            "insider_trades": insider_summary if insider_summary else trades,
            "view_all_filings": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=40"
        }

    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def get_robinhood_portfolio() -> dict:
    """Get your real Robinhood portfolio — all positions, values, and daily change."""
    try:
        r = _rh_login()

        positions = r.get_open_stock_positions()
        portfolio_value = r.load_portfolio_profile()
        account = r.load_account_profile()

        holdings = []
        total_value = 0

        for position in positions:
            try:
                instrument_url = position.get("instrument")
                instrument = r.get_instrument_by_url(instrument_url)
                ticker = instrument.get("symbol", "???")

                quantity = float(position.get("quantity", 0))
                avg_cost = float(position.get("average_buy_price", 0))

                quote = r.get_stock_quote_by_symbol(ticker)
                current_price = float(quote.get("last_trade_price", 0))

                market_value = quantity * current_price
                cost_basis = quantity * avg_cost
                gain_loss = market_value - cost_basis
                gain_loss_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost else 0

                total_value += market_value

                holdings.append({
                    "ticker": ticker,
                    "shares": round(quantity, 4),
                    "avg_cost": f"${round(avg_cost, 2)}",
                    "current_price": f"${round(current_price, 2)}",
                    "market_value": f"${round(market_value, 2)}",
                    "gain_loss": f"${round(gain_loss, 2)}",
                    "gain_loss_pct": f"{round(gain_loss_pct, 2)}%",
                    "status": "UP" if gain_loss >= 0 else "DOWN"
                })
            except Exception:
                continue

        buying_power = float(account.get("buying_power", 0)) if account else 0

        return {
            "total_market_value": f"${round(total_value, 2)}",
            "buying_power": f"${round(buying_power, 2)}",
            "holdings": sorted(holdings, key=lambda x: float(x["market_value"].replace("$", "").replace(",", "")), reverse=True)
        }

    except Exception as e:
        return {"error": str(e)}


def get_robinhood_history() -> dict:
    """Get your recent Robinhood trade history."""
    try:
        r = _rh_login()
        orders = r.get_all_stock_orders()

        trades = []
        for order in orders[:15]:
            if order.get("state") != "filled":
                continue
            try:
                instrument = r.get_instrument_by_url(order.get("instrument"))
                ticker = instrument.get("symbol", "???")
                side = order.get("side", "").upper()
                qty = float(order.get("quantity", 0))
                price = float(order.get("average_price") or order.get("price") or 0)
                date = order.get("last_transaction_at", "")[:10]

                trades.append({
                    "ticker": ticker,
                    "action": side,
                    "shares": round(qty, 4),
                    "price": f"${round(price, 2)}",
                    "total": f"${round(qty * price, 2)}",
                    "date": date
                })
            except Exception:
                continue

        return {"recent_trades": trades}

    except Exception as e:
        return {"error": str(e)}


def get_robinhood_buying_power() -> dict:
    """Get your available cash and buying power in Robinhood."""
    try:
        r = _rh_login()
        account = r.load_account_profile()
        portfolio = r.load_portfolio_profile()

        return {
            "buying_power": f"${float(account.get('buying_power', 0)):.2f}",
            "cash": f"${float(account.get('cash', 0)):.2f}",
            "portfolio_value": f"${float(portfolio.get('market_value', 0)):.2f}",
            "total_equity": f"${float(portfolio.get('equity', 0)):.2f}"
        }

    except Exception as e:
        return {"error": str(e)}


def get_options_chain(ticker: str, expiration_date: str = None) -> dict:
    """Get the options chain for a stock — calls and puts with strikes, prices, and IV.
    If no expiration_date given, returns the next available expiration dates to choose from.
    expiration_date format: 'YYYY-MM-DD'
    """
    try:
        stock = yf.Ticker(ticker.upper())
        available_expirations = stock.options

        if not available_expirations:
            return {"ticker": ticker.upper(), "error": "No options available for this ticker"}

        if not expiration_date:
            return {
                "ticker": ticker.upper(),
                "message": "Pass an expiration_date to see the chain",
                "available_expirations": list(available_expirations[:8])
            }

        chain = stock.option_chain(expiration_date)

        def parse_contracts(df, option_type):
            contracts = []
            for _, row in df.iterrows():
                contracts.append({
                    "strike": f"${row['strike']:.2f}",
                    "last_price": f"${row['lastPrice']:.2f}",
                    "bid": f"${row['bid']:.2f}",
                    "ask": f"${row['ask']:.2f}",
                    "volume": int(row['volume']) if row['volume'] == row['volume'] else 0,
                    "open_interest": int(row['openInterest']) if row['openInterest'] == row['openInterest'] else 0,
                    "implied_volatility": f"{round(row['impliedVolatility'] * 100, 1)}%",
                    "in_the_money": bool(row['inTheMoney']),
                    "type": option_type
                })
            return contracts

        calls = parse_contracts(chain.calls, "call")
        puts = parse_contracts(chain.puts, "put")

        return {
            "ticker": ticker.upper(),
            "expiration": expiration_date,
            "calls": calls[:15],
            "puts": puts[:15]
        }

    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def get_open_option_positions() -> dict:
    """Get your current open options positions from Robinhood."""
    try:
        r = _rh_login()
        positions = r.get_open_option_positions()

        if not positions:
            return {"message": "No open options positions", "positions": []}

        parsed = []
        for pos in positions:
            try:
                option_id = pos.get("option_id") or pos.get("option", "").split("/")[-2]
                option_data = r.get_option_instrument_data_by_id(option_id) if option_id else {}

                quantity = float(pos.get("quantity", 0))
                avg_price = float(pos.get("average_price", 0))
                trade_value_multiplier = float(pos.get("trade_value_multiplier", 100))

                parsed.append({
                    "ticker": option_data.get("chain_symbol", "???"),
                    "type": option_data.get("type", "???"),
                    "strike": f"${float(option_data.get('strike_price', 0)):.2f}",
                    "expiration": option_data.get("expiration_date", "???"),
                    "contracts": int(quantity),
                    "avg_cost_per_share": f"${round(avg_price, 2)}",
                    "total_cost": f"${round(avg_price * quantity * trade_value_multiplier, 2)}"
                })
            except Exception:
                parsed.append({"raw": pos.get("option", "unknown")})

        return {"open_option_positions": parsed}

    except Exception as e:
        return {"error": str(e)}


def place_option_buy(ticker: str, strike: float, expiration: str, option_type: str,
                     quantity: int, limit_price: float) -> dict:
    """Buy a call or put option on Robinhood.

    Args:
        ticker: Stock symbol e.g. 'AAPL'
        strike: Strike price e.g. 150.0
        expiration: Expiration date 'YYYY-MM-DD'
        option_type: 'call' or 'put'
        quantity: Number of contracts (1 contract = 100 shares)
        limit_price: Max price per share you'll pay (e.g. 1.50 = $150 total per contract)
    """
    try:
        r = _rh_login()

        order = r.order_buy_option_limit(
            positionEffect='open',
            creditOrDebit='debit',
            price=limit_price,
            symbol=ticker.upper(),
            quantity=quantity,
            expirationDate=expiration,
            strike=strike,
            optionType=option_type.lower()
        )

        if order and isinstance(order, dict):
            return {
                "status": "ORDER PLACED",
                "ticker": ticker.upper(),
                "type": option_type.upper(),
                "strike": f"${strike}",
                "expiration": expiration,
                "contracts": quantity,
                "limit_price": f"${limit_price} per share",
                "max_cost": f"${round(limit_price * quantity * 100, 2)} total",
                "order_id": order.get("id", "N/A")
            }
        else:
            return {"status": "FAILED", "response": str(order)}

    except Exception as e:
        return {"error": str(e)}


def close_option_position(ticker: str, strike: float, expiration: str, option_type: str,
                          quantity: int, limit_price: float) -> dict:
    """Sell an options contract to close your position.

    Args:
        ticker: Stock symbol e.g. 'AAPL'
        strike: Strike price e.g. 150.0
        expiration: Expiration date 'YYYY-MM-DD'
        option_type: 'call' or 'put'
        quantity: Number of contracts to close
        limit_price: Minimum price per share you'll accept
    """
    try:
        r = _rh_login()

        order = r.order_sell_option_limit(
            positionEffect='close',
            creditOrDebit='credit',
            price=limit_price,
            symbol=ticker.upper(),
            quantity=quantity,
            expirationDate=expiration,
            strike=strike,
            optionType=option_type.lower()
        )

        if order and isinstance(order, dict):
            return {
                "status": "CLOSE ORDER PLACED",
                "ticker": ticker.upper(),
                "type": option_type.upper(),
                "strike": f"${strike}",
                "expiration": expiration,
                "contracts": quantity,
                "limit_price": f"${limit_price} per share",
                "min_proceeds": f"${round(limit_price * quantity * 100, 2)} total",
                "order_id": order.get("id", "N/A")
            }
        else:
            return {"status": "FAILED", "response": str(order)}

    except Exception as e:
        return {"error": str(e)}


def place_option_with_stop_loss(ticker: str, strike: float, expiration: str, option_type: str,
                                 quantity: int, buy_limit: float, stop_price: float,
                                 timeout_seconds: int = 120) -> dict:
    """Buy an option and set a stop loss ONLY after the buy confirms as filled.

    Flow:
    1. Place the buy order
    2. Poll every 5 seconds until it fills (up to timeout_seconds)
    3. Once filled, place the stop limit sell order
    4. If not filled within timeout, return the buy order ID so you can check back

    Args:
        ticker: Stock symbol e.g. 'AAPL'
        strike: Strike price e.g. 150.0
        expiration: Expiration date 'YYYY-MM-DD'
        option_type: 'call' or 'put'
        quantity: Number of contracts
        buy_limit: Max price per share to pay when buying
        stop_price: Price per share that triggers your stop loss sell
        timeout_seconds: How long to wait for fill before giving up (default 120s)
    """
    import time

    try:
        r = _rh_login()

        # Step 1: place the buy order
        buy_order = r.order_buy_option_limit(
            positionEffect='open',
            creditOrDebit='debit',
            price=buy_limit,
            symbol=ticker.upper(),
            quantity=quantity,
            expirationDate=expiration,
            strike=strike,
            optionType=option_type.lower()
        )

        if not buy_order or not isinstance(buy_order, dict):
            return {"status": "BUY ORDER FAILED", "response": str(buy_order)}

        buy_order_id = buy_order.get("id")
        if not buy_order_id:
            return {"status": "BUY ORDER FAILED", "reason": "No order ID returned"}

        # Step 2: poll until filled or timeout
        elapsed = 0
        poll_interval = 5
        fill_price = None

        while elapsed < timeout_seconds:
            time.sleep(poll_interval)
            elapsed += poll_interval

            order_info = r.get_option_order_info(buy_order_id)
            state = order_info.get("state", "")

            if state == "filled":
                legs = order_info.get("legs", [])
                if legs:
                    fill_price = legs[0].get("executions", [{}])[0].get("price")
                break
            elif state in ("cancelled", "rejected", "failed"):
                return {
                    "status": f"BUY ORDER {state.upper()}",
                    "buy_order_id": buy_order_id
                }

        else:
            # Timed out — buy still pending
            return {
                "status": "BUY ORDER PENDING — STOP LOSS NOT YET SET",
                "reason": f"Buy order did not fill within {timeout_seconds}s",
                "buy_order_id": buy_order_id,
                "next_step": "Check your Robinhood app. Once filled, place the stop loss separately."
            }

        # Step 3: buy is filled — now place the stop loss
        stop_limit_price = round(stop_price * 0.90, 2)

        stop_order = r.order_sell_option_stop_limit(
            positionEffect='close',
            creditOrDebit='credit',
            limitPrice=stop_limit_price,
            stopPrice=stop_price,
            symbol=ticker.upper(),
            quantity=quantity,
            expirationDate=expiration,
            strike=strike,
            optionType=option_type.lower()
        )

        stop_status = "PLACED" if stop_order and isinstance(stop_order, dict) else "FAILED"

        return {
            "status": f"FILLED + STOP LOSS {stop_status}",
            "trade": {
                "ticker": ticker.upper(),
                "type": option_type.upper(),
                "strike": f"${strike}",
                "expiration": expiration,
                "contracts": quantity,
                "filled_at": f"${fill_price} per share" if fill_price else "confirmed filled",
                "total_cost": f"${round(float(fill_price or buy_limit) * quantity * 100, 2)}"
            },
            "stop_loss": {
                "status": stop_status,
                "triggers_at": f"${stop_price} per share",
                "sells_at": f"${stop_limit_price} per share (limit)",
                "stop_order_id": stop_order.get("id", "N/A") if isinstance(stop_order, dict) else "N/A"
            },
            "buy_order_id": buy_order_id
        }

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    print("=== PORTFOLIO SUMMARY ===")
    portfolio = get_portfolio_summary("AAPL, TSLA, NVDA")
    print(json.dumps(portfolio, indent=2))

    print("\n=== STOCK NEWS ===")
    news = get_stock_news("AAPL")
    print(json.dumps(news, indent=2))

    print("\n=== EARNINGS ===")
    earnings = get_earnings("AAPL")
    print(json.dumps(earnings, indent=2))

    print("\n=== COMPARE STOCKS ===")
    comparison = compare_stocks("AAPL", "MSFT")
    print(json.dumps(comparison, indent=2))
