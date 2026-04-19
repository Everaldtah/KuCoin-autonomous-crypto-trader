# Bot v5.0 → v6.0 "Hephaestus Reforged" Upgrade Patch

## Summary of Changes Based on Walk-Forward Analysis

### CRITICAL CHANGE #1: PAIR FILTERING
**File:** `src/multi_pair_bot_clean.py`
**Location:** Around line 125 (watchlist definition)

**CURRENT (v5):**
```python
self.watchlist: List[str] = [
    "ETH-USDT", "BTC-USDT", "SOL-USDT", "LINK-USDT",
    "AVAX-USDT", "DOT-USDT", "MATIC-USDT", "UNI-USDT",
    "AAVE-USDT", "ATOM-USDT", "ADA-USDT", "DOGE-USDT"
]
```

**UPGRADED (v6):**
```python
# ============================================================
# v6 CRITICAL CHANGE: Only trade pairs with POSITIVE EDGE
# Analysis of 3,788 out-of-sample trades showed:
#   SHIB-USDT: +0.034% avg | 43.9% WR | PF 1.03
#   TRX-USDT:  +0.021% avg | 49.0% WR | PF 1.03
#   BTC-USDT:  +0.011% avg | 46.1% WR | PF 1.01
#   KCS-USDT:  +0.009% avg | 44.1% WR | PF 1.01
# ALL OTHER PAIRS HAVE NEGATIVE EXPECTED VALUE
# ============================================================
VALIDATED_PAIRS = ["SHIB-USDT", "TRX-USDT", "BTC-USDT", "KCS-USDT"]

self.watchlist: List[str] = VALIDATED_PAIRS
```

### CRITICAL CHANGE #2: HIGHER SIGNAL THRESHOLDS
**File:** `src/multi_pair_bot_clean.py`
**Location:** Around line 120 (threshold definitions)

**CURRENT (v5):**
```python
BUY_SIGNAL_THRESHOLD = 0.55  # Was 0.55
SELL_SIGNAL_THRESHOLD = 0.35
```

**UPGRADED (v6):**
```python
# v6: Raised thresholds to reduce false signals
# Backtesting showed 0.55 threshold generated too many losing trades
BUY_SIGNAL_THRESHOLD = 0.62   # Was 0.55 - require stronger conviction
SELL_SIGNAL_THRESHOLD = 0.38   # Was 0.35 - exit sooner on weakness
```

### CRITICAL CHANGE #3: ATR-BASED DYNAMIC TP/SL
**File:** `src/multi_pair_bot_clean.py`
**Location:** Around line 125 (take profit / stop loss definitions)

**CURRENT (v5):**
```python
TAKE_PROFIT_PCT_BASE = 3.0
STOP_LOSS_PCT_BASE = 1.5
```

**UPGRADED (v6):**
```python
# v6: ATR-based dynamic stops instead of fixed percentages
# This adapts to each pair's actual volatility
ATR_TP_MULTIPLIER = 2.0   # Take profit at 2x ATR
ATR_SL_MULTIPLIER = 1.5   # Stop loss at 1.5x ATR
# Keep for fallback:
TAKE_PROFIT_PCT_BASE = 3.0  # Fallback if ATR unavailable
STOP_LOSS_PCT_BASE = 1.5     # Fallback if ATR unavailable
```

### CRITICAL CHANGE #4: MOMENTUM FILTER
**File:** `src/multi_pair_bot_clean.py`
**Location:** In `_open_position()` method (around line 900)

**ADD THIS CHECK before opening any position:**
```python
# v6: Momentum filter - only trade in direction of 4h trend
# Get 4h candles and check EMA alignment
candles_4h = await self.client.get_ohlcv(symbol, "4hour", limit=50)
if candles_4h:
    closes_4h = [float(c[4]) for c in candles_4h]
    ema_4h_fast = self._calc_ema(closes_4h, 10)
    ema_4h_slow = self._calc_ema(closes_4h, 20)
    if ema_4h_fast < ema_4h_slow:
        print(f"[FILTER] {symbol}: 4h trend bearish, skipping")
        return False  # Only trade with 4h trend
```

### CRITICAL CHANGE #5: VOLATILITY-ADJUSTED POSITION SIZING
**File:** `src/multi_pair_bot_clean.py`
**Location:** In `calculate_position_size()` method

**MODIFY the volatility section:**
```python
# v6: Enhanced volatility adjustment
# Low volatility = larger positions (more stable)
# High volatility = smaller positions (more risk)
if volatility > 3.0:  # Very high volatility
    kelly_bet_pct *= 0.4  # Reduce by 60%
elif volatility > 2.0:   # High volatility  
    kelly_bet_pct *= 0.6  # Reduce by 40%
elif volatility < 0.5:   # Low volatility
    kelly_bet_pct *= 1.3  # Allow 30% more
```

## Files to Modify

1. `/root/KuCoin-autonomous-crypto-trader/src/multi_pair_bot_clean.py`
   - Lines ~120-130: Update thresholds and pair list
   - Lines ~900-950: Add momentum filter in _open_position()
   - Lines ~750-780: Enhance volatility adjustment in position sizing

2. Create new file: `/root/KuCoin-autonomous-crypto-trader/src/multi_pair_bot_v6.py`
   - Full rewrite incorporating all changes

## Testing the Upgrade

Before deploying v6 with real money:

1. Run in dry-run mode for at least 1 week:
   ```bash
   python3 multi_pair_bot_v6.py --dry-run --capital 1000
   ```

2. Compare signal frequency - should be ~40% fewer trades due to higher threshold

3. Verify the bot only trades: SHIB, TRX, BTC, KCS

4. Check log for "FILTER" messages confirming momentum filter working

## Rollback Plan

If v6 underperforms:
1. Stop the bot
2. Rename `multi_pair_bot_v6.py` → `multi_pair_bot_v6.py.disabled`
3. Restart with v5: `python3 multi_pair_bot_clean.py --capital X`
