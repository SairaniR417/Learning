#!/usr/bin/env python3

"""
Traders Gita - NSE F&O Data Sync

WHAT THIS SCRIPT DOES
---------------------

1. Gets CURRENT NSE F&O tradable stocks.

2. Downloads 1-DAY historical CASH market data for those stocks:
      01-Jan-2020 -> yesterday

   Example:
      RELIANCE
      SBIN
      HDFCBANK
      etc.

   Data:
      Date
      Open
      High
      Low
      Close
      Volume
      Turnover
      Trades

3. For stocks selected using --option-stocks:

      RELIANCE
      SBIN
      etc.

   Downloads ONLY CURRENT / NEAREST EXPIRY:

      FUTURE
      CE
      PE

   Example:

      RELIANCE OCT FUT
      RELIANCE OCT 1400 CE
      RELIANCE OCT 1400 PE
      RELIANCE OCT 1420 CE
      RELIANCE OCT 1420 PE

   It DOES NOT download historical expired options.

4. Existing historical dates are skipped.
   Missing dates are downloaded automatically.

RUN:

python sync_fno_data.py --option-stocks RELIANCE,SBIN

"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import time
import zipfile

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests


# ============================================================
# CONFIGURATION
# ============================================================

UPSTOX_NSE_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
)

NSE_ARCHIVE = "https://nsearchives.nseindia.com"

# NSE changed Bhavcopy format from this date
UDIFF_START = date(2024, 7, 8)

# Default history
DEFAULT_HISTORY_START = date(2020, 1, 1)


# ============================================================
# FOLDERS
# ============================================================

DATA_DIR = Path("data")

UNIVERSE_DIR = DATA_DIR / "fno"

HISTORY_DIR = DATA_DIR / "fno_history"

DERIVATIVES_DIR = DATA_DIR / "current_derivatives"

STATUS_FILE = HISTORY_DIR / "_download_status.json"


# ============================================================
# REQUEST SESSION
# ============================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/155.0 Safari/537.36"
    ),

    "Accept": "*/*",

    "Referer": "https://www.nseindia.com/",
}


SESSION = requests.Session()

SESSION.headers.update(HEADERS)


# ============================================================
# CREATE FOLDERS
# ============================================================

def ensure_dirs():

    for folder in [

        UNIVERSE_DIR,
        HISTORY_DIR,
        DERIVATIVES_DIR,

    ]:

        folder.mkdir(
            parents=True,
            exist_ok=True,
        )


# ============================================================
# UPSTOX INSTRUMENT MASTER
# ============================================================

def decode_json_gz(content):

    if content[:2] == b"\x1f\x8b":

        content = gzip.decompress(content)

    return json.loads(
        content.decode("utf-8")
    )


def download_upstox_instruments():

    print()

    print(
        "Downloading Upstox NSE instrument master..."
    )

    response = SESSION.get(

        UPSTOX_NSE_INSTRUMENTS_URL,

        timeout=60,
    )

    response.raise_for_status()

    instruments = decode_json_gz(
        response.content
    )

    if not isinstance(instruments, list):

        raise RuntimeError(
            "Unexpected Upstox instrument format."
        )

    print(
        f"Instrument records received: "
        f"{len(instruments):,}"
    )

    return instruments


# ============================================================
# EXPIRY PARSER
# ============================================================

def parse_expiry(value):

    if value in (
        None,
        "",
        0,
    ):

        return None


    # Epoch timestamp
    if isinstance(
        value,
        (int, float),
    ):

        seconds = float(value)

        if seconds > 10_000_000_000:

            seconds /= 1000

        return datetime.fromtimestamp(

            seconds,

            tz=timezone.utc,

        ).date()


    text = str(value).strip()


    formats = [

        "%Y-%m-%d",

        "%d-%m-%Y",

        "%d-%b-%Y",

    ]


    for fmt in formats:

        try:

            return datetime.strptime(

                text,

                fmt,

            ).date()

        except ValueError:

            pass


    return None


# ============================================================
# BUILD CURRENT F&O STOCK UNIVERSE
# ============================================================

def build_current_fno_universe(
    instruments,
):

    stocks = {}


    for item in instruments:


        if item.get("segment") != "NSE_FO":

            continue


        if (
            str(
                item.get(
                    "underlying_type",
                    "",
                )
            ).upper()
            != "EQUITY"
        ):

            continue


        if item.get("instrument_type") not in {

            "FUT",
            "CE",
            "PE",

        }:

            continue


        symbol = str(

            item.get(
                "underlying_symbol",
                "",
            )

        ).strip().upper()


        if not symbol:

            continue


        stocks[symbol] = {

            "symbol":
                symbol,

            "underlying_key":
                item.get(
                    "underlying_key"
                ),

            "name":
                item.get(
                    "name"
                ),

        }


    if not stocks:

        raise RuntimeError(
            "No NSE F&O stocks found."
        )


    df = pd.DataFrame(
        stocks.values()
    )


    df = df.sort_values(
        "symbol"
    ).reset_index(
        drop=True
    )


    output = (

        UNIVERSE_DIR
        / "current_fno_stocks.csv"

    )


    df.to_csv(

        output,

        index=False,

    )


    print()

    print(
        f"Current F&O stocks: "
        f"{len(df):,}"
    )

    print(
        f"Saved: {output}"
    )


    return df


# ============================================================
# CURRENT FUTURES + OPTIONS
# ============================================================

def build_current_derivatives(

    instruments,

    selected_symbols,

    today,

):


    future_rows = []

    option_rows = []

    combined_rows = []


    if not selected_symbols:

        print(
            "No option stocks selected."
        )

        return


    # --------------------------------------------------------
    # Gather all active contracts
    # --------------------------------------------------------

    contracts_by_stock = {

        symbol: []

        for symbol
        in selected_symbols

    }


    for item in instruments:


        if item.get(
            "segment"
        ) != "NSE_FO":

            continue


        if (
            str(
                item.get(
                    "underlying_type",
                    "",
                )
            ).upper()
            != "EQUITY"
        ):

            continue


        instrument_type = item.get(
            "instrument_type"
        )


        if instrument_type not in {

            "FUT",
            "CE",
            "PE",

        }:

            continue


        symbol = str(

            item.get(
                "underlying_symbol",
                "",
            )

        ).strip().upper()


        if symbol not in selected_symbols:

            continue


        expiry = parse_expiry(

            item.get(
                "expiry"
            )

        )


        if expiry is None:

            continue


        # Ignore expired contracts
        if expiry < today:

            continue


        contracts_by_stock[
            symbol
        ].append(

            (
                expiry,
                item,
            )

        )


    # --------------------------------------------------------
    # Find nearest expiry
    # --------------------------------------------------------

    for symbol in sorted(
        selected_symbols
    ):


        contracts = contracts_by_stock.get(

            symbol,

            [],

        )


        if not contracts:

            print(
                f"WARNING: "
                f"No active contracts "
                f"found for {symbol}"
            )

            continue


        current_expiry = min(

            expiry

            for expiry, _
            in contracts

        )


        print()

        print(
            f"{symbol}"
        )

        print(
            f"Current expiry: "
            f"{current_expiry}"
        )


        current_contracts = [

            item

            for expiry, item
            in contracts

            if expiry
            == current_expiry

        ]


        future_count = 0

        option_count = 0


        for item in current_contracts:


            instrument_type = item.get(
                "instrument_type"
            )


            # =================================================
            # CURRENT FUTURE
            # =================================================

            if instrument_type == "FUT":


                future_rows.append({

                    "underlying_symbol":
                        symbol,

                    "expiry":
                        current_expiry.isoformat(),

                    "instrument_key":
                        item.get(
                            "instrument_key"
                        ),

                    "underlying_key":
                        item.get(
                            "underlying_key"
                        ),

                    "trading_symbol":
                        item.get(
                            "trading_symbol"
                        ),

                    "lot_size":
                        item.get(
                            "lot_size"
                        ),

                    "tick_size":
                        item.get(
                            "tick_size"
                        ),

                })


                combined_rows.append({

                    "underlying_symbol":
                        symbol,

                    "expiry":
                        current_expiry.isoformat(),

                    "contract_type":
                        "FUT",

                    "strike_price":
                        None,

                    "option_type":
                        None,

                    "instrument_key":
                        item.get(
                            "instrument_key"
                        ),

                    "underlying_key":
                        item.get(
                            "underlying_key"
                        ),

                    "trading_symbol":
                        item.get(
                            "trading_symbol"
                        ),

                    "lot_size":
                        item.get(
                            "lot_size"
                        ),

                })


                future_count += 1


            # =================================================
            # CURRENT OPTIONS
            # =================================================

            elif instrument_type in {

                "CE",
                "PE",

            }:


                option_rows.append({

                    "underlying_symbol":
                        symbol,

                    "expiry":
                        current_expiry.isoformat(),

                    "strike_price":
                        item.get(
                            "strike_price"
                        ),

                    "option_type":
                        instrument_type,

                    "instrument_key":
                        item.get(
                            "instrument_key"
                        ),

                    "underlying_key":
                        item.get(
                            "underlying_key"
                        ),

                    "trading_symbol":
                        item.get(
                            "trading_symbol"
                        ),

                    "lot_size":
                        item.get(
                            "lot_size"
                        ),

                    "tick_size":
                        item.get(
                            "tick_size"
                        ),

                    "weekly":
                        item.get(
                            "weekly"
                        ),

                })


                combined_rows.append({

                    "underlying_symbol":
                        symbol,

                    "expiry":
                        current_expiry.isoformat(),

                    "contract_type":
                        "OPTION",

                    "strike_price":
                        item.get(
                            "strike_price"
                        ),

                    "option_type":
                        instrument_type,

                    "instrument_key":
                        item.get(
                            "instrument_key"
                        ),

                    "underlying_key":
                        item.get(
                            "underlying_key"
                        ),

                    "trading_symbol":
                        item.get(
                            "trading_symbol"
                        ),

                    "lot_size":
                        item.get(
                            "lot_size"
                        ),

                })


                option_count += 1


        print(
            f"Futures: {future_count}"
        )

        print(
            f"CE/PE contracts: "
            f"{option_count}"
        )


    # ========================================================
    # SAVE FUTURES
    # ========================================================

    futures_df = pd.DataFrame(
        future_rows
    )


    if not futures_df.empty:

        futures_df = futures_df.sort_values(

            [
                "underlying_symbol",
                "expiry",
            ]

        )


    future_output = (

        DERIVATIVES_DIR
        / "current_futures.csv"

    )


    futures_df.to_csv(

        future_output,

        index=False,

    )


    # ========================================================
    # SAVE OPTIONS
    # ========================================================

    options_df = pd.DataFrame(
        option_rows
    )


    if not options_df.empty:

        options_df = options_df.sort_values(

            [

                "underlying_symbol",

                "expiry",

                "strike_price",

                "option_type",

            ]

        )


    option_output = (

        DERIVATIVES_DIR
        / "current_options.csv"

    )


    options_df.to_csv(

        option_output,

        index=False,

    )


    # ========================================================
    # COMBINED
    # ========================================================

    combined_df = pd.DataFrame(
        combined_rows
    )


    combined_output = (

        DERIVATIVES_DIR
        / "current_fno_contracts.csv"

    )


    combined_df.to_csv(

        combined_output,

        index=False,

    )


    print()

    print(
        f"Current futures saved: "
        f"{len(futures_df):,}"
    )

    print(
        f"Current options saved: "
        f"{len(options_df):,}"
    )

    print(
        f"Saved: {DERIVATIVES_DIR}"
    )


# ============================================================
# NSE BHAVCOPY URL
# ============================================================

def bhavcopy_url(day):


    # New UDiFF format
    if day >= UDIFF_START:


        filename = (

            "BhavCopy_NSE_CM_0_0_0_"

            f"{day:%Y%m%d}"

            "_F_0000.csv.zip"

        )


        return (

            f"{NSE_ARCHIVE}/content/cm/"

            f"{filename}"

        )


    # Legacy Bhavcopy
    month = day.strftime(
        "%b"
    ).upper()


    filename = (

        f"cm"

        f"{day:%d}"

        f"{month}"

        f"{day:%Y}"

        f"bhav.csv.zip"

    )


    return (

        f"{NSE_ARCHIVE}"

        f"/content/historical/EQUITIES"

        f"/{day:%Y}"

        f"/{month}"

        f"/{filename}"

    )


# ============================================================
# HTTP RETRY
# ============================================================

def request_with_retry(

    url,

    attempts=5,

):


    for attempt in range(
        attempts
    ):


        try:


            response = SESSION.get(

                url,

                timeout=60,

            )


            if response.status_code == 404:

                return None


            if response.status_code in {

                403,
                429,
                500,
                502,
                503,
                504,

            }:


                delay = min(

                    30,

                    2 ** (
                        attempt + 1
                    ),

                )


                print(

                    f"HTTP "
                    f"{response.status_code} "

                    f"retrying in "
                    f"{delay}s"

                )


                time.sleep(
                    delay
                )


                continue


            response.raise_for_status()


            return response


        except requests.RequestException as exc:


            if attempt == attempts - 1:

                raise


            delay = min(

                30,

                2 ** (
                    attempt + 1
                ),

            )


            print(

                f"Request error: "
                f"{exc}"

            )


            time.sleep(
                delay
            )


    return None


# ============================================================
# READ ZIP CSV
# ============================================================

def read_zip_csv(content):


    with zipfile.ZipFile(

        io.BytesIO(
            content
        )

    ) as archive:


        csv_files = [

            name

            for name
            in archive.namelist()

            if name.lower().endswith(
                ".csv"
            )

        ]


        if not csv_files:

            raise RuntimeError(

                "No CSV found "
                "inside Bhavcopy ZIP"

            )


        with archive.open(
            csv_files[0]
        ) as file:


            return pd.read_csv(

                file,

                low_memory=False,

            )


# ============================================================
# COLUMN HELPER
# ============================================================

def get_column(
    df,
    *names,
):


    lookup = {

        str(column)
        .strip()
        .upper():

        column

        for column
        in df.columns

    }


    for name in names:


        actual = lookup.get(
            name.upper()
        )


        if actual is not None:

            return df[
                actual
            ]


    return pd.Series(

        [None] * len(df),

        index=df.index,

    )


# ============================================================
# FILTER CURRENT F&O STOCKS
# ============================================================

def standardize_and_filter(

    raw,

    day,

    allowed_symbols,

):


    symbol = (

        get_column(

            raw,

            "TckrSymb",

            "SYMBOL",

        )

        .astype(str)

        .str.strip()

        .str.upper()

    )


    series = (

        get_column(

            raw,

            "SctySrs",

            "SERIES",

        )

        .astype(str)

        .str.strip()

        .str.upper()

    )


    mask = symbol.isin(
        allowed_symbols
    )


    # Keep normal equity series
    if series.eq(
        "EQ"
    ).any():

        mask &= series.eq(
            "EQ"
        )


    selected = raw.loc[
        mask
    ].copy()


    columns = [

        "trade_date",

        "symbol",

        "series",

        "open",

        "high",

        "low",

        "close",

        "previous_close",

        "last_price",

        "volume",

        "turnover",

        "trades",

        "isin",

    ]


    if selected.empty:

        return pd.DataFrame(
            columns=columns
        )


    out = pd.DataFrame(
        index=selected.index
    )


    out[
        "trade_date"
    ] = day.isoformat()


    out[
        "symbol"
    ] = (

        get_column(

            selected,

            "TckrSymb",

            "SYMBOL",

        )

        .astype(str)

        .str.strip()

        .str.upper()

    )


    out[
        "series"
    ] = (

        get_column(

            selected,

            "SctySrs",

            "SERIES",

        )

        .astype(str)

        .str.strip()

        .str.upper()

    )


    out["open"] = pd.to_numeric(

        get_column(

            selected,

            "OpnPric",

            "OPEN",

        ),

        errors="coerce",

    )


    out["high"] = pd.to_numeric(

        get_column(

            selected,

            "HghPric",

            "HIGH",

        ),

        errors="coerce",

    )


    out["low"] = pd.to_numeric(

        get_column(

            selected,

            "LwPric",

            "LOW",

        ),

        errors="coerce",

    )


    out["close"] = pd.to_numeric(

        get_column(

            selected,

            "ClsPric",

            "CLOSE",

        ),

        errors="coerce",

    )


    out[
        "previous_close"
    ] = pd.to_numeric(

        get_column(

            selected,

            "PrvsClsgPric",

            "PREVCLOSE",

        ),

        errors="coerce",

    )


    out[
        "last_price"
    ] = pd.to_numeric(

        get_column(

            selected,

            "LastPric",

            "LAST",

        ),

        errors="coerce",

    )


    out[
        "volume"
    ] = pd.to_numeric(

        get_column(

            selected,

            "TtlTradgVol",

            "TOTTRDQTY",

        ),

        errors="coerce",

    )


    out[
        "turnover"
    ] = pd.to_numeric(

        get_column(

            selected,

            "TtlTrfVal",

            "TOTTRDVAL",

        ),

        errors="coerce",

    )


    out[
        "trades"
    ] = pd.to_numeric(

        get_column(

            selected,

            "TtlNbOfTxsExctd",

            "TOTALTRADES",

        ),

        errors="coerce",

    )


    out[
        "isin"
    ] = get_column(

        selected,

        "ISIN",

    ).astype(str)


    return out[
        columns
    ].reset_index(
        drop=True
    )


# ============================================================
# STATUS FILE
# ============================================================

def load_status():


    if not STATUS_FILE.exists():

        return {}


    try:

        return json.loads(

            STATUS_FILE.read_text(
                encoding="utf-8"
            )

        )

    except Exception:

        return {}


def save_status(
    status
):


    STATUS_FILE.write_text(

        json.dumps(

            status,

            indent=2,

            sort_keys=True,

        ),

        encoding="utf-8",

    )


# ============================================================
# MONTH ITERATOR
# ============================================================

def month_dates(

    start,

    end,

):


    cursor = date(

        start.year,

        start.month,

        1,

    )


    while cursor <= end:


        if cursor.month == 12:

            next_month = date(

                cursor.year + 1,

                1,

                1,

            )

        else:

            next_month = date(

                cursor.year,

                cursor.month + 1,

                1,

            )


        month_start = max(

            start,

            cursor,

        )


        month_end = min(

            end,

            next_month
            - timedelta(
                days=1
            ),

        )


        yield (

            month_start,

            month_end,

        )


        cursor = next_month


# ============================================================
# DOWNLOAD MONTH
# ============================================================

def download_month(

    start,

    end,

    allowed_symbols,

    delay,

    force,

    status,

):


    filename = (

        f"{start:%Y-%m}.csv"

    )


    output = (

        HISTORY_DIR
        / filename

    )


    # --------------------------------------------------------
    # Existing monthly data
    # --------------------------------------------------------

    if output.exists():

        existing = pd.read_csv(

            output,

            low_memory=False,

        )

    else:

        existing = pd.DataFrame()


    existing_dates = set()


    if (

        not existing.empty

        and

        "trade_date"
        in existing.columns

    ):


        existing_dates = set(

            existing[
                "trade_date"
            ].astype(str)

        )


    new_frames = []


    cursor = start


    while cursor <= end:


        # Weekend
        if cursor.weekday() >= 5:

            cursor += timedelta(
                days=1
            )

            continue


        date_key = cursor.isoformat()


        # Skip already downloaded dates
        if not force:


            if date_key in existing_dates:

                cursor += timedelta(
                    days=1
                )

                continue


            if status.get(
                date_key
            ) == "no_file":

                cursor += timedelta(
                    days=1
                )

                continue


        print(
            f"{cursor}: downloading..."
        )


        url = bhavcopy_url(
            cursor
        )


        response = request_with_retry(
            url
        )


        if response is None:


            print(
                f"{cursor}: "
                "holiday / no Bhavcopy"
            )


            status[
                date_key
            ] = "no_file"


            save_status(
                status
            )


            cursor += timedelta(
                days=1
            )


            continue


        raw = read_zip_csv(
            response.content
        )


        filtered = standardize_and_filter(

            raw,

            cursor,

            allowed_symbols,

        )


        if not filtered.empty:


            new_frames.append(
                filtered
            )


            status[
                date_key
            ] = "ok"


            print(

                f"{cursor}: "
                f"{len(filtered):,} "
                "F&O stock rows"

            )

        else:


            status[
                date_key
            ] = "empty"


            print(

                f"{cursor}: "
                "no matching stocks"

            )


        save_status(
            status
        )


        time.sleep(
            delay
        )


        cursor += timedelta(
            days=1
        )


    # --------------------------------------------------------
    # Combine existing + new
    # --------------------------------------------------------

    frames = []


    if (

        not existing.empty

        and

        not force

    ):

        frames.append(
            existing
        )


    frames.extend(
        new_frames
    )


    if not frames:

        return


    month_df = pd.concat(

        frames,

        ignore_index=True,

    )


    month_df[
        "symbol"
    ] = (

        month_df[
            "symbol"
        ]

        .astype(str)

        .str.upper()

        .str.strip()

    )


    month_df = month_df[

        month_df[
            "symbol"
        ].isin(
            allowed_symbols
        )

    ]


    month_df = (

        month_df

        .drop_duplicates(

            subset=[

                "trade_date",

                "symbol",

                "series",

            ],

            keep="last",

        )

        .sort_values(

            [

                "trade_date",

                "symbol",

            ]

        )

        .reset_index(
            drop=True
        )

    )


    month_df.to_csv(

        output,

        index=False,

    )


    print(

        f"Saved {len(month_df):,} rows "

        f"-> {output}"

    )


# ============================================================
# COMBINE HISTORY
# ============================================================

def combine_history(

    start,

    end,

    allowed_symbols,

):


    files = sorted(

        HISTORY_DIR.glob(
            "????-??.csv"
        )

    )


    if not files:

        print(
            "No historical files found."
        )

        return


    frames = []


    for file in files:


        df = pd.read_csv(

            file,

            low_memory=False,

        )


        if df.empty:

            continue


        df[
            "trade_date"
        ] = pd.to_datetime(

            df[
                "trade_date"
            ],

            errors="coerce",

        )


        df[
            "symbol"
        ] = (

            df[
                "symbol"
            ]

            .astype(str)

            .str.strip()

            .str.upper()

        )


        mask = (

            (
                df[
                    "trade_date"
                ].dt.date
                >= start
            )

            &

            (
                df[
                    "trade_date"
                ].dt.date
                <= end
            )

            &

            (
                df[
                    "symbol"
                ].isin(
                    allowed_symbols
                )
            )

        )


        filtered = df.loc[
            mask
        ].copy()


        if not filtered.empty:

            frames.append(
                filtered
            )


    if not frames:

        print(
            "No historical rows found."
        )

        return


    combined = pd.concat(

        frames,

        ignore_index=True,

    )


    combined = (

        combined

        .drop_duplicates(

            subset=[

                "trade_date",

                "symbol",

                "series",

            ],

            keep="last",

        )

        .sort_values(

            [

                "symbol",

                "trade_date",

            ]

        )

        .reset_index(
            drop=True
        )

    )


    combined[
        "trade_date"
    ] = (

        combined[
            "trade_date"
        ]

        .dt.date

        .astype(str)

    )


    output = (

        UNIVERSE_DIR
        / "fno_stock_daily_1d.csv"

    )


    combined.to_csv(

        output,

        index=False,

    )


    print()

    print(
        f"Combined history rows: "
        f"{len(combined):,}"
    )

    print(
        f"Saved: {output}"
    )


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():


    yesterday = (

        date.today()

        - timedelta(
            days=1
        )

    )


    parser = argparse.ArgumentParser(

        description=(

            "Traders Gita NSE "
            "F&O data downloader"

        )

    )


    parser.add_argument(

        "--start",

        default="2020-01-01",

        help=(

            "Historical start date. "
            "Default: 2020-01-01"

        ),

    )


    parser.add_argument(

        "--end",

        default=yesterday.isoformat(),

        help=(

            "Historical end date. "
            "Default: yesterday"

        ),

    )


    parser.add_argument(

        "--option-stocks",

        default="",

        help=(

            "Stocks for current FUT + "
            "CE/PE. "

            "Example: "
            "RELIANCE,SBIN"

        ),

    )


    parser.add_argument(

        "--delay",

        type=float,

        default=1.25,

        help=(

            "Delay between downloads."

        ),

    )


    parser.add_argument(

        "--force",

        action="store_true",

        help=(

            "Force re-download."

        ),

    )


    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():


    args = parse_args()


    ensure_dirs()


    today = date.today()


    yesterday = (

        today

        - timedelta(
            days=1
        )

    )


    start = date.fromisoformat(
        args.start
    )


    end = date.fromisoformat(
        args.end
    )


    # Do not download today's incomplete daily candle
    if end > yesterday:


        print(

            f"End date changed "

            f"from {end} "

            f"to yesterday "

            f"{yesterday}"

        )


        end = yesterday


    if start > end:

        raise SystemExit(

            "Start date cannot be "
            "after end date."

        )


    selected_stocks = {

        stock.strip().upper()

        for stock
        in args.option_stocks.split(",")

        if stock.strip()

    }


    print()

    print(
        "=" * 75
    )

    print(
        "TRADERS GITA - NSE F&O DATA SYNC"
    )

    print(
        "=" * 75
    )

    print(
        f"Underlying timeframe : 1 DAY"
    )

    print(
        f"Historical start     : {start}"
    )

    print(
        f"Historical end       : {end}"
    )

    print(
        "Current F&O stocks   : "
        + (

            ", ".join(
                sorted(
                    selected_stocks
                )
            )

            if selected_stocks

            else "(none)"

        )
    )

    print(
        "F&O contracts        : "
        "NEAREST LIVE EXPIRY ONLY"
    )

    print(
        "=" * 75
    )


    # ========================================================
    # LOAD INSTRUMENTS
    # ========================================================

    instruments = (
        download_upstox_instruments()
    )


    # ========================================================
    # CURRENT F&O UNIVERSE
    # ========================================================

    universe_df = (
        build_current_fno_universe(
            instruments
        )
    )


    universe = set(

        universe_df[
            "symbol"
        ]

        .astype(str)

        .str.strip()

        .str.upper()

    )


    # ========================================================
    # VALIDATE SELECTED STOCKS
    # ========================================================

    invalid = (

        selected_stocks

        - universe

    )


    if invalid:


        print()

        print(

            "WARNING: "

            "Not currently in NSE F&O: "

            + ", ".join(

                sorted(
                    invalid
                )

            )

        )


    valid_selected = (

        selected_stocks

        & universe

    )


    # ========================================================
    # CURRENT FUT + OPTIONS
    # ========================================================

    build_current_derivatives(

        instruments,

        valid_selected,

        today,

    )


    # ========================================================
    # HISTORICAL 1D DATA
    # ========================================================

    print()

    print(
        "=" * 75
    )

    print(
        "DOWNLOADING 1-DAY UNDERLYING HISTORY"
    )

    print(
        "=" * 75
    )


    status = load_status()


    for (

        month_start,

        month_end,

    ) in month_dates(

        start,

        end,

    ):


        print()

        print(
            f"Processing "
            f"{month_start:%Y-%m}"
        )


        download_month(

            month_start,

            month_end,

            universe,

            max(
                0.5,
                args.delay,
            ),

            args.force,

            status,

        )


    # ========================================================
    # COMBINE HISTORY
    # ========================================================

    combine_history(

        start,

        end,

        universe,

    )


    # ========================================================
    # DONE
    # ========================================================

    print()

    print(
        "=" * 75
    )

    print(
        "DONE"
    )

    print(
        "=" * 75
    )


    print(

        "F&O Stock List:"

    )

    print(

        UNIVERSE_DIR
        / "current_fno_stocks.csv"

    )


    print()

    print(

        "1-Day Historical Stock Data:"

    )

    print(

        UNIVERSE_DIR
        / "fno_stock_daily_1d.csv"

    )


    print()

    print(

        "Current Futures:"

    )

    print(

        DERIVATIVES_DIR
        / "current_futures.csv"

    )


    print()

    print(

        "Current CE/PE Options:"

    )

    print(

        DERIVATIVES_DIR
        / "current_options.csv"

    )


    print()

    print(

        "Combined Current F&O:"

    )

    print(

        DERIVATIVES_DIR
        / "current_fno_contracts.csv"

    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()