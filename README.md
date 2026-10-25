# Market Desk

## F&O stock scope

Stock views use `data/fno/current_fno_stocks.csv` as the shared stock list (currently
213 NSE F&O underlying stocks). Searches work without broker login. Overview
quotes, Market Scanner, Focused, Stock Details, Watchlist, alerts, and journal
stock selection are limited to that list. Commodity and index instruments are
excluded from stored stock scans. The Option Chains view separately supports
indices and MCX commodity option underlyings. Index membership filters show only matching stocks within this list.
Journal Futures/Options entries use an eligible underlying symbol; contract details
belong in the Contract / CE / PE field.

The configured PostgreSQL database contains 322,544 daily candles for these stocks,
through 16 October 2026. Individual histories have different start dates. These are
underlying stock OHLCV candles, not futures/options contract price histories.
Live quotes and provider history still require an Upstox connection; stored scans
and stored daily history do not.

To preview a database cleanup and daily CSV import:

```powershell
.\.venv\Scripts\python.exe scripts\restrict_to_fno.py
```

Add `--apply` to back up every configured database table under `data/backups/`,
remove excluded instruments and related candles, coverage, jobs, watchlist entries,
alerts, notifications and journal trades, clear scan caches, and import the saved
F&O daily CSV. The obsolete SQLite database is archived when PostgreSQL is active.
Backups are excluded from Git. Routine imports reject stocks outside the saved list;
`sync_fno_data.py` reuses the saved list instead of replacing it from the exchange.


A personal market dashboard built with Angular and FastAPI. Upstox supplies live LTP quotes and historical NSE candles. API secrets and access tokens stay on the Python server.

## On-demand option chains

Open **Option Chains**, select Indices, F&O stocks or Commodities, then choose
an underlying. Nifty 50, Bank Nifty and Sensex are available alongside the saved
F&O stocks. Commodity choices come from Upstox's current MCX instrument master;
each choice identifies an underlying futures contract, not a commodity spot price.
Only the selected chain is fetched. Stock Details' Options tab uses the same flow.

The chain refreshes every 60 seconds while the view is visible. Leaving the view
cancels polling and browser requests; hiding the browser tab pauses polling and
returning fetches again. An already-started shared backend fetch can finish for
other viewers. Backend responses are cached for 55 seconds per credential,
underlying and expiry, and concurrent requests share a single fetch. Expiry lists
are cached for 15 minutes; the MCX master for up to an hour. Option provider calls
are serialized with at least one second between starts. Other app API calls have
their existing behavior. Cache and pacing apply per backend process; use one
worker or introduce a shared cache/limiter before scaling to multiple workers.

Upstox's native option-chain endpoint does not support MCX. Commodity chains are
assembled from listed CE/PE contracts and full market quotes in batches of 500.
Greeks/IV remain unavailable for these assembled chains. Missing quotes are
reported rather than filled with zero. A valid Upstox token and appropriate
market-data access are required. Retrieval time is not the exchange tick time.

Set `OPTION_CHAIN_SAVE_SNAPSHOTS=true` in `.env` to retain successful fetched
responses in the `option_chain_snapshots` database table (default: false).
Restart the backend to create the table and apply configuration. Only requested
chains are captured; this does not produce continuous history. Snapshots have no
automatic retention deletion; plan storage cleanup if enabling long term.

Validation: `python -m unittest discover -s tests -p "test_option*.py"` and,
from `frontend`, `npm run test:option-chain` and `npm run build`.

## Selected option analysis

The **Scanner** navigation item combines stock charts and option chains. Select
**F&O stocks**, choose a stock, then use **Stock chart / Options** to switch views
for the same underlying. Stock charts offer 1m, 5m, 15m, 30m, 1h and daily candles
with the shared strategy selector, settings, price/RSI panes and fullscreen view.
Indices and commodities retain their existing option-chain and CE/PE analysis.
The market-wide screening grid is labelled **Stock Screener**.

Stock workspace analysis uses `/api/stocks/analysis`, reading DB history and
fetching live candles for the selected stock only. Strategies use up to 1,000
completed bars; Ghost Rider can include the developing bar, and RSI follows its
Wait for close setting. Offline daily analysis remains available. Switching
stock/options views destroys the inactive component and cancels its browser
polling and requests. Validation includes `tests.test_stock_analysis`, frontend
lifecycle tests, and the mocked desktop/mobile `option_analysis_browser_smoke.py`.

