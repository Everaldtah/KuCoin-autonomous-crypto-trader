# Changelog

## v4.0 — Smart Entry Edition (Current)

### Added
- **RSI(14) Indicator**: Wilder's smoothed RSI for oversold/overbought detection
- **EMA(9/21) Crossover**: Fast/slow exponential moving average for trend confirmation
- **Trail Exit**: Exits profitable positions when bearish reversal detected (RSI > 70 + bearish EMA)
- **Native HTTP Client**: `requests` library replaces all subprocess+curl calls (10x faster)
- **Environment Config**: All credentials/params in `.env` file
- **Server Timestamp Sync**: Caches KuCoin server time, adjusts for drift
- **Kline Fetcher**: Pulls 30x 1h candles for indicator calculations

### Changed
- Entry logic: Was "buy after 6 cycles" → Now requires RSI < 30 + bullish EMA crossover
- Exit logic: Was TP/SL only → Now includes trail exit on bearish signal
- Logging: Single write path (file-only when redirected, avoids duplicate lines)
- API performance: ~50ms per call (was ~300ms with subprocess+curl)

## v3.0 — Guard-Protected Edition

### Added
- **TradingGuard module**: Comprehensive safety wrapper
- Circuit breaker with exponential backoff (5 failures → cooldown)
- Daily loss limit ($5 default) with emergency stop
- Max position hold time (4 hours)
- Position-reality sync (detects stale state vs actual exchange balance)
- Log rotation (5MB max)
- API rate limiting (1 call/second)
- PID lockfile to prevent duplicate processes

### Changed
- All critical paths wrapped in guard checks
- Guard state persisted to `guard_state.json`

## v2.5 — Always-On Edition

### Added
- Auto-recovery from crashes
- State persistence between restarts (`trader_state.json`)
- Basic buy/sell with take profit / stop loss
- Periodic status logging

### Fixed
- Position tracking survives bot restarts
- Balance sync on startup
