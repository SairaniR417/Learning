# RSI divergence: research and specification

RSI is Wilder's momentum oscillator, ranging from 0 to 100. Default period: 14 closes. Seed average gains/losses with the first 14 price changes, then smooth each with `(previous_average * 13 + current_change) / 14`. Compute `100 - 100 / (1 + average_gain / average_loss)`. No losses gives 100; no gains gives 0; a completely flat series uses 50. Warm up for at least 250 bars before identifying swings.

30 and 70 are traditional oversold/overbought reference levels, not automatic buy/sell instructions. RSI can stay extreme in strong trends. The 50 line provides momentum context. Failure swings, centerline crossings and an oversold bounce are different patterns from divergence.

| Pattern | Price swings | RSI at those swings | Interpretation |
| --- | --- | --- | --- |
| Regular bullish | Lower low | Higher low | Potential upward reversal |
| Regular bearish | Higher high | Lower high | Potential downward reversal |
| Hidden bullish | Higher low | Lower low | Potential uptrend continuation |
| Hidden bearish | Lower high | Higher high | Potential downtrend continuation |

References reviewed October 12, 2026:

- [StockCharts ChartSchool: RSI](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi): Wilder calculation, regular divergences, Cardwell positive/negative reversals (commonly called hidden divergences), trend context and failure swings.
- [Fidelity: RSI](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI): traditional levels, persistent extremes and trend ranges.
- [TradingView: RSI divergence](https://www.tradingview.com/support/solutions/43000589127-rsi-divergence-indicator/): divergence limitations and confirmation.
- [StockCharts: scanning divergences](https://help.stockcharts.com/scanning-and-alerts/scan-writing-resource-center/scanning-case-studies/scanning-for-divergences): swing detection, noise and delay.

## Our explicit scanner convention

There is no universal numeric definition of a meaningful swing, minimum separation, or breakout confirmation. The settings below are engineering choices, not claims that these numbers are universally standard or optimized.

- Daily completed NSE candles; no current-session bars, no live intraday RSI claim.
- Strict price low/high pivots with 3 bars on each side. Equal-price plateaus are excluded.
- Compare consecutive pivots of the same kind, 5–60 bars apart. RSI is sampled **at the price pivot dates**; separate RSI extrema need not occur on those exact dates. This may differ from TradingView oscillator-pivot scripts.
- Price difference at least 0.5%; RSI difference at least 3 points. Flat/equal swings do not qualify.
- Hidden bullish: close above SMA50 and SMA50 higher than five bars earlier, at the second pivot. Hidden bearish requires the opposite. Regular patterns have no mandatory trend filter.
- Traditional 30/70 proximity is displayed as context; it is not required for every divergence.
- **WATCH**: both price pivots confirmed, divergence detected, breakout not confirmed.
- **BULLISH CONFIRMED**: a close above the highest high between the two lows. **BEARISH CONFIRMED**: a close below the lowest low between the two highs. Breakout must occur within 20 bars after detection, and never before detection time.
- A low below the second bullish pivot or high above the second bearish pivot invalidates the setup. Invalidation takes precedence if the same candle also crosses the trigger. Expired/broken patterns are omitted from current results.
- Show only detections or breakout confirmations from the last 5 stored bars; display the latest stored date so old data is visible. Show one most recent applicable pattern per stock, not duplicate stock rows.
- Dates distinguish pivot time, detected time and breakout time. No retroactive signal at the second pivot.
- Reset history around malformed/non-finite OHLC, duplicate timestamps, close changes greater than 25%, or gaps greater than 10 calendar days. These resets avoid bridging suspected corporate actions/data gaps but can omit legitimate large moves. Raw prices are not automatically adjusted.

## Backtest protocol

`scanner/backtest_rsi_divergence.py` reuses the detector. It reads the latest 1,500 completed daily bars per currently active NSE instrument without changing the database. Two predeclared swing widths (3 and 5) are evaluated; other settings stay fixed. January 1, 2024 is the chronological development/holdout boundary. No parameters are selected using holdout results.

Detection-entry and breakout-entry scenarios are reported separately, by divergence type and sample. Entry is at the **next bar's open**, never the historical pivot price. A 0.1% buffered second-pivot stop, 2R target and 10-bar time exit provide a reproducible simulation. Stops take precedence when both stop and target touch within one daily candle; gap stops fill at the open. Deduct 20 basis points round trip; also report stress results at 50 basis points. Skip entry gaps already beyond the stop, incomplete outcome windows and trades crossing the sample boundary. Positions do not overlap for a given symbol/scenario. Report counts, mean/median net trade returns, win rate, profit factor and 10-bar directional forward returns.

The raw JSON report is `data/rsi-divergence-backtest.json`. Its results are evidence about these specific rules and this dataset, not portfolio performance or a profitability guarantee. No CAGR, Sharpe or portfolio drawdown is invented. Limitations include current-universe survivorship bias, cross-stock correlated trades, unknown historical corporate-action adjustment, missing/delisted securities, optimistic fillability in illiquid/limit-bound stocks, and fixed-cost assumptions. Bearish simulations are hypothetical shorts: overnight cash delivery shorting is not represented as an executable product flow. Signals are observations; no orders are placed.

Run the study with `.venv/Scripts/python.exe -m scanner.backtest_rsi_divergence`. Results depend on the stored data revision and date. Run tests with `.venv/Scripts/python.exe -m unittest tests.test_rsi_divergence -v`.
