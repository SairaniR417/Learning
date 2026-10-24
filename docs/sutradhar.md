# Sutradhar

Derived from the user-supplied Sutradhar Pine script, © sairanir23, under the
Mozilla Public License 2.0: https://mozilla.org/MPL/2.0/. The normalized source
is preserved in `sutradhar.pine` (chat bold formatting and HTML spaces removed).
The supplied text contains both version=6 and version=5 directives; the port
implements its displayed formulas rather than compiling those directives.

Select **Sutradhar** in Option Analysis or Market Scanner. Stock scans/charts
offer stored 5m, 15m and 1h candles. Daily and weekly charts show the source's
intraday-only restriction instead of applying an invented daily adaptation.

For each session, O is that instrument's daily open. Flow/Value are O plus/minus
half the difference between the averages of prior daily highs and lows over 14
bars. Crest/Base use 7 and Crown/Origin use 5. Mid is (Flow + Value)/2, equal to O
when Flow and Value are available. The optional EMA uses Pine's first-valid-value
seed and alpha 2/(period+1). Today's daily high/low are never used in today's
ranges. Periods are independent: the implementation does not reorder levels.

Options use the selected CE/PE contract's own daily history, not the underlying's
daily range. Daily history is fetched only after Sutradhar is selected. Its
history cache is shared; result keys include all calculation inputs. Source
errors affect Sutradhar levels without hiding the other strategies. For stored
equities, the actual latest-session 09:15 opening candle may provide O before
today's daily candle is stored. A truncated midday window cannot establish O;
missing prior daily ranges are not reconstructed from partial intraday candles.
An authoritative daily open takes precedence over the stored opening candle.

The script switches futures symbols to root 1! continuous daily data. This app's
current analysis screens accept equity/option contracts, not direct futures
charts. The engine rejects a requested futures calculation without that feed;
it never silently replaces a continuous root with one futures expiry.

The chart uses a black background, the seven supplied input colours, Crown and
Origin circles, Mid step line, O width 2, and the original four fixed fill colours
with 88/94 transparency. Current labels sit one bar to the right. Labels are
updated in place rather than accumulating a new set every polling cycle. Labels
are independent of individual plot switches, as in the source. Settings provide
Inputs, Style and Visibility; Defaults, Cancel and Ok; and fullscreen. Colour,
fill, visibility, precision and style changes require no data fetch. Changing
periods or SMA/EMA recalculates against cached daily history.

Scanner results expose reference levels with neutral status. The source defines
no entry, buy/sell, exit, stop-loss, target, holding time or alert condition. No
Sutradhar directional vote is added to Focused confluence. Future decision rules
must be specified separately. Provider history/adjustments and continuous-futures
roll conventions can differ from TradingView; no exported TradingView parity
dataset was supplied.

Validation covers prior-day SMA/EMA formulas and seeding, partial warmup,
no current-day/future high-low leakage, opening-bar validation, intraday guard,
daily-source failures, shared scanner/chart output, cache inputs and revisions,
request lifecycle, and mocked browser rendering/settings/navigation.