Choose **Analyze CE** or **Analyze PE** at a strike to replace the chain with
Option Analysis. The backend resolves the exact underlying/expiry/strike/side
against listed provider contracts, including MCX, before requesting any history.
Choose 5m, 15m, 1 hour, 1 day or 1 week. Minute history covers 28 calendar days,
hourly history 89 days, and daily/weekly history up to three years, subject to
the contract's listing date and a 1,000-candle cap. Weekly OHLCV combines daily
candles in Monday-to-Sunday IST weeks; the current week remains provisional
until the next Monday. Newer contracts may lack enough bars for a strategy.
Historical and today's intraday candles are combined by timestamp; unfinished
candles are excluded with a five-second buffer for intraday frames. Daily NSE/BSE
candles close after 16:00 IST; MCX daily candles close at the next local date.
Invalid OHLCV breaks history so
signals do not bridge invalid bars. Derivative candles stay outside the stock DB.

The six directional strategies run on the selected option premium using defaults.
Sutradhar daily-open reference levels load on selection for intraday charts.
The desktop layout gives 40% to the chart and 60% to strategy details. Choose a
strategy in the dropdown to show its conditions, signal times, and defined levels
alongside its chart evidence. **Fullscreen** expands the chart; Escape returns to
the split view. Narrow screens stack the panels. Short histories report insufficient
candles. RSI Divergence uses the supplied Pine RSI-pivot engine and a separate
black oscillator pane. Ghost Rider and RSI Divergence stock scans support stored
daily, 1h, 15m and 5m candles. Option analysis also supports weekly candles.
There is no invented forecast or combined probability score.

The underlying's close relative to EMA 20 provides separate context: an uptrend
supports CE premium direction, a downtrend supports PE direction, before
volatility/time-decay effects. Option bullish/bearish labels always refer to the
premium itself. Underlying history failure does not hide available option results.
Analysis refreshes every minute while visible, shares history/results for 55
seconds, and cancels browser requests on exit, timeframe changes or tab hiding.
Chain polling pauses during analysis. **Back to option chain** resumes it.

## Ghost rider v.2 chart

The supplied source is preserved verbatim in `docs/ghost-rider-v2.pine`. The option
Ghost Rider view ports its EMA 9/21 crossover state, Wilder ATR 14 risk, entry/SL,
all five R-multiple targets, same-candle target detection and latched hit flags.
Only an opposite crossover replaces the setup: a touched stop does not cancel it.
Negative targets are retained. There is no additional 250-bar entry gate in this
overlay. Market Scanner now uses this same engine and history policy.

The chart renders both EMAs and their direction-colored ribbon, daily-session
HLC3 volume-weighted VWAP, all BUY/SELL plotshapes, signal candle body colors and
orange retest bodies. Rays start at the most recent crossover; TP1–TP3 are dashed,
TP4/TP5 use the source widths and dark greens, hits turn turquoise, and the six
right-offset entry/target labels use the supplied icons. The source has no SL
label, so SL is a line only. All levels participate in chart autoscaling.

The middle-right dashboard uses the source's seven independent votes, fixed
denominator, exact bias thresholds, MACD 12/26/9, DMI/ADX 14/14, RSI 14, volume
SMA 20 and a separately requested 5-minute RSI. Historical 15-minute bars use the
last 5-minute intrabar without lookahead; no 15-minute RSI is substituted for it.
Missing 5-minute data remains n/a. Votes do not filter the crossover signals.

Settings reproduce the source input names/defaults: dashboard/trade sizes small,
ribbon opacity 75, label offset 12, ATR multiplier 1.5. Style switches control
plots, candle colors, shapes, labels, rays, table and output precision. Minute,
hour, day and week visibility settings apply to the corresponding chart frames. Settings
have Defaults, Cancel and Ok; ATR changes reuse cached candles and recompute risk.

Ghost Rider alone includes a developing candle when supplied by the intraday API;
it recalculates from confirmed history on each minute refresh, so provisional
crosses/hits can disappear before close, as with the Pine indicator. Other
strategies continue using completed candles. VWAP resets by exchange-local India
calendar session. Our 28-day/1,000-bar window, Upstox candles and minute sampling
can differ from TradingView's warm-up, feed and tick-by-tick execution. Numerical
parity is not asserted without matching exported input candles from TradingView.

## Requirements

