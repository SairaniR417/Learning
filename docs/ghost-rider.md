# Ghost Rider scanner

Port of the user-supplied Pine Script `Ghost rider v.2`, not Python.

Choose Ghost Rider in Market Scanner. The table displays BUY/SELL, NEW/WAIT,
signal date, entry, stop loss, and TP1–TP5. Target cells marked with a check
were touched by a candle high (BUY) or low (SELL) since the signal, including
the signal candle, as in the supplied script. This does not establish that
a limit order placed after the candle close could have filled.

EMA 9 crosses EMA 21 to create a setup at that candle's close. Risk equals
Wilder ATR 14 times the configurable multiplier (default 1.5). Stop is 1R
against the signal; targets are 1R through 5R in its direction. Prices are
fixed until an opposite cross resets the setup and target flags. NEW means
the latest completed candle crossed; WAIT retains the last setup. Stop
touches are shown separately and do not retire the setup, matching the script.

This release supports completed daily, hourly, 15-minute and 5-minute candles from the existing database
(today's NSE candle is eligible after 16:00 IST),
using the latest 1,000 per instrument. Crossovers need at least two bars; ATR-based
levels remain unavailable if the signal occurs before ATR warms up. EMA is
seeded at the first loaded close; ATR is seeded with the first 14 true ranges.
Older TradingView history, provider adjustments, timestamps, or a different
chart timeframe can produce different results. No setup means no result row.
There is no candle-history request to TradingView.

The shared Pine v2 engine also calculates the Pullers/Draggers dashboard, session
VWAP, RSI, MACD and ADX. The 5-minute vote uses matching stored 5m history;
missing 5m history stays n/a. Neither dashboard scores nor stop touches filter
the original BUY/SELL entries. Daily RSI is never substituted for 5-minute RSI.

Click a Ghost Rider result to open the dark 40/60 chart view inside Market Scanner,
including the EMA ribbon, BUY/SELL labels, VWAP, ENTRY/SL/TP1–TP5 rays, dashboard,
settings and fullscreen. Back restores the scan results. Leaving Market Scanner
closes the chart and stops its refresh. The chart reads only the selected stock's
stored history, without broker login or live history downloads. Import/sync
intraday candles before choosing an intraday scan. Cache keys include both the
selected timeframe's candle revision and the 5m revision.

Validation: tests cover Wilder ATR seeding, new BUY, fixed levels while
waiting, target persistence, opposite SELL/reset, and signal-candle hits.

## Scanner session and entry assessment

Ghost Rider now adds separate columns and a stock-chart summary for session open,
latest candle close versus open, high/low versus open, position in the day's range,
nearest SL/target, distance to the stop, next untouched target and remaining R/R.
These use the selected candle snapshot, not the independently polled live quote.
Missing 09:15 history does not become a synthetic session open. Intraday extremes
use the available stored bars, so incomplete sessions can omit an earlier extreme.
Daily bars use their actual open/high/low. Weekly context has no daily-open estimate.

The original Pine BUY/SELL and target-hit behaviour is unchanged. The new
**Entry assessment** is a separate conservative screen: a setup at most five bars
old, at least 35 bars of warm-up, matching recent 5m RSI, ADX strictly above 25,
at least five of seven directional votes with a three-vote lead, an untouched
positive stop, and at least 1.5 remaining reward/risk to TP2 or the next untouched
target beyond TP2. TP1 is a 1R scale-out and is shown separately. Stops touched
on the signal bar also block a candidate. Developing, stale and incomplete data
show WAIT with reasons. An opposing held opening range also blocks a candidate.
The Filters panel can select BUY CANDIDATE, SELL CANDIDATE or WAIT.

Directional votes are the original dashboard's agreement percentage, not a win
rate. ADX measures strength rather than direction; **WEAK BULLISH** can therefore
coexist with the original **STRONG BULL** dashboard bias. MACD histogram is main
minus signal; relative volume is latest volume divided by the 20-bar mean. RSI,
MACD, EMA, VWAP, ADX, ATR and volume remain selectable as individual columns.
Near a level means within 0.25 ATR, with a 0.25% price fallback when ATR is absent.
No costs, slippage, execution fills or profitability are estimated. Bearish stock
signals do not imply overnight cash-stock short availability.

## Opening Range Breakout

Select **Stock Screener → Opening Range Breakout**, choose a 15-, 30- or 60-minute
range and scan stored 5m candles. The range starts at 09:15 IST and ends at 09:30,
09:45 or 10:15. All opening slots must exist and be valid. By default two consecutive
completed 5m closes above the range high qualify as BULLISH; below the range low
qualify as BEARISH. A wick, one close, missing bar or return inside cannot establish
that hold. Hold length is configurable from one to six bars. Choose “Include
waiting / incomplete stocks” to inspect stocks without a confirmed hold.

Results show the actual session date, range levels, hold length, distance beyond
the range and candle time. Old holds are labelled HISTORICAL. Both scans require
stored intraday history; neither downloads the full universe during a scan. The
Ghost chart summary shows the first 15-minute range; the separate scan supports
all three durations. Opening-range scans are excluded from daily Focused confluence.

Validation: `python -m unittest discover -s tests -p test_scanner_context.py` and,
from `frontend`, `node --test tests/scanner-context.test.cjs`. Existing Ghost Rider,
stock workspace, option analysis and Focused regression tests also apply.
