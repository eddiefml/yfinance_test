# YFinance Flask Multi-Stock App

Simple Flask app to query multiple stock symbols with `yfinance` and show a clean dashboard UI.

## Features

- Multi-symbol input (`AAPL, MSFT, TSLA` or one per line)
- Last price, change, and change %
- Previous close, open, day range
- 52-week range and 52-week position indicator
- Volume, market cap, currency, exchange, trend signal
- Latest top 20 news for each stock symbol
- Per-symbol error display (invalid ticker or missing data)

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

開啟瀏覽器到 <http://127.0.0.1:5000>

## Market Data Timing Note

- Data is sourced from Yahoo Finance via `yfinance`.
- Quote fields like `last` may be real-time or delayed (commonly around 15 minutes), depending on exchange and licensing.
- News timestamps come from Yahoo provider publish time and are formatted in your local machine time.