- Python 3.10 or newer
- Node.js 20.19 or newer
- An approved Upstox account and developer app with its redirect URI set to `http://localhost:4200/oauth/callback`

## Run locally

1. Copy `.env.example` to `.env` and fill in `UPSTOX_ACCESS_TOKEN` with your daily Upstox access token, plus `OPENAI_API_KEY` for general DRISHTI chat. For OAuth sign-in instead, set `UPSTOX_CLIENT_ID` and `UPSTOX_CLIENT_SECRET`. Register `http://localhost:4200/oauth/callback` as the redirect URL in that app. The OpenAI key stays on the FastAPI server. `DRISHTI_OPENAI_MODEL` can override the configured default model.
2. First-time setup only (do not recreate an active `.venv`):

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

   For normal startup, activate the existing environment and run the API:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m uvicorn main:app --reload --port 8000
   ```

3. In a second terminal, install and run Angular:

   ```powershell
   cd frontend
   npm install
   npm start
   ```

4. Open `http://localhost:4200` and connect Upstox to load F&O stock quotes, then search the saved stock list.

Stock Details combines PostgreSQL history with selected-stock Upstox candles. The Overview chart and live
quotes use Upstox. Provider credentials stay on the Python server. The application
is intended for a single local user.

## Instrument analysis

Select a saved F&O stock to open its stored daily chart and paginated history.
Company information, corporate actions and live prices use Upstox; news is loaded
separately. A failure in one source does not block the stored chart.

Market Scanner runs the selected registered strategy against stored candles.
The EMA/SMA strategy checks whether the close is above EMA 9, EMA 20, SMA 50 and
SMA 200; it does not require those averages to be in bullish order. Available
strategies also include Golden/Death Cross, multi-MA alignment, RSI, RSI divergence
and Ghost Rider. Focused combines evidence from these strategies.

The DRISHTI chat and deterministic EMA-analysis APIs remain available through
`/api/drishti/chat` and `/api/drishti/ema-alignment`. They are not a visible tab.
The unused dashboard component and legacy `/api/scanner/ema` endpoint have been
removed; scanners use `/api/strategies/scan`.

## Incremental candle storage

Restart the API after upgrading to create the candle revision table. The configured database stores
candles keyed by instrument, timeframe, and timestamp.
Repeated imports skip identical values; corrected OHLCV values replace the old row.
Changed data advances a timeframe revision so future scans cannot reuse old results.

After connecting Upstox, open `http://localhost:8000/docs`:

1. Call `POST /api/sync/universe` to load the saved F&O stock list.
2. Call `POST /api/sync/candles` with
   `{"unit":"minutes","interval":1,"lookback_days":30,"concurrency":5}`.
   For hourly or daily candles, use `hours` or `days` with interval `1`.
3. Repeat the sync request when new candles are available. Existing instruments
   resume from their latest stored date with a two-day correction overlap.
4. Call `POST /api/strategies/scan` with
   `{"strategy_id":"ema_sma_alignment","timeframe":"1m"}` to use stored data.

Backfills use bounded date windows; today's minute/hour candles use the intraday
endpoint. Open intraday candles are excluded using their duration plus a five-second
buffer. NSE daily candles can include today after 16:00 IST when supplied by the provider.
The sync uses time-based completion checks, not an exchange holiday calendar.

Storage keeps one OHLCV row per candle and does not duplicate it per user or strategy.
Scans load a bounded recent window per instrument, sized for the selected strategy.
PostgreSQL uses an indexed per-instrument query; SQLite uses a ranked query for
local testing. Indicator values may differ from calculations seeded with all history.

API sync is manually triggered and runs in the API process. Follow a returned job ID
with `GET /api/sync/jobs/{job_id}`. The Windows scheduled updater below runs separately;
there is no durable API worker queue or distributed lock. Older gaps outside the correction overlap need separate
reconciliation. Each timeframe is stored independently; daily candles do not
populate intraday history automatically.

## Selected-stock charts and automatic daily updates

Restart the API to create `stock_chart_selections`, then refresh the frontend.
Stock Details supports 1m, 5m, 15m, 30m, 1h and daily charts. Stored daily history
loads immediately; `GET /api/stocks/chart?instrument_key=...&timeframe=1d` merges
DB history with Upstox data for that stock only. Intraday charts use up to 28
calendar days of 1-minute candles, aggregated from the NSE 09:15 IST session open.
Developing bars are labelled and are excluded from persistent candle storage.
Completed provider daily candles repair recent daily gaps. BHAV later reconciles
official daily OHLCV. Daily history cannot reconstruct past minute candles.

