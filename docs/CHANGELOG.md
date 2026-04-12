# Changelog

## v5.0 — Confluence Engine Edition (Current)

### Added
- **Multi-Timeframe Confluence Engine**: Weighted scoring across 1H, 4H, 1D timeframes
- **Advanced Indicators Module**: MACD(12,26,9), Bollinger Bands(20,2), ATR(14), Stochastic RSI, ADX, Ichimoku Cloud, VWAP, Volume Analysis
- **Regime Detection**: Auto-detects market state (strong_trend, weak_trend, ranging, volatile, quiet) and adjusts strategy
- **Kelly Criterion Position Sizing**: Professional 1-2% risk per trade (was 34%!)
- **ATR-Based Dynamic Stops**: Stop loss and take profit adapt to market volatility
- **Trailing Stops**: Ratchet profits in trending markets with ATR-based trail
- **Backtester Engine**: Full historical simulation with walk-forward validation, Sharpe/Sortino/max DD metrics
- **Signal Scoring**: Individual indicators scored -1 to +1, weighted across timeframes for confluence
- **Multi-Pair Support**: Configurable trading pair via TRADING_PAIR env variable
- **Correlation Risk Detection**: Rapid-loss cluster detection with escalating cooldowns
- **Portfolio Drawdown Tracking**: High-water mark drawdown protection
- **Percentage-Based Daily Loss**: Daily loss limits as % of balance (not just fixed $)

### Changed
- Entry logic: Was RSI<30 + EMA crossover → Now multi-TF confluence score + regime confidence threshold
- Exit logic: Was fixed TP/SL → Now ATR-based dynamic stops + trailing stops + regime-based exit
- Position sizing: Was fixed $25 → Now Kelly Criterion scaled by regime (1-2% risk)
- Architecture: Monolithic trader → Modular (indicators.py, strategy.py, risk_manager.py, backtester.py)

### Fixed
- Position sizing no longer risks 34% per trade on small accounts
- Duplicate log lines eliminated (single write path)
- State persistence includes peak balance for drawdown tracking

## v4.0 — Smart Entry Edition

### Added
- RSI(14) oversold/overbought detection
- EMA(9/21) crossover trend confirmation
- Native HTTP client (requests library, 10x faster than curl)
- Environment-based credentials (.env file)

## v3.0 — Guard-Protected Edition

### Added
- TradingGuard safety wrapper with circuit breaker
- Daily loss limit, max hold time, position sync
- Log rotation, API rate limiting, PID lockfile

## v2.5 — Always-On Edition

### Added
- Auto-recovery from crashes, state persistence
- Basic buy/sell with fixed TP/SL
