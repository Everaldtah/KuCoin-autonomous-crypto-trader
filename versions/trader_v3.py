#!/usr/bin/env python3
"""
LIVE ETH-USDT Trading Bot v3.0 - Guard-Protected Edition

Built on v2.5 but with TradingGuard wrapping all critical paths:
- No duplicate processes
- Circuit breaker on API failures
- Daily loss limit ($5)
- Max hold time (4h)
- Position-reality sync
- Log rotation
- Rate limiting

Changes from v2.5:
+ TradingGuard integrated at all decision points
+ State save errors are no longer silent
+ save_state() doesn't call get_balance() every cycle (was hammering API)
+ Position sync detects stale/orphaned state
+ Emergency stop on catastrophic loss
"""

import json
import time
import hashlib
import hmac
import math
import base64
import subprocess
import sys
import os
from datetime import datetime, timedelta
from threading import Thread

# Import the guard
from trading_guard import TradingGuard, TradingHalt, CircuitOpen, DailyLossExceeded

# Bot configuration
CREDS = {
    "api_key": "YOUR_API_KEY",
    "api_secret": "YOUR_API_SECRET",
    "passphrase": "YOUR_PASSPHRASE"
}

PAIR = "ETH-USDT"
INITIAL_BALANCE = 72.982119
TRADE_AMOUNT = 25.0
TAKE_PROFIT_PCT = 2.5
STOP_LOSS_PCT = 1.5
STATE_FILE = "/root/trader_state.json"
LOG_FILE = "/root/bot.log"


