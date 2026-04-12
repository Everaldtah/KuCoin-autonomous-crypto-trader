# Architecture

## System Overview (v5.0)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Server (root)                                    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                    trader.py v5.0 (ConfluenceTrader)               │  │
│  │                                                                    │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐   │  │
│  │  │ KucoinClient │  │  indicators  │  │    strategy.py         │   │  │
│  │  │              │  │    .py       │  │                        │   │  │
│  │  │ get()        │  │              │  │ ConfluenceEngine       │   │  │
│  │  │ post()       │  │ RSI(14)      │  │  score_rsi/macd/bb/... │   │  │
│  │  │ timestamp    │  │ MACD(12,26,9)│  │  generate_signal()     │   │  │
│  │  │              │  │ BB(20,2)     │  │                        │  │  │
│  │  │              │  │ ATR(14)      │  │ RegimeSwitcher         │   │  │
│  │  │              │  │ StochRSI     │  │  detect_regime()       │   │  │
│  │  │              │  │ ADX(14)      │  │  get_strategy_params() │   │  │
│  │  │              │  │ Ichimoku     │  │                        │   │  │
│  │  │              │  │ VWAP         │  │ TimeframeData          │   │  │
│  │  │              │  │ Volume       │  │  1H(w=1.0)            │   │  │
│  │  │              │  │ Regime Det.  │  │  4H(w=1.5)            │   │  │
│  │  │              │  │              │  │  1D(w=2.0)            │   │  │
│  │  │              │  │              │  │                        │   │  │
│  │  └──────────────┘  └──────────────┘  └────────────────────────┘   │  │
│  │                                                                    │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐   │  │
│  │  │ risk_manager │  │trading_guard │  │   backtester.py        │   │  │
│  │  │    .py       │  │    .py       │  │                        │   │  │
│  │  │              │  │              │  │ Backtester             │   │  │
│  │  │ KellyCriter  │  │ Circuit Brkr │  │  run(candles, strat)   │   │  │
│  │  │  optimal()   │  │ Daily Loss % │  │  walk_forward()        │   │  │
│  │  │  safe()      │  │ Max Hold     │  │                        │   │  │
│  │  │              │  │ Pos Sync     │  │ Metrics:               │   │  │
│  │  │ ATRStops     │  │ Rate Limit   │  │  Sharpe/Sortino        │   │  │
│  │  │  stop_loss() │  │ PID Lock     │  │  Max Drawdown          │   │  │
│  │  │  take_profit │  │ Log Rotation │  │  Profit Factor         │   │  │
│  │  │  trailing()  │  │ Correlation  │  │  Win Rate              │   │  │
│  │  │              │  │ Drawdown %   │  │  Avg Hold Time         │   │  │
│  │  │ RiskManager  │  │              │  │                        │   │  │
│  │  │  validate()  │  │              │  │                        │   │  │
│  │  │  pos_size()  │  │              │  │                        │   │  │
│  │  └──────────────┘  └──────────────┘  └────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│           │                              │                               │
│     data/trader_state.json         data/bot_state.json                  │
│     data/guard_state.json          (dashboard snapshot)                 │
│     logs/bot.log                                                         │
└──────────────────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
   KuCoin API                    Telegram API
   (REST/v1)                     (Bot notifications)
```

## Signal Flow

```
1. Fetch candles (1H, 4H, 1D)
2. Run AdvancedIndicators.compute_all() for each timeframe
3. Build TimeframeData with weights (1H=1.0, 4H=1.5, 1D=2.0)
4. ConfluenceEngine.generate_signal() scores all indicators:
   - RSI → -1 to +1 (weight 15%)
   - MACD → -1 to +1 (weight 20%)
   - Bollinger → -1 to +1 (weight 12%)
   - EMA Cross → -1 to +1 (weight 18%)
   - ADX → -1 to +1 (weight 10%)
   - Volume → -1 to +1 (weight 10%)
   - StochRSI → -1 to +1 (weight 8%)
   - Ichimoku → -1 to +1 (weight 7%)
5. Weighted average → final score (-2 to +2)
6. Signal: STRONG_BUY(≥1.5) | BUY(≥0.5) | NEUTRAL | SELL | STRONG_SELL
7. Confidence = |score| / 2.0 (higher = more agreement)
8. Regime detection adjusts TP/SL/size/confidence threshold
9. RiskManager validates trade (Kelly sizing, daily loss, drawdown)
10. Execute with ATR-based stops + trailing stop
```

## Module Details

### indicators.py — AdvancedIndicators
Pure numpy calculations, no external TA libraries.
- **RSI(14)**: Wilder's smoothed method
- **MACD(12,26,9)**: Standard with signal line crossover
- **Bollinger Bands(20,2)**: With %B and bandwidth
- **ATR(14)**: Wilder's smoothed Average True Range
- **Stochastic RSI(14,14,3,3)**: RSI of RSI with K/D smoothing
- **ADX(14)**: Trend strength with +DI/-DI direction
- **Ichimoku**: Tenkan/Kijun/Senkou/Chikou
- **VWAP**: Volume-weighted average price
- **Volume Analysis**: Ratio vs MA, spike detection, trend
- **Regime Detection**: Trending up/down, ranging, volatile
- **compute_all()**: Single call returns comprehensive dict

### strategy.py — ConfluenceEngine + RegimeSwitcher
- Weighted indicator scoring (-1 to +1 each)
- Multi-timeframe confluence (weighted average)
- Confidence calculation (cross-timeframe agreement)
- Market regime detection with strategy parameter adjustment
- 5 regimes: strong_trend, weak_trend, ranging, volatile, quiet

### risk_manager.py — KellyCriterion + ATRStops + RiskManager
- **Kelly Criterion**: optimal_fraction(), safe_fraction() (half-Kelly)
- **ATR Stops**: Dynamic SL/TP based on volatility
- **Trailing Stop**: Ratcheting trail that only tightens
- **RiskManager**: Pre-trade validation, daily loss, drawdown, circuit breaker

### backtester.py — Backtester
- Event-driven simulation with realistic slippage and fees
- Walk-forward validation (sliding window)
- Metrics: Sharpe ratio, Sortino ratio, max drawdown, profit factor
- Trade tracking with entry/exit indicators

### trading_guard.py — TradingGuard (v1.1)
- Circuit breaker with exponential backoff
- Fixed + percentage-based daily loss limits
- Portfolio drawdown tracking with high-water mark
- Position-reality sync (detects stale state)
- Correlation risk (rapid-loss cluster detection)
- Log rotation, rate limiting, PID lockfile

## File Structure

```
src/
├── trader.py           # v5.0 main loop (ConfluenceTrader)
├── indicators.py       # Advanced technical indicators
├── strategy.py         # Multi-TF confluence engine + regime switcher
├── risk_manager.py     # Kelly Criterion, ATR stops, risk validation
├── backtester.py       # Historical simulation engine
├── trading_guard.py    # Safety wrapper (v1.1)
└── bot_state_server.py # Dashboard state API (HTTP :8080)

config/
└── .env.example        # Configuration template

data/                   # Runtime state (gitignored)
├── trader_state.json
├── guard_state.json
├── bot_state.json
└── bot.pid

logs/                   # Runtime logs (gitignored)
└── bot.log

scripts/
└── trader_daemon.sh    # Auto-restart watchdog

versions/
├── trader_v2.py        # Archived basic bot
└── trader_v3.py        # Archived guard-protected bot
```
