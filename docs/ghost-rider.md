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
