# Supplied Pine RSI Divergence

`docs/rsi-divergence.pine` preserves the identical scripts supplied on October 25,
2026. Live scanner, option analysis, stock RSI charts and Focused evidence use
`services/rsi_overlay.py`. Ghost Rider retains its own source-script RSI logic.

RSI uses Wilder RMA, first seeded with `length` changes. The script tests zero
losses before zero gains: a warmed-up flat series is 100. Source choices are
close/open/high/low/hl2/hlc3/ohlc4/hlcc4. Smoothing supports None, SMA, SMA + Bollinger
Bands, EMA, SMMA (RMA), WMA and volume-weighted MA. Bollinger deviation is the
population standard deviation, with the source multiplier default of 2.

Divergence uses RSI extrema with five bars to the left and five to the right.
A regular bullish event has a higher RSI low and a lower price low; bearish is
the converse. Compare consecutive same-kind RSI pivots. The source's
`barssince(found[1])` range of 5?60 corresponds to pivot separation of 6?61 bars.
Equal RSI does not qualify. An equal plateau chooses the rightmost extremum.
There are no hidden patterns, trend gates, minimum percentage/delta filters,
250-bar warmup, breakout conditions, stop losses or targets in this script.

A label is drawn five bars back on the RSI pivot; detection/confirmation time is
five bars later. App result cards preserve this distinction. Scanner freshness
(default 5 confirmation bars) is a result filter only; charts retain all events
within the loaded history. The source alertcondition events are the bullish and
bearish confirmations; importing this script does not subscribe users to alerts
or send messages.

The app preset enables Calculate Divergence and disables the 70/50/30 guide
lines to match the screenshots. The Pine input default itself is false and its
hline defaults visible. Defaults in the app restore the screenshot preset:
purple RSI, yellow SMA 14, dark background, purple band, green/red gradients,
and green Bull/red Bear labels. Settings have Defaults, Cancel and Ok and an
accessible keyboard focus trap. Style-only changes require no provider request.

Calculation timeframe defaults to Chart. The selectable feed intervals are 5m,
15m, 1h, 1d and 1w. Waiting for timeframe closes is enabled. Disabling it includes
a developing provider candle when available; signals may then repaint until it
closes. Weekly bars combine Monday-to-Sunday IST daily OHLCV and are final next
Monday. Stock charts read stored candles only. Missing history stays unavailable;
this app has no tick/second candle feed. Visibility preferences do not fetch data.
Different calculation timeframes are drawn on their own candle timestamps with
no forward-filled oscillator values (the Pine declaration uses timeframe_gaps).

Options retain their existing one-minute polling and shared bounded cache.
The cache includes every RSI calculation input, while history cache entries are
shared across settings. Leaving the chart cancels polling and browser requests.
A broker/data-feed difference, available history, or minute refresh can produce
values different from a TradingView live chart; no exported TradingView candle
parity dataset was supplied. No price forecast is inferred from divergence.

Validation: `python -m unittest discover -s tests -p test_pine_rsi.py`, option and
Focused integration tests, frontend lifecycle tests and mocked browser checks.
The original price-pivot research is in `rsi-divergence-legacy.md` and
`scanner/rsi_divergence_legacy.py`; the original backtest imports only that
archived detector, preserving reproducibility without using it in live views.
