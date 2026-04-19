#!/usr/bin/env python3
"""
LIVE ETH-USDT Trading Bot v4.2 - Advanced Indicators + Trailing Stop Edition

Upgrades from v4.1:
  1. BOLLINGER BANDS — Volatility-based entry/exit confirmation
     - BB(20,2) for dynamic overbought/oversold zones
     - Price below lower band + RSI oversold = strong buy
     - Price above upper band + RSI overbought = strong sell
  2. ATR (Average True Range) — Dynamic position sizing
     - ATR(14) measures volatility
     - Smaller trades in high volatility, larger in low volatility
     - Replaces fixed TRADE_AMOUNT with adaptive sizing
  3. TRAILING STOP — Lock in profits dynamically
     - Starts at 0.8% trailing after position reaches 1.5% profit
     - Trailing distance widens as profit grows (volatility-aware)
     - Replaces fixed TP exit for better upside capture
  4. VOLUME CONFIRMATION — Filter low-volume signals
     - Requires volume above 20-period moving average
     - Prevents entries on weak/noise moves

Upgrades from v4.0:
  - MACD(12/26/9) histogram confirmation for entries

Upgrades from v3:
  - Native HTTP client (requests), env-based credentials
  - RSI(14) + EMA(9/21) trend indicators
  - TradingGuard: circuit breaker, daily loss limit, position sync
"""

import json
import time
import hashlib
import hmac
import math
import base64
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
import numpy as np

from trading_guard import TradingGuard, TradingHalt, CircuitOpen, DailyLossExceeded

# ─── Configuration from .env ────────────────────────────────────────────────
def load_env(env_path="/root/.env"):
    """Load .env file into os.environ (simple parser, no dependency needed)."""
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'\"")
                os.environ[key] = val

load_env()

KUCOIN_API_KEY = os.environ.get("KUCOIN_API_KEY", "")
KUCOIN_API_SECRET = os.environ.get("KUCOIN_API_SECRET", "")
KUCOIN_PASSPHRASE = os.environ.get("KUCOIN_PASSPHRASE", "")

PAIR = "ETH-USDT"
INITIAL_BALANCE = float(os.environ.get("INITIAL_BALANCE", "72.982119"))
TRADE_AMOUNT = float(os.environ.get("TRADE_AMOUNT", "25.0"))
TAKE_PROFIT_PCT = float(os.environ.get("TAKE_PROFIT_PCT", "2.5"))
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "1.5"))
STATE_FILE = "/root/trader_state.json"
LOG_FILE = "/root/bot_v4.log"

# RSI parameters
RSI_PERIOD = 14
RSI_OVERSOLD = 30       # Buy signal when RSI < this
RSI_OVERBOUGHT = 70     # Sell signal when RSI > this
EMA_FAST = 9
EMA_SLOW = 21
KLINE_INTERVAL = "1hour"  # 1h candles for trend analysis
KLINE_LOOKBACK = 50       # Increased from 30 to support BB + ATR calculations

# Bollinger Bands parameters (v4.2)
BB_PERIOD = 20           # Standard BB period
BB_STD_DEV = 2.0         # Standard deviations

# ATR parameters (v4.2)
ATR_PERIOD = 14          # ATR lookback period
ATR_POSITION_SCALE = True # Use ATR for dynamic position sizing

# Trailing Stop parameters (v4.2)
TRAILING_STOP_ENABLED = True
TRAILING_ACTIVATION_PCT = 1.5   # Start trailing after 1.5% profit
TRAILING_DISTANCE_PCT = 0.8     # Initial trailing distance
TRAILING_STEP_PCT = 0.3         # Trailing tightens by this per step
TRAILING_MIN_DISTANCE = 0.5     # Minimum trailing distance %
TRAILING_MAX_DISTANCE = 3.0     # Maximum trailing distance %

# Volume confirmation (v4.2)
VOLUME_CONFIRM_ENABLED = True
VOLUME_MA_PERIOD = 20           # Volume moving average period
VOLUME_THRESHOLD = 1.0          # Must be >= 1.0x average volume

# Dynamic position sizing (v4.2)
MIN_TRADE_AMOUNT = 20.0         # Minimum trade in USDT
MAX_TRADE_AMOUNT = 50.0         # Maximum trade in USDT (matches default TRADE_AMOUNT)

# Telegram notifications
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


