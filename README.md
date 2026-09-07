# Financial Dashboard

## Introduction
A web-based financial dashboard for stock analysis and side by side comparisons, expanding on Yahoo Finance's existing tools. Users can enter any ticker to then see its actual and forward valuation, earnings and revenue metrics.
Built with Python (Flask) on the backend, yfinance for market data, HTML, CSS, and Chart.js for visualizations.

## Core fuctionalities
The dashboard has two tabs, both connected by the same user ticker input:
- P/E & EPS consists of
    - two tables (both showing actual + analyst estimates for the current and next fiscal years):
        - P/E table with trailing and forward P/E ratios and EPS growth. Clicking a ticker in this table expands a chart showing how that stock's forward P/E has shifted over the last 90 days.
        - EPS table with trailing and forward EPS. Clicking a ticker in this table expands a chart showing how that stock's actual EPS over the past 3 years, current year EPS, and estimates for the next 2 years, connected by historical and forward CAGRs.
    - a scatter chart plotting P/E for the current year against EPS growth, split into quadrants based on the group average.
- P/S & Revenue consists of
    - a table with trailing MCap, current and forward MCap/Rev ratios, and revenue growth. Clicking a ticker in this table expands a chart showing how that stock's actual revenue over the past 3 years, current year revenue, and estimates for the next 2 years, connected by historical and forward CAGRs.
    - a scatter chart plotting MCap/Rev for the current year against Revenue Growth, split into quadrants based on the group average.

**Worth noting:**
- Cross-currency handling — some stocks (foreign listings, ADRs) trade in one currency but report financials in another (e.g. a Hong Kong-listed share trading in HKD with USD-denominated earnings), and UK-listed shares are quoted in pence rather than pounds. The app detects each ticker's actual trading and financial-reporting currencies and converts everything to a consistent basis using live exchange rates. A stock is only flagged as invalid if no exchange rate can be found at all.
- Tiered caching — live price data is cached briefly (worth refreshing often), while slower-moving fundamentals (EPS/revenue estimates, historicals) are cached for hours, balancing data recency and the rate limits set by the free data source.

**Limitations:**
- This app's accuracy is limited by Yahoo Finance's own data quality. Beyond the mismatches handled above, Yahoo is occasionally inconsistent by reporting data in different currencies, causing possible discrepancies in case of foreign listings and ADRs.

## How to Open
**Live demo:** [financial_dashboard](https://financial-dashboard-53fy.onrender.com)
The app is hosted on a free tier, which sleeps after 15 minutes of inactivity — the first load after a quiet period can take up to 60 seconds to wake up.

**If the link doesn't load:** the data source - Yahoo Financen (`yfinance`) - occasionally rate-limits shared hosting IPs, which can make the live demo unavailable. If that happens, run it locally instead — local connections aren't subject to the same rate limiting:

```bash
git clone https://github.com/cemacrae/financial_dashboard.git
cd financial-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```
Then open `http://127.0.0.1:5001` in browser.

## Structure of Code
```
financial-dashboard/
├── app.py                  # Flask app: handles routes, data fetching/caching, formatting
├── requirements.txt        # Python dependencies
├── static/
│   └── style.css           # All styling for both pages
└── templates/
    ├── index.html          # P/E & EPS page
    └── ps_revenue.html     # P/S & Revenue page
```

`app.py` fetches data from `yfinance` in two tiers (fast-refreshing price, slow-refreshing fundamentals), formats it for display, and passes it to the Jinja2 templates, which render the tables and pass the underlying numbers to Chart.js for the visualizations.