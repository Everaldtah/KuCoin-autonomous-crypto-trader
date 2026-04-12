# KuCoin Autonomous Crypto Trader

Autonomous ETH-USDT trading bot with technical analysis indicators, safety guardrails, and real-time dashboard monitoring.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Trading Bot v4                    │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ KuCoin   │  │  Technical   │  │ Trading Guard │  │
│  │ API      │  │  Indicators  │  │ (Safety Layer)│  │
│  │ Client   │  │  RSI + EMA   │  │               │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
│       │              │                   │           │
│  ┌─────────────────────────────────────────────┐    │
│  │            Smart Trading Engine              │    │
│  │  Entry: RSI < 30 + Bullish EMA crossover    │    │
│  │  Exit:  TP + SL + Trail (RSI > 70 + Bear)   │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
         │                    │
    ┌────┴────┐        ┌─────┴──────┐
    │ Telegram │        │ Dashboard  │
    │ Alerts   │        │ State API  │
    └─────────┘        └────────────┘
```

## Features

### Smart Entry/Exit (v4)
- **RSI(14)**: Identifies oversold (<30) / overbought (>70) conditions
- **EMA(9/21) Crossover**: Confirms bullish/bearish trend direction
- **Trail Exit**: Locks in profits when bearish reversal detected while in profit
- **No random entries** — every trade requires indicator confirmation

### Trading Guard (v3)
- Duplicate process prevention (PID lockfile)
- Circuit breaker for API failures (exponential backoff)
- Daily loss limit ($5/day default)
- Max position hold time (4h default)
- Position-reality sync with exchange
- Log rotation (prevents disk fill)
- Rate limiting for API calls
- Emergency shutdown on catastrophic loss

### Infrastructure
- Native HTTP client (requests library — 10x faster than curl)
- Environment-based credentials (.env file)
- Auto-restart daemon with watchdog
- Real-time dashboard state API
- Telegram notifications for trades & alerts

## Quick Start

```bash
# 1. Install dependencies
pip install requests numpy

# 2. Configure credentials
cp config/.env.example config/.env
# Edit config/.env with your KuCoin API keys

# 3. Start the bot
python3 src/trader.py

# Or use the daemon for auto-restart:
bash scripts/trader_daemon.sh daemon
```

## Configuration

All configuration via environment variables (see `config/.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `KUCOIN_API_KEY` | - | KuCoin API key |
| `KUCOIN_API_SECRET` | - | KuCoin API secret |
| `KUCOIN_PASSPHRASE` | - | KuCoin API passphrase |
| `TRADE_AMOUNT` | 25.0 | USDT per trade |
| `TAKE_PROFIT_PCT` | 2.5 | Take profit % |
| `STOP_LOSS_PCT` | 1.5 | Stop loss % |
| `INITIAL_BALANCE` | 100.0 | Starting balance for P&L tracking |
| `RSI_OVERSOLD` | 30 | RSI buy threshold |
| `RSI_OVERBOUGHT` | 70 | RSI sell threshold |
| `TELEGRAM_TOKEN` | - | Telegram bot token |
| `TELEGRAM_CHAT_ID` | - | Telegram chat ID |

## Trading Logic

### Entry Conditions (ALL must be true)
1. RSI(14) < 30 (oversold)
2. EMA(9) > EMA(21) (bullish crossover)
3. Sufficient USDT balance

### Exit Conditions (ANY triggers)
1. Take Profit: Position +2.5%
2. Stop Loss: Position -1.5%
3. Trail Exit: RSI > 70 + bearish crossover + position profitable > 0.5%

### Guard Safety Limits
- Max daily loss: $5.00
- Max position hold: 4 hours
- Max consecutive API failures: 5 (circuit breaker)
- Max trades per hour: 10
- API rate limit: 1 call/second

## File Structure

```
├── src/
│   ├── trader.py              # Main trading bot (v4 — RSI+EMA)
│   ├── trading_guard.py       # Safety wrapper module
│   └── bot_state_server.py    # HTTP API for dashboard
├── config/
│   └── .env.example           # Configuration template
├── scripts/
│   └── trader_daemon.sh       # Auto-restart daemon
├── dashboard/                 # Next.js dashboard (separate)
├── versions/
│   ├── trader_v2.py           # Archive: v2 — basic auto-recovery
│   └── trader_v3.py           # Archive: v3 — guard-protected
└── docs/
    ├── CHANGELOG.md           # Version history
    └── ARCHITECTURE.md        # Detailed design docs
```

## Version History

| Version | Focus | Key Addition |
|---------|-------|-------------|
| v2 | Stability | Auto-recovery, state persistence |
| v3 | Safety | TradingGuard, circuit breaker, loss limits |
| v4 | Intelligence | RSI + EMA indicators, native HTTP, .env config |

## License

MIT — Use at your own risk. Trading crypto involves significant financial risk.