class KucoinClient:
    """Native HTTP client for KuCoin API — replaces subprocess+curl."""

    BASE_URL = "https://api.kucoin.com"

    def __init__(self, api_key, api_secret, passphrase):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "KC-API-KEY-VERSION": "2",
        })
        # Connection pooling: reuse TCP connections
        adapter = requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=4)
        self.session.mount("https://", adapter)

    def _get_server_timestamp(self):
        """Get KuCoin server timestamp. Caches for 30s to avoid extra API calls."""
        if (not hasattr(self, '_server_ts_cache')
                or time.time() - self._server_ts_cache[0] > 30):
            try:
                resp = self.session.get(
                    self.BASE_URL + "/api/v1/timestamp", timeout=5
                )
                ts = resp.json()["data"]
                self._server_ts_cache = (time.time(), ts)
            except Exception:
                ts = int(time.time() * 1000)
                self._server_ts_cache = (time.time(), ts)
        # Adjust cached server time by elapsed time since last fetch
        elapsed_ms = int((time.time() - self._server_ts_cache[0]) * 1000)
        return self._server_ts_cache[1] + elapsed_ms

    def _headers(self, method, endpoint, body=""):
        # Use server timestamp to avoid clock drift issues
        now = self._get_server_timestamp()
        str_to_sign = str(now) + method.upper() + endpoint + body
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                str_to_sign.encode(),
                hashlib.sha256
            ).digest()
        ).decode()
        passphrase_sig = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                self.passphrase.encode(),
                hashlib.sha256
            ).digest()
        ).decode()
        return {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": str(now),
            "KC-API-PASSPHRASE": passphrase_sig,
        }

    def get(self, endpoint, params=None, auth=True, timeout=10):
        url = self.BASE_URL + endpoint
        # Build full endpoint with query string for signature
        sign_endpoint = endpoint
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            sign_endpoint = f"{endpoint}?{query}"
        # Use server timestamp for signature (avoid clock drift)
        headers = self._headers("GET", sign_endpoint) if auth else {}
        resp = self.session.get(url, params=params, headers=headers, timeout=timeout)
        data = resp.json()
        if data.get("code") == "200000":
            return True, data["data"]
        return False, data.get("msg", data)

    def post(self, endpoint, body_dict, timeout=15):
        body = json.dumps(body_dict)
        headers = self._headers("POST", endpoint, body)
        resp = self.session.post(
            self.BASE_URL + endpoint,
            data=body,
            headers=headers,
            timeout=timeout
        )
        data = resp.json()
        if data.get("code") == "200000":
            return True, data["data"]
        return False, data.get("msg", data)


