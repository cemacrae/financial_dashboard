import math
import json
from flask import Flask, render_template, request
from flask_caching import Cache
import pandas as pd
import yfinance as yf


def fmt_price(value, currency="USD"):
    if value is None:
        return "N/A"
    try:
        return f"{currency} {float(value):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def fmt_eps(value, currency="USD"):
    if value is None:
        return "N/A"
    try:
        return f"{currency} {float(value):.2f}"
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

def fmt_market_cap(value, currency="USD"):
    """Format market cap with its currency, compacted e.g. 'USD 3.24T'."""
    if value is None:
        return "N/A"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    abs_v = abs(v)
    if abs_v >= 1e12:
        compact = f"{v / 1e12:.2f}T"
    elif abs_v >= 1e9:
        compact = f"{v / 1e9:.2f}B"
    elif abs_v >= 1e6:
        compact = f"{v / 1e6:.2f}M"
    else:
        compact = f"{v:,.0f}"
    return f"{currency} {compact}"


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

def fetch_historical_financials(ticker):
    """
    Returns (eps_history, rev_history), each a list of 4 floats or None,
    ordered oldest to newest: [FY-3, FY-2, FY-1, FY0].
    Pulled from income_stmt columns[0..3], most-recent-first, then reversed.
    """
    try:
        stmt = ticker.income_stmt
        if stmt is None or stmt.empty:
            return [None, None, None, None], [None, None, None, None]

        cols = list(stmt.columns[:4])

        def safe_row(row_label):
            if row_label not in stmt.index:
                return [None] * 4
            values = []
            for col in cols:
                try:
                    v = stmt.loc[row_label, col]
                    values.append(float(v) if v is not None and not math.isnan(float(v)) else None)
                except Exception:
                    values.append(None)
            values_padded = (values + [None] * 4)[:4]
            return list(reversed(values_padded))

        eps_history = safe_row("Diluted EPS")
        rev_history = safe_row("Total Revenue")

        return eps_history, rev_history
    except Exception:
        return [None, None, None, None], [None, None, None, None]


def history_cagr(start_value, end_value, years):
    """Same math as raw_cagr but named for clarity when used on historical arrays."""
    return raw_cagr(start_value, end_value, years)

def fetch_eps_trend_fy2(ticker):
    """
    Returns dict with keys current, 7daysAgo, 30daysAgo, 60daysAgo, 90daysAgo
    (raw EPS floats or None), pulled from the '+1y' (next fiscal year) row of
    the EPS Trend table on Yahoo Finance's Analysis tab.
    """
    keys = ["current", "7daysAgo", "30daysAgo", "60daysAgo", "90daysAgo"]
    try:
        trend = ticker.eps_trend
        if trend is None or trend.empty or "+1y" not in trend.index:
            return {k: None for k in keys}

        def safe(col):
            try:
                v = trend.loc["+1y", col]
                return float(v) if v is not None and not math.isnan(float(v)) else None
            except Exception:
                return None

        return {k: safe(k) for k in keys}
    except Exception:
        return {k: None for k in keys}


def fetch_price_days_ago(ticker, days_back=(0, 7, 30, 60, 90)):
    """
    Returns dict {offset_in_days: raw close price or None}. For each offset,
    finds the closing price on the most recent trading day at or before
    (today - offset) — this snaps backward over weekends/holidays instead of failing.
    """
    result = {d: None for d in days_back}
    try:
        hist = ticker.history(period="6mo")
        if hist is None or hist.empty:
            return result

        idx = hist.index
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        hist = hist.copy()
        hist.index = idx

        today = pd.Timestamp.now().normalize()
        for d in days_back:
            target = today - pd.Timedelta(days=d)
            eligible = hist.index[hist.index <= target]
            if len(eligible) == 0:
                continue
            result[d] = float(hist.loc[eligible[-1], "Close"])
    except Exception:
        pass
    return result


app = Flask(__name__)
app.config["CACHE_TYPE"] = "SimpleCache"
app.config["CACHE_DEFAULT_TIMEOUT"] = 900
cache = Cache(app)

PRICE_CACHE_SECONDS = 60
FUNDAMENTALS_CACHE_SECONDS = 6 * 60 * 60

