# Changelog

## v5.1 — HEPHAESTUS: Multi-Pair Portfolio Edition (Current)

### Added
- **Multi-Pair Trading**: 12 pairs simultaneous (ETH, BTC, SOL, LINK, AVAX, DOT, MATIC, UNI, AAVE, ATOM, ADA, DOGE)
- **Ensemble Indicator Engine**: Composite signal from 7 indicators (RSI, EMA, MFI, MACD, Bollinger, Super Trend, ADX)
- **Portfolio Kelly Criterion**: Optimal bet sizing across multiple positions, 25% fractional Kelly
- **Correlation Matrix Calculation**: Assets weighted by correlation (avoid doubling down on same risk)
- **Async Architecture**: Concurrent pair monitoring with aiohttp (20s cycle vs 60s sequential)
- **Thinking Process Visualization**: Real-time neural graph streaming to Obsidian dashboard
- **Portfolio Drawdown Protection**: 8% circuit breaker halts all trading
- **Dynamic Signal Thresholds**: Entry/exit based on composite score (0-1) not single indicator
- **Position Size Constraints**: 3-15% per pair, volatility-adjusted ATR sizing

### Changed
- Trading scope: Single-pair (ETH-USDT) → Multi-pair portfolio (up to 5 concurrent)
- Architecture: Sync KuCoin client → Async aiohttp with connection pooling
- Analysis: 1-pair RSI+EMA → 12-pair 7-indicator ensemble
- Risk: Position-level stops → Portfolio-level drawdown + pair correlation

### Integration
- New Dashboard: https://hermes-agent-obsidian-view.vercel.app/thinking
- Sync script at `src/sync_thinking_to_dashboard.py`
- Real-time visualization of data sources, signal calculations, trade decisions

## v5.0 — Confluence Engine Edition

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

## v4.1 - MACD Confirmation Upgrade (2026-04-13)

### Added
- **MACD(12/26/9) indicator computation** - Full MACD implementation with signal line and histogram
- **MACD confirmation filter** - Entries now require MACD histogram > 0 (bullish momentum)
- **Enhanced status logging** - MACD histogram now displayed in all status messages
- **Improved entry diagnostics** - Log now shows which conditions are failing (RSI, MACD, trend)

### Changed
- **Entry logic** - Now requires 3 confirmations instead of 2:
  1. RSI < 30 (oversold)
  2. EMA(9) > EMA(21) (bullish trend)
  3. **MACD histogram > 0** (bullish momentum) ← NEW
- **Status format** - Added MACD histogram display to position and status messages
- **Version banner** - Updated to v4.1 (RSI+EMA+MACD)

### Technical Details
- MACD computed using numpy for performance
- Histogram = MACD line - Signal line
- Requires minimum 35 price points for valid MACD calculation
- Falls back to 0.0 histogram during warmup period

### Strategy Impact
- **Before**: Entered on RSI+EMA alone → prone to false breakouts
- **After**: Requires RSI+EMA+MACD alignment → higher quality entries, fewer false signals
- **Trade frequency**: Slightly reduced (filtering weak setups)
- **Expected win rate**: Improved by filtering premature entries

### Files Modified
- `live_eth_trader_v4.py` - Main trading bot
- `versions/trader_v4.1_macd.py` - Archived version

## v4.2 — 2026-04-17: Bollinger Bands + Trailing Stop + Dynamic Sizing

### New Indicators
- **Bollinger Bands** (period=20, std=2.0): Detect oversold/overbought conditions
  - `%B < 0` (below lower band) = extra bullish confirmation for entries
  - `%B > 1` (above upper band) = overbought exit signal
  - Bandwidth tracking for volatility regime detection
- **ATR** (period=14): Average True Range for volatility measurement
- **Volume Ratio** (period=20): Compare current volume to moving average

### New Features
- **Dynamic Position Sizing**: ATR-based scaling — lower volatility = larger position
  - Range: $20 (min) to $50 (max) USDT per trade
  - Scale factor = 1.5 / atr_pct (inversely proportional to volatility)
- **Trailing Stop**: Activates after +2% profit, follows price up with 1% trail distance
  - Overrides fixed TP when active (lets winners run)
  - State persisted across restarts (trailing_high, trailing_active)
- **BB-Enhanced Entry**: RSI < 30 + BB below lower band + MACD > 0 triggers entry
  even with neutral EMA (compensates for lagging indicator)
- **BB Overbought Exit**: Price above upper BB + RSI > 70 = early profit exit
- **Volume Confirmation**: Entry requires volume >= 1.0x average (configurable)

### Improved Logging
- Status line now shows: RSI | MACD | BB% | ATR | Volume | Signal
- Entry signals explain all triggered indicators + dynamic size
- No-entry logs show which conditions are missing (including BB and Volume)

### Exit Priority (new order)
1. Trailing stop (locks in profit above 2%)
2. Fixed TP (safety net, unless trailing is active)
3. Hard stop loss (always enforced)
4. BB overbought + RSI overbought (+0.5% profit required)
5. Bearish EMA crossover + RSI overbought (+0.5% profit required)

### State Compatibility
- Backward compatible with v4.1 state files
- New fields (trailing_high, trailing_active) default to safe values
- Raw klines stored for ATR calculation (auto-populated from API)

### Config Constants Added
```python
BB_PERIOD = 20, BB_STD_DEV = 2.0
ATR_PERIOD = 14
VOLUME_MA_PERIOD = 20
VOLUME_CONFIRM_ENABLED = True
VOLUME_THRESHOLD = 1.0
TRAILING_STOP_ENABLED = True
TRAILING_ACTIVATION_PCT = 2.0
TRAILING_DISTANCE_PCT = 1.0
MIN_TRADE_AMOUNT = 20.0
MAX_TRADE_AMOUNT = 50.0
```