class TechnicalIndicators:
    """RSI, EMA, MACD calculations using numpy."""

    @staticmethod
    def compute_rsi(prices, period=14):
        """Compute RSI from a price series. Returns latest RSI value."""
        if len(prices) < period + 1:
            return 50.0  # Neutral if not enough data
        prices_arr = np.array(prices, dtype=float)
        deltas = np.diff(prices_arr)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi)

    @staticmethod
    def compute_ema(prices, period=9):
        """Compute EMA from price series. Returns latest EMA value."""
        if len(prices) < period:
            return float(np.mean(prices))
        prices_arr = np.array(prices, dtype=float)
        multiplier = 2.0 / (period + 1)
        ema = float(np.mean(prices_arr[:period]))
        for price in prices_arr[period:]:
            ema = (price - ema) * multiplier + ema
        return float(ema)

    @staticmethod
    def compute_macd(prices, fast=12, slow=26, signal=9):
        """
        Compute MACD line, signal line, and histogram.
        Returns: (macd_line, signal_line, histogram)
        """
        if len(prices) < slow + signal:
            return 0.0, 0.0, 0.0

        prices_arr = np.array(prices, dtype=float)

        # Compute fast and slow EMAs
        mult_fast = 2.0 / (fast + 1)
        mult_slow = 2.0 / (slow + 1)

        ema_fast = np.empty_like(prices_arr)
        ema_slow = np.empty_like(prices_arr)
        ema_fast[0] = prices_arr[0]
        ema_slow[0] = prices_arr[0]

        for i in range(1, len(prices_arr)):
            ema_fast[i] = (prices_arr[i] - ema_fast[i-1]) * mult_fast + ema_fast[i-1]
            ema_slow[i] = (prices_arr[i] - ema_slow[i-1]) * mult_slow + ema_slow[i-1]

        macd_line_arr = ema_fast - ema_slow

        # Signal line is EMA of MACD line
        if len(macd_line_arr) < signal:
            return float(macd_line_arr[-1]), 0.0, float(macd_line_arr[-1])

        mult_sig = 2.0 / (signal + 1)
        signal_arr = np.empty_like(macd_line_arr)
        signal_arr[:signal] = macd_line_arr[:signal]
        signal_arr[signal-1] = np.mean(macd_line_arr[:signal])

        for i in range(signal, len(macd_line_arr)):
            signal_arr[i] = (macd_line_arr[i] - signal_arr[i-1]) * mult_sig + signal_arr[i-1]

        macd_val = float(macd_line_arr[-1])
        signal_val = float(signal_arr[-1])
        histogram = macd_val - signal_val

        return macd_val, signal_val, histogram

    @staticmethod
    def compute_bollinger_bands(prices, period=20, num_std=2.0):
        """
        Compute Bollinger Bands.
        Returns: (middle, upper, lower, bandwidth, percent_b)
          - middle: SMA(period)
          - upper: middle + num_std * stdev
          - lower: middle - num_std * stdev
          - bandwidth: (upper - lower) / middle * 100
          - percent_b: (price - lower) / (upper - lower) [0-1 range, <0 below lower, >1 above upper]
        """
        if len(prices) < period:
            price = prices[-1] if prices else 0
            return price, price, price, 0.0, 0.5

        prices_arr = np.array(prices, dtype=float)
        recent = prices_arr[-period:]
        middle = float(np.mean(recent))
        std = float(np.std(recent, ddof=1))
        upper = middle + num_std * std
        lower = middle - num_std * std
        bandwidth = ((upper - lower) / middle * 100) if middle > 0 else 0.0

        current_price = float(prices_arr[-1])
        if upper != lower:
            percent_b = (current_price - lower) / (upper - lower)
        else:
            percent_b = 0.5

        return middle, upper, lower, bandwidth, percent_b

    @staticmethod
    def compute_atr(klines_data, period=14):
        """
        Compute Average True Range from kline data.
        klines_data: list of [timestamp, open, close, high, low, volume, amount]
        Returns: ATR value
        """
        if len(klines_data) < period + 1:
            return 0.0

        true_ranges = []
        for i in range(1, len(klines_data)):
            high = float(klines_data[i][3])
            low = float(klines_data[i][4])
            prev_close = float(klines_data[i-1][2])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return float(np.mean(true_ranges)) if true_ranges else 0.0

        # Use EMA-style ATR calculation (Wilder's method)
        atr = np.mean(true_ranges[:period])
        for i in range(period, len(true_ranges)):
            atr = (atr * (period - 1) + true_ranges[i]) / period

        return float(atr)

    @staticmethod
    def compute_volume_ratio(volumes, period=20):
        """
        Compute current volume relative to moving average.
        Returns ratio: current_volume / avg_volume (e.g., 1.5 = 50% above average)
        """
        if len(volumes) < period:
            return 1.0  # Neutral if not enough data

        vol_arr = np.array(volumes[-period:], dtype=float)
        avg_vol = float(np.mean(vol_arr))
        current_vol = float(volumes[-1])

        if avg_vol > 0:
            return current_vol / avg_vol
        return 1.0

    @staticmethod
    def trend_signal(prices):
        """
        Returns (signal, rsi, ema_fast, ema_slow, macd_histogram):
          signal: 'bullish', 'bearish', or 'neutral'
        """
        rsi = TechnicalIndicators.compute_rsi(prices, RSI_PERIOD)
        ema_fast = TechnicalIndicators.compute_ema(prices, EMA_FAST)
        ema_slow = TechnicalIndicators.compute_ema(prices, EMA_SLOW)
        macd_line, macd_signal, macd_histogram = TechnicalIndicators.compute_macd(prices)

        if ema_fast > ema_slow and rsi < RSI_OVERBOUGHT:
            signal = "bullish"
        elif ema_fast < ema_slow and rsi > RSI_OVERSOLD:
            signal = "bearish"
        else:
            signal = "neutral"
        return signal, rsi, ema_fast, ema_slow, macd_histogram

    @staticmethod
    def full_analysis(prices, klines_data=None):
        """
        v4.2: Comprehensive analysis with all indicators.
        Returns dict with all indicator values for decision-making.
        """
        signal, rsi, ema_fast, ema_slow, macd_histogram = TechnicalIndicators.trend_signal(prices)

        bb_middle, bb_upper, bb_lower, bb_bandwidth, bb_percent_b = \
            TechnicalIndicators.compute_bollinger_bands(prices, BB_PERIOD, BB_STD_DEV)

        atr = 0.0
        if klines_data:
            atr = TechnicalIndicators.compute_atr(klines_data, ATR_PERIOD)

        volume_ratio = 1.0
        if klines_data and len(klines_data) > 1:
            volumes = [float(k[5]) for k in klines_data]
            volume_ratio = TechnicalIndicators.compute_volume_ratio(volumes, VOLUME_MA_PERIOD)

        current_price = prices[-1] if prices else 0

        # BB-based signal enhancements
        bb_oversold = bb_percent_b < 0.0    # Price below lower band
        bb_overbought = bb_percent_b > 1.0  # Price above upper band

        return {
            "signal": signal,
            "rsi": rsi,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "macd_histogram": macd_histogram,
            "bb_middle": bb_middle,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_bandwidth": bb_bandwidth,
            "bb_percent_b": bb_percent_b,
            "bb_oversold": bb_oversold,
            "bb_overbought": bb_overbought,
            "atr": atr,
            "volume_ratio": volume_ratio,
            "price": current_price,
        }