Charts refresh every minute while visible, cancel browser requests on stock/frame
changes and tab hiding, and stop polling on exit. Shared backend work already in
progress may finish and persist completed bars. Fetches are cached for 55 seconds
across timeframe switches; historical responses for 15 minutes. Requests are paced
and serialized per process. Stored data stays available without broker login.
Use one backend worker for this local application.

Install or update the local Windows task from the repository root:

```powershell
.\scripts\install_market_data_task.ps1
```

`TradersGita-MarketData` runs daily at 18:30 IST and repeats hourly for four hours,
with up to three 30-minute retries on failure. It runs as the installing Windows
user while logged in, starts missed runs when available, and prevents overlapping
instances. The PC must be awake and connected. It does not install a cloud job.

The standalone `scripts/update_market_data.py` downloads NSE PR archives directly,
validates their trading dates, and applies the existing duplicate-safe BHAV importer
for all saved F&O stocks. It catches up from the stalest stored daily date with a
two-day correction overlap, bounded to one year (14 days for an empty DB). Weekends
are skipped; 404 archives are reported as unavailable, not invented trading bars.
Missing archives are retried by subsequent scheduled runs within the catch-up range.
Other download/import failures return a failing exit status for Task Scheduler.
Backups precede BHAV corrections; market-cap metadata never moves to an older date.

Intraday catch-up is limited to stocks explicitly opened in Stock Details during
the past 28 days. It needs a valid `UPSTOX_ACCESS_TOKEN` in `.env`; browser OAuth
tokens are not available to the separate scheduled process. BHAV needs no broker
token and still runs when one is absent. Provider rejection is recorded in the
summary. Database connection details come from the existing `.env`.

Latest run: `data/scheduled-update.json`; per-day details:
`data/bhavcopy-import-YYYY-MM-DD.json`; downloaded archives: `data/archives/`.
Run once manually with `.venv\Scripts\python.exe scripts\update_market_data.py`.
If the summary reports damaged PostgreSQL pages, recover the database from a
verified backup before retrying; the updater does not discard or replace damaged
database storage pages.

Recovery tooling: `scripts/recover_market_database.py` restores non-candle data
and copies readable heap-page ranges into a separate database. It requires a
physical preservation snapshot and a non-candle custom-format dump in the folder
referenced by `data/backups/current-recovery.txt`. It reports unreadable pages
and invalid OHLCV explicitly, checks personal-record counts and contents, and
never switches the app automatically. `--resume` resumes a failed copy after
checking its destination row count. `scripts/reconcile_recovered_history.py`
rebuilds any deferred indexes and fills missing saved F&O daily CSV rows without
overwriting recovered prices. Inspect the recovery report, validate the new DB,
and take a healthy backup before changing `.env` and re-enabling the scheduler.
Validation: `python -m unittest tests.test_stock_chart tests.test_scheduled_market_data
tests.test_stock_details tests.test_candle_storage tests.test_market_cap` and the
frontend Angular build. Provider reference: [Upstox intraday candles](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/).

For a production deployment, add durable ingestion workers, authentication and
rate limiting. The current configured database is already PostgreSQL.

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

Watchlist now stores named lists, sections, ordered symbols and coloured flags in the database. Use **+** to search the saved F&O stock list. Imported lists and new alerts are validated against the same list. Symbols can be removed or reordered; lists can be created, copied, renamed, cleared, deleted, exported and imported as JSON. The table shows Last, Chg and Chg%, supports sorting/filtering, and refreshes selected-list quotes every 15 seconds. Selecting a row opens a compact quote/news preview with links to Stock Details. A list supports up to 100 symbols; the local app supports up to 30 lists.

Price alerts support at-or-above, at-or-below, crossing-above and crossing-below thresholds. Each alert is one-shot. The API lifespan starts a 30-second monitor, which persists its baseline prices, trigger time, and notifications. Crossing alerts require a baseline sample before they can trigger. Conditions are evaluated against sampled last prices, not every exchange tick; transient crossings between checks can be missed. Level conditions already met may trigger on the next check. Removing a symbol or clearing/deleting a list does not cancel independent alerts; cancel them in the alert panel.

