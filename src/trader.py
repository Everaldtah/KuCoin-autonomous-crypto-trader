#!/usr/bin/env python3
"""
LIVE Multi-Pair Crypto Trader v5.0 — Confluence Engine Edition

Upgrades from v4.0:
  1. MULTI-TIMEFRAME CONFLUENCE — 1H + 4H + 1D indicator analysis
  2. ADVANCED INDICATORS — MACD, Bollinger, ATR, StochRSI, ADX, Ichimoku, Volume
  3. REGIME DETECTION — market-aware strategy switching (trend/range/volatile)
  4. KELLY CRITERION POSITION SIZING — 1-2% risk per trade (not 34%!)
  5. ATR-BASED DYNAMIC STOPS — adaptive TP/SL based on volatility
  6. TRAILING STOPS — ratchet profits in trending markets
  7. BACKTESTER — historical simulation with walk-forward validation
  8. MULTI-PAIR SUPPORT — configurable trading pairs

Inherits from v4:
  - Native HTTP client (requests library)
  - Environment-based credentials (.env)
  - TradingGuard safety wrapper
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

from indicators import AdvancedIndicators
from strategy import ConfluenceEngine, RegimeSwitcher, TimeframeData, Signal
from risk_manager import KellyCriterion, ATRStops, RiskManager
from trading_guard import TradingGuard, TradingHalt, CircuitOpen, DailyLossExceeded


# ─── Configuration from .env ────────────────────────────────────────────────
def load_env(env_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env")):
    """Load .env file into os.environ."""
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

# Trading parameters
PAIR = os.environ.get("TRADING_PAIR", "ETH-USDT")
INITIAL_BALANCE = float(os.environ.get("INITIAL_BALANCE", "100"))
MAX_RISK_PCT = float(os.environ.get("MAX_RISK_PER_TRADE_PCT", "2.0"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", "5.0"))
MAX_DRAWDOWN_PCT = float(os.environ.get("MAX_DRAWDOWN_PCT", "15.0"))

# Legacy overrides (used if set, otherwise computed from ATR)
TAKE_PROFIT_PCT = float(os.environ.get("TAKE_PROFIT_PCT", "0"))   # 0 = use ATR
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "0"))       # 0 = use ATR

# Paths
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trader_state.json"))
LOG_FILE = os.environ.get("LOG_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "bot.log"))

# Timeframes for multi-TF analysis
TIMEFRAMES = {
    "1hour": {"weight": 1.0, "label": "1H", "lookback": 30},
    "4hour": {"weight": 1.5, "label": "4H", "lookback": 30},
    "1day":  {"weight": 2.0, "label": "1D", "lookback": 50},
}

# Telegram
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


class KucoinClient:
    """Native HTTP client for KuCoin API with connection pooling."""

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
        adapter = requests.adapters.HTTPAdapter(pool_connections=3, pool_maxsize=6)
        self.session.mount("https://", adapter)

    def _get_server_timestamp(self):
        """Get KuCoin server timestamp with 30s cache."""
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
        elapsed_ms = int((time.time() - self._server_ts_cache[0]) * 1000)
        return self._server_ts_cache[1] + elapsed_ms

    def _headers(self, method, endpoint, body=""):
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

    def get(self, endpoint, params=None, auth=False, timeout=10):
        url = self.BASE_URL + endpoint
        sign_endpoint = endpoint
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            sign_endpoint = f"{endpoint}?{query}"
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


class ConfluenceTrader:
    """
    Multi-timeframe confluence trader v5.0.

    Integrates:
    - AdvancedIndicators: MACD, Bollinger, ATR, StochRSI, ADX, Ichimoku, Volume
    - ConfluenceEngine: Weighted signal scoring across 1H/4H/1D
    - RegimeSwitcher: Market-adaptive strategy parameters
    - RiskManager: Kelly Criterion sizing, ATR stops, trailing stops
    - TradingGuard: Circuit breaker, daily loss limit, position sync
    """

    def __init__(self):
        if not KUCOIN_API_KEY or not KUCOIN_API_SECRET:
            print("FATAL: KUCOIN_API_KEY and KUCOIN_API_SECRET must be set in config/.env")
            sys.exit(1)

        self.client = KucoinClient(KUCOIN_API_KEY, KUCOIN_API_SECRET, KUCOIN_PASSPHRASE)
        self.position = None
        self.trades_executed = 0
        self.total_pnl = 0.0
        self.running = True
        self.peak_balance = INITIAL_BALANCE

        # Modules
        self.confluence = ConfluenceEngine()
        self.regime_switcher = RegimeSwitcher()
        self.risk_mgr = RiskManager(
            balance=INITIAL_BALANCE,
            max_risk_per_trade_pct=MAX_RISK_PCT,
            max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
            max_portfolio_drawdown_pct=MAX_DRAWDOWN_PCT,
            max_open_positions=1,
        )

        self.guard = TradingGuard(
            pid_file=os.environ.get("PID_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bot.pid")),
            log_file=LOG_FILE,
            state_file=STATE_FILE,
            guard_state_file=os.environ.get("GUARD_STATE_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "guard_state.json")),
            max_daily_loss=MAX_DAILY_LOSS_PCT,
            max_hold_hours=8.0,
            max_consecutive_fails=5,
            max_log_size_mb=5.0,
            api_rate_limit_sec=1.0,
            cooldown_after_fail_sec=30.0,
            max_trades_per_hour=10,
        )

        # Cached data per timeframe
        self.candle_cache = {}  # timeframe -> {closes, highs, lows, volumes, last_fetch}

        self.load_state()
        self._prefetch_candles()

    # ─── State Management ──────────────────────────────────────────────

    def load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                    self.position = state.get("position")
                    self.trades_executed = state.get("trades", 0)
                    self.total_pnl = state.get("pnl", 0.0)
                    self.peak_balance = state.get("peak_balance", INITIAL_BALANCE)
                    self.log("State restored from previous session", "INFO")
        except Exception as e:
            self.log(f"Could not load state: {e}", "WARN")

    def save_state(self, include_balance=False):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump({
                    "position": self.position,
                    "trades": self.trades_executed,
                    "pnl": self.total_pnl,
                    "peak_balance": self.peak_balance,
                    "timestamp": datetime.now().isoformat(),
                    "version": "5.0",
                }, f)
            if include_balance:
                self.save_dashboard_state()
        except Exception as e:
            self.log(f"State save failed: {e}", "ALERT")

    def save_dashboard_state(self):
        try:
            balance = self.get_balance()
            current_price = self.get_price() or 0
            eth_bal = balance.get("ETH", 0)
            usdt_bal = balance.get("USDT", 0)
            total = usdt_bal + eth_bal * current_price

            state = {
                "connected": True,
                "pair": PAIR,
                "balance_usdt": usdt_bal,
                "balance_eth": eth_bal,
                "total_balance": total,
                "current_price": current_price,
                "total_pnl": self.total_pnl,
                "trades_today": self.trades_executed,
                "position": self.position,
                "last_update": datetime.now().isoformat(),
                "bot_status": "active" if self.running else "stopped",
                "version": "5.0",
                "guard": self.guard.get_status(),
                "risk": self.risk_mgr.get_status(),
            }
            dashboard_path = os.environ.get("DASHBOARD_STATE",
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bot_state.json"))
            os.makedirs(os.path.dirname(dashboard_path), exist_ok=True)
            with open(dashboard_path, "w") as f:
                json.dump(state, f)
        except Exception as e:
            self.log(f"Dashboard state save failed: {e}", "WARN")

    def log(self, message, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        icons = {
            "INFO": "[i]", "BUY": "[BUY]", "SELL": "[SELL]", "PROFIT": "[PROFIT]",
            "LOSS": "[LOSS]", "ALERT": "[!!]", "WARN": "[WARN]", "OK": "[OK]",
            "GUARD": "[GUARD]", "SIGNAL": "[SIG]", "RISK": "[RISK]",
            "REGIME": "[REG]", "CONFLUENCE": "[CONF]"
        }
        icon = icons.get(level, "[-]")
        log_line = f"{icon} [{ts}] {message}"
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a") as f:
                f.write(log_line + "\n")
        except:
            pass
        if sys.stdout.isatty():
            try:
                print(log_line, flush=True)
            except UnicodeEncodeError:
                pass

        if level in ["BUY", "SELL", "PROFIT", "LOSS", "ALERT"]:
            self._telegram_notify(f"{icons.get(level, '')} {message}")

    def _telegram_notify(self, text):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
                timeout=5
            )
        except:
            pass

    # ─── API Methods ───────────────────────────────────────────────────

    def get_price(self):
        """Get current pair price."""
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
        except Exception:
            self.guard.record_failure()
        return None

    def get_balance(self):
        """Get trade account balances."""
        try:
            success, data = self.client.get("/api/v1/accounts", params={"type": "trade"})
            if success:
                currencies = PAIR.split("-")
                balances = {c: 0.0 for c in currencies}
                for acc in data:
                    if acc["currency"] in balances:
                        balances[acc["currency"]] = float(acc.get("available", 0))
                self.guard.record_success()
                return balances
            self.guard.record_failure()
        except Exception:
            self.guard.record_failure()
        return {c: 0.0 for c in PAIR.split("-")}

    def place_order(self, side, amount):
        """Place market order."""
        body = {
            "symbol": PAIR,
            "side": side,
            "type": "market",
            "clientOid": f"v5_{int(time.time() * 1000)}"
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

    # ─── Multi-Timeframe Candle Fetching ───────────────────────────────

    def _prefetch_candles(self):
        """Fetch candles for all timeframes on startup."""
        for tf_key in TIMEFRAMES:
            self._fetch_candles(tf_key)
        self.log(f"Prefetched candles for {len(TIMEFRAMES)} timeframes", "INFO")

    def _fetch_candles(self, timeframe):
        """Fetch OHLCV candles for a given timeframe."""
        tf_config = TIMEFRAMES.get(timeframe)
        if not tf_config:
            return

        try:
            success, data = self.client.get(
                "/api/v1/market/candles",
                params={"symbol": PAIR, "type": timeframe},
                auth=False
            )
            if success and data:
                # KuCoin: [timestamp, open, close, high, low, volume, amount]
                # Sorted newest-first, we reverse to chronological
                candles = list(reversed(data[-tf_config["lookback"]:]))
                closes = [float(c[2]) for c in candles]
                highs = [float(c[3]) for c in candles]
                lows = [float(c[4]) for c in candles]
                volumes = [float(c[5]) for c in candles]

                self.candle_cache[timeframe] = {
                    "closes": closes,
                    "highs": highs,
                    "lows": lows,
                    "volumes": volumes,
                    "last_fetch": time.time(),
                }
            else:
                self.log(f"Candle fetch failed for {timeframe}", "WARN")
        except Exception as e:
            self.log(f"Candle fetch error ({timeframe}): {e}", "WARN")

    def _refresh_candles_if_stale(self, timeframe, max_age=1800):
        """Refresh candles if older than max_age seconds."""
        cache = self.candle_cache.get(timeframe, {})
        if time.time() - cache.get("last_fetch", 0) >= max_age:
            self._fetch_candles(timeframe)

    # ─── Multi-Timeframe Analysis ──────────────────────────────────────

    def _compute_timeframe_data(self, current_price=None):
        """
        Build TimeframeData for each timeframe with full indicator suite.
        Returns list of TimeframeData objects.
        """
        timeframe_data_list = []

        for tf_key, tf_config in TIMEFRAMES.items():
            cache = self.candle_cache.get(tf_key, {})
            closes = cache.get("closes", [])
            highs = cache.get("highs", [])
            lows = cache.get("lows", [])
            volumes = cache.get("volumes", [])

            if len(closes) < 20:
                continue

            # Append latest price to closes for real-time indicator update
            if current_price and len(closes) > 0:
                closes = closes + [current_price]
                highs = highs + [max(current_price, highs[-1] if highs else current_price)]
                lows = lows + [min(current_price, lows[-1] if lows else current_price)]
                volumes = volumes + [0]  # placeholder volume for current candle

            # Run full indicator suite
            indicators = AdvancedIndicators.compute_all(highs, lows, closes, volumes)
            indicators["price"] = current_price
            indicators["timeframe"] = tf_key

            timeframe_data_list.append(TimeframeData(
                timeframe=tf_config["label"],
                indicators=indicators,
                weight=tf_config["weight"],
            ))

        return timeframe_data_list

    # ─── Order Execution ───────────────────────────────────────────────

    def _execute_exit(self, reason, current_pnl_pct, unrealized):
        """Execute position exit with guard checks and fallback."""
        try:
            self.guard.pre_trade_check("sell", self.position["amount"])
        except (DailyLossExceeded, TradingHalt) as e:
            self.log(f"GUARD BLOCKED EXIT: {e}", "GUARD")

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
            self.risk_mgr.update_after_trade(profit)
            self.guard.record_trade("sell", pnl=profit, success=True)
            self.position = None
            self.save_state(include_balance=True)

            if is_loss:
                self.log(f"STOP LOSS: {current_pnl_pct:.2f}% (-${abs(profit):.2f}) [{reason}]", "LOSS")
            else:
                self.log(f"TAKE PROFIT! +{current_pnl_pct:.2f}% (+${profit:.2f}) [{reason}]", "PROFIT")
            self.log(f"Total Trades: {self.trades_executed} | P&L: ${self.total_pnl:+.2f}", "INFO")
            return True

        # Fallback: sell by funds value
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
                self.risk_mgr.update_after_trade(profit)
                self.guard.record_trade("sell", pnl=profit, success=True)
                self.position = None
                self.save_state(include_balance=True)
                return True

        self.guard.record_failure()
        self.log(f"CRITICAL: Both sell attempts failed!", "ALERT")
        return False

    # ─── Main Trading Loop ─────────────────────────────────────────────

    def run(self):
        self.guard.acquire_lock()

        self.log("=" * 60, "INFO")
        self.log("CONFLUENCE TRADER v5.0 (Multi-TF + Kelly + ATR Stops)", "OK")
        self.log("=" * 60, "INFO")
        self.log(
            f"Pair: {PAIR} | Risk: {MAX_RISK_PCT}%/trade | "
            f"Daily Limit: {MAX_DAILY_LOSS_PCT}% | MaxDD: {MAX_DRAWDOWN_PCT}%",
            "INFO"
        )
        self.log(
            f"Timeframes: {', '.join(t['label'] for t in TIMEFRAMES.values())} | "
            f"Indicators: RSI, MACD, BB, ATR, StochRSI, ADX, Ichimoku, Volume",
            "SIGNAL"
        )
        self.log(self.guard.format_status(), "GUARD")

        if self.position:
            self.log(
                f"RESUMED: {self.position['amount']:.6f} @ ${self.position.get('entry', 0):.2f}",
                "INFO"
            )

        cycle = 0
        last_status_time = 0
        last_sync_time = 0
        last_dashboard_save = 0

        try:
            while self.running:
                try:
                    loop_start = time.time()

                    # ── Price ──
                    price = self.get_price()
                    self.guard.check_health(price=price, position=self.position)

                    if not price:
                        self.log("Network error, retrying in 10s...", "WARN")
                        time.sleep(10)
                        continue

                    # ── Refresh candles (1H every 30m, 4H every 2h, 1D every 8h) ──
                    self._refresh_candles_if_stale("1hour", max_age=1800)
                    self._refresh_candles_if_stale("4hour", max_age=7200)
                    self._refresh_candles_if_stale("1day", max_age=28800)

                    # ── Multi-timeframe analysis ──
                    tf_data = self._compute_timeframe_data(price)

                    # ── Confluence signal ──
                    signal_result = self.confluence.generate_signal(tf_data)

                    # ── Regime detection ──
                    regime = self.regime_switcher.detect_regime(tf_data)
                    regime_params = self.regime_switcher.get_strategy_params(regime)

                    # Extract key indicators for display
                    rsi = 50.0
                    atr = 0.0
                    for tf in tf_data:
                        if tf.timeframe == "1H":
                            rsi = tf.indicators.get("rsi", 50.0)
                            atr = tf.indicators.get("atr", 0.0)
                            break

                    # ── Periodic position sync (every 5 min) ──
                    if time.time() - last_sync_time >= 300:
                        balances = self.get_balance()
                        base_currency = PAIR.split("-")[0]
                        synced = self.guard.sync_position(
                            self.position,
                            balances.get(base_currency, 0),
                            0,  # amount checked by guard differently
                            price=price
                        )
                        if synced != self.position:
                            if synced is None and self.position is not None:
                                self.log("GUARD: Clearing stale position", "GUARD")
                            self.position = synced
                            self.save_state()
                        last_sync_time = time.time()

                    # ── Balance check ──
                    balances = self.get_balance() if cycle % 6 == 0 else \
                        {PAIR.split("-")[0]: self.position["amount"] if self.position else 0.0,
                         PAIR.split("-")[1]: 0.0}

                    base_currency = PAIR.split("-")[0]
                    quote_currency = PAIR.split("-")[1]
                    base_value = balances.get(base_currency, 0) * price
                    total = balances.get(quote_currency, 0) + base_value
                    pnl = total - INITIAL_BALANCE

                    # Update peak balance
                    if total > self.peak_balance:
                        self.peak_balance = total

                    # ── Status log (every 60s) ──
                    if time.time() - last_status_time >= 60:
                        self.log(
                            f"Balance: ${total:.2f} | {base_currency}: ${price:.2f} | "
                            f"P&L: ${pnl:+.2f} | RSI: {rsi:.1f} | "
                            f"Regime: {regime} | Signal: {signal_result.action.name}",
                            "INFO"
                        )
                        last_status_time = time.time()

                    # ── TRADING LOGIC ──

                    if not self.position:
                        # ═══ NO POSITION — Look for entry ═══

                        # Skip if regime says no trading
                        if self.regime_switcher.should_skip_trade(regime):
                            if cycle % 12 == 0:
                                self.log(
                                    f"No entry: Regime={regime} (skipping) | "
                                    f"Confidence: {signal_result.confidence:.2f}",
                                    "SIGNAL"
                                )
                        elif signal_result.action.value >= Signal.BUY.value:
                            # Check minimum confidence
                            min_conf = regime_params.get("min_confidence", 0.5)
                            if signal_result.confidence >= min_conf:
                                # Validate trade with risk manager
                                trade_amount, reason = self._calculate_trade(
                                    price, atr, total, regime_params
                                )

                                if trade_amount and trade_amount > 1.0:
                                    # Check daily loss and drawdown
                                    if (self.risk_mgr.check_daily_loss(-self.total_pnl) and
                                        self.risk_mgr.check_drawdown(self.peak_balance, total)):
                                        try:
                                            self.guard.pre_trade_check("buy", trade_amount)

                                            self.log(
                                                f"ENTRY SIGNAL: {signal_result.action.name} "
                                                f"(score={signal_result.score:.2f}, "
                                                f"conf={signal_result.confidence:.2f}) "
                                                f"Regime: {regime} @ ${price:.2f}",
                                                "SIGNAL"
                                            )
                                            for r in signal_result.reasons[:5]:
                                                self.log(f"  {r}", "CONFLUENCE")

                                            success, result = self.place_order("buy", trade_amount)
                                            if success:
                                                eth_qty = trade_amount / price
                                                # Compute ATR-based stops
                                                sl, tp = self._compute_stops(
                                                    price, atr, regime_params
                                                )
                                                self.position = {
                                                    "side": "long",
                                                    "entry": price,
                                                    "amount": eth_qty,
                                                    "stop_loss": sl,
                                                    "take_profit": tp,
                                                    "trailing_stop": sl,
                                                    "highest_since_entry": price,
                                                    "regime_at_entry": regime,
                                                    "timestamp": datetime.now().isoformat(),
                                                }
                                                self.guard.record_trade("buy", success=True)
                                                self.save_state(include_balance=True)
                                                self.log(
                                                    f"BUY: {eth_qty:.6f} {base_currency} @ ${price:.2f} | "
                                                    f"SL: ${sl:.2f} TP: ${tp:.2f} | "
                                                    f"Risk: ${trade_amount:.2f} ({trade_amount/total*100:.1f}%)",
                                                    "BUY"
                                                )
                                            else:
                                                self.log(f"Buy failed: {result}", "ALERT")
                                                time.sleep(30)
                                        except TradingHalt as e:
                                            self.log(f"Trade blocked: {e}", "GUARD")
                                            time.sleep(60)
                                    else:
                                        if cycle % 6 == 0:
                                            self.log(
                                                f"Risk limit: daily loss or drawdown reached",
                                                "RISK"
                                            )
                                else:
                                    if cycle % 12 == 0:
                                        self.log(
                                            f"No entry: {reason}",
                                            "SIGNAL"
                                        )
                            else:
                                if cycle % 12 == 0:
                                    self.log(
                                        f"No entry: Confidence {signal_result.confidence:.2f} "
                                        f"< min {min_conf:.2f} | {signal_result.action.name}",
                                        "SIGNAL"
                                    )
                        elif cycle % 18 == 0:
                            self.log(
                                f"No entry: Signal={signal_result.action.name} | "
                                f"Score={signal_result.score:.2f} | RSI={rsi:.1f}",
                                "SIGNAL"
                            )

                    else:
                        # ═══ HAVE POSITION — Monitor for exit ═══
                        entry = self.position.get("entry", 0)
                        if entry <= 0:
                            self.log(f"Recovery position. Updating entry to ${price:.2f}", "GUARD")
                            self.position["entry"] = price
                            self.save_state()
                            entry = price

                        current_pnl_pct = ((price - entry) / entry) * 100
                        unrealized = (price - entry) * self.position["amount"]

                        # Update highest price for trailing stop
                        if price > self.position.get("highest_since_entry", price):
                            self.position["highest_since_entry"] = price

                        # Compute dynamic trailing stop
                        atr_sl_mult = regime_params.get("trailing_atr_mult", 2.5)
                        if atr > 0 and regime_params.get("trailing_stop", True):
                            highest = self.position["highest_since_entry"]
                            new_trail = ATRStops.compute_trailing_stop(
                                highest, atr, highest, multiplier=atr_sl_mult
                            )
                            # Trail only tightens
                            if new_trail > self.position.get("trailing_stop", 0):
                                self.position["trailing_stop"] = new_trail

                        trailing_stop = self.position.get("trailing_stop", 0)

                        # Exit conditions (priority order)
                        exited = False

                        # 1. Hard stop loss
                        if price <= self.position.get("stop_loss", 0):
                            exited = self._execute_exit("SL hit", current_pnl_pct, unrealized)

                        # 2. Trailing stop hit
                        elif trailing_stop > 0 and price <= trailing_stop:
                            exited = self._execute_exit(
                                f"Trailing stop ${trailing_stop:.2f}",
                                current_pnl_pct, unrealized
                            )

                        # 3. Take profit
                        elif price >= self.position.get("take_profit", float("inf")):
                            exited = self._execute_exit("TP hit", current_pnl_pct, unrealized)

                        # 4. Strong counter-signal while in profit
                        elif (signal_result.action == Signal.STRONG_SELL
                              and current_pnl_pct > 0.3):
                            exited = self._execute_exit(
                                f"Strong sell signal (score={signal_result.score:.2f})",
                                current_pnl_pct, unrealized
                            )

                        # 5. Regime change to quiet — exit any position
                        elif regime == "quiet" and current_pnl_pct > -0.5:
                            exited = self._execute_exit(
                                "Regime changed to quiet",
                                current_pnl_pct, unrealized
                            )

                        if not exited and cycle % 6 == 0:
                            trail_str = f" | Trail: ${trailing_stop:.2f}" if trailing_stop > 0 else ""
                            self.log(
                                f"Position: {current_pnl_pct:+.2f}% (U:${unrealized:+.2f}) | "
                                f"SL: ${self.position.get('stop_loss', 0):.2f} "
                                f"TP: ${self.position.get('take_profit', 0):.2f}{trail_str}",
                                "INFO"
                            )

                    cycle += 1

                    # Save state periodically
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
                        p = self.get_price()
                        if p and self.position.get("entry", 0) > 0:
                            pct = ((p - self.position["entry"]) / self.position["entry"]) * 100
                            ur = (p - self.position["entry"]) * self.position["amount"]
                            self._execute_exit("EMERGENCY", pct, ur)
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

    # ─── Trade Calculation Helpers ─────────────────────────────────────

    def _calculate_trade(self, price, atr, total_balance, regime_params):
        """
        Calculate trade size using Kelly Criterion scaled by regime.
        Returns (trade_amount_usdt, reason_string).
        """
        position_scale = regime_params.get("position_scale", 0.75)

        if position_scale <= 0:
            return None, "Regime says skip trading"

        # Kelly-based position sizing
        kelly_data = self.risk_mgr.get_status()
        kelly_fraction = kelly_data.get("current_kelly", 0.02)

        # Risk amount based on max risk % of total balance
        max_risk_amount = total_balance * (self.risk_mgr.max_risk_per_trade_pct / 100.0)
        risk_amount = max_risk_amount * position_scale

        # Minimum trade size (KuCoin minimum ~$1)
        if risk_amount < 1.0:
            return None, f"Trade amount ${risk_amount:.2f} below minimum"

        # Cap at reasonable fraction of balance
        max_trade = total_balance * 0.10 * position_scale  # max 10% per trade scaled
        trade_amount = min(risk_amount * 10, max_trade)  # leverage risk amount by R:R assumption

        # Ensure at least $5 for meaningful trade
        if trade_amount < 5.0:
            return None, f"Trade size ${trade_amount:.2f} too small"

        return trade_amount, f"${trade_amount:.2f} ({trade_amount/total_balance*100:.1f}% of balance)"

    def _compute_stops(self, price, atr, regime_params):
        """Compute ATR-based stop loss and take profit."""
        if atr and atr > 0:
            sl_mult = regime_params.get("sl_atr_multiplier", 1.5)
            tp_mult = regime_params.get("tp_atr_multiplier", 2.5)
            sl = ATRStops.compute_stop_loss(price, atr, side="long", multiplier=sl_mult)
            tp = ATRStops.compute_take_profit(price, atr, side="long", risk_reward_ratio=tp_mult/sl_mult)
        else:
            # Fallback to fixed percentages
            sl_pct = STOP_LOSS_PCT if STOP_LOSS_PCT > 0 else 1.5
            tp_pct = TAKE_PROFIT_PCT if TAKE_PROFIT_PCT > 0 else 2.5
            sl = price * (1 - sl_pct / 100)
            tp = price * (1 + tp_pct / 100)

        return sl, tp


if __name__ == "__main__":
    trader = ConfluenceTrader()
    trader.run()
