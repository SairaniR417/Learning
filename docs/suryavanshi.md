# Suryavanshi

The original user supplied source is preserved byte for byte in
[`suryavanshi.pine`](suryavanshi.pine). The calculation implementation is
`services/suryavanshi.py`, shared by the stock screener, stored-stock chart,
selected-stock workspace and option premium chart. No orders are placed.

## Inputs and signals

Defaults: Length 20, Wicks, RR Ratio 1.1, SL Type Close, Show SL off,
breakout line style Dashed, bull #028545, bear #f60707. Type Body compares
**close**, not open/close extremes. Pivots always use high/low.

* A swing confirms Length bars later. The first confirmed pivot on each side
  and subsequent unchanged pivot prices do not arm a break, matching
  `change(fixnan(PH/PL))`. Equal extremes select the rightmost candidate.
* Breaks are strict > / <. An armed swing is consumed even during an open trade.
  There is no reversal or second simultaneous trade.
* Risk uses TR Wilder RMA(14), SMA seeded, multiplied by 1.5. Long stop is
  low minus ATR*1.5; short stop is high plus ATR*1.5. Target is close plus/minus
  RR times the absolute risk distance. TP/SL calculations are not tick rounded.
* Entry candle exits are evaluated. Target uses high/low; stop uses Close or
  High/Low as configured. Target and stop checks are independent: both may
  count on one candle, and stop color/tooltip takes precedence.
* If both breaks fire while flat, both source labels/alert conditions occur;
  Short overwrites direction, while Long wins the TP/SL switch. This unusual
  behavior is deliberately preserved. An ATR-unseeded early entry keeps null
  TP/SL rather than silently adding a new warmup rule. Zero and negative finite
  RR values are accepted as in the source.
* Volume dots include the break candle and exclude the pivot candle. Dojis
  count toward total volume. Rounded (two decimal) bullish/bearish share must
  exceed 55%; green takes precedence, otherwise red, otherwise yellow. The
  source's shared within-bar volume arrays are preserved for two calls.
* Winning/Losing Trades count the entire loaded prefix, even after drawings
  are garbage collected. Lines and labels each retain their newest 500 objects.
  Target tags and lines freeze on exit; target tags sit one bar to the right.
* `Adj=volAdj(30)` and DYNAMICSLG are unused in the supplied script and have no
  effect. The fourth candle color and third background color are unused source
  style slots; they remain available without introducing extra states.

## Display and scope

Inputs, Style and Visibility are draft settings: Cancel discards, Defaults
resets the draft, Ok applies. Style/visibility changes redraw locally. Calculation
input changes cancel stale requests and replay the same engine. The candle
overlay takes precedence over Bar Color when both are enabled, as the source's
plotcandle is drawn over its chart bars. Background opacity defaults to 10%.
CHoCH/BOS, volume dots, entry badges, target connectors/tags, optional SL, candle
colors, full-height background bands and score table use chart primitives.
Stop tag hover uses the source tooltip text; its display currently assumes a
0.05 tick. This affects only tooltip text, never signals or TP/SL levels.

The stock screener uses completed stored daily, 1h, 15m or 5m candles, at most
1000 per instrument. A result means an active source trade or a trade opened on
the latest completed candle (including immediate exit); its state distinguishes
ACTIVE, TARGET, STOP and BOTH. This result-selection policy does not change the
indicator. Clicking a result opens the same stored prefix/settings, with no
broker request. Suryavanshi does not change the separate Focused confluence rules.

The main Scanner workspace uses the selected stock's DB/live candles, including
the developing candle. Option analysis uses the selected contract's candles.
Every refresh recomputes the whole prefix so changing developing OHLCV does not
accumulate phantom outcomes across polls, consistent with Pine rollback.
BUY and Sell alert-condition events are included in the API `alerts` array;
TradingView's alert delivery service is not reproduced by this application.

Visibility controls render supported chart intervals; ticks, seconds, ranges and
monthly chart feeds are unavailable here. Disabling visibility hides drawings,
colors and the table without changing calculations. The settings and custom
canvas renderer reproduce the source appearance; TradingView-specific fonts,
label spacing and native color picker widgets are approximated.

Exact numeric agreement with TradingView has **not** been certified against an
export from TradingView. It requires identical OHLCV, sessions, timeframe,
loaded history start and inputs. Different providers or a longer TradingView
prefix can change pivots, ATR, trade state and cumulative counts. The screenshot's
41/29 counts are reference output, not hardcoded values.

## Verification

`tests/test_suryavanshi.py` covers pivots, close-only Body breaks, same-bar
outcomes, simultaneous signals, consumed opposite breaks, ATR warmup, volume
thresholds, retained objects and scan/chart agreement. Existing option/stock
analysis tests, frontend cancellation tests and mocked Chrome browser smoke
cover integration and settings rendering on desktop/mobile.

Pine execution and array behavior references:
[execution model](https://www.tradingview.com/pine-script-docs/language/execution-model/),
[arrays](https://www.tradingview.com/pine-script-docs/language/arrays/).
