"""Dated company-size metadata from the supplied NSE PR archive."""
import csv
from datetime import datetime
import io
import json
import math
from pathlib import Path
import zipfile

SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "nse-market-cap.json"


def parse_market_caps(archive: str | Path) -> dict:
    with zipfile.ZipFile(archive) as z:
        members = [n for n in z.namelist() if Path(n).name.lower().startswith("mcap") and n.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("Expected one NSE market-cap report")
        rows = csv.DictReader(io.StringIO(z.read(members[0]).decode("utf-8-sig")))
        values, dates = {}, set()
        for raw in rows:
            row = {key.strip(): (value or "").strip() for key, value in raw.items()}
            if not row.get("Symbol") or row.get("Series") not in {"EQ", "BE", "BZ", "SM", "ST", "SZ"}:
                continue
            dates.add(datetime.strptime(row["Trade Date"], "%d %b %Y").date().isoformat())
            cap = float(row["Market Cap(Rs.)"])
            if not math.isfinite(cap) or cap <= 0:
                continue
            symbol = row["Symbol"]
            if symbol in values and values[symbol] != cap:
                raise ValueError(f"Conflicting market caps for {symbol}")
            values[symbol] = cap
        if len(dates) != 1:
            raise ValueError("Market-cap report must contain one trading date")
        return dict(asOf=next(iter(dates)), source=f"NSE {Path(archive).name} / {members[0]}", values=values)


def attach_market_caps(result: dict) -> dict:
    # Enrich even cached results so a metadata import need not rescan candles.
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else {}
    current = snapshot.get("asOf") == result.get("asOf")
    values = snapshot.get("values", {}) if current else {}
    enriched = dict(result, marketCapAsOf=snapshot.get("asOf") if current else None,
                    marketCapSource=snapshot.get("source") if current else None)
    for side in ("bullish", "bearish"):
        enriched[side] = [dict(stock, marketCap=values.get(stock["symbol"]),
                              marketCapAsOf=snapshot.get("asOf") if current and stock["symbol"] in values else None)
                          for stock in result[side]]
    return enriched
