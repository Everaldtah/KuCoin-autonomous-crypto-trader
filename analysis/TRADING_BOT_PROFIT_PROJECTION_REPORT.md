================================================================================
  MULTI-PAIR TRADING BOT — PROFIT PROJECTION & RISK ANALYSIS
  Generated: 2026-04-19 17:18
  Starting Capital: £1,000 GBP
================================================================================

████████████████████████████████████████████████████████████████████████████████
EXECUTIVE SUMMARY
████████████████████████████████████████████████████████████████████████████████

Bot: KuCoin Multi-Pair Portfolio Trader v5.0 (Hephaestus)
Pairs Traded: 12 (BTC, ETH, SOL, LINK, AVAX, DOT, MATIC, UNI, AAVE, ATOM, ADA, DOGE)
Timeframe: 1-hour candles
Strategy: Ensemble technical indicators (RSI, EMA, MFI, MACD, Bollinger, SuperTrend, ADX)
Position Sizing: Quarter-Kelly with 15% max per pair
Historical Data: 12 months KuCoin OHLCV → Walk-forward OOS testing
Simulations: 10,000 Monte Carlo runs per scenario

DEPLOYMENT RECOMMENDATION: NO

At the 50th percentile (median), the bot projects:
  → 1-month:  £927.27  (-7.3%)
  → 3-month:  £781.80  (-21.8%)
  → 6-month:  £563.59  (-43.6%)

At the 5th percentile (adverse but plausible):
  → 6-month:  £514.99  (-48.5%)

At the 95th percentile (favourable):
  → 6-month:  £617.82  (-38.2%)

Risk of losing >50% of capital: 1.4%
Risk of ≥20% drawdown:         100.0%
Median max drawdown:            43.9%


████████████████████████████████████████████████████████████████████████████████
METHODOLOGY NOTE
████████████████████████████████████████████████████████████████████████████████

This analysis uses WALK-FORWARD backtesting to ensure all results are out-of-sample:
  • Training window: 6 months (indicator calibration)
  • Test window: 2 months (simulated trading)
  • Step: 2 months (rolling forward)
  • Only test-window results feed Monte Carlo projections

All returns are NET of:
  • KuCoin taker fees (0.1% per side × 2 = 0.2% total)
  • Estimated slippage: 0.05% (liquid pairs) / 0.15% (low-liquidity)
  • Fee + slippage total: ~0.25-0.45% per round-trip trade

Monte Carlo resamples trades in correlation-respecting blocks to avoid
underestimating drawdowns when correlated assets move together.


████████████████████████████████████████████████████████████████████████████████
PER-PAIR PERFORMANCE (Out-of-Sample)
████████████████████████████████████████████████████████████████████████████████

Pair        Trades    Win%  Avg Win  Avg Loss      PF  Trades/Day   Status
--------------------------------------------------------------------------------
ATOM-USDT      271   37.6%    2.16%    -1.90%    1.06       1.51       ✅
AVAX-USDT      270   37.0%    2.25%    -1.82%    1.05       1.50       ✅
AAVE-USDT      318   36.5%    2.18%    -1.98%    1.04       1.77       ✅
SOL-USDT       269   36.4%    2.22%    -1.86%    1.03       1.49       ✅
UNI-USDT       313   36.4%    2.34%    -1.80%    1.04       1.74       ✅
DOT-USDT       289   35.3%    2.27%    -1.80%    0.95       1.61      ⚠️
ETH-USDT       235   34.9%    2.11%    -1.93%    0.96       1.31      ⚠️
ADA-USDT       282   34.4%    2.35%    -1.78%    0.94       1.57      ⚠️
LINK-USDT      257   34.2%    2.42%    -1.80%    0.98       1.43      ⚠️
DOGE-USDT      260   34.2%    2.28%    -1.79%    0.90       1.44      ⚠️
BTC-USDT       169   33.1%    2.11%    -1.90%    0.93       0.94      ⚠️

████████████████████████████████████████████████████████████████████████████████
MONTHLY PROJECTION TABLES — ALL SCENARIOS
████████████████████████████████████████████████████████████████████████████████

────────────────────────────────────────────────────────────
  BASE SCENARIO
────────────────────────────────────────────────────────────
  Percentile                     1 Month        3 Months        6 Months
  ────────────────────── ─────────────── ─────────────── ───────────────
  5th (low-end)                  £919.16         £757.49         £514.99
  25th                           £923.84         £771.53         £543.07
  50th (median/average)          £927.27         £781.80         £563.59
  75th                           £930.77         £792.31         £584.62
  95th (high-end)                £936.30         £808.91         £617.82

  Risk Metrics:
    Prob ≥20% drawdown:     100.0%
    Prob ≥30% drawdown:     100.0%
    Prob ≥50% drawdown:     1.7%
    Prob losing >50%:       1.4%
    Median max drawdown:    43.9%
    95th pct max drawdown:  48.7%

────────────────────────────────────────────────────────────
  CONSERVATIVE SCENARIO
────────────────────────────────────────────────────────────
  Percentile                     1 Month        3 Months        6 Months
  ────────────────────── ─────────────── ─────────────── ───────────────
  5th (low-end)                £1,000.00       £1,000.00       £1,000.00
  25th                         £1,000.00       £1,000.00       £1,000.00
  50th (median/average)        £1,000.00       £1,000.00       £1,000.00
  75th                         £1,000.00       £1,000.00       £1,000.00
  95th (high-end)              £1,000.00       £1,000.00       £1,000.00

  Risk Metrics:
    Prob ≥20% drawdown:     0.0%
    Prob ≥30% drawdown:     0.0%
    Prob ≥50% drawdown:     0.0%
    Prob losing >50%:       0.0%
    Median max drawdown:    0.0%
    95th pct max drawdown:  0.0%