class RobustTrader:
    def __init__(self):
        self.position = None
        self.trades_executed = 0
        self.total_pnl = 0.0
        self.running = True

        # Initialize guard
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

    def load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                    self.position = state.get('position')
                    self.trades_executed = state.get('trades', 0)
                    self.total_pnl = state.get('pnl', 0.0)
                    self.log("State restored from previous session", "INFO")
        except Exception as e:
            self.log(f"Could not load state: {e}", "WARN")

    def save_state(self, include_balance=False):
        """Save state. Only fetches balance when explicitly requested."""
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump({
                    'position': self.position,
                    'trades': self.trades_executed,
                    'pnl': self.total_pnl,
                    'timestamp': datetime.now().isoformat()
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
                'connected': True,
                'pair': PAIR,
                'balance_usdt': balance.get('USDT', 0),
                'balance_eth': balance.get('ETH', 0),
                'total_balance': balance.get('USDT', 0) + (balance.get('ETH', 0) * current_price),
                'current_price': current_price,
                'total_pnl': self.total_pnl,
                'trades_today': self.trades_executed,
                'position': self.position,
                'last_update': datetime.now().isoformat(),
                'bot_status': 'active' if self.running else 'stopped',
                'guard': self.guard.get_status(),
            }

            with open('/root/bot_state.json', 'w') as f:
                json.dump(state, f)
        except Exception as e:
            self.log(f"Dashboard state save failed: {e}", "WARN")

    def log(self, message, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        icons = {
            "INFO": "ℹ️", "BUY": "🟢", "SELL": "🔴", "PROFIT": "💰",
            "LOSS": "⚠️", "ALERT": "🚨", "WARN": "⚡", "OK": "✅",
            "GUARD": "🛡️"
        }
        log_line = f"{icons.get(level, '•')} [{ts}] {message}"

        print(log_line)
        sys.stdout.flush()

        try:
            with open(LOG_FILE, 'a') as f:
                f.write(log_line + "\n")
        except:
            pass

        if level in ["BUY", "SELL", "PROFIT", "LOSS", "ALERT"]:
            try:
                subprocess.run([
                    "termux-notification",
                    "--title", "ETH Trader",
                    "--content", message,
                    "--priority", "high" if level in ["ALERT", "PROFIT", "LOSS"] else "default",
                    "--id", "1000"
                ], check=False)
            except:
                pass

    def get_kucoin_timestamp(self):
        try:
            result = subprocess.run(
                ["curl", "-s", "https://api.kucoin.com/api/v1/timestamp"],
                capture_output=True, text=True, timeout=10
            )
            return json.loads(result.stdout)["data"]
        except:
            return int(time.time() * 1000)

    def get_signature(self, endpoint, method="GET", body=""):
        now = self.get_kucoin_timestamp()
        str_to_sign = str(now) + method.upper() + endpoint + body
        signature = base64.b64encode(
            hmac.new(CREDS["api_secret"].encode(), str_to_sign.encode(), hashlib.sha256).digest()
        ).decode()
        passphrase_sig = base64.b64encode(
            hmac.new(CREDS["api_secret"].encode(), CREDS["passphrase"].encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "KC-API-KEY": CREDS["api_key"],
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": str(now),
            "KC-API-PASSPHRASE": passphrase_sig,
            "KC-API-KEY-VERSION": "2"
        }

    def api_call(self, command_str):
        """API call with guard circuit breaker."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    command_str,
                    capture_output=True, text=True, timeout=30, shell=True
                )
                data = json.loads(result.stdout)
                if data.get("code") == "200000":
                    self.guard.record_success()
                    return True, data["data"]
                if attempt == max_retries - 1:
                    self.guard.record_failure()
                    return False, data
            except Exception as e:
                if attempt == max_retries - 1:
                    self.guard.record_failure()
                    return False, str(e)
                time.sleep(1)
        self.guard.record_failure()
        return False, "Max retries exceeded"

    def get_price(self):
        cmd = f"curl -s 'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={PAIR}'"
        success, data = self.api_call(cmd)
        if success:
            return float(data.get("price", 0))
        return None

    def get_balance(self):
        headers = self.get_signature("/api/v1/accounts?type=trade")
        cmd = [
            "curl", "-s",
            "-H", f"KC-API-KEY: {headers['KC-API-KEY']}",
            "-H", f"KC-API-SIGN: {headers['KC-API-SIGN']}",
            "-H", f"KC-API-TIMESTAMP: {headers['KC-API-TIMESTAMP']}",
            "-H", f"KC-API-PASSPHRASE: {headers['KC-API-PASSPHRASE']}",
            "-H", "KC-API-KEY-VERSION: 2",
            "https://api.kucoin.com/api/v1/accounts?type=trade"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            if data.get("code") == "200000":
                balances = {"ETH": 0.0, "USDT": 0.0}
                for acc in data["data"]:
                    if acc["currency"] in balances:
                        balances[acc["currency"]] = float(acc.get("available", 0))
                self.guard.record_success()
                return balances
            self.guard.record_failure()
        except Exception as e:
            self.log(f"Balance fetch error: {e}", "WARN")
            self.guard.record_failure()
        return {"ETH": 0.0, "USDT": 0.0}

    def place_order(self, side, amount):
        body_dict = {
            "symbol": PAIR,
            "side": side,
            "type": "market",
            "clientOid": f"trader_{int(time.time() * 1000)}"
        }
        if side == "buy":
            body_dict["funds"] = str(amount)
        else:
            if amount < 1.0:
                rounded = math.floor(amount * 100000) / 100000
                body_dict["size"] = str(rounded)
            else:
                body_dict["funds"] = str(round(amount, 2))

        body = json.dumps(body_dict)
        headers = self.get_signature("/api/v1/orders", "POST", body)

        cmd = [
            "curl", "-s", "-X", "POST",
            "-H", f"KC-API-KEY: {headers['KC-API-KEY']}",
            "-H", f"KC-API-SIGN: {headers['KC-API-SIGN']}",
            "-H", f"KC-API-TIMESTAMP: {headers['KC-API-TIMESTAMP']}",
            "-H", f"KC-API-PASSPHRASE: {headers['KC-API-PASSPHRASE']}",
            "-H", "KC-API-KEY-VERSION: 2",
            "-H", "Content-Type: application/json",
            "-d", body,
            "https://api.kucoin.com/api/v1/orders"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            if data.get("code") == "200000":
                self.guard.record_success()
                return True, data["data"]
            self.guard.record_failure()
            return False, data.get("msg", "Unknown error")
        except Exception as e:
            self.guard.record_failure()
            return False, str(e)

    def _execute_exit(self, reason, current_pnl_pct, unrealized):
        """Safely execute a position exit with retries and guard checks."""
        # Pre-trade guard check
        try:
            self.guard.pre_trade_check("sell", self.position["amount"])
        except (DailyLossExceeded, TradingHalt) as e:
            self.log(f"GUARD BLOCKED EXIT: {e}", "GUARD")
            # Still try to exit — loss limit means we NEED out
            # But log it as a guard event

        amount = self.position["amount"]
        is_loss = unrealized < 0

        # Primary attempt: sell by ETH size
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
                self.total_pnl -= abs(profit) if is_loss else 0
                self.total_pnl += profit if not is_loss else 0
                self.trades_executed += 1
                self.guard.record_trade("sell", pnl=profit, success=True)
                self.position = None
                self.save_state(include_balance=True)
                return True

        # Both failed — log emergency but don't loop
        self.guard.record_failure()
        self.log(f"CRITICAL: Both sell attempts failed! Position still open. {result} | {result2 if not success else ''}", "ALERT")
        return False

    def run(self):
        """Main trading loop with guard protection."""
        # Acquire exclusive process lock (kills duplicates)
        self.guard.acquire_lock()

        self.log("=" * 60, "INFO")
        self.log("ROBUST ETH-USDT TRADER v3.0 (Guard-Protected)", "OK")
        self.log("=" * 60, "INFO")
        self.log(f"Balance: ${INITIAL_BALANCE:.2f} | Trade: ${TRADE_AMOUNT} | TP:{TAKE_PROFIT_PCT}% SL:{STOP_LOSS_PCT}%", "INFO")
        self.log(self.guard.format_status(), "GUARD")

        if self.position:
            self.log(f"RESUMED: Open position {self.position['amount']:.6f} ETH @ ${self.position['entry']:.2f}", "INFO")

        cycle = 0
        last_status_time = 0
        last_sync_time = 0
        last_balance_save = 0
        last_dashboard_save = 0
        consecutive_sell_fails = 0

        try:
            while self.running:
                try:
                    main_loop_start = time.time()

                    # ── Guard health check ──
                    price = self.get_price()
                    self.guard.check_health(price=price, position=self.position)

                    if not price:
                        self.log("Network error, retrying in 10s...", "WARN")
                        time.sleep(10)
                        continue

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

                    # Get balance (only for status, not every cycle)
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
                        self.log(f"Balance: ${total:.2f} | ETH: ${price:.2f} | P&L: ${pnl:+.2f}", "INFO")
                        last_status_time = time.time()

                    # ── TRADING LOGIC ──

                    if not self.position:
                        # NO POSITION - Look for entry
                        if cycle >= 6 and balances.get("USDT", 0) >= TRADE_AMOUNT * 1.05:
                            try:
                                self.guard.pre_trade_check("buy", TRADE_AMOUNT)
                                eth_qty = TRADE_AMOUNT / price
                                self.log(f"ENTRY SIGNAL: Price ${price:.2f}", "INFO")

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
                    else:
                        # HAVE POSITION - Monitor for exit
                        entry = self.position.get("entry", 0)
                        if entry <= 0:
                            # Recovery position with unknown entry — use current price
                            self.log(f"Recovery position (no entry price). Updating to ${price:.2f}", "GUARD")
                            self.position["entry"] = price
                            self.save_state()
                            entry = price
                        current_pnl_pct = ((price - entry) / entry) * 100
                        unrealized = (price - entry) * self.position["amount"]

                        # Check exit conditions
                        if current_pnl_pct >= TAKE_PROFIT_PCT:
                            self._execute_exit("TP hit", current_pnl_pct, unrealized)

                        elif current_pnl_pct <= -STOP_LOSS_PCT:
                            self._execute_exit("SL hit", current_pnl_pct, unrealized)

                        else:
                            # Position running normally
                            if cycle % 6 == 0:
                                self.log(f"Position: {current_pnl_pct:+.2f}% (U:${unrealized:+.2f} E:${price:.2f})", "INFO")

                    cycle += 1

                    # Save state periodically (lightweight, no API call)
                    if cycle % 3 == 0:
                        self.save_state(include_balance=False)

                    # Full dashboard save every 60s
                    if time.time() - last_dashboard_save >= 60:
                        self.save_state(include_balance=True)
                        last_dashboard_save = time.time()

                    # Calculate sleep to maintain 10s cycle
                    elapsed = time.time() - main_loop_start
                    sleep_time = max(0, 10 - elapsed)
                    time.sleep(sleep_time)

                except CircuitOpen as e:
                    self.log(f"CIRCUIT BREAKER: {e}", "GUARD")
                    # Wait for circuit to close (exponential backoff)
                    wait = min(60 * (2 ** min(self.guard._state["consecutive_fails"], 5)), 600)
                    self.log(f"Pausing {wait}s for recovery...", "GUARD")
                    time.sleep(wait)

                except TradingHalt as e:
                    self.log(f"EMERGENCY: {e}", "ALERT")
                    # Try to force-exit position if we have one
                    if self.position:
                        price = self.get_price()
                        if price:
                            pnl_pct = ((price - self.position["entry"]) / self.position["entry"]) * 100
                            unrealized = (price - self.position["entry"]) * self.position["amount"]
                            self._execute_exit("EMERGENCY", pnl_pct, unrealized)
                    # Stop the bot
                    self.log("Bot stopped by guard. Manual restart required.", "ALERT")
                    break

                except Exception as e:
                    self.log(f"ERROR: {str(e)[:100]}", "ALERT")
                    self.guard.record_failure()
                    self.save_state()
                    time.sleep(10)

        finally:
            # Always clean up
            self.running = False
            self.save_state(include_balance=True)
            self.guard.release_lock()
            self.log("Final state saved. Bot stopped.", "INFO")

if __name__ == "__main__":
    trader = RobustTrader()
    trader.run()
