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



## Stock Details

Click a scanner result row or its company button in any strategy to open the Stock Details tab. Returning to Market Scanner preserves the scan and filters. The tab displays the selected strategy signal and checks, latest available broker quote, interactive daily candlesticks and volume with selectable ranges, daily moving averages, paginated OHLCV, Upstox company profile and corporate actions, and dated news links from Google News RSS.

History uses all locally stored `1d` candles, with explicit earliest/latest coverage dates. Refresh reloads available data; it does not initiate a universe backfill. Import/sync daily candles to extend the range. The database does not record the original instrument-added date, and the first candle must not be interpreted as that date or an IPO date. Prices are displayed as stored without additional corporate-action adjustments. Profile and quote retrieval require a valid Upstox connection and applicable fundamentals access. News is cached for 15 minutes and represents matching recent articles, not an exhaustive archive. Individual source failures are displayed without blocking other sections.

Endpoints: `GET /api/stocks/history?instrument_key=...&page=1&page_size=50` and `GET /api/stocks/news?symbol=...&name=...`.

The stock workspace shows the chart beside a compact tabbed information panel (Overview, Company, News, Actions, History). It starts at one month of daily candles, supports scroll zoom, drag pan, and crosshair OHLCV readouts, and offers a fullscreen chart with Escape to close. Full stored history remains available through ALL and the paginated History tab. Small screens stack the chart and bounded information panel. Restart the API after this update: chart responses now include complete OHLCV instead of only closing prices.

## Heatmap index groups

The existing Sector dropdown includes Nifty 50, Bank Nifty, Nifty Midcap 100, and Sensex alongside the sector options. Choose either an index group or a sector; symbol/company search filters the selected group. Membership is fetched from official NSE Indices CSVs or the BSE Indices Sensex API and cached for 24 hours. Sensex scrip codes are mapped through the Upstox BSE instrument master to ISINs; the existing heatmap uses NSE quotes for those companies. Only constituents with available dashboard quotes appear. Fetch failures show a retry action rather than displaying an estimated or hardcoded list. Restart the API to enable `/api/market/index-constituents/{index_id}`.

## Watchlists and price alerts

Watchlist now stores named lists, sections, ordered symbols and coloured flags in the database. Use **+** to search Upstox stocks/indices or MCX commodity contracts. Symbols can be removed or reordered; lists can be created, copied, renamed, cleared, deleted, exported and imported as JSON. The table shows Last, Chg and Chg%, supports sorting/filtering, and refreshes selected-list quotes every 15 seconds. Selecting a row opens a compact quote/news preview with links to Stock Details. A list supports up to 100 symbols; the local app supports up to 30 lists.

Price alerts support at-or-above, at-or-below, crossing-above and crossing-below thresholds. Each alert is one-shot. The API lifespan starts a 30-second monitor, which persists its baseline prices, trigger time, and notifications. Crossing alerts require a baseline sample before they can trigger. Conditions are evaluated against sampled last prices, not every exchange tick; transient crossings between checks can be missed. Level conditions already met may trigger on the next check. Removing a symbol or clearing/deleting a list does not cancel independent alerts; cancel them in the alert panel.

The global bell shows saved trigger notifications on every page, and new triggers display in-app toasts. The browser polls the inbox every 15 seconds. **Enable desktop notifications** requests browser permission through a user click; desktop delivery requires an open app tab and browser support. Closing the browser does not stop the server monitor, and saved notifications appear on return. Alerts cannot be monitored while the API is stopped or broker authorization is unavailable. The UI reports monitoring/connection errors. Watchlists and alerts persist across API restarts. No email, SMS, push delivery to a closed browser, or cloud scheduler is implemented. This remains a single-local-user app.

Restart the API after this update to create `user_watchlists`, `price_alerts`, and `alert_notifications` and start monitoring. Tests: `python -m unittest discover -s tests -p test_watchlists.py`. The manual `tests/watchlist_browser_smoke.py` uses a headless Chrome debugging instance on port 9331 and intercepts all API calls with fixtures to verify adding a symbol, saving an alert and displaying a trigger toast without changing real data.

## RSI divergence scanner

Choose **Market Scanner > RSI Divergence** for completed daily NSE candles. Filter regular bullish, regular bearish, hidden bullish or hidden bearish using the grid's Filters panel. WATCH identifies a confirmed pair of price swings; BULLISH/BEARISH CONFIRMED identifies a closing breakout. Each stock appears once with pivot prices/dates, RSI comparisons, trigger, invalidation and stored-data date. Clicking it preserves this evidence in Stock Details. Restart the API to load the new strategy registration.

Research and signal conventions: [docs/rsi-divergence.md](docs/rsi-divergence.md). Results: [docs/rsi-divergence-backtest.md](docs/rsi-divergence-backtest.md). Reproducible read-only study: `.venv/Scripts/python.exe -m scanner.backtest_rsi_divergence`. The October 12, 2026 run evaluated 2,701 stocks; all held-out scenarios had negative mean trade returns after costs. This is a divergence identification tool, not a validated standalone trading system.

## Trade journal

The Trade Journal tab contains a dashboard, calendar, trade log, reflections, grouped reports, a historical size replay and browser display settings. It works independently of Upstox login. Journal trades are saved to the `journal_trades` database table, created on API startup. Restart the API after installing this feature if its endpoints are unavailable.

Fields combine `Trading_Journal(1).xlsx` and `reflecttion journal.xlsx`: execution, quantity/lot size, risk budget, stop/target, setup evidence, RSI/divergence, emotions before/during/after, confidence, rule adherence, mistakes, strengths, lessons, rating and chart links. Calculations use direction-aware price differences times total units, less entered charges. Percentage risk uses percentage points: 1 means 1%. Open trades are excluded from realised analytics; break-even trades remain in the closed-trade win-rate denominator. Equity is plotted in exit order. Daily P&L uses exit dates; hourly/session reports use entry time in Asia/Kolkata. No unrealised P&L, broker sync or automatic order placement is implied.

Settings offers a reviewable import of the one filled reflection trade. The numbered blank template rows are not trades. The template's self-referencing net-P&L formula is corrected in the app. The reflection row records SELL, 37 entry, 80 exit, quantity 100, but has a cached 3,225 profit based on a hard-coded multiplier and reversed sign. The app preserves those recorded inputs, computes -4,300 before unrecorded charges, retains the warning in notes and leaves missing contract details uninferred. Verify direction, contract, quantity, actual lot size and charges after import. Re-imports are idempotent.

Trades can be edited/deleted with confirmation for deletion and exported as filtered CSV. Chart links accept only HTTP(S). The scaling simulator is a linear historical replay, not a forecast: fills, margin, liquidity and non-linear charges are not simulated. Quick re-entry flags mean a same-account entry within five minutes of a completed loss; they do not diagnose revenge trading. Starting balance and hidden-price settings are local to the browser and do not alter records.

Validation: `.venv/Scripts/python.exe -m unittest tests.test_trade_journal -v`. Manual browser test `tests/journal_browser_smoke.py` intercepts all API calls so it cannot modify real trades. Requires frontend on 4200 and a temporary headless Chrome instance on debugging port 9333.