class SmartTrader:
    """ETH-USDT Trader v4.2 with advanced indicators and trailing stop."""

    def __init__(self):
        if not KUCOIN_API_KEY or not KUCOIN_API_SECRET:
            print("FATAL: KUCOIN_API_KEY and KUCOIN_API_SECRET must be set in /root/.env")
            sys.exit(1)

        self.client = KucoinClient(KUCOIN_API_KEY, KUCOIN_API_SECRET, KUCOIN_PASSPHRASE)
        self.position = None
        self.trades_executed = 0
        self.total_pnl = 0.0
        self.running = True
        self.price_history = []  # Cached closes for indicators
        self.klines_raw = []     # Raw kline data for ATR + volume (v4.2)
        self.trailing_high = 0.0  # Track highest price since entry (v4.2)
        self.trailing_active = False  # Whether trailing stop is active (v4.2)

        self.guard = TradingGuard(
            pid_file="/root/bot.pid",
            log_file=LOG_FILE,
            state_file=STATE_FILE,
            guard_state_file="/root/guard_state.json",
            max_daily_loss=5.0,
            max_hold_hours=4.0,
            max_consecutive_fails=5,
            max_log_size_mb=5.0,
            api_rate_limit_sec=1.0,
            cooldown_after_fail_sec=30.0,
            max_trades_per_hour=10,
        )

        self.load_state()
        self._fetch_price_history()

    def load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                    self.position = state.get("position")
                    self.trades_executed = state.get("trades", 0)
                    self.total_pnl = state.get("pnl", 0.0)
                    # v4.2: Restore trailing stop state
                    self.trailing_high = state.get("trailing_high", 0.0)
                    self.trailing_active = state.get("trailing_active", False)
                    self.log("State restored from previous session", "INFO")
        except Exception as e:
            self.log(f"Could not load state: {e}", "WARN")

    def save_state(self, include_balance=False):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({
                    "position": self.position,
                    "trades": self.trades_executed,
                    "pnl": self.total_pnl,
                    "timestamp": datetime.now().isoformat(),
                    "trailing_high": self.trailing_high,
                    "trailing_active": self.trailing_active,
                }, f)
            if include_balance:
                self.save_dashboard_state()
        except Exception as e:
            self.log(f"State save failed: {e}", "ALERT")

    def save_dashboard_state(self):
        try:
            balance = self.get_balance()
            current_price = self.get_price() or 0
            state = {
                "connected": True,
                "pair": PAIR,
                "balance_usdt": balance.get("USDT", 0),
                "balance_eth": balance.get("ETH", 0),
                "total_balance": balance.get("USDT", 0) + (balance.get("ETH", 0) * current_price),
                "current_price": current_price,
                "total_pnl": self.total_pnl,
                "trades_today": self.trades_executed,
                "position": self.position,
                "last_update": datetime.now().isoformat(),
                "bot_status": "active" if self.running else "stopped",
                "guard": self.guard.get_status(),
            }
            with open("/root/bot_state.json", "w") as f:
                json.dump(state, f)
        except Exception as e:
            self.log(f"Dashboard state save failed: {e}", "WARN")

    def log(self, message, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        icons = {
            "INFO": "[i]", "BUY": "[BUY]", "SELL": "[SELL]", "PROFIT": "[PROFIT]",
            "LOSS": "[LOSS]", "ALERT": "[!!]", "WARN": "[WARN]", "OK": "[OK]",
            "GUARD": "[GUARD]", "SIGNAL": "[SIG]"
        }
        icon = icons.get(level, "[-]")
        log_line = f"{icon} [{ts}] {message}"
        # Single write path: write directly to file
        # stdout redirect also captures print(), but we avoid duplication
        # by only using explicit file write
        try:
            with open(LOG_FILE, "a") as f:
                f.write(log_line + "\n")
        except Exception as e:  # SECURITY: Specific exception handling
            pass
        # Print to console only if NOT redirected (interactive mode)
        if sys.stdout.isatty():
            try:
                print(log_line, flush=True)
            except UnicodeEncodeError:
                pass

        # Send important events to Telegram
        if level in ["BUY", "SELL", "PROFIT", "LOSS", "ALERT"]:
            self._telegram_notify(f"{icons.get(level, '')} {message}")

    def _telegram_notify(self, text):
        """Send notification to Telegram."""
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
                timeout=5
            )
        except Exception as e:  # SECURITY: Specific exception handling
            pass  # Non-critical — don't break the bot

    # ─── API Methods (native requests — no subprocess!) ─────────────────

    def get_price(self):
        """Get current ETH price. ~50ms vs ~300ms with curl."""
        try:
            success, data = self.client.get(
                "/api/v1/market/orderbook/level1",
                params={"symbol": PAIR},
                auth=False
            )
            if success:
                price = float(data.get("price", 0))
                if price > 0:
                    self.guard.record_success()
                    return price
            self.guard.record_failure()
        except Exception as e:
            self.guard.record_failure()
        return None

    def get_balance(self):
        """Get trade account balances."""
        try:
            success, data = self.client.get("/api/v1/accounts", params={"type": "trade"})
            if success:
                balances = {"ETH": 0.0, "USDT": 0.0}
                for acc in data:
                    if acc["currency"] in balances:
                        balances[acc["currency"]] = float(acc.get("available", 0))
                self.guard.record_success()
                return balances
            self.guard.record_failure()
        except Exception:
            self.guard.record_failure()
        return {"ETH": 0.0, "USDT": 0.0}

    def place_order(self, side, amount):
        """Place market order."""
        body = {
            "symbol": PAIR,
            "side": side,
            "type": "market",
            "clientOid": f"v4_{int(time.time() * 1000)}"
        }
        if side == "buy":
            body["funds"] = str(amount)
        else:
            if amount < 1.0:
                body["size"] = str(math.floor(amount * 100000) / 100000)
            else:
                body["funds"] = str(round(amount, 2))
        try:
            success, result = self.client.post("/api/v1/orders", body)
            if success:
                self.guard.record_success()
                return True, result
            self.guard.record_failure()
            return False, result
        except Exception as e:
            self.guard.record_failure()
            return False, str(e)

    # ─── Technical Analysis ─────────────────────────────────────────────

    def _fetch_price_history(self):
        """Fetch recent klines for indicator calculation."""
        try:
            success, data = self.client.get(
                "/api/v1/market/candles",
                params={"symbol": PAIR, "type": KLINE_INTERVAL},
                auth=False
            )
            if success and data:
                # KuCoin returns [timestamp, open, close, high, low, volume, amount]
                # Sorted newest-first
                recent = data[-KLINE_LOOKBACK:]
                closes = [float(candle[2]) for candle in reversed(recent)]
                self.price_history = closes
                self.klines_raw = list(reversed(recent))  # Oldest-first for ATR
                self.log(f"Loaded {len(closes)} candles for analysis", "INFO")
            else:
                self.price_history = []
                self.klines_raw = []
        except Exception as e:
            self.log(f"Kline fetch failed: {e}", "WARN")
            self.price_history = []
            self.klines_raw = []

    def _update_indicators(self, price):
        """Append latest price to history, compute all indicators (v4.2)."""
        self.price_history.append(price)
        # Keep only what we need
        if len(self.price_history) > KLINE_LOOKBACK * 2:
            self.price_history = self.price_history[-KLINE_LOOKBACK:]

        if len(self.price_history) < EMA_SLOW + 1:
            return {
                "signal": "neutral", "rsi": 50.0,
                "ema_fast": price, "ema_slow": price,
                "macd_histogram": 0.0,
                "bb_middle": price, "bb_upper": price, "bb_lower": price,
                "bb_bandwidth": 0.0, "bb_percent_b": 0.5,
                "bb_oversold": False, "bb_overbought": False,
                "atr": 0.0, "volume_ratio": 1.0, "price": price,
            }

        analysis = TechnicalIndicators.full_analysis(self.price_history, self.klines_raw)
        return analysis

    # ─── Order Execution ────────────────────────────────────────────────

    def _calculate_trade_amount(self, analysis):
        """
        v4.2: Dynamic position sizing based on ATR (volatility).
        - Low volatility → larger position (up to MAX_TRADE_AMOUNT)
        - High volatility → smaller position (down to MIN_TRADE_AMOUNT)
        """
        if not ATR_POSITION_SCALE or analysis.get("atr", 0) == 0:
            return TRADE_AMOUNT

        atr = analysis["atr"]
        price = analysis["price"]
        if price <= 0:
            return TRADE_AMOUNT

        # ATR as percentage of price
        atr_pct = (atr / price) * 100

        # Baseline: at ~1.5% ATR, use default TRADE_AMOUNT
        # Scale inversely: lower ATR = larger trade, higher ATR = smaller trade
        if atr_pct <= 0:
            return TRADE_AMOUNT

        scale_factor = min(max(1.5 / atr_pct, 0.5), 2.0)
        amount = TRADE_AMOUNT * scale_factor

        # Clamp to min/max
        amount = max(MIN_TRADE_AMOUNT, min(MAX_TRADE_AMOUNT, amount))
        return round(amount, 2)

    def _check_trailing_stop(self, price, current_pnl_pct):
        """
        v4.2: Trailing stop logic.
        Returns (should_exit, reason) tuple.
        """
        if not TRAILING_STOP_ENABLED:
            return False, ""

        if not self.position or not self.position.get("entry"):
            return False, ""

        entry = self.position["entry"]

        # Update trailing high
        if price > self.trailing_high:
            self.trailing_high = price

        # Activate trailing after position reaches activation threshold
        if not self.trailing_active:
            if current_pnl_pct >= TRAILING_ACTIVATION_PCT:
                self.trailing_active = True
                self.trailing_high = price
                self.log(
                    f"TRAILING STOP ACTIVATED at +{current_pnl_pct:.2f}% "
                    f"(trailing from ${price:.2f})",
                    "SIGNAL"
                )
            return False, ""

        # Trailing is active — calculate trailing distance
        # Dynamic: tighter for small profits, wider for large profits
        profit_pct = ((self.trailing_high - entry) / entry) * 100

        # Trailing distance scales with profit
        trail_distance = min(
            TRAILING_DISTANCE_PCT + (profit_pct - TRAILING_ACTIVATION_PCT) * TRAILING_STEP_PCT,
            TRAILING_MAX_DISTANCE
        )
        trail_distance = max(trail_distance, TRAILING_MIN_DISTANCE)

        # Calculate trailing stop price
        trailing_stop_price = self.trailing_high * (1 - trail_distance / 100)

        if price <= trailing_stop_price:
            # Calculate actual PnL at exit
            exit_pnl = ((price - entry) / entry) * 100
            reason = (
                f"Trailing stop hit: ${price:.2f} <= ${trailing_stop_price:.2f} "
                f"(trail dist: {trail_distance:.1f}%, peak: ${self.trailing_high:.2f})"
            )
            return True, reason

        return False, ""

    def _execute_exit(self, reason, current_pnl_pct, unrealized):
        """Safely execute a position exit with retries and guard checks."""
        try:
            self.guard.pre_trade_check("sell", self.position["amount"])
        except (DailyLossExceeded, TradingHalt) as e:
            self.log(f"GUARD BLOCKED EXIT: {e}", "GUARD")
            # Still try to exit — loss limit means we NEED out

        amount = self.position["amount"]
        is_loss = unrealized < 0

        success, result = self.place_order("sell", amount)
        if success:
            profit = unrealized
            if is_loss:
                self.total_pnl -= abs(profit)
            else:
                self.total_pnl += profit
            self.trades_executed += 1
            self.guard.record_trade("sell", pnl=profit, success=True)
            self.position = None
            # Reset trailing stop state
            self.trailing_high = 0.0
            self.trailing_active = False
            self.save_state(include_balance=True)

            if is_loss:
                self.log(f"STOP LOSS: {current_pnl_pct:.2f}% (-${abs(profit):.2f}) [{reason}]", "LOSS")
            else:
                self.log(f"TAKE PROFIT! +{current_pnl_pct:.2f}% (+${profit:.2f}) [{reason}]", "PROFIT")
            self.log(f"Total Trades: {self.trades_executed} | P&L: ${self.total_pnl:+.2f}", "INFO")
            return True

        # Fallback: sell by USDT funds value
        self.log(f"Sell by size failed: {result}. Trying funds fallback...", "WARN")
        price = self.get_price()
        if price:
            funds_val = round(amount * price, 2)
            success2, result2 = self.place_order("sell", funds_val)
            if success2:
                profit = unrealized
                if is_loss:
                    self.total_pnl -= abs(profit)
                else:
                    self.total_pnl += profit
                self.trades_executed += 1
                self.guard.record_trade("sell", pnl=profit, success=True)
                self.position = None
                self.save_state(include_balance=True)
                return True

        self.guard.record_failure()
        self.log(f"CRITICAL: Both sell attempts failed! {result} | {result2 if not success else ''}", "ALERT")
        return False

    # ─── Main Trading Loop ──────────────────────────────────────────────

    def run(self):
        self.guard.acquire_lock()

        self.log("=" * 60, "INFO")
        self.log("SMART ETH-USDT TRADER v4.2 (RSI+EMA+MACD+BB+ATR+Trailing)", "OK")
        self.log("=" * 60, "INFO")
        self.log(
            f"Balance: ${INITIAL_BALANCE:.2f} | Trade: ${TRADE_AMOUNT} | "
            f"TP:{TAKE_PROFIT_PCT}% SL:{STOP_LOSS_PCT}%", "INFO"
        )
        self.log(
            f"Indicators: RSI({RSI_PERIOD}) {RSI_OVERSOLD}/{RSI_OVERBOUGHT} | "
            f"EMA({EMA_FAST}/{EMA_SLOW}) | MACD(12/26/9) | BB({BB_PERIOD},{BB_STD_DEV}) | "
            f"ATR({ATR_PERIOD}) | Trailing:{TRAILING_STOP_ENABLED}", "SIGNAL"
        )
        self.log(self.guard.format_status(), "GUARD")

        if self.position:
            self.log(
                f"RESUMED: Open position {self.position['amount']:.6f} ETH @ ${self.position.get('entry', 0):.2f}",
                "INFO"
            )

        cycle = 0
        last_status_time = 0
        last_sync_time = 0
        last_balance_save = 0
        last_dashboard_save = 0
        last_kline_refresh = 0
        last_signal_log = 0

        try:
            while self.running:
                try:
                    loop_start = time.time()

                    # ── Price + Indicators ──
                    price = self.get_price()
                    self.guard.check_health(price=price, position=self.position)

                    if not price:
                        self.log("Network error, retrying in 10s...", "WARN")
                        time.sleep(10)
                        continue

                    analysis = self._update_indicators(price)
                    signal = analysis["signal"]
                    rsi = analysis["rsi"]
                    ema_fast = analysis["ema_fast"]
                    ema_slow = analysis["ema_slow"]
                    macd_histogram = analysis["macd_histogram"]
                    bb_percent_b = analysis["bb_percent_b"]
                    bb_oversold = analysis["bb_oversold"]
                    bb_overbought = analysis["bb_overbought"]
                    bb_lower = analysis["bb_lower"]
                    bb_upper = analysis["bb_upper"]
                    bb_bandwidth = analysis["bb_bandwidth"]
                    atr = analysis["atr"]
                    volume_ratio = analysis["volume_ratio"]

                    # Refresh klines every 30 min (don't hammer API)
                    if time.time() - last_kline_refresh >= 1800:
                        self._fetch_price_history()
                        last_kline_refresh = time.time()

                    # ── Periodic position sync (every 5 min) ──
                    if time.time() - last_sync_time >= 300:
                        balances = self.get_balance()
                        synced = self.guard.sync_position(
                            self.position,
                            balances.get("ETH", 0),
                            TRADE_AMOUNT,
                            price=price
                        )
                        if synced != self.position:
                            if synced is None and self.position is not None:
                                self.log("GUARD: Clearing stale position", "GUARD")
                            self.position = synced
                            self.save_state()
                        last_sync_time = time.time()

                    # Get balance (only every 60s)
                    if time.time() - last_balance_save >= 60:
                        balances = self.get_balance()
                        last_balance_save = time.time()
                    else:
                        balances = {"ETH": self.position["amount"] if self.position else 0.0, "USDT": 0.0}

                    eth_value = balances.get("ETH", 0) * price
                    total = balances.get("USDT", 0) + eth_value
                    pnl = total - INITIAL_BALANCE

                    # Status every 60s
                    if time.time() - last_status_time >= 60:
                        macd_str = f"MACD:{macd_histogram:+.2f}" if macd_histogram != 0 else "MACD:--"
                        bb_str = f"BB%:{bb_percent_b:.2f}" if bb_bandwidth > 0 else "BB:--"
                        atr_str = f"ATR:{atr:.1f}" if atr > 0 else "ATR:--"
                        vol_str = f"Vol:{volume_ratio:.1f}x" if volume_ratio != 1.0 else "Vol:--"
                        self.log(
                            f"Balance: ${total:.2f} | ETH: ${price:.2f} | "
                            f"P&L: ${pnl:+.2f} | RSI: {rsi:.1f} | {macd_str} | "
                            f"{bb_str} | {atr_str} | {vol_str} | {signal.upper()}",
                            "INFO"
                        )
                        last_status_time = time.time()

                    # ── SMART TRADING LOGIC ──

                    if not self.position:
                        # NO POSITION — Wait for smart entry signal
                        # v4.2: Added Bollinger Bands + Volume confirmation + Dynamic sizing
                        macd_confirmed = macd_histogram > 0

                        # Volume filter: require sufficient market participation
                        volume_ok = True
                        if VOLUME_CONFIRM_ENABLED:
                            volume_ok = volume_ratio >= VOLUME_THRESHOLD

                        # BB-enhanced entry: stronger signal when price is below lower band
                        bb_entry_bonus = bb_oversold  # Extra bullish when below lower BB

                        # Core entry: RSI oversold + bullish EMA + MACD confirmed + volume
                        # OR: RSI oversold + BB below lower band + MACD confirmed (stronger signal)
                        core_signal = (
                            signal == "bullish"
                            and rsi < RSI_OVERSOLD
                            and macd_confirmed
                            and volume_ok
                        )

                        bb_enhanced_signal = (
                            rsi < RSI_OVERSOLD
                            and bb_oversold
                            and macd_confirmed
                            and signal in ("bullish", "neutral")  # BB oversold compensates for neutral EMA
                            and volume_ok
                        )

                        if (core_signal or bb_enhanced_signal) and balances.get("USDT", 0) >= MIN_TRADE_AMOUNT * 1.05:
                            try:
                                # Dynamic position sizing based on ATR
                                trade_amt = self._calculate_trade_amount(analysis)
                                self.guard.pre_trade_check("buy", trade_amt)
                                eth_qty = trade_amt / price

                                # Build entry reason
                                reasons = [f"RSI={rsi:.1f}"]
                                if signal == "bullish":
                                    reasons.append(f"EMA cross {ema_fast:.2f}>{ema_slow:.2f}")
                                if bb_oversold:
                                    reasons.append(f"BB below lower (${bb_lower:.2f})")
                                reasons.append(f"MACD hist {macd_histogram:+.2f}")
                                if volume_ratio > 1.0:
                                    reasons.append(f"Vol {volume_ratio:.1f}x")
                                reasons.append(f"Size=${trade_amt:.0f}")

                                self.log(
                                    f"ENTRY SIGNAL: {' + '.join(reasons)} = BULLISH @ ${price:.2f}",
                                    "SIGNAL"
                                )

                                success, result = self.place_order("buy", trade_amt)
                                if success:
                                    self.position = {
                                        "side": "long",
                                        "entry": price,
                                        "amount": eth_qty,
                                        "timestamp": datetime.now().isoformat()
                                    }
                                    # Reset trailing stop for new position
                                    self.trailing_high = price
                                    self.trailing_active = False
                                    self.guard.record_trade("buy", success=True)
                                    self.save_state(include_balance=True)
                                    self.log(f"BUY: {eth_qty:.6f} ETH @ ${price:.2f} (${trade_amt:.2f})", "BUY")
                                else:
                                    self.log(f"Buy failed: {result}", "ALERT")
                                    time.sleep(30)
                            except TradingHalt as e:
                                self.log(f"Trade blocked: {e}", "GUARD")
                                time.sleep(60)

                        elif cycle % 12 == 0:
                            # Periodically explain why we're NOT buying
                            reasons = []
                            if signal != "bullish" and not bb_oversold:
                                reasons.append(f"trend={signal}")
                            if rsi >= RSI_OVERSOLD:
                                reasons.append(f"RSI={rsi:.1f} (need <{RSI_OVERSOLD})")
                            if not macd_confirmed:
                                reasons.append(f"MACD hist={macd_histogram:+.2f} (need >0)")
                            if not volume_ok:
                                reasons.append(f"Vol={volume_ratio:.1f}x (need >={VOLUME_THRESHOLD}x)")
                            if not bb_oversold:
                                reasons.append(f"BB%={bb_percent_b:.2f} (need <0)")
                            reason_str = " | ".join(reasons) if reasons else "waiting for setup"
                            self.log(f"No entry: {reason_str} | EMA: {ema_fast:.2f} vs {ema_slow:.2f}", "SIGNAL")
                    else:
                        # HAVE POSITION — Monitor for exit
                        entry = self.position.get("entry", 0)
                        if entry <= 0:
                            self.log(f"Recovery position. Updating entry to ${price:.2f}", "GUARD")
                            self.position["entry"] = price
                            self.save_state()
                            entry = price

                        current_pnl_pct = ((price - entry) / entry) * 100
                        unrealized = (price - entry) * self.position["amount"]

                        # Check exit conditions
                        # 0. Trailing stop (v4.2) — checked first to lock in profits
                        trail_exit, trail_reason = self._check_trailing_stop(price, current_pnl_pct)
                        if trail_exit:
                            self._execute_exit(trail_reason, current_pnl_pct, unrealized)

                        # 1. Take profit hit (fixed TP as safety net)
                        elif current_pnl_pct >= TAKE_PROFIT_PCT:
                            # If trailing is active, let it ride instead of fixed TP
                            if self.trailing_active:
                                # Trailing stop manages the exit — only log
                                if cycle % 3 == 0:
                                    self.log(
                                        f"TP zone (+{current_pnl_pct:.2f}%) — trailing stop managing exit "
                                        f"(peak: ${self.trailing_high:.2f})",
                                        "INFO"
                                    )
                            else:
                                self._execute_exit("TP hit", current_pnl_pct, unrealized)

                        # 2. Stop loss hit (hard stop — always enforced)
                        elif current_pnl_pct <= -STOP_LOSS_PCT:
                            self._execute_exit("SL hit", current_pnl_pct, unrealized)

                        # 3. BB overbought exit (v4.2) — price above upper band + RSI overbought
                        elif (bb_overbought
                              and rsi > RSI_OVERBOUGHT
                              and current_pnl_pct > 0.5):
                            self._execute_exit(
                                f"BB overbought (%B={bb_percent_b:.2f}) + RSI {rsi:.1f}",
                                current_pnl_pct, unrealized
                            )

                        # 4. Bearish signal while in profit (EMA exit)
                        elif (signal == "bearish"
                              and rsi > RSI_OVERBOUGHT
                              and current_pnl_pct > 0.5):
                            self._execute_exit(
                                f"RSI overbought ({rsi:.1f}) + bearish crossover",
                                current_pnl_pct, unrealized
                            )

                        else:
                            # Position running normally
                            if cycle % 6 == 0:
                                macd_str = f"MACD:{macd_histogram:+.2f}" if macd_histogram != 0 else "MACD:--"
                                bb_str = f"BB%:{bb_percent_b:.2f}" if bb_bandwidth > 0 else "BB:--"
                                trail_str = ""
                                if self.trailing_active:
                                    trail_str = f" | Trail:${self.trailing_high:.2f}"
                                self.log(
                                    f"Position: {current_pnl_pct:+.2f}% "
                                    f"(U:${unrealized:+.2f}) | RSI: {rsi:.1f} | "
                                    f"{macd_str} | {bb_str}{trail_str}",
                                    "INFO"
                                )

                    cycle += 1

                    # Save state periodically (lightweight)
                    if cycle % 3 == 0:
                        self.save_state(include_balance=False)

                    # Dashboard save every 60s
                    if time.time() - last_dashboard_save >= 60:
                        self.save_state(include_balance=True)
                        last_dashboard_save = time.time()

                    # Maintain ~10s cycle
                    elapsed = time.time() - loop_start
                    time.sleep(max(0, 10 - elapsed))

                except CircuitOpen as e:
                    self.log(f"CIRCUIT BREAKER: {e}", "GUARD")
                    wait = min(60 * (2 ** min(self.guard._state["consecutive_fails"], 5)), 600)
                    self.log(f"Pausing {wait}s for recovery...", "GUARD")
                    time.sleep(wait)

                except TradingHalt as e:
                    self.log(f"EMERGENCY: {e}", "ALERT")
                    if self.position:
                        price = self.get_price()
                        if price and self.position.get("entry", 0) > 0:
                            pnl_pct = ((price - self.position["entry"]) / self.position["entry"]) * 100
                            unrealized = (price - self.position["entry"]) * self.position["amount"]
                            self._execute_exit("EMERGENCY", pnl_pct, unrealized)
                    self.log("Bot stopped by guard. Manual restart required.", "ALERT")
                    break

                except Exception as e:
                    self.log(f"ERROR: {str(e)[:100]}", "ALERT")
                    self.guard.record_failure()
                    self.save_state()
                    time.sleep(10)

        finally:
            self.running = False
            self.save_state(include_balance=True)
            self.guard.release_lock()
            self.log("Final state saved. Bot stopped.", "INFO")


if __name__ == "__main__":
    trader = SmartTrader()
    trader.run()
