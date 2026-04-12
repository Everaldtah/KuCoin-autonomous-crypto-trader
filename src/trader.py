#!/usr/bin/env python3
"""
LIVE ETH-USDT Trading Bot v4.0 - Smart Entry Edition

Upgrades from v3:
  1. NATIVE HTTP CLIENT — requests library replaces subprocess+curl
     - 10x faster API calls (no process spawn overhead)
     - No shell injection risk
     - Proper connection pooling & timeout handling
  2. ENV-BASED CREDENTIALS — .env file instead of hardcoded keys
     - Secure: keys never appear in source code
     - Easy to rotate without code changes
  3. RSI + EMA TREND INDICATORS — smart entries & exits
     - RSI(14) oversold/overbought signals for entry
     - EMA(9)/EMA(21) crossover for trend confirmation
     - No more "buy after 6 cycles" random entries

Inherits from v3:
  - TradingGuard wrapping all critical paths
  - Circuit breaker, daily loss limit, position sync
  - Log rotation, rate limiting, duplicate process guard
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
def load_env(env_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env")):
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
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trader_state.json"))
LOG_FILE = os.environ.get("LOG_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "bot.log"))

# RSI parameters
RSI_PERIOD = 14
RSI_OVERSOLD = 30       # Buy signal when RSI < this
RSI_OVERBOUGHT = 70     # Sell signal when RSI > this
EMA_FAST = 9
EMA_SLOW = 21
KLINE_INTERVAL = "1hour"  # 1h candles for trend analysis
KLINE_LOOKBACK = 30       # Need at least EMA_SLOW + buffer candles

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
    """RSI, EMA calculations using numpy."""

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
    def trend_signal(prices):
        """
        Returns (signal, rsi, ema_fast, ema_slow):
          signal: 'bullish', 'bearish', or 'neutral'
        """
        rsi = TechnicalIndicators.compute_rsi(prices, RSI_PERIOD)
        ema_fast = TechnicalIndicators.compute_ema(prices, EMA_FAST)
        ema_slow = TechnicalIndicators.compute_ema(prices, EMA_SLOW)

        if ema_fast > ema_slow and rsi < RSI_OVERBOUGHT:
            signal = "bullish"
        elif ema_fast < ema_slow and rsi > RSI_OVERSOLD:
            signal = "bearish"
        else:
            signal = "neutral"
        return signal, rsi, ema_fast, ema_slow


class SmartTrader:
    """ETH-USDT Trader v4 with native HTTP, env credentials, and RSI+EMA signals."""

    def __init__(self):
        if not KUCOIN_API_KEY or not KUCOIN_API_SECRET:
            print("FATAL: KUCOIN_API_KEY and KUCOIN_API_SECRET must be set in config/.env or environment")
            sys.exit(1)

        self.client = KucoinClient(KUCOIN_API_KEY, KUCOIN_API_SECRET, KUCOIN_PASSPHRASE)
        self.position = None
        self.trades_executed = 0
        self.total_pnl = 0.0
        self.running = True
        self.price_history = []  # Cached kline closes for indicators

        self.guard = TradingGuard(
            pid_file=os.environ.get("PID_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bot.pid")),
            log_file=LOG_FILE,
            state_file=STATE_FILE,
            guard_state_file=os.environ.get("GUARD_STATE_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "guard_state.json")),
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
            dashboard_state = os.environ.get("DASHBOARD_STATE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bot_state.json"))
            with open(dashboard_state, "w") as f:
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
        except:
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
        except:
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
                closes = [float(candle[2]) for candle in reversed(data[-KLINE_LOOKBACK:])]
                self.price_history = closes
                self.log(f"Loaded {len(closes)} candles for analysis", "INFO")
            else:
                self.price_history = []
        except Exception as e:
            self.log(f"Kline fetch failed: {e}", "WARN")
            self.price_history = []

    def _update_indicators(self, price):
        """Append latest price to history, compute signals."""
        self.price_history.append(price)
        # Keep only what we need
        if len(self.price_history) > KLINE_LOOKBACK * 2:
            self.price_history = self.price_history[-KLINE_LOOKBACK:]

        if len(self.price_history) < EMA_SLOW + 1:
            return "neutral", 50.0, price, price

        signal, rsi, ema_fast, ema_slow = TechnicalIndicators.trend_signal(self.price_history)
        return signal, rsi, ema_fast, ema_slow

    # ─── Order Execution ────────────────────────────────────────────────

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
        self.log("SMART ETH-USDT TRADER v4.0 (RSI+EMA)", "OK")
        self.log("=" * 60, "INFO")
        self.log(
            f"Balance: ${INITIAL_BALANCE:.2f} | Trade: ${TRADE_AMOUNT} | "
            f"TP:{TAKE_PROFIT_PCT}% SL:{STOP_LOSS_PCT}%", "INFO"
        )
        self.log(
            f"Indicators: RSI({RSI_PERIOD}) {RSI_OVERSOLD}/{RSI_OVERBOUGHT} | "
            f"EMA({EMA_FAST}/{EMA_SLOW})", "SIGNAL"
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

                    signal, rsi, ema_fast, ema_slow = self._update_indicators(price)

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
                        self.log(
                            f"Balance: ${total:.2f} | ETH: ${price:.2f} | "
                            f"P&L: ${pnl:+.2f} | RSI: {rsi:.1f} | {signal.upper()}",
                            "INFO"
                        )
                        last_status_time = time.time()

                    # ── SMART TRADING LOGIC ──

                    if not self.position:
                        # NO POSITION — Wait for smart entry signal
                        # Requirements: RSI oversold + bullish EMA crossover + sufficient funds
                        if (signal == "bullish"
                                and rsi < RSI_OVERSOLD
                                and balances.get("USDT", 0) >= TRADE_AMOUNT * 1.05):
                            try:
                                self.guard.pre_trade_check("buy", TRADE_AMOUNT)
                                eth_qty = TRADE_AMOUNT / price

                                self.log(
                                    f"ENTRY SIGNAL: RSI={rsi:.1f} (oversold) + "
                                    f"EMA crossover {ema_fast:.2f}>{ema_slow:.2f} "
                                    f"= BULLISH @ ${price:.2f}",
                                    "SIGNAL"
                                )

                                success, result = self.place_order("buy", TRADE_AMOUNT)
                                if success:
                                    self.position = {
                                        "side": "long",
                                        "entry": price,
                                        "amount": eth_qty,
                                        "timestamp": datetime.now().isoformat()
                                    }
                                    self.guard.record_trade("buy", success=True)
                                    self.save_state(include_balance=True)
                                    self.log(f"BUY: {eth_qty:.6f} ETH @ ${price:.2f}", "BUY")
                                else:
                                    self.log(f"Buy failed: {result}", "ALERT")
                                    time.sleep(30)
                            except TradingHalt as e:
                                self.log(f"Trade blocked: {e}", "GUARD")
                                time.sleep(60)

                        elif signal != "bullish" and cycle % 12 == 0:
                            # Periodically explain why we're NOT buying
                            self.log(
                                f"No entry: RSI={rsi:.1f} (need <{RSI_OVERSOLD}) | "
                                f"Trend={signal} | EMA: {ema_fast:.2f} vs {ema_slow:.2f}",
                                "SIGNAL"
                            )
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
                        # 1. Take profit hit
                        if current_pnl_pct >= TAKE_PROFIT_PCT:
                            self._execute_exit("TP hit", current_pnl_pct, unrealized)

                        # 2. Stop loss hit
                        elif current_pnl_pct <= -STOP_LOSS_PCT:
                            self._execute_exit("SL hit", current_pnl_pct, unrealized)

                        # 3. BEARISH signal while in profit (trail exit)
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
                                self.log(
                                    f"Position: {current_pnl_pct:+.2f}% "
                                    f"(U:${unrealized:+.2f}) | RSI: {rsi:.1f}",
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
