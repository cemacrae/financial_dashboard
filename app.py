import math
import json
from flask import Flask, render_template, request
from flask_caching import Cache
import yfinance as yf


def fmt_price(value):
    if value is None:
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def fmt_eps(value):
    if value is None:
        return "N/A"
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def fmt_ratio(value, decimals=1):
    """Format a pre-calculated ratio as e.g. 7.3x. N/A if missing or non-positive."""
    if value is None:
        return "N/A"
    try:
        v = float(value)
        if v <= 0:
            return "N/A"
        return f"{v:.{decimals}f}x"
    except (TypeError, ValueError):
        return "N/A"


def fmt_pe(price, eps):
    """Price / EPS, shown as e.g. 28.4x. N/A if eps is zero, negative, or missing."""
    if price is None or eps is None:
        return "N/A"
    try:
        p, e = float(price), float(eps)
        if e <= 0:
            return "N/A"
        return f"{p / e:.1f}x"
    except (TypeError, ValueError):
        return "N/A"


def raw_pe(price, eps):
    """Raw float P/E for chart use. None if eps is zero, negative, or missing."""
    if price is None or eps is None:
        return None
    try:
        p, e = float(price), float(eps)
        if e <= 0:
            return None
        return round(p / e, 2)
    except (TypeError, ValueError):
        return None


def fmt_cagr(fy0, fy2, years=2):
    """CAGR from FY0 to FY2. N/A if either value is missing or FY0 <= 0."""
    if fy0 is None or fy2 is None:
        return "N/A"
    try:
        f0, f2 = float(fy0), float(fy2)
        if f0 <= 0:
            return "N/A"
        cagr = (f2 / f0) ** (1 / years) - 1
        return f"{cagr * 100:.1f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        return "N/A"


