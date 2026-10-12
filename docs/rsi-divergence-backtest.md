# RSI divergence backtest results

Run: October 12, 2026. Universe: 2,701 currently active NSE instruments with stored daily history. Last available session: October 9, 2026 (India time). Up to 1,500 bars per instrument; start dates vary. Fixed holdout boundary: January 1, 2024. Runtime: 97.85 seconds.

**Finding: every tested holdout scenario had a negative average net trade return. These rules do not establish a profitable standalone trading strategy.**

The default three-bar pivots were predeclared. Five-bar pivots provide a sensitivity comparison; holdout results were not used to choose defaults. Breakout confirmation describes observed price action, not a profitability score.

## Holdout results

| Pivot bars | Entry | Pattern | Trades | Win % | Mean net % | Median net % | Profit factor |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 3 | confirmed | Hidden Bearish | 2,185 | 48.05 | -0.8898 | -0.4093 | 0.7719 |
| 3 | confirmed | Hidden Bullish | 1,717 | 41.70 | -0.7260 | -1.3647 | 0.8106 |
| 3 | confirmed | Regular Bearish | 2,813 | 46.57 | -1.2291 | -0.5778 | 0.6565 |
| 3 | confirmed | Regular Bullish | 2,534 | 40.53 | -1.0229 | -1.7154 | 0.7406 |
| 3 | detected | Hidden Bearish | 4,194 | 45.76 | -0.3115 | -0.9123 | 0.8890 |
| 3 | detected | Hidden Bullish | 4,139 | 36.63 | -0.6044 | -2.0265 | 0.7934 |
| 3 | detected | Regular Bearish | 5,898 | 45.02 | -0.4196 | -0.8233 | 0.8470 |
| 3 | detected | Regular Bullish | 5,852 | 35.94 | -0.8823 | -2.1385 | 0.7257 |
| 5 | confirmed | Hidden Bearish | 1,758 | 52.39 | -0.2767 | 0.5465 | 0.9252 |
| 5 | confirmed | Hidden Bullish | 1,528 | 43.39 | -0.5165 | -0.9121 | 0.8516 |
| 5 | confirmed | Regular Bearish | 2,358 | 47.07 | -1.1135 | -0.4207 | 0.6831 |
| 5 | confirmed | Regular Bullish | 2,167 | 38.90 | -1.2621 | -2.0190 | 0.6922 |
| 5 | detected | Hidden Bearish | 3,117 | 48.28 | -0.1532 | -0.3245 | 0.9491 |
| 5 | detected | Hidden Bullish | 3,190 | 39.91 | -0.5453 | -1.6172 | 0.8146 |
| 5 | detected | Regular Bearish | 5,402 | 46.46 | -0.5064 | -0.5584 | 0.8233 |
| 5 | detected | Regular Bullish | 5,344 | 35.46 | -0.9870 | -2.1935 | 0.7070 |

Net returns deduct 0.20% round-trip costs. The JSON report also includes 0.50% cost stress, development-period results, exit reasons and directional 10-bar forward returns. Samples are distinct per scenario, not a combined portfolio. Win rate alone does not establish profitability.

## Assumptions and limits

Last 1500 completed daily candles per currently active NSE instrument; 250-bar warm-up; next-open entry; pivot stop buffered 0.1%; 2R target; 10-bar timeout; stop first on ambiguous bars; 20bps round-trip costs; one position per symbol within each scenario. Bearish trades are hypothetical shorts, not executable cash delivery trades. Current-universe survivorship bias, raw corporate-action prices, gaps, liquidity and historical slippage remain limitations. Segments reset on >25% close jumps, bad OHLC, >10-day gaps. No portfolio equity or annualized return claim.

Prices are not independently audited or adjusted for corporate actions. Conservative stop-first treatment may change results when daily OHLC cannot establish intrabar order. Same-symbol trades do not overlap; trades in different symbols can be correlated. No liquidity screen or market-regime optimization was added after seeing the holdout. Bearish results describe hypothetical shorts, not cash delivery execution.

Read the [research/specification](rsi-divergence.md) and [raw report](../data/rsi-divergence-backtest.json). Re-run `.venv/Scripts/python.exe -m scanner.backtest_rsi_divergence` after updating history.