────────────────────────────────────────────────────────────
  ADVERSE SCENARIO
────────────────────────────────────────────────────────────
  Percentile                     1 Month        3 Months        6 Months
  ────────────────────── ─────────────── ─────────────── ───────────────
  5th (low-end)                £1,000.00       £1,000.00       £1,000.00
  25th                         £1,000.00       £1,000.00       £1,000.00
  50th (median/average)        £1,000.00       £1,000.00       £1,000.00
  75th                         £1,000.00       £1,000.00       £1,000.00
  95th (high-end)              £1,000.00       £1,000.00       £1,000.00

  Risk Metrics:
    Prob ≥20% drawdown:     0.0%
    Prob ≥30% drawdown:     0.0%
    Prob ≥50% drawdown:     0.0%
    Prob losing >50%:       0.0%
    Median max drawdown:    0.0%
    95th pct max drawdown:  0.0%

████████████████████████████████████████████████████████████████████████████████
CORRELATION RISK ANALYSIS
████████████████████████████████████████████████████████████████████████████████

  Pair clusters detected (correlation > 0.6 — move together):
    Cluster 1: BTC-USDT, ETH-USDT, SOL-USDT, LINK-USDT, AVAX-USDT, UNI-USDT
    Cluster 2: DOT-USDT, ETH-USDT, SOL-USDT, LINK-USDT, AVAX-USDT, UNI-USDT, AAVE-USDT, DOGE-USDT
    Cluster 3: ATOM-USDT
    Cluster 4: ADA-USDT

  ⚠️ When BTC dumps, most altcoin pairs will dump simultaneously.
  The bot's correlation matrix is used to reduce position sizing
  when multiple highly-correlated pairs show BUY signals.


████████████████████████████████████████████████████████████████████████████████
POSITION SIZING RECOMMENDATION
████████████████████████████████████████████████████████████████████████████████

  Kelly Criterion (full):  -17.33% of capital per trade
  Recommended fraction:    half_Kelly
  Max position size:       -8.7% of portfolio per pair
  Max £ per trade (initially): £-86.66

  Note: Quarter-Kelly is recommended over Full or Half-Kelly because:
    1. £1,000 is a relatively small capital base — ruin risk is high at full Kelly
    2. Crypto markets are fat-tailed — extreme moves happen more often than normal dist assumes
    3. Conservative sizing preserves capital for compounding over the 6-month horizon


████████████████████████████████████████████████████████████████████████████████
CAVEATS & LIMITATIONS
████████████████████████████████████████████████████████████████████████████████

  1. BACKTESTING BIAS: Walk-forward analysis minimises but does not eliminate
     in-sample optimisation. Real performance may differ by ±15-30%.

  2. REGIME CHANGE: 2022-2023 historical data may not reflect current market
     conditions (post-halving bull markets behave differently).

  3. BLACK SWANS: No model captures black swan events (exchange hacks, stablecoin
     depegs, regulatory bans, force majeure). The "adverse" scenario is not
     the worst-case scenario.

  4. SLIPPAGE: Real-world slippage on large orders in low-liquidity pairs may
     exceed the 0.15% estimate used here, especially during volatile periods.

  5. API DOWNTIME: Bot does not trade during API outages, downtime, or rate
     limit hits. This creates unfilled signals that are not captured in backtest.

  6. FEE TIER: Default KuCoin fee tier (0.1% maker/taker) assumed. If you've
     traded >$100k on KuCoin, your fees may be lower, improving returns.

  7. WITHDRAWAL/FUNDING: GBP deposit/withdrawal spreads (£20-30 per transaction)
     materially affect ROI at the £1,000 capital level. Budget £50-100 for this.

  8. BOT BUGS: The current bot has known issues (position sizing errors,
     order increment failures). These degrade real returns vs. backtest.

  9. CORRELATION INSTABILITY: Correlations shift over time. The static 0.6
     threshold may misclassify pairs during regime changes.

  10. MONTE CARLO ASSUMPTIONS: Resampling with replacement assumes historical
      trade outcomes are independently drawable. In reality, trades cluster
      in time and correlate across pairs in ways that amplify drawdowns.


████████████████████████████████████████████████████████████████████████████████
FINAL RECOMMENDATION
████████████████████████████████████████████████████████████████████████████████

  Deploy? NO

  The median projection (£563.59 at 6 months, +-43.6%)
  is positive but modest. At the 5th percentile, you could lose
  49% of your capital.

  BOT ISSUES THAT MUST BE FIXED BEFORE DEPLOYING £1,000:
  ─────────────────────────────────────────────────────────
  1. "Order size increment invalid" errors — bot cannot place trades
  2. $0 USDT balance detection bug (fixed Apr 17 but verify)
  3. Position sizes calibrated for $1,000 when only $71 is deposited

  If you deposit £1,000 TODAY, the bot will likely:
  ✅ Trade (once order size bugs are fixed)
  ⚠️ Have lower win rate than backtest (real fees, slippage, spread)
  ⚠️ Experience correlated drawdowns across all pairs simultaneously
  ⚠️ Generate returns that trail backtest by 20-40%

  RECOMMENDED DEPLOYMENT SEQUENCE:
  1. Fix all bot bugs first (order sizing, balance detection)
  2. Run in dry-run mode for 2 weeks to verify signal quality
  3. Deposit £500 initially (NOT £1,000)
  4. Monitor for 30 days; if drawdown < 10% and win rate > 50%, add remaining £500
  5. Set up daily P&L reports to Telegram for monitoring

  The bot has potential but current implementation needs hardening before
  significant capital is deployed.


================================================================================
  Report generated: 2026-04-19 17:18
  Data sources: KuCoin API, bot source code, 12-month OHLCV history
================================================================================