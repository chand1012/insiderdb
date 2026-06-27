from __future__ import annotations

PLACEHOLDER_TICKERS = frozenset({"", "NONE", "N/A", "NA", "NULL", "-", "--"})


def normalize_ticker_symbol(value: str | None) -> str | None:
    if value is None:
        return None
    ticker = value.strip().upper()
    if ticker in PLACEHOLDER_TICKERS:
        return None
    return ticker
