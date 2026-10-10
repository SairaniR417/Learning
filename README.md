# Market Desk

A personal market dashboard built with Angular and FastAPI. Upstox supplies live LTP quotes and historical NSE candles. API secrets and access tokens stay on the Python server.

## Requirements

- Python 3.10 or newer
- Node.js 20.19 or newer
- An approved Upstox account and developer app with its redirect URI set to `http://localhost:4200/oauth/callback`

## Run locally

1. Copy `.env.example` to `.env` and fill in `UPSTOX_ACCESS_TOKEN` with your daily Upstox access token, plus `OPENAI_API_KEY` for general DRISHTI chat. For OAuth sign-in instead, set `UPSTOX_CLIENT_ID` and `UPSTOX_CLIENT_SECRET`. Register `http://localhost:4200/oauth/callback` as the redirect URL in that app. The OpenAI key stays on the FastAPI server. `DRISHTI_OPENAI_MODEL` can override the configured default model.
2. In a terminal, install and run the API:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   uvicorn main:app --reload --port 8000
   ```

3. In a second terminal, install and run Angular:

   ```powershell
   cd frontend
   npm install
   npm start
   ```

4. Open `http://localhost:4200` and connect Upstox to load Nifty 50 by default, then search for other instruments and intervals.

Upstox V3 historical data provides minute/hour candles from January 2022 and daily/weekly/monthly candles from January 2000, subject to interval-specific maximum query ranges. Charts currently fetch history from Upstox directly. Strategy scans can reuse candles stored in the local database. Upstox access tokens stay on the API server and expire daily. A token in `.env` is loaded at API startup; replace it when it expires. A public deployment needs HTTPS, per-user sessions, and deployment-specific redirect URI configuration; this starter is for a single local user.

## Instrument analysis

Choose a cash equity or MCX futures market, search an instrument after connecting Upstox, and its history opens in a focused full-screen chart. The chart starts with EMA 9, 20, 50, and 200 overlays. The status panel checks `close > EMA 9 > EMA 20 > EMA 50 > EMA 200`, marks a newly aligned bullish entry, and reports bearish, mixed, or insufficient-history states. Use at least 200 candles for a complete EMA 200 setup. The default instrument is Nifty 50, loaded from Upstox after connection.

Use the NSE scanner's **Scan NSE equities** button to scan the full NSE cash-equity universe for the latest candle close above EMA 9, EMA 20, SMA 50, and SMA 200. The scan displays matching symbols, each moving-average value, the close, and when the condition first appeared in the selected history. This scanner rule does not require the averages to be in bullish order.

DRISHTI chat answers general questions through OpenAI's Responses API and can search the web for current information. Asking to analyze the selected instrument continues to use the deterministic EMA endpoint.


python -m venv .venv
.\.venv\Scripts\Activate.ps1

uvicorn main:app --reload --port 8000 

.venv/Scripts/uvicorn main:app --reload --port 8000



## Incremental candle storage

Restart the API after upgrading to create the candle revision table. SQLite stores
candles in `data/market_desk.db`, keyed by instrument, timeframe, and timestamp.
Repeated imports skip identical values; corrected OHLCV values replace the old row.
Changed data advances a timeframe revision so future scans cannot reuse old results.

After connecting Upstox, open `http://localhost:8000/docs`:

1. Call `POST /api/sync/universe` to load the NSE equity master.
2. Call `POST /api/sync/candles` with
   `{"unit":"minutes","interval":1,"lookback_days":30,"concurrency":5}`.
   For hourly or daily candles, use `hours` or `days` with interval `1`.
3. Repeat the sync request when new candles are available. Existing instruments
   resume from their latest stored date with a two-day correction overlap.
4. Call `POST /api/strategies/scan` with
   `{"strategy_id":"ema_sma_alignment","timeframe":"1m"}` to use stored data.

Backfills use bounded date windows; today's minute/hour candles use the intraday
endpoint. Open intraday candles are excluded using their duration plus a five-second
buffer. Daily candles are imported on the following Indian calendar date. No exchange
calendar or session-close finalization is implemented yet.

Storage keeps one OHLCV row per candle and does not duplicate it per user or strategy.
Scans load only the latest bounded window per instrument, with ten times the largest
configured period/minimum history for indicator warm-up. EMA/RSI values may differ
slightly from calculations seeded at the beginning of all stored history. SQL still
ranks stored history; this bounds application memory, not total database work.

Current limits: sync is manually triggered and runs in the API process; there is no
recurring scheduler, durable queue, distributed lock, automatic retry, or job-status
endpoint. Failed chunks resume on a later sync, but older gaps/corrections outside
the overlap require a separate reconciliation. Increasing lookback does not backfill
older history for an already populated instrument. Each requested timeframe is stored
independently; aggregation and archival retention are not implemented. No existing
candles are automatically deleted. The universe sync currently covers NSE equities.
Historical charts still use the provider directly. This is not a 1,000-user deployment.

For production, move to PostgreSQL, durable ingestion workers and rate limiting,
then add time partitions and an explicit archive/retention policy after measuring
actual data growth. Keep long-term daily bars and archive older minute bars according
to backtesting needs. Do not discard minute history before defining that requirement.

Provider references: [historical limits](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
and [intraday candles](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/).

## PostgreSQL historical storage

The API can store Upstox OHLCV history in the PostgreSQL `traders_gita` database. The SQLAlchemy mappings use the existing `instruments`, `candles`, `ingestion_jobs`, and `data_coverage` tables. On startup, the API also creates its scan cache and candle revision support tables when missing.

1. Install the PostgreSQL driver after installing the Python requirements: `python -m pip install -r requirements.txt`.
2. Add a connection string to the project `.env` (edit the example; do not commit your password):

   ```dotenv
   DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/traders_gita
   ```

3. Restart the API and connect Upstox. In `http://localhost:8000/docs`, call `POST /api/sync/universe` once to save the NSE equity instrument master.
4. Call `POST /api/sync/candles` with `{"unit":"days","interval":1,"lookback_days":10000,"concurrency":5}` to backfill available daily history from January 2000 for active NSE equities. The response includes a `job_id`; poll `GET /api/sync/jobs/{job_id}` for `pending`, `running`, `complete`, `partial`, or `failed` status.
5. Check stored ranges with `SELECT i.symbol, c.timeframe, c.earliest_candle, c.latest_candle FROM data_coverage c JOIN instruments i ON i.id=c.instrument_id ORDER BY i.symbol;` in psql.

A full-universe backfill makes many provider requests and can take a long time. The API uses bounded concurrency; provider throttling or per-symbol errors can leave a job `partial`. Repeat the sync to retry from recent stored candles. Daily bars are the recommended first backfill; minute data uses a much shorter provider history window and creates substantially more data. Upstox authorization, data availability, and provider rate limits apply. Background jobs currently run inside the API process and are not durable across a server restart.