@cache.memoize(timeout=PRICE_CACHE_SECONDS)
def fetch_price(symbol):
    ticker = yf.Ticker(symbol)
    try:
        price = ticker.fast_info["lastPrice"]
        if price:
            return float(price)
    except Exception:
        pass
    try:
        info = ticker.info
        return info.get("currentPrice") or info.get("regularMarketPrice")
    except Exception:
        return None
    
EXCHANGE_RATE_CACHE_SECONDS = 5 * 60

@cache.memoize(timeout=EXCHANGE_RATE_CACHE_SECONDS)
def fetch_exchange_rate(from_currency, to_currency):
    """
    Returns how many units of to_currency one unit of from_currency is worth
    (e.g. fetch_exchange_rate("HKD", "USD") -> ~0.128), or None if no rate found
    """
    if not from_currency or not to_currency:
        return None
    if from_currency == to_currency:
        return 1.0
    fx_ticker = yf.Ticker(f"{from_currency}{to_currency}=X")
    try:
        rate = fx_ticker.fast_info["lastPrice"]
        if rate:
            return float(rate)
    except Exception:
        pass
    try:
        info = fx_ticker.info
        rate = info.get("regularMarketPrice") or info.get("currentPrice")
        return float(rate) if rate else None
    except Exception:
        return None


@cache.memoize(timeout=FUNDAMENTALS_CACHE_SECONDS)
def fetch_fundamentals(symbol):
    ticker = yf.Ticker(symbol)
    info = ticker.info
    """
    Some stocks (e.g. foreign listings, ADRs) trade in one currency but
    report financials in another - e.g. 9988.HK trades in HKD but may
    report earnings in USD or CNY, so we flag the mismatch and skip the rest
    """
    currency = info.get("currency")
    financial_currency = info.get("financialCurrency")

    if currency and financial_currency and currency != financial_currency:
        fx_rate = fetch_exchange_rate(currency, financial_currency)
    else:
        fx_rate = 1.0

    name = info.get("longName", "N/A")

    if fx_rate is None:
        return {
            "currency_mismatch": True,
            "currency": currency,
            "financial_currency": financial_currency,
            "name": name,
        }
    
    eps_ttm_raw = info.get("trailingEps")

    fy0_raw, fy1_raw, fy2_raw = fetch_earnings_estimates(ticker)
    fy_end = fetch_fy_end_date(ticker)
    rev_fy0_raw, rev_fy1_raw, rev_fy2_raw = fetch_revenue_estimates(ticker)
    market_cap_raw = info.get("marketCap")
    ps_ttm_raw = info.get("priceToSalesTrailing12Months")

    eps_history, rev_history = fetch_historical_financials(ticker)
    eps_trend_fy2 = fetch_eps_trend_fy2(ticker)
    price_by_offset = fetch_price_days_ago(ticker)

    return {
        "currency_mismatch": False,
        "fx_rate": fx_rate,
        "currency": currency,
        "financial_currency": financial_currency,
        "name": name,
        "eps_ttm_raw": eps_ttm_raw,
        "fy0_raw": fy0_raw,
        "fy1_raw": fy1_raw,
        "fy2_raw": fy2_raw,
        "fy_end": fy_end,
        "rev_fy0_raw": rev_fy0_raw,
        "rev_fy1_raw": rev_fy1_raw,
        "rev_fy2_raw": rev_fy2_raw,
        "market_cap_raw": market_cap_raw,
        "ps_ttm_raw": ps_ttm_raw,
        "eps_history": eps_history,
        "rev_history": rev_history,
        "eps_trend_fy2": eps_trend_fy2,
        "price_by_offset": price_by_offset,
    }


