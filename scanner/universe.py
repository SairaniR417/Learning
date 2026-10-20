"""The saved F&O underlying list is the application's only stock universe."""
import csv
import hashlib
from pathlib import Path
from fastapi import HTTPException

STOCK_LIST = Path(__file__).resolve().parents[1] / "data" / "fno" / "current_fno_stocks.csv"


def get_fno_stocks() -> list[dict]:
    try:
        with STOCK_LIST.open(encoding="utf-8-sig", newline="") as source:
            stocks = [{"key": row["underlying_key"], "symbol": row["symbol"],
                       "name": row["name"], "exchange": "NSE", "segment": "NSE_EQ",
                       "isin": row["underlying_key"].split("|", 1)[1], "instrument_type": "EQ"}
                      for row in csv.DictReader(source)]
        if not stocks or len({s["key"] for s in stocks}) != len(stocks) or any(
            not s["key"].startswith("NSE_EQ|") or not s["symbol"] for s in stocks):
            raise ValueError("Invalid saved universe")
        return sorted(stocks, key=lambda s: s["symbol"])
    except (OSError, KeyError, IndexError, ValueError, csv.Error) as exc:
        raise HTTPException(503, "The saved F&O stock list is unavailable or invalid.") from exc


def fno_keys() -> set[str]:
    return {s["key"] for s in get_fno_stocks()}


def fno_symbols() -> set[str]:
    return {s["symbol"] for s in get_fno_stocks()}


def universe_version() -> str:
    return hashlib.sha256("\n".join(sorted(fno_keys())).encode()).hexdigest()[:16]


def require_fno_key(key: str) -> None:
    if key not in fno_keys():
        raise HTTPException(400, "Select a stock from the saved F&O list.")


async def get_nse_equity_universe() -> list[dict]:
    return get_fno_stocks()