The global bell shows saved trigger notifications on every page, and new triggers display in-app toasts. The browser polls the inbox every 15 seconds. **Enable desktop notifications** requests browser permission through a user click; desktop delivery requires an open app tab and browser support. Closing the browser does not stop the server monitor, and saved notifications appear on return. Alerts cannot be monitored while the API is stopped or broker authorization is unavailable. The UI reports monitoring/connection errors. Watchlists and alerts persist across API restarts. No email, SMS, push delivery to a closed browser, or cloud scheduler is implemented. This remains a single-local-user app.

Restart the API after this update to create `user_watchlists`, `price_alerts`, and `alert_notifications` and start monitoring. Tests: `python -m unittest discover -s tests -p test_watchlists.py`. The manual `tests/watchlist_browser_smoke.py` uses a headless Chrome debugging instance on port 9331 and intercepts all API calls with fixtures to verify adding a symbol, saving an alert and displaying a trigger toast without changing real data.

## RSI divergence scanner

Choose **Market Scanner > RSI Divergence** for the supplied Pine regular bullish
and bearish RSI-pivot rules. Choose daily, 1h, 15m or 5m stored candles. The recent
signal window filters scanner results by confirmation age; it does not change
which divergences the indicator detects. Click a result for the shared dark RSI
pane and Inputs/Style/Visibility settings. Option Analysis uses the same engine.
Focused confluence uses the same confirmed RSI-pivot events.

See [current Pine specification](docs/rsi-divergence.md) and the preserved
[source script](docs/rsi-divergence.pine). The former price-pivot/hidden-divergence
study is archived separately; its backtest does not validate this supplied script.
Restart the API and refresh the frontend to load the new implementation.

## Trade journal

The Trade Journal tab contains a dashboard, calendar, trade log, reflections, grouped reports, a historical size replay and browser display settings. It works independently of Upstox login. Journal trades are saved to the `journal_trades` database table, created on API startup. Restart the API after installing this feature if its endpoints are unavailable.

Fields combine `Trading_Journal(1).xlsx` and `reflecttion journal.xlsx`: execution, quantity/lot size, risk budget, stop/target, setup evidence, RSI/divergence, emotions before/during/after, confidence, rule adherence, mistakes, strengths, lessons, rating and chart links. Calculations use direction-aware price differences times total units, less entered charges. Percentage risk uses percentage points: 1 means 1%. Open trades are excluded from realised analytics; break-even trades remain in the closed-trade win-rate denominator. Equity is plotted in exit order. Daily P&L uses exit dates; hourly/session reports use entry time in Asia/Kolkata. No unrealised P&L, broker sync or automatic order placement is implied.

Settings imports only workbook trades whose underlying symbol belongs to the saved F&O list. Excluded source rows remain in the reference workbook but cannot be imported. Re-imports are idempotent; recorded inputs and source warnings are retained for eligible trades.

Trades can be edited/deleted with confirmation for deletion and exported as filtered CSV. Chart links accept only HTTP(S). The scaling simulator is a linear historical replay, not a forecast: fills, margin, liquidity and non-linear charges are not simulated. Quick re-entry flags mean a same-account entry within five minutes of a completed loss; they do not diagnose revenge trading. Starting balance and hidden-price settings are local to the browser and do not alter records.

Validation: `.venv/Scripts/python.exe -m unittest tests.test_trade_journal -v`. Manual browser test `tests/journal_browser_smoke.py` intercepts all API calls so it cannot modify real trades. Requires frontend on 4200 and a temporary headless Chrome instance on debugging port 9333.


## Focused shortlist

The Focused tab combines all six registered strategies against one shared NSE daily database snapshot. It returns all qualified stocks and shows five per page by default, with reasons and links to stock analysis. Pagination gives access to every match without expanding the page. The database scan requires no broker token. Results are cached for 15 minutes and invalidated by the daily candle revision.

Qualification requires at least two confirmed directional strategies from at least two signal families. Trend, crossover and momentum each contribute at most three points, so overlapping MA checks do not inflate the score. SUPER requires three confirmed strategies, at least six points and no opposing evidence. Scores are deterministic confluence points, not calibrated probabilities or a backtested combined trading system. Absence of a bullish match never creates a bearish vote. Conflicting confirmed signals, weakened cross setups, unconfirmed divergence, old/stopped Ghost Rider setups and stale stock data are excluded.

