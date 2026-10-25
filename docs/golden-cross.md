# Golden / Death Cross

The scanner, stored-stock chart, selected-stock workspace and option chart now
share `services/golden_cross.py`. Default mode is a classic **SMA 50/200** cross:
previous short SMA <= long SMA and current short SMA > long SMA is Golden;
previous short SMA >= long SMA and current short SMA < long SMA is Death.
Equality alone is not a cross. No RSI, volume or breakout filter gates classic
signals. Cross detection starts on the first candle with two valid SMA pairs
(201 candles for 50/200), removing the old arbitrary 250-bar detection gate.

Periods count candles on the selected timeframe. Use Daily for the traditional
50-day/200-day cross. Intraday or weekly charts calculate the corresponding
50-bar/200-bar cross; they do not silently request daily data.

The chart plots both SMAs and every cross in the loaded prefix. Settings provide
Inputs, Style and Visibility with Defaults/Cancel/Ok, optional EMA lines,
colors/widths, label visibility, precision, scale/status values and interval
ranges. Style changes redraw locally; input edits cancel the old request and
recalculate. Fullscreen and minute refresh use the existing chart lifecycle.

Stock Screener returns a classic cross when its age is within the configured
Recent Cross window (default 30 bars, inclusive). A zero window returns only
crosses on the latest completed candle. The chart retains older historical
cross markers even when no current scan match exists. No cross in loaded history
is distinct from insufficient history; a pre-existing SMA trend alone is not
reported as a newly detected cross.

Optional **Require six-filter confirmation** preserves the earlier policy:
EMA/EMA/SMA/SMA alignment, close above/below both EMAs, both SMA slopes,
strict bullish/bearish RSI threshold, relative volume against prior bars, and
close breaking the prior high/low window must pass together within the window.
Volume and breakout lookbacks exclude the current candle. A cross is still drawn
while WATCH; a separate confirmation marker appears when all six pass.
Expired unconfirmed crosses do not scan as matches. Confirmed setups remain
CONFIRMED_ACTIVE or CONFIRMED_WEAKENED until the next opposite cross. Focused
confluence explicitly retains this confirmation mode and its existing age and
strength filters; classic crosses do not automatically become confirmed votes.

Scans and their targeted charts use at most 1000 completed stored candles per
stock and identical inputs. The workspace and options also calculate this
indicator on completed candles, so developing bars cannot invent a committed
cross. Daily completion uses the existing exchange-session close check. Stored
chart frames are daily, 1h, 15m and 5m; selected-stock workspace additionally
supports its existing 1m/30m frames. All supported frames use the same engine.

No stop, target or trade win/loss statistics are invented for an SMA crossover.
Historical coverage and data-provider differences can change the visible cross
history. `tests/test_golden_cross.py` verifies early crosses, equality, both
directions, custom periods, freshness, no lookahead, optional confirmation,
forming-bar exclusion and scan/chart agreement. Browser smoke covers stock
workspace, settings, mobile and opening the stored chart from a screener result.