def raw_cagr(fy0, fy2, years=2):
    """Raw float CAGR (as a percentage, e.g. 12.5) for chart use. None if invalid."""
    if fy0 is None or fy2 is None:
        return None
    try:
        f0, f2 = float(fy0), float(fy2)
        if f0 <= 0:
            return None
        return round(((f2 / f0) ** (1 / years) - 1) * 100, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def fmt_ps(market_cap, revenue):
    """Market cap / revenue, shown as e.g. 7.3x. N/A if revenue is zero, negative, or missing."""
    if market_cap is None or revenue is None:
        return "N/A"
    try:
        m, r = float(market_cap), float(revenue)
        if r <= 0:
            return "N/A"
        return f"{m / r:.1f}x"
    except (TypeError, ValueError):
        return "N/A"


def raw_ps(market_cap, revenue):
    """Raw float P/S for chart use. None if revenue is zero, negative, or missing."""
    if market_cap is None or revenue is None:
        return None
    try:
        m, r = float(market_cap), float(revenue)
        if r <= 0:
            return None
        return round(m / r, 2)
    except (TypeError, ValueError):
        return None


def fetch_fy_end_date(ticker):
    """Most recent fiscal year-end date as e.g. '1/31/2026'."""
    try:
        stmt = ticker.income_stmt
        if stmt is not None and not stmt.empty:
            return stmt.columns[0].strftime("%-m/%-d/%Y")
    except Exception:
        pass
    return "N/A"


def fetch_earnings_estimates(ticker):
    """
    Returns (fy0_year_ago_eps, fy1_avg_eps, fy2_avg_eps) as raw floats or None.
    earnings_estimate index: 0q, +1q, 0y, +1y
    columns: numberOfAnalysts, avg, low, high, yearAgoEps, growth
    """
    try:
        ee = ticker.earnings_estimate
        if ee is None or ee.empty:
            return None, None, None

        def safe(row, col):
            try:
                v = ee.loc[row, col]
                return float(v) if v is not None and not math.isnan(float(v)) else None
            except Exception:
                return None

        return (
            safe("0y", "yearAgoEps"),
            safe("0y", "avg"),
            safe("+1y", "avg"),
        )
    except Exception:
        return None, None, None


def fetch_revenue_estimates(ticker):
    """
    Returns (rev_fy0, rev_fy1, rev_fy2) as raw floats (dollars) or None.
    revenue_estimate index: 0q, +1q, 0y, +1y
    columns: numberOfAnalysts, avg, low, high, yearAgoRevenue, growth
    """
    try:
        re = ticker.revenue_estimate
        if re is None or re.empty:
            return None, None, None

        def safe(row, col):
            try:
                v = re.loc[row, col]
                return float(v) if v is not None and not math.isnan(float(v)) else None
            except Exception:
                return None

        return (
            safe("0y", "yearAgoRevenue"),
            safe("0y", "avg"),
            safe("+1y", "avg"),
        )
    except Exception:
        return None, None, None


app = Flask(__name__)
app.config["CACHE_TYPE"] = "SimpleCache"
app.config["CACHE_DEFAULT_TIMEOUT"] = 900
cache = Cache(app)


@cache.memoize(timeout=900)
def fetch_stock(symbol):
    ticker = yf.Ticker(symbol)
    info = ticker.info

    price_raw = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price_raw:
        return None

    eps_ttm_raw = info.get("trailingEps")
    fy0_raw, fy1_raw, fy2_raw = fetch_earnings_estimates(ticker)
    fy_end = fetch_fy_end_date(ticker)
    rev_fy0_raw, rev_fy1_raw, rev_fy2_raw = fetch_revenue_estimates(ticker)
    market_cap_raw = info.get("marketCap")
    ps_ttm_raw = info.get("priceToSalesTrailing12Months")

    return {
        # Identifiers
        "symbol": symbol,
        "name": info.get("longName", "N/A"),

        # P/E table (formatted)
        "price": fmt_price(price_raw),
        "pe_ttm": fmt_pe(price_raw, eps_ttm_raw),
        "pe_fy0": fmt_pe(price_raw, fy0_raw),
        "pe_fy1": fmt_pe(price_raw, fy1_raw),
        "pe_fy2": fmt_pe(price_raw, fy2_raw),
        "eps_growth": fmt_cagr(fy0_raw, fy2_raw),

        # Raw floats for P/E chart
        "pe_fy0_raw": raw_pe(price_raw, fy0_raw),
        "eps_growth_raw": raw_cagr(fy0_raw, fy2_raw),

        # EPS table (formatted)
        "fy_end": fy_end,
        "eps_ttm": fmt_eps(eps_ttm_raw),
        "eps_fy0": fmt_eps(fy0_raw),
        "eps_fy1": fmt_eps(fy1_raw),
        "eps_fy2": fmt_eps(fy2_raw),

        # P/S table (formatted)
        "ps_ttm": fmt_ratio(ps_ttm_raw),
        "ps_fy0": fmt_ps(market_cap_raw, rev_fy0_raw),
        "ps_fy1": fmt_ps(market_cap_raw, rev_fy1_raw),
        "ps_fy2": fmt_ps(market_cap_raw, rev_fy2_raw),
        "rev_growth": fmt_cagr(rev_fy0_raw, rev_fy2_raw),

        # Raw floats for P/S chart
        "ps_fy0_raw": raw_ps(market_cap_raw, rev_fy0_raw),
        "rev_growth_raw": raw_cagr(rev_fy0_raw, rev_fy2_raw),
    }


@app.route("/")
def home():
    symbols_input = request.args.get("symbols", "AAPL,MSFT,GOOGL")
    symbols = [s.strip().upper() for s in symbols_input.split(",")]

    stocks = []
    errors = []

    for symbol in symbols:
        try:
            result = fetch_stock(symbol)
            if result is None:
                errors.append(f"'{symbol}' — no data found. Check the ticker symbol.")
            else:
                stocks.append(result)
        except Exception as e:
            errors.append(f"'{symbol}' — something went wrong: {str(e)}")

    chart_data = [
        {
            "symbol": s["symbol"],
            "pe_fy0": s["pe_fy0_raw"],
            "epsGrowth": s["eps_growth_raw"],
        }
        for s in stocks
        if s["pe_fy0_raw"] is not None and s["eps_growth_raw"] is not None
    ]

    return render_template(
        "index.html",
        stocks=stocks,
        errors=errors,
        symbols_input=symbols_input,
        chart_json=json.dumps(chart_data),
    )


@app.route("/ps-revenue")
def ps_revenue():
    symbols_input = request.args.get("symbols", "AAPL,MSFT,GOOGL")
    symbols = [s.strip().upper() for s in symbols_input.split(",")]

    stocks = []
    errors = []

    for symbol in symbols:
        try:
            result = fetch_stock(symbol)
            if result is None:
                errors.append(f"'{symbol}' — no data found. Check the ticker symbol.")
            else:
                stocks.append(result)
        except Exception as e:
            errors.append(f"'{symbol}' — something went wrong: {str(e)}")

    chart_data = [
        {
            "symbol": s["symbol"],
            "ps_fy0": s["ps_fy0_raw"],
            "revGrowth": s["rev_growth_raw"],
        }
        for s in stocks
        if s["ps_fy0_raw"] is not None and s["rev_growth_raw"] is not None
    ]

    return render_template(
        "ps_revenue.html",
        stocks=stocks,
        errors=errors,
        symbols_input=symbols_input,
        chart_json=json.dumps(chart_data),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)