# Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         Server (root)                            │
│                                                                  │
│  ┌─────────────────────┐    ┌─────────────────────────────────┐ │
│  │   trader.py (v4)    │    │       trading_guard.py          │ │
│  │                     │    │                                 │ │
│  │  ┌───────────────┐  │    │  ┌──────────────────────────┐  │ │
│  │  │ KucoinClient  │  │◄───┤  │ acquire_lock()           │  │ │
│  │  │ - get()       │  │    │  │ check_health()           │  │ │
│  │  │ - post()      │  │    │  │ pre_trade_check()        │  │ │
│  │  │ - timestamp   │  │    │  │ record_trade()           │  │ │
│  │  └───────────────┘  │    │  │ sync_position()          │  │ │
│  │                     │    │  │ circuit breaker           │  │ │
│  │  ┌───────────────┐  │    │  └──────────────────────────┘  │ │
│  │  │ TechnicalInd  │  │    └─────────────────────────────────┘ │
│  │  │ - compute_rsi │  │                                        │
│  │  │ - compute_ema │  │    ┌─────────────────────────────────┐ │
│  │  │ - trend_signal│  │    │      bot_state_server.py        │ │
│  │  └───────────────┘  │    │      (HTTP :8080)               │ │
│  │                     │    └─────────────────────────────────┘ │
│  │  ┌───────────────┐  │                                        │
│  │  │ SmartTrader   │  │    ┌─────────────────────────────────┐ │
│  │  │ - run()       │  │    │     trader_daemon.sh            │ │
│  │  │ - entry/exit  │──┼───►│     (watchdog)                  │ │
│  │  └───────────────┘  │    └─────────────────────────────────┘ │
│  └─────────────────────┘                                        │
│           │                                                      │
│     trader_state.json  (position, trades, P&L)                  │
│     bot_state.json     (dashboard snapshot)                     │
│     guard_state.json   (safety counters)                        │
└──────────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
   KuCoin API                    Telegram API
   (REST/v1)                     (Bot notifications)
```

## Component Details

### KucoinClient
Native HTTP client using `requests` library.
- Connection pooling (HTTPAdapter with 2 connections, max 4)
- Server timestamp caching (syncs every 30s, adjusts for drift)
- HMAC-SHA256 signing for authenticated endpoints
- Separate `get()`/`post()` methods with auto-auth

### TechnicalIndicators
Pure numpy calculations, no external TA libraries needed.
- **RSI(14)**: Wilder's smoothed method (initial SMA, then exponential)
- **EMA(9/21)**: Standard exponential moving average (multiplier = 2/(period+1))
- **trend_signal()**: Combines RSI + EMA into bullish/bearish/neutral signal
- Price history sourced from KuCoin 1h klines (30 candles), refreshed every 30 min

### SmartTrader (Main Loop)
10-second trading cycle:
1. Fetch current ETH price
2. Update technical indicators with latest price
3. Guard health check (loss limit, hold time, API health)
4. Position sync every 5 min (compare state vs exchange)
5. Execute entry/exit logic based on indicator signals
6. Save state + dashboard snapshot every 60s

### TradingGuard
Stateless safety layer that wraps around any trading bot.
- Persisted to `guard_state.json` (survives restarts)
- Daily counters auto-reset at midnight
- Thread-safe rate limiting with `threading.Lock`
- Standalone utilities: `--kill`, `--status`, `--reset`

### Daemon & State Server
- `trader_daemon.sh`: Bash watchdog, checks bot every 30s, auto-restarts on crash
- `bot_state_server.py`: Lightweight HTTP server on port 8080, serves JSON state for dashboards