def fetch_stock(symbol):
    price_raw = fetch_price(symbol)
    if not price_raw:
        return None

    f = fetch_fundamentals(symbol)
    if f is None:
        return None

    if f.get("currency_mismatch"):
        raise ValueError(
            f"price is in {f['currency']} but financials are reported in "
            f"{f['financial_currency']} — couldn't find an exchange rate to convert between them"
        )

    fx_rate = f["fx_rate"]
    currency = f["currency"] or "USD"
    financial_currency = f["financial_currency"] or "USD"

    eps_ttm_raw = f["eps_ttm_raw"]
    fy0_raw, fy1_raw, fy2_raw = f["fy0_raw"], f["fy1_raw"], f["fy2_raw"]
    fy_end = f["fy_end"]
    rev_fy0_raw, rev_fy1_raw, rev_fy2_raw = f["rev_fy0_raw"], f["rev_fy1_raw"], f["rev_fy2_raw"]
    market_cap_raw = f["market_cap_raw"]
    ps_ttm_raw = f["ps_ttm_raw"]
    eps_history, rev_history = f["eps_history"], f["rev_history"]
    eps_trend_fy2 = f["eps_trend_fy2"]

    price_converted = price_raw * fx_rate
    market_cap_converted = market_cap_raw * fx_rate if market_cap_raw is not None else None

    # Use a fresh copy of the cached historical prices, but swap in today's
    # live price so that one bar always reflects the price we just fetched, 
    # not a stale fundamentals-cache price. Then convert every point into the 
    # financials' currency
    price_by_offset = dict(f["price_by_offset"])
    price_by_offset[0] = price_raw
    price_by_offset = {
        off: (p * fx_rate if p is not None else None)
        for off, p in price_by_offset.items()
    }

    pe_trend_labels = ["Current", "7d Ago", "30d Ago", "60d Ago", "90d Ago"]
    pe_trend_offsets = [0, 7, 30, 60, 90]
    pe_trend_eps_keys = ["current", "7daysAgo", "30daysAgo", "60daysAgo", "90daysAgo"]

    pe_trend_values = [
        raw_pe(price_by_offset.get(off), eps_trend_fy2.get(ek))
        for off, ek in zip(pe_trend_offsets, pe_trend_eps_keys)
    ]

    # Full 6-point series: [FY-3, FY-2, FY-1, FY0, FY1, FY2]
    eps_series = eps_history + [fy1_raw, fy2_raw]
    rev_series = rev_history + [rev_fy1_raw, rev_fy2_raw]

    eps_hist_cagr = history_cagr(eps_history[0], eps_history[3], 3)
    eps_fwd_cagr = history_cagr(eps_history[3], fy2_raw, 2)
    rev_hist_cagr = history_cagr(rev_history[0], rev_history[3], 3)
    rev_fwd_cagr = history_cagr(rev_history[3], rev_fy2_raw, 2)

    history_payload = {
        "labels": ["FY-3", "FY-2", "FY-1", "FY0", "FY1", "FY2"],
        "currency": financial_currency,
        "eps": eps_series,
        "revenue": rev_series,
        "epsHistCagr": eps_hist_cagr,
        "epsFwdCagr": eps_fwd_cagr,
        "revHistCagr": rev_hist_cagr,
        "revFwdCagr": rev_fwd_cagr,
        "peTrendLabels": pe_trend_labels,
        "peTrendValues": pe_trend_values,
    }

    return {
        # Identifiers
        "symbol": symbol,
        "name": f["name"],

        # P/E table (formatted)
        "price": fmt_price(price_raw, currency),
        "pe_ttm": fmt_pe(price_converted, eps_ttm_raw),
        "pe_fy0": fmt_pe(price_converted, fy0_raw),
        "pe_fy1": fmt_pe(price_converted, fy1_raw),
        "pe_fy2": fmt_pe(price_converted, fy2_raw),
        "eps_growth": fmt_cagr(fy0_raw, fy2_raw),

        # Raw floats for P/E chart
        "pe_fy0_raw": raw_pe(price_converted, fy0_raw),
        "eps_growth_raw": raw_cagr(fy0_raw, fy2_raw),

        # EPS table (formatted)
        "fy_end": fy_end,
        "eps_ttm": fmt_eps(eps_ttm_raw, financial_currency),
        "eps_fy0": fmt_eps(fy0_raw, financial_currency),
        "eps_fy1": fmt_eps(fy1_raw, financial_currency),
        "eps_fy2": fmt_eps(fy2_raw, financial_currency),

        # P/S table (formatted)
        "market_cap_ttm": fmt_market_cap(market_cap_converted, financial_currency),
        "ps_fy0": fmt_ps(market_cap_converted, rev_fy0_raw),
        "ps_fy1": fmt_ps(market_cap_converted, rev_fy1_raw),
        "ps_fy2": fmt_ps(market_cap_converted, rev_fy2_raw),
        "rev_growth": fmt_cagr(rev_fy0_raw, rev_fy2_raw),

        # Raw floats for P/S chart
        "ps_fy0_raw": raw_ps(market_cap_converted, rev_fy0_raw),
        "rev_growth_raw": raw_cagr(rev_fy0_raw, rev_fy2_raw),

        # Per-stock history for expandable chart rows
        "history_json": json.dumps(history_payload),
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