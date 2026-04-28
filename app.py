from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Tuple

from flask import Flask, render_template, request
import yfinance as yf


app = Flask(__name__)


def _to_float(value: Any) -> float | None:
    """Convert values to float safely."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def _fmt_int(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def _parse_symbols(raw_text: str) -> List[str]:
    chunks = raw_text.replace("\n", ",").split(",")
    cleaned = [part.strip().upper() for part in chunks if part.strip()]
    # Preserve order while removing duplicates.
    seen = set()
    result = []
    for symbol in cleaned:
        normalized = _normalize_symbol(symbol)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _normalize_symbol(symbol: str) -> str:
    """Normalize common HK symbol input patterns to Yahoo format."""
    s = symbol.strip().upper()
    if not s:
        return s

    # hk.0700 / hk0700 / hk-0700 -> 0700.HK
    hk_prefix = re.fullmatch(r"HK[\.\-_]?(\d{1,5})", s)
    if hk_prefix:
        return f"{int(hk_prefix.group(1)):04d}.HK"

    # 0700.hk / 700.hk -> 0700.HK
    hk_suffix = re.fullmatch(r"(\d{1,5})\.HK", s)
    if hk_suffix:
        return f"{int(hk_suffix.group(1)):04d}.HK"

    return s


def _format_publish_time(value: Any) -> str:
    """Format Unix timestamp to readable local time."""
    try:
        if value is None:
            return "N/A"
        ts = int(value)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "N/A"


def _to_publish_ts(value: Any) -> int:
    """Normalize publish time into Unix timestamp for sorting."""
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        if isinstance(value, str):
            try:
                return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
            except ValueError:
                return 0
        return 0


def _deep_get(data: Dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _pick_first(*values: Any) -> Any:
    for val in values:
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        return val
    return None


def _read_map_value(data: Any, *keys: str) -> Any:
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return None


def _extract_news_item(entry: Dict[str, Any]) -> Dict[str, str] | None:
    """
    Yahoo news schema changes over time.
    This parser supports both flat and nested (content-based) payloads.
    """
    title = _pick_first(
        entry.get("title"),
        _deep_get(entry, "content", "title"),
    )
    publisher = _pick_first(
        entry.get("publisher"),
        _deep_get(entry, "content", "provider", "displayName"),
        _deep_get(entry, "content", "provider", "name"),
    )
    link = _pick_first(
        entry.get("link"),
        _deep_get(entry, "content", "canonicalUrl", "url"),
        _deep_get(entry, "content", "clickThroughUrl", "url"),
    )
    publish_raw = _pick_first(
        entry.get("providerPublishTime"),
        _deep_get(entry, "content", "pubDate"),
    )

    publish_ts = _to_publish_ts(publish_raw)

    if not title and not link:
        return None

    return {
        "title": str(title or "Untitled"),
        "publisher": str(publisher or "Unknown publisher"),
        "link": str(link or "#"),
        "published": _format_publish_time(publish_ts),
        "published_ts": publish_ts,
    }


def _ticker_news(symbol: str, limit: int = 10) -> List[Dict[str, str]]:
    """Fetch latest news for one symbol."""
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []
        items: List[Dict[str, str]] = []
        for entry in raw_news:
            if not isinstance(entry, dict):
                continue
            parsed = _extract_news_item(entry)
            if parsed is None:
                continue
            items.append(parsed)
        items.sort(key=lambda x: x.get("published_ts", 0), reverse=True)
        trimmed = items[:limit]
        for item in trimmed:
            item.pop("published_ts", None)
        return trimmed
    except Exception:
        return []


def _ticker_snapshot(symbol: str) -> Tuple[Dict[str, Any] | None, str | None]:
    """
    Return stock snapshot for one symbol.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info or {}

        last_price = _to_float(_read_map_value(info, "last_price", "lastPrice", "regularMarketPrice", "currentPrice"))
        previous_close = _to_float(_read_map_value(info, "previous_close", "previousClose", "regularMarketPreviousClose"))
        open_price = _to_float(_read_map_value(info, "open", "regularMarketOpen"))
        day_high = _to_float(_read_map_value(info, "day_high", "dayHigh", "regularMarketDayHigh"))
        day_low = _to_float(_read_map_value(info, "day_low", "dayLow", "regularMarketDayLow"))
        year_high = _to_float(_read_map_value(info, "year_high", "yearHigh", "fiftyTwoWeekHigh"))
        year_low = _to_float(_read_map_value(info, "year_low", "yearLow", "fiftyTwoWeekLow"))
        volume = _read_map_value(info, "last_volume", "lastVolume", "volume", "regularMarketVolume")
        market_cap = _read_map_value(info, "market_cap", "marketCap")
        currency = _read_map_value(info, "currency") or "N/A"
        exchange = _read_map_value(info, "exchange", "fullExchangeName") or "N/A"
        timezone = _read_map_value(info, "timezone", "exchangeTimezoneName") or "N/A"

        if last_price is None:
            info2 = ticker.info or {}
            last_price = _to_float(_read_map_value(info2, "regularMarketPrice", "currentPrice", "previousClose"))
            previous_close = _to_float(_pick_first(previous_close, _read_map_value(info2, "previousClose", "regularMarketPreviousClose")))
            open_price = _to_float(_pick_first(open_price, _read_map_value(info2, "open", "regularMarketOpen")))
            day_high = _to_float(_pick_first(day_high, _read_map_value(info2, "dayHigh", "regularMarketDayHigh")))
            day_low = _to_float(_pick_first(day_low, _read_map_value(info2, "dayLow", "regularMarketDayLow")))
            year_high = _to_float(_pick_first(year_high, _read_map_value(info2, "fiftyTwoWeekHigh")))
            year_low = _to_float(_pick_first(year_low, _read_map_value(info2, "fiftyTwoWeekLow")))
            volume = _pick_first(volume, _read_map_value(info2, "volume", "regularMarketVolume"))
            market_cap = _pick_first(market_cap, _read_map_value(info2, "marketCap"))
            currency = _pick_first(currency, _read_map_value(info2, "currency")) or currency
            exchange = _pick_first(exchange, _read_map_value(info2, "exchange", "fullExchangeName")) or exchange
            timezone = _pick_first(timezone, _read_map_value(info2, "exchangeTimezoneName", "timeZoneFullName")) or timezone

        if last_price is None:
            # Fallback using yf.download to avoid known PriceHistory edge-cases.
            history = yf.download(
                symbol,
                period="1mo",
                interval="1d",
                progress=False,
                auto_adjust=False,
                actions=False,
            )
            if not history.empty:
                cols = history.columns
                if hasattr(cols, "nlevels") and cols.nlevels > 1:
                    history.columns = cols.get_level_values(0)

                close_series = history["Close"] if "Close" in history else None
                open_series = history["Open"] if "Open" in history else None
                high_series = history["High"] if "High" in history else None
                low_series = history["Low"] if "Low" in history else None
                vol_series = history["Volume"] if "Volume" in history else None

                if close_series is not None and len(close_series) > 0:
                    last_price = _to_float(close_series.iloc[-1])
                    if len(close_series) > 1:
                        previous_close = _to_float(close_series.iloc[-2])
                if open_series is not None and len(open_series) > 0:
                    open_price = _to_float(open_series.iloc[-1])
                if high_series is not None and len(high_series) > 0:
                    day_high = _to_float(high_series.iloc[-1])
                if low_series is not None and len(low_series) > 0:
                    day_low = _to_float(low_series.iloc[-1])
                if vol_series is not None and len(vol_series) > 0:
                    volume = vol_series.iloc[-1]

        if last_price is None:
            return None, "No price data found."

        change = None
        change_pct = None
        if previous_close not in (None, 0):
            change = last_price - previous_close
            change_pct = (change / previous_close) * 100

        position_52w = None
        if year_high is not None and year_low is not None and year_high > year_low:
            position_52w = ((last_price - year_low) / (year_high - year_low)) * 100

        trend = "N/A"
        if change is not None:
            trend = "Bullish ▲" if change > 0 else ("Bearish ▼" if change < 0 else "Flat")

        news_items = _ticker_news(symbol, limit=10)

        row = {
            "symbol": symbol,
            "last_price": _fmt_price(last_price),
            "previous_close": _fmt_price(previous_close),
            "open": _fmt_price(open_price),
            "change": _fmt_price(change) if change is not None else "N/A",
            "change_pct": _fmt_pct(change_pct),
            "day_range": f"{_fmt_price(day_low)} - {_fmt_price(day_high)}",
            "year_range": f"{_fmt_price(year_low)} - {_fmt_price(year_high)}",
            "position_52w": _fmt_pct(position_52w),
            "volume": _fmt_int(volume),
            "market_cap": _fmt_int(market_cap),
            "currency": currency,
            "exchange": exchange,
            "timezone": timezone,
            "trend": trend,
            "news": news_items,
        }
        return row, None
    except Exception as exc:  # noqa: BLE001 - show a friendly error per symbol.
        return None, str(exc)


@app.route("/", methods=["GET", "POST"])
def index():
    raw_symbols = "AAPL,MSFT,TSLA,0700.HK"
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    if request.method == "POST":
        raw_symbols = request.form.get("symbols", "")
        symbols = _parse_symbols(raw_symbols)
        if not symbols:
            errors.append({"symbol": "-", "message": "Please provide at least one ticker symbol."})
        elif len(symbols) > 20:
            errors.append({"symbol": "-", "message": "Please query up to 20 symbols at one time."})
        else:
            for symbol in symbols:
                row, err = _ticker_snapshot(symbol)
                if err:
                    errors.append({"symbol": symbol, "message": err})
                else:
                    results.append(row)

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return render_template(
        "index.html",
        symbols_input=raw_symbols,
        results=results,
        errors=errors,
        updated_at=updated_at,
        price_delay_note="Market data from Yahoo Finance may be real-time or delayed (commonly about 15 minutes), depending on exchange/data rights.",
    )


if __name__ == "__main__":
    app.run(debug=True)
