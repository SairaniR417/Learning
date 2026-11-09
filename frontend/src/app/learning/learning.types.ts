export interface LearningHeading { id: string; title: string; level: number; }
export interface LearningChapter {
  id: string; number: number; title: string; category: string; source: string; filename: string;
  sha256: string; minutes: number; words: number; tables: number; formulas: number; images: number;
  headings: LearningHeading[]; searchText: string; verifiedTextNodes: number;
}
export interface LearningManifest {
  version: number; importedOn: string; totalWords: number; totalDocuments: number;
  sources: { name: string; sha256: string; bytes: number }[]; chapters: LearningChapter[];
}
export interface LearningContent { id: string; html: string; text: string; headings: LearningHeading[]; }
export interface TradingCheck { id: string; title: string; detail: string; chapter: string; required?: boolean; }
export interface TradingCheckGroup { id: string; title: string; description: string; optionsOnly?: boolean; items: TradingCheck[]; }

export const TRADING_CHECKLIST: TradingCheckGroup[] = [
  { id: 'prepare', title: 'Before the market', description: 'Know the market and your own state of mind.', items: [
    { id: 'calm', title: 'I am calm and not trying to recover a loss.', detail: 'Pause if anger, fear or the urge to win money back is driving the decision.', chapter: 'the-mind-of-a-trader', required: true },
    { id: 'events', title: 'I have checked today’s important events.', detail: 'Note earnings, announcements and other events that could change the trade.', chapter: 'entry-planning-emotional-control', required: true },
    { id: 'trend', title: 'I know whether the market is trending or ranging.', detail: 'Compare the execution chart with a higher timeframe and the relevant index.', chapter: 'dow-theory' },
    { id: 'levels', title: 'I have marked the levels that matter to this setup.', detail: 'Use relevant support, resistance, supply/demand or session levels; do not add every indicator.', chapter: 'trendlines-supply-demand-support-resistance' },
    { id: 'gap', title: 'I have checked the opening gap and early price range.', detail: 'Know where the session opened and whether price is accepting or rejecting the early levels.', chapter: 'market-gaps' }
  ] },
  { id: 'risk', title: 'Protect the account', description: 'Write the loss limit before thinking about the profit.', items: [
    { id: 'limits', title: 'My risk per trade and daily loss limit are written down.', detail: 'Use your own tested risk plan. A percentage shown in a chapter is an example, not a required setting.', chapter: 'risk-position-sizing', required: true },
    { id: 'plan', title: 'My entry, stop-loss and target are clear.', detail: 'State what invalidates the setup and how you will exit if it does not move as expected.', chapter: 'entry-planning-emotional-control', required: true },
    { id: 'stop', title: 'The stop-loss fits the price structure and volatility.', detail: 'Check the technical level and volatility buffer; do not move a stop simply to fit a larger position.', chapter: 'volatility-atr', required: true },
    { id: 'size', title: 'My quantity or lot count fits the risk budget.', detail: 'Calculate risk from the traded instrument’s price and stop distance. For options, use the premium risk, not just the stock’s movement.', chapter: 'risk-position-sizing', required: true },
    { id: 'costs', title: 'I have allowed for charges, spread and possible slippage.', detail: 'Check that the planned reward still makes sense after the costs of entering and exiting.', chapter: 'risk-position-sizing', required: true }
  ] },
  { id: 'entry', title: 'Before clicking buy or sell', description: 'Check the conditions of your chosen setup.', items: [
    { id: 'setup', title: 'This trade matches a setup I have defined and practised.', detail: 'Name the setup and the evidence. A coloured signal or a high indicator score alone is not a tested edge.', chapter: 'entry-planning-emotional-control', required: true },
    { id: 'confirmation', title: 'The entry candle or breakout confirmation is complete.', detail: 'Follow your close, retest or hold rule. Do not treat a wick through a level as a confirmed breakout.', chapter: 'breakouts-pullbacks', required: true },
    { id: 'participation', title: 'I have checked volume and the quality of the move.', detail: 'Look for participation that supports the chosen setup, rather than an isolated price spike.', chapter: 'understanding-volume', required: true },
    { id: 'context', title: 'The price action, levels and chosen indicators agree.', detail: 'Check relevant trend and VWAP context. Do not count several similar indicators as independent proof.', chapter: 'vwap', required: true },
    { id: 'room', title: 'There is room to the target before the next obstacle.', detail: 'Check nearby support/resistance and compare the remaining reward with the planned risk.', chapter: 'trendlines-supply-demand-support-resistance', required: true }
  ] },
  { id: 'options', title: 'Extra checks for an options trade', description: 'The underlying chart and the option premium need separate checks.', optionsOnly: true, items: [
    { id: 'contract', title: 'I have selected the correct underlying, call/put, strike and expiry.', detail: 'Verify the exact contract and current lot size before placing an order.', chapter: 'options-1-the-basics', required: true },
    { id: 'premium', title: 'I understand the premium and moneyness I am paying for.', detail: 'Identify intrinsic versus time value and why this strike fits the intended move.', chapter: 'options-2-premium-moneyness', required: true },
    { id: 'greeks', title: 'I have checked time decay, volatility and directional sensitivity.', detail: 'Consider theta, IV/vega and delta/gamma together. A correct direction does not by itself ensure a profitable option trade.', chapter: 'options-3-the-greeks', required: true },
    { id: 'liquid', title: 'The option has usable bid/ask quotes and enough liquidity.', detail: 'Check the current spread and activity, not just an attractive last traded price.', chapter: 'open-interest-oi', required: true },
    { id: 'payoff', title: 'I can explain the payoff and worst-case loss of the whole position.', detail: 'Include all legs, expiry effects and the exit plan. Do not copy a ratio spread or another structure without understanding its exposure.', chapter: 'advanced-options-structures', required: true },
    { id: 'flow', title: 'I have checked whether option conditions fit the setup.', detail: 'Review IV, events, price and OI/PCR context; do not treat one reading as certainty about direction.', chapter: 'options-5-option-flow-edge-mapping', required: true }
  ] },
  { id: 'manage', title: 'While the trade is open', description: 'Follow the plan rather than the changing P&L.', items: [
    { id: 'protect', title: 'The stop and exit rules remain in place.', detail: 'Follow the planned stop, target, trailing or time-based exit. Record any rule-based change.', chapter: 'risk-position-sizing' },
    { id: 'discipline', title: 'I am not averaging a loser or increasing risk to recover money.', detail: 'If the plan is invalidated, follow the exit rather than inventing a new reason to hold.', chapter: 'trading-discipline-daily-routines' },
    { id: 'pause', title: 'I will stop when my loss limit or emotional limit is reached.', detail: 'Take the planned break. The next trade does not have to recover the previous one.', chapter: 'the-mind-of-a-trader' }
  ] },
  { id: 'review', title: 'After the trade', description: 'Save the evidence and one lesson for next time.', items: [
    { id: 'journal', title: 'I recorded the entry, exit, size, costs and result.', detail: 'Include the setup, stop and a screenshot so the decision can be reviewed later.', chapter: 'the-mind-of-a-trader' },
    { id: 'process', title: 'I reviewed whether I followed my rules.', detail: 'Separate a good process with a loss from a poor process with a lucky win.', chapter: 'trading-discipline-daily-routines' },
    { id: 'lesson', title: 'I noted my emotions and one improvement.', detail: 'Choose one specific habit to repeat or change in the next session.', chapter: 'entry-planning-emotional-control' }
  ] }
];