Focused uses at most 500 recent candles per stock with default parameters; Golden/Death Cross votes require a cross within 30 bars and Ghost Rider votes within five bars. The individual strategy screens retain their existing history windows. Stocks require 251 candles, price at least Rs 20, positive latest volume, and average 20-day traded value of at least Rs 1 crore. Results use the newest completed date present in the database, which is shown explicitly. Shortlists are not padded when few stocks qualify.

Reference entry is the latest completed close. A new SL is placed beyond the latest ten-bar low/high with a 0.25 ATR-14 buffer, at least 1.5 ATR away. Targets are 2R and 3R projections from this close. Nonpositive levels and stop distances above 12% are excluded. These plans are separate from historical Ghost Rider targets. Bearish analysis does not imply an available overnight cash-equity short.

Default UI ranking uses company market capitalization (largest first), then traded value and signal score. Other sorts use traded value, signal score or share price. Price and market-cap filters are optional; neither company size nor share price is presented as a business-quality rating. The NSE PR archive market-cap report is imported into `data/nse-market-cap.json`; import_nse_bhavcopy updates it on each applied daily import. Metadata is attached to cached scanner results only when its trading date matches. Missing caps remain unknown and sort last.

API: `GET /api/focused?limit=5` (limit 1?200); background scan jobs return the complete list. Tests: `.venv/Scripts/python -m unittest tests.test_focused`.

## Option chain

Select a stock in Stock Details and open **Option Chain**. The tab loads current
expiries from Upstox and selects the nearest available expiry. Calls and puts appear
by strike with LTP, OI, volume, IV and bid/ask prices; **Show Greeks** adds delta,
gamma, theta and vega. The nearest strike to the supplied underlying price is marked
ATM. **Refresh** reloads expiries and the selected snapshot. Switching stocks clears
previous results. Empty, missing and failed responses are shown explicitly.

This requires an active Upstox connection and is a snapshot, not a streaming feed.
The displayed retrieval time is not an exchange tick timestamp. Option contracts
are not inserted into the stock database. The underlying must belong to the saved
F&O list.

Provider references: [Option contracts](https://upstox.com/developer/api-documentation/get-option-contracts/)
and [Put/call option chain](https://upstox.com/developer/api-documentation/get-pc-option-chain/).

## Frontend API routing in local and production builds

`src/environments/environment.ts` uses an empty backend base URL. `npm start`
therefore keeps API and login requests on the Angular origin and forwards them
through the existing `proxy.conf.json` to `http://localhost:8000`.

Production builds replace that environment with `environment.production.ts`, whose
backend is `https://traders-gita-api.onrender.com`. The root HTTP interceptor rewrites
relative backend requests for every HttpClient service, including the journal.
The shared `backendUrl()` helper also resolves login links, since browser navigation
does not pass through an HTTP interceptor. External URLs and static assets remain
unchanged. Future direct fetch/EventSource calls should use the same helper.

Cloudflare Pages should build with `npm run build -- --configuration production`
from `frontend` and publish `dist/market-desk/browser`. Deploy the new build for
these routing changes to take effect; the source changes do not update hosting.
FastAPI already allows `https://traders-gita.pages.dev` and `http://localhost:4200`
through CORS. Render's existing `FRONTEND_ORIGIN` controls the OAuth return location;
its production value should be `https://traders-gita.pages.dev`.

Validation: `npm run test:api-routing` in `frontend`, and
`.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_cors.py` at the
repository root. The production build can require network access to inline Google
Fonts. Its current initial-bundle warning threshold is 500 kB (error threshold 1 MB).

If local startup fails with `socket.gaierror`, check the database hostname and URL
encoding. Special characters inside the password must be percent-encoded in a
connection URL (`@` becomes `%40`); do not encode the entire URL or double-encode an
already encoded password. Never paste a complete credential-bearing URL into logs.

## Sutradhar

Select **Sutradhar** in Option Analysis or Market Scanner for the supplied
intraday daily-open levels: Flow, Crest, Crown, Value, Base, Origin, Mid and O.
The dark chart includes the original colours, four fills, circles, labels and
Inputs/Style/Visibility settings. SMA periods default to 14/7/5; EMA is optional.
Daily option history loads only when this strategy is selected. Stock scans use
stored intraday and daily candles. These are reference levels, with no source
entry, stop-loss, target or holding-time rules. See [Sutradhar](docs/sutradhar.md)
and its [MPL-2.0 source](docs/sutradhar.pine).
