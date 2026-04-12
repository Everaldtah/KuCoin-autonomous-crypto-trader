#!/usr/bin/env python3
"""
Trading Guard Module v1.1
=========================
Prevents loops, bugs, and runaway losses in the ETH trading bot.

Import and wrap around any trading bot to get:
  - Duplicate process prevention (PID lockfile)
  - Circuit breaker for API failures
  - Daily loss limit enforcement (fixed $ and percentage-based)
  - Portfolio drawdown tracking (peak-balance high-water mark)
  - Correlation warning (rapid-loss cluster detection)
  - Max position hold time
  - Position-reality sync (detects stale state)
  - Log rotation (prevents disk fill)
  - Rate limiting for API calls
  - Emergency shutdown on critical conditions

Usage:
  from trading_guard import TradingGuard

  guard = TradingGuard(
      pid_file="/root/bot.pid",
      log_file="/root/bot.log",
      state_file="/root/trader_state.json",
      max_daily_loss=5.0,              # $5 max daily loss
      max_daily_loss_pct=5.0,          # 5% of starting balance
      max_drawdown_pct=15.0,           # 15% drawdown from peak
      max_hold_hours=4,                # Force-exit after 4h in same position
      max_consecutive_fails=5,         # Circuit breaker threshold
      max_log_size_mb=5,               # Rotate log at 5MB
      api_rate_limit_sec=1,            # Min 1s between API calls
      correlation_loss_window_sec=300, # 5-min window for rapid loss detection
      correlation_loss_threshold=3,    # 3 losses in window triggers cooldown
  )

  # In your main loop:
  guard.acquire_lock()              # Kills duplicate processes
  guard.rotate_log_if_needed()
  guard.update_balance(total_usd)   # Feed portfolio value each iteration

  while running:
      guard.check_health(price, position)  # Raises TradingHalt on critical

      # Wrap API calls:
      data = guard.guarded_call(get_price)

      # Before placing orders:
      guard.pre_trade_check(side, amount)

      # After trade result:
      guard.record_trade(result)

  # On shutdown:
  guard.release_lock()
"""

import os
import sys
import json
import time
import fcntl
import signal
import logging
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from functools import wraps


class TradingHalt(Exception):
    """Raised when the guard determines trading should stop."""
    pass


class CircuitOpen(Exception):
    """Raised when circuit breaker is tripped - too many consecutive failures."""
    pass


class DailyLossExceeded(Exception):
    """Raised when daily loss limit is breached."""
    pass


class StalePositionError(Exception):
    """Raised when position state doesn't match exchange reality."""
    pass


class DuplicateProcessError(Exception):
    """Raised when another instance is already running."""
    pass


class TradingGuard:
    """
    Comprehensive safety wrapper for trading bots.

    Prevents:
    - Duplicate bot processes (PID lockfile with auto-kill of stale PIDs)
    - Runaway losses (daily loss limit)
    - API failure loops (circuit breaker with exponential backoff)
    - Stale state (position-reality reconciliation)
    - Disk fill (log rotation)
    - Position limbo (max hold time enforcement)
    - Rate limit violations (API call throttling)
    """

    def __init__(
        self,
        pid_file: str = os.environ.get("PID_FILE", "/tmp/bot.pid"),
        log_file: str = os.environ.get("LOG_FILE", "/tmp/bot.log"),
        state_file: str = os.environ.get("STATE_FILE", "/tmp/trader_state.json"),
        guard_state_file: str = os.environ.get("GUARD_STATE_FILE", "/tmp/guard_state.json"),
        max_daily_loss: float = 5.0,
        max_hold_hours: float = 4.0,
        max_consecutive_fails: int = 5,
        max_log_size_mb: float = 5.0,
        api_rate_limit_sec: float = 1.0,
        cooldown_after_fail_sec: float = 30.0,
        max_trades_per_hour: int = 10,
        # ── Portfolio-level risk parameters ──
        max_daily_loss_pct: float = 5.0,
        max_drawdown_pct: float = 15.0,
        correlation_loss_window_sec: float = 300.0,
        correlation_loss_threshold: int = 3,
        correlation_cooldown_multiplier: float = 3.0,
    ):
        self.pid_file = pid_file
        self.log_file = log_file
        self.state_file = state_file
        self.guard_state_file = guard_state_file
        self.max_daily_loss = max_daily_loss
        self.max_hold_hours = max_hold_hours
        self.max_consecutive_fails = max_consecutive_fails
        self.max_log_size_bytes = max_log_size_mb * 1024 * 1024
        self.api_rate_limit_sec = api_rate_limit_sec
        self.cooldown_after_fail_sec = cooldown_after_fail_sec
        self.max_trades_per_hour = max_trades_per_hour

        # Portfolio-level risk settings
        self.max_daily_loss_pct = max_daily_loss_pct          # e.g. 5.0 means 5%
        self.max_drawdown_pct = max_drawdown_pct              # e.g. 15.0 means 15% drawdown from peak
        self.correlation_loss_window_sec = correlation_loss_window_sec   # seconds for rapid-loss window
        self.correlation_loss_threshold = correlation_loss_threshold     # losses in window to trigger warning
        self.correlation_cooldown_multiplier = correlation_cooldown_multiplier

        self._lock_fd = None
        self._api_lock = Lock()
        self._last_api_call = 0.0

        # Runtime counters (persisted to guard_state_file)
        self._state = self._load_guard_state()

    # ─── Guard State Persistence ──────────────────────────────────

    def _default_state(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "daily_loss": 0.0,
            "daily_loss_date": today,
            "consecutive_fails": 0,
            "circuit_open_until": None,
            "trades_today": 0,
            "trades_today_date": today,
            "trade_timestamps": [],
            "last_position_entry": None,
            "total_guarded_calls": 0,
            "total_blocked_trades": 0,
            "emergency_stops": 0,
            "last_health_check": None,
            # ── Portfolio-level risk state ──
            "peak_balance": 0.0,
            "current_balance": 0.0,
            "starting_balance_today": 0.0,
            "max_drawdown_reached_pct": 0.0,
            "loss_timestamps": [],
            "correlation_warnings": 0,
            "correlation_cooldown_active": False,
            "correlation_cooldown_until": None,
        }

    def _load_guard_state(self) -> dict:
        try:
            if os.path.exists(self.guard_state_file):
                with open(self.guard_state_file, "r") as f:
                    saved = json.load(f)
                # Reset daily counters if date changed
                today = datetime.now().strftime("%Y-%m-%d")
                if saved.get("daily_loss_date") != today:
                    saved["daily_loss"] = 0.0
                    saved["daily_loss_date"] = today
                    saved["starting_balance_today"] = saved.get("current_balance", 0.0)
                if saved.get("trades_today_date") != today:
                    saved["trades_today"] = 0
                    saved["trades_today_date"] = today
                    saved["trade_timestamps"] = []
                # Backfill any missing portfolio risk keys from defaults
                defaults = self._default_state()
                for key in defaults:
                    if key not in saved:
                        saved[key] = defaults[key]
                return saved
        except Exception:
            pass
        return self._default_state()

    def _save_guard_state(self):
        try:
            with open(self.guard_state_file, "w") as f:
                json.dump(self._state, f, indent=2)
        except Exception:
            pass

    def _reset_daily_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._state.get("daily_loss_date") != today:
            self._state["daily_loss"] = 0.0
            self._state["daily_loss_date"] = today
            self._state["trades_today"] = 0
            self._state["trades_today_date"] = today
            self._state["trade_timestamps"] = []
            self._state["starting_balance_today"] = self._state.get("current_balance", 0.0)
            self._state["loss_timestamps"] = []

    # ─── Duplicate Process Prevention ─────────────────────────────

    def acquire_lock(self):
        """
        Acquire exclusive PID lock. Kills stale processes if needed.
        Raises DuplicateProcessError if a live process holds the lock.
        """
        try:
            # Check if PID file exists and process is alive
            if os.path.exists(self.pid_file):
                try:
                    with open(self.pid_file, "r") as f:
                        old_pid = int(f.read().strip())

                    # Check if old process is still alive
                    if self._is_process_alive(old_pid):
                        # Check if it's actually our bot (not some reused PID)
                        cmdline = self._get_process_cmdline(old_pid)
                        if cmdline and "live_eth_trader" in cmdline:
                            # It's a real duplicate — kill it
                            print(f"[GUARD] ⚠️ Killing duplicate bot process PID {old_pid}")
                            os.kill(old_pid, signal.SIGTERM)
                            time.sleep(2)
                            if self._is_process_alive(old_pid):
                                os.kill(old_pid, signal.SIGKILL)
                                time.sleep(1)
                            print(f"[GUARD] ✅ Duplicate process terminated")
                        else:
                            # PID reused by something else — safe to overwrite
                            pass
                except (ValueError, ProcessLookupError, PermissionError):
                    pass  # Stale or invalid PID file — safe to proceed

            # Create/truncate PID file and acquire flock
            self._lock_fd = open(self.pid_file, "w")
            self._lock_fd.write(str(os.getpid()))
            self._lock_fd.flush()

            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                raise DuplicateProcessError(
                    f"Another bot process holds the lock on {self.pid_file}"
                )

            print(f"[GUARD] 🔒 Process lock acquired (PID {os.getpid()})")

        except DuplicateProcessError:
            raise
        except Exception as e:
            print(f"[GUARD] ⚠️ Lock acquisition warning: {e}")
            # Continue without lock rather than crash
            self._lock_fd = None

    def release_lock(self):
        """Release the PID lock on shutdown."""
        try:
            if self._lock_fd:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                self._lock_fd.close()
                self._lock_fd = None
            if os.path.exists(self.pid_file):
                # Only remove if it contains our PID
                try:
                    with open(self.pid_file, "r") as f:
                        if f.read().strip() == str(os.getpid()):
                            os.remove(self.pid_file)
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    @staticmethod
    def _get_process_cmdline(pid: int) -> str:
        try:
            with open(f"/proc/{pid}/cmdline", "r") as f:
                return f.read().replace("\x00", " ")
        except Exception:
            return ""

    # ─── Log Rotation ─────────────────────────────────────────────

    def rotate_log_if_needed(self):
        """Rotate log file if it exceeds max size. Keeps 1 backup."""
        try:
            if not os.path.exists(self.log_file):
                return
            size = os.path.getsize(self.log_file)
            if size > self.max_log_size_bytes:
                backup = self.log_file + ".1"
                if os.path.exists(backup):
                    os.remove(backup)
                os.rename(self.log_file, backup)
                print(f"[GUARD] 📝 Log rotated (was {size / 1024 / 1024:.1f}MB)")
        except Exception:
            pass

    # ─── Circuit Breaker ──────────────────────────────────────────

    def _check_circuit(self):
        """
        Check if circuit breaker is open.
        Raises CircuitOpen if too many consecutive failures.
        """
        # Check if circuit was opened with a timeout
        open_until = self._state.get("circuit_open_until")
        if open_until:
            if datetime.now().isoformat() < open_until:
                raise CircuitOpen(
                    f"Circuit breaker open until {open_until}. "
                    f"Consecutive fails: {self._state['consecutive_fails']}"
                )
            else:
                # Circuit half-open — allow one attempt
                self._state["circuit_open_until"] = None

        if self._state["consecutive_fails"] >= self.max_consecutive_fails:
            # Open circuit for escalating cooldown
            cooldown = min(
                self.cooldown_after_fail_sec * (2 ** (self._state["consecutive_fails"] - self.max_consecutive_fails)),
                3600  # Max 1 hour
            )
            open_until = (datetime.now() + timedelta(seconds=cooldown)).isoformat()
            self._state["circuit_open_until"] = open_until
            self._save_guard_state()
            raise CircuitOpen(
                f"Circuit breaker tripped! {self._state['consecutive_fails']} consecutive failures. "
                f"Paused for {cooldown:.0f}s"
            )

    def record_success(self):
        """Record a successful API call — resets failure counter."""
        self._state["consecutive_fails"] = 0
        self._state["circuit_open_until"] = None
        self._state["total_guarded_calls"] += 1

    def record_failure(self):
        """Record a failed API call — increments failure counter."""
        self._state["consecutive_fails"] += 1
        self._save_guard_state()
        print(
            f"[GUARD] ⚠️ API failure #{self._state['consecutive_fails']}/"
            f"{self.max_consecutive_fails}"
        )

    # ─── Rate Limiting ────────────────────────────────────────────

    def _rate_limit(self):
        """Enforce minimum time between API calls."""
        with self._api_lock:
            now = time.time()
            elapsed = now - self._last_api_call
            if elapsed < self.api_rate_limit_sec:
                time.sleep(self.api_rate_limit_sec - elapsed)
            self._last_api_call = time.time()

    # ─── Guarded API Call ─────────────────────────────────────────

    def guarded_call(self, fn, *args, **kwargs):
        """
        Wrap an API call with circuit breaker + rate limiting.

        Usage:
            price = guard.guarded_call(bot.get_price)
            balance = guard.guarded_call(bot.get_balance)

        Returns the function result on success.
        Raises CircuitOpen if circuit breaker is tripped.
        """
        self._check_circuit()
        self._rate_limit()

        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except CircuitOpen:
            raise
        except Exception as e:
            self.record_failure()
            raise

    # ─── Trade Guards ─────────────────────────────────────────────

    def pre_trade_check(self, side: str, amount: float):
        """
        Validate a trade before execution.
        Raises TradingHalt if trade should be blocked.
        """
        self._reset_daily_if_needed()
        self._check_circuit()

        # ── Check correlation cooldown ──
        correlation_remaining = self._check_correlation_cooldown()
        if correlation_remaining > 0:
            self._state["total_blocked_trades"] += 1
            self._save_guard_state()
            raise TradingHalt(
                f"Correlation cooldown active: {correlation_remaining:.0f}s remaining. "
                f"Multiple rapid losses detected."
            )

        # ── Check daily loss limit (fixed dollar) ──
        if side == "sell":
            if self._state["daily_loss"] >= self.max_daily_loss:
                self._state["total_blocked_trades"] += 1
                self._save_guard_state()
                raise DailyLossExceeded(
                    f"Daily loss limit reached: ${self._state['daily_loss']:.2f} / "
                    f"${self.max_daily_loss:.2f}"
                )

        # ── Check daily loss limit (percentage-based) ──
        if self._state.get("starting_balance_today", 0) > 0:
            daily_loss_pct_actual = (
                self._state["daily_loss"] / self._state["starting_balance_today"] * 100
            )
            if daily_loss_pct_actual >= self.max_daily_loss_pct:
                self._state["total_blocked_trades"] += 1
                self._save_guard_state()
                raise DailyLossExceeded(
                    f"Daily loss % limit reached: {daily_loss_pct_actual:.2f}% / "
                    f"{self.max_daily_loss_pct:.2f}% of starting balance "
                    f"(${self._state['starting_balance_today']:.2f})"
                )

        # ── Check portfolio drawdown ──
        if self._state.get("peak_balance", 0) > 0:
            drawdown_pct = self._compute_drawdown_pct()
            if drawdown_pct >= self.max_drawdown_pct:
                self._state["total_blocked_trades"] += 1
                self._save_guard_state()
                raise TradingHalt(
                    f"Portfolio drawdown limit reached: {drawdown_pct:.2f}% / "
                    f"{self.max_drawdown_pct:.2f}% from peak "
                    f"(${self._state['peak_balance']:.2f})"
                )

        # Check trades-per-hour rate
        now = time.time()
        one_hour_ago = now - 3600
        recent_trades = [
            t for t in self._state.get("trade_timestamps", [])
            if t > one_hour_ago
        ]
        if len(recent_trades) >= self.max_trades_per_hour:
            self._state["total_blocked_trades"] += 1
            self._save_guard_state()
            raise TradingHalt(
                f"Trade rate limit: {len(recent_trades)} trades in last hour "
                f"(max {self.max_trades_per_hour})"
            )

    def record_trade(self, side: str, pnl: float = 0.0, success: bool = True):
        """
        Record a completed trade for guard tracking.
        Call AFTER order confirmation.
        """
        self._reset_daily_if_needed()

        if success:
            self._state["trades_today"] += 1
            self._state["trade_timestamps"].append(time.time())
            # Trim old timestamps (keep last 2 hours)
            cutoff = time.time() - 7200
            self._state["trade_timestamps"] = [
                t for t in self._state["trade_timestamps"] if t > cutoff
            ]

            if pnl < 0:
                self._state["daily_loss"] += abs(pnl)
                # ── Track loss timestamp for correlation detection ──
                self._state["loss_timestamps"].append(time.time())
                self._trim_loss_timestamps()
                self._check_correlation_warning()

            if side == "buy":
                self._state["last_position_entry"] = datetime.now().isoformat()

        self._save_guard_state()

    # ─── Health Check ─────────────────────────────────────────────

    def check_health(self, price: float = None, position: dict = None):
        """
        Comprehensive health check. Call each loop iteration.
        Raises TradingHalt if any critical condition is met.
        """
        self._reset_daily_if_needed()
        self._state["last_health_check"] = datetime.now().isoformat()
        self.rotate_log_if_needed()

        # ── Daily loss check (fixed dollar) ──
        if self._state["daily_loss"] >= self.max_daily_loss:
            self._state["emergency_stops"] += 1
            self._save_guard_state()
            raise TradingHalt(
                f"🚨 EMERGENCY STOP: Daily loss ${self._state['daily_loss']:.2f} "
                f"exceeds limit ${self.max_daily_loss:.2f}"
            )

        # ── Daily loss check (percentage-based) ──
        if self._state.get("starting_balance_today", 0) > 0:
            daily_loss_pct_actual = (
                self._state["daily_loss"] / self._state["starting_balance_today"] * 100
            )
            if daily_loss_pct_actual >= self.max_daily_loss_pct:
                self._state["emergency_stops"] += 1
                self._save_guard_state()
                raise TradingHalt(
                    f"🚨 EMERGENCY STOP: Daily loss {daily_loss_pct_actual:.2f}% "
                    f"exceeds {self.max_daily_loss_pct:.2f}% of starting balance "
                    f"(${self._state['starting_balance_today']:.2f})"
                )

        # ── Portfolio drawdown check ──
        if self._state.get("peak_balance", 0) > 0:
            drawdown_pct = self._compute_drawdown_pct()
            if drawdown_pct >= self.max_drawdown_pct:
                self._state["emergency_stops"] += 1
                self._save_guard_state()
                raise TradingHalt(
                    f"🚨 EMERGENCY STOP: Portfolio drawdown {drawdown_pct:.2f}% "
                    f"exceeds {self.max_drawdown_pct:.2f}% limit. "
                    f"Peak: ${self._state['peak_balance']:.2f}, "
                    f"Current: ${self._state.get('current_balance', 0):.2f}"
                )

        # ── Max hold time check ──
        if position and position.get("timestamp"):
            try:
                entry_time = datetime.fromisoformat(position["timestamp"])
                hold_duration = datetime.now() - entry_time
                max_hold = timedelta(hours=self.max_hold_hours)

                if hold_duration > max_hold:
                    raise TradingHalt(
                        f"🚨 EMERGENCY EXIT: Position held for {hold_duration} "
                        f"(max {self.max_hold_hours}h). Force-sell required!"
                    )
            except (ValueError, TypeError):
                pass  # Invalid timestamp format — skip check

        # ── Position staleness check ──
        if position and price:
            entry = position.get("entry", 0)
            if entry > 0:
                pnl_pct = ((price - entry) / entry) * 100
                # If position is down more than 3x stop loss, something is very wrong
                if pnl_pct <= -(self._get_stop_loss_pct() * 3):
                    self._state["emergency_stops"] += 1
                    self._save_guard_state()
                    raise TradingHalt(
                        f"🚨 CATASTROPHIC LOSS: Position down {pnl_pct:.1f}% — "
                        f"emergency exit required!"
                    )

        self._save_guard_state()

    def _get_stop_loss_pct(self) -> float:
        """Try to read stop loss % from the main bot config, default 1.5%."""
        try:
            # Check if running alongside live_eth_trader_v2
            if "live_eth_trader_v2" in sys.modules:
                return sys.modules["live_eth_trader_v2"].STOP_LOSS_PCT
        except Exception:
            pass
        return 1.5

    # ─── Portfolio Risk Methods ────────────────────────────────────

    def update_balance(self, current_balance: float):
        """
        Update the guard's knowledge of the current portfolio balance.
        Call periodically (e.g. each main loop iteration) to track
        peak balance and drawdown.

        Args:
            current_balance: Total portfolio value in USD (cash + positions)
        """
        self._state["current_balance"] = current_balance

        # Update peak balance (high-water mark)
        if current_balance > self._state.get("peak_balance", 0):
            self._state["peak_balance"] = current_balance

        # Set starting balance for today if not yet set
        if self._state.get("starting_balance_today", 0) <= 0:
            self._state["starting_balance_today"] = current_balance

        # Track max drawdown reached
        drawdown = self._compute_drawdown_pct()
        if drawdown > self._state.get("max_drawdown_reached_pct", 0):
            self._state["max_drawdown_reached_pct"] = round(drawdown, 4)

        self._save_guard_state()

    def _compute_drawdown_pct(self) -> float:
        """
        Compute current drawdown percentage from peak balance.
        Returns 0.0 if peak balance is not set or current exceeds peak.
        """
        peak = self._state.get("peak_balance", 0)
        current = self._state.get("current_balance", 0)
        if peak <= 0 or current <= 0:
            return 0.0
        if current >= peak:
            return 0.0
        return ((peak - current) / peak) * 100

    def _trim_loss_timestamps(self):
        """Remove loss timestamps older than the correlation window."""
        cutoff = time.time() - self.correlation_loss_window_sec
        self._state["loss_timestamps"] = [
            t for t in self._state.get("loss_timestamps", [])
            if t > cutoff
        ]

    def _check_correlation_warning(self):
        """
        Detect multiple rapid losses in a short window and activate
        an enhanced cooldown. This catches correlated adverse events
        (e.g. flash crash, cascading liquidations).
        """
        recent_losses = self._state.get("loss_timestamps", [])
        if len(recent_losses) >= self.correlation_loss_threshold:
            self._state["correlation_warnings"] += 1
            # Compute cooldown: base cooldown * multiplier * warning count
            base_cooldown = self.cooldown_after_fail_sec
            cooldown = min(
                base_cooldown
                * self.correlation_cooldown_multiplier
                * self._state["correlation_warnings"],
                3600  # Cap at 1 hour
            )
            cooldown_until = (datetime.now() + timedelta(seconds=cooldown)).isoformat()
            self._state["correlation_cooldown_active"] = True
            self._state["correlation_cooldown_until"] = cooldown_until
            print(
                f"[GUARD] 🔴 CORRELATION WARNING: {len(recent_losses)} losses in "
                f"{self.correlation_loss_window_sec:.0f}s window. "
                f"Cooldown {cooldown:.0f}s (warning #{self._state['correlation_warnings']})"
            )
            self._save_guard_state()

    def _check_correlation_cooldown(self) -> float:
        """
        Check if correlation cooldown is active. Returns seconds remaining
        if active, 0.0 if cooldown is clear.
        """
        if not self._state.get("correlation_cooldown_active", False):
            return 0.0

        cooldown_until_str = self._state.get("correlation_cooldown_until")
        if not cooldown_until_str:
            self._state["correlation_cooldown_active"] = False
            return 0.0

        try:
            cooldown_until = datetime.fromisoformat(cooldown_until_str)
            remaining = (cooldown_until - datetime.now()).total_seconds()
            if remaining <= 0:
                self._state["correlation_cooldown_active"] = False
                self._state["correlation_cooldown_until"] = None
                self._save_guard_state()
                return 0.0
            return remaining
        except (ValueError, TypeError):
            self._state["correlation_cooldown_active"] = False
            self._state["correlation_cooldown_until"] = None
            return 0.0

    # ─── Position Reality Sync ────────────────────────────────────

    def sync_position(self, state_position: dict, exchange_eth_balance: float,
                      trade_amount: float, price: float = None) -> dict:
        """
        Reconcile local position state with actual exchange balance.
        Returns corrected position dict, or None if position should be cleared.

        Detects:
        - Position exists in state but no ETH on exchange (already sold)
        - ETH on exchange but no position in state (orphaned)
        - Position amount doesn't match actual holdings
        """
        if state_position is None and exchange_eth_balance < 0.0001:
            # Both agree: no position
            return None

        if state_position and exchange_eth_balance < 0.0001:
            # State says we have a position, but exchange has no ETH
            # The position was likely already sold (by a stop loss or manual trade)
            print(
                f"[GUARD] 🔍 STALE POSITION: State says {state_position['amount']:.6f} ETH "
                f"but exchange balance is {exchange_eth_balance:.6f}. Clearing stale state."
            )
            return None

        if state_position and exchange_eth_balance > 0.0001:
            # Both exist — check if amounts match
            state_amount = state_position.get("amount", 0)
            diff_pct = abs(exchange_eth_balance - state_amount) / max(state_amount, 0.0001)

            if diff_pct > 0.10:  # More than 10% discrepancy
                print(
                    f"[GUARD] ⚠️ POSITION DRIFT: State={state_amount:.6f} ETH, "
                    f"Exchange={exchange_eth_balance:.6f} ETH ({diff_pct*100:.1f}% off). "
                    f"Updating to exchange value."
                )
                state_position["amount"] = exchange_eth_balance

        if state_position is None and exchange_eth_balance >= trade_amount / 5000:
            # ETH on exchange but no position tracked — small dust is OK
            if exchange_eth_balance > 0.001:
                # Use current price as estimated entry (best guess)
                # This prevents division-by-zero in PnL calculations
                est_entry = price if price else 2200.0
                print(
                    f"[GUARD] 🔍 ORPHANED ETH: {exchange_eth_balance:.6f} ETH on exchange "
                    f"but no position in state. Creating recovery position @ ~${est_entry:.2f}"
                )
                return {
                    "side": "long",
                    "entry": est_entry,
                    "amount": exchange_eth_balance,
                    "timestamp": datetime.now().isoformat(),
                    "recovery": True,
                }

        return state_position

    # ─── Status & Reporting ───────────────────────────────────────

    def get_status(self) -> dict:
        """Get current guard status for dashboard/reporting."""
        self._reset_daily_if_needed()

        drawdown_pct = self._compute_drawdown_pct()
        daily_loss_pct_actual = 0.0
        if self._state.get("starting_balance_today", 0) > 0:
            daily_loss_pct_actual = (
                self._state["daily_loss"] / self._state["starting_balance_today"] * 100
            )

        return {
            "daily_loss": self._state["daily_loss"],
            "daily_loss_limit": self.max_daily_loss,
            "daily_loss_pct": (
                (self._state["daily_loss"] / self.max_daily_loss * 100)
                if self.max_daily_loss > 0 else 0
            ),
            "trades_today": self._state["trades_today"],
            "consecutive_fails": self._state["consecutive_fails"],
            "circuit_open": self._state.get("circuit_open_until") is not None,
            "circuit_open_until": self._state.get("circuit_open_until"),
            "emergency_stops": self._state.get("emergency_stops", 0),
            "blocked_trades": self._state.get("total_blocked_trades", 0),
            "last_health_check": self._state.get("last_health_check"),
            "pid": os.getpid(),
            "lock_held": self._lock_fd is not None,
            # ── Portfolio risk metrics ──
            "portfolio": {
                "current_balance": self._state.get("current_balance", 0.0),
                "peak_balance": self._state.get("peak_balance", 0.0),
                "starting_balance_today": self._state.get("starting_balance_today", 0.0),
                "drawdown_pct": round(drawdown_pct, 4),
                "drawdown_limit_pct": self.max_drawdown_pct,
                "max_drawdown_reached_pct": self._state.get("max_drawdown_reached_pct", 0.0),
                "daily_loss_pct_of_start": round(daily_loss_pct_actual, 4),
                "daily_loss_pct_limit": self.max_daily_loss_pct,
            },
            "correlation": {
                "active": self._state.get("correlation_cooldown_active", False),
                "cooldown_until": self._state.get("correlation_cooldown_until"),
                "warnings_count": self._state.get("correlation_warnings", 0),
                "recent_losses_in_window": len(self._state.get("loss_timestamps", [])),
                "threshold": self.correlation_loss_threshold,
                "window_sec": self.correlation_loss_window_sec,
            },
        }

    def format_status(self) -> str:
        """Human-readable status for Telegram/logging."""
        s = self.get_status()
        p = s["portfolio"]
        c = s["correlation"]
        lines = [
            f"🛡️ GUARD STATUS",
            f"  Daily Loss: ${s['daily_loss']:.2f} / ${s['daily_loss_limit']:.2f} ({s['daily_loss_pct']:.0f}%)",
            f"  Trades Today: {s['trades_today']}",
            f"  Consecutive Fails: {s['consecutive_fails']}/{self.max_consecutive_fails}",
            f"  Circuit Breaker: {'🔴 OPEN' if s['circuit_open'] else '🟢 CLOSED'}",
        ]
        if s["circuit_open_until"]:
            lines.append(f"  Circuit Reopens: {s['circuit_open_until']}")
        lines.extend([
            f"  Emergency Stops: {s['emergency_stops']}",
            f"  Blocked Trades: {s['blocked_trades']}",
            f"  PID: {s['pid']} (lock: {'✅' if s['lock_held'] else '❌'})",
            "",
            f"📊 PORTFOLIO RISK",
            f"  Current Balance: ${p['current_balance']:.2f}",
            f"  Peak Balance:    ${p['peak_balance']:.2f}",
            f"  Start (today):   ${p['starting_balance_today']:.2f}",
            f"  Drawdown:        {p['drawdown_pct']:.2f}% / {p['drawdown_limit_pct']:.2f}% limit",
            f"  Max Drawdown:    {p['max_drawdown_reached_pct']:.2f}%",
            f"  Daily Loss %:    {p['daily_loss_pct_of_start']:.2f}% / {p['daily_loss_pct_limit']:.2f}% limit",
            "",
            f"🔗 CORRELATION RISK",
            f"  Recent Losses ({c['window_sec']:.0f}s): {c['recent_losses_in_window']} / {c['threshold']} threshold",
            f"  Warnings: {c['warnings_count']}",
            f"  Cooldown: {'🔴 ACTIVE until ' + str(c['cooldown_until']) if c['active'] else '🟢 CLEAR'}",
        ])
        return "\n".join(lines)


# ─── Standalone Kill Duplicates Utility ───────────────────────────

def kill_duplicate_bots(pid_file: str = os.environ.get("PID_FILE", "/tmp/bot.pid")):
    """
    Find and kill ALL running bot instances.
    Use as: python3 trading_guard.py --kill
    """
    killed = 0

    # Check PID file
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            if TradingGuard._is_process_alive(pid):
                cmdline = TradingGuard._get_process_cmdline(pid)
                if "trader" in cmdline.lower() or "eth" in cmdline.lower():
                    print(f"Killing PID {pid}: {cmdline[:80]}")
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(2)
                    if TradingGuard._is_process_alive(pid):
                        os.kill(pid, signal.SIGKILL)
                    killed += 1
        except Exception as e:
            print(f"PID file cleanup error: {e}")

    # Scan /proc for any python processes running the trader
    try:
        for pid_dir in Path("/proc").iterdir():
            try:
                pid = int(pid_dir.name)
                if pid == os.getpid():
                    continue
                cmdline_path = pid_dir / "cmdline"
                if cmdline_path.exists():
                    cmdline = cmdline_path.read_text().replace("\x00", " ")
                    if "live_eth_trader" in cmdline:
                        print(f"Killing duplicate bot PID {pid}: {cmdline[:80]}")
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(1)
                        if TradingGuard._is_process_alive(pid):
                            os.kill(pid, signal.SIGKILL)
                        killed += 1
            except (ValueError, ProcessLookupError, PermissionError):
                continue
    except Exception:
        pass

    print(f"✅ Killed {killed} duplicate bot process(es)")
    # Clean up PID file
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except Exception:
            pass


def show_guard_status():
    """Show guard status from state file. Use as: python3 trading_guard.py --status"""
    guard = TradingGuard()
    print(guard.format_status())
    state = guard._state
    print(f"\n📊 Raw state:")
    print(json.dumps(state, indent=2))


def reset_guard():
    """Reset guard state. Use as: python3 trading_guard.py --reset"""
    guard = TradingGuard()
    guard._state = guard._default_state()
    guard._save_guard_state()
    print("✅ Guard state reset to defaults")


if __name__ == "__main__":
    if "--kill" in sys.argv:
        kill_duplicate_bots()
    elif "--status" in sys.argv:
        show_guard_status()
    elif "--reset" in sys.argv:
        reset_guard()
    else:
        print("Trading Guard Module v1.1")
        print("Usage:")
        print("  python3 trading_guard.py --kill     Kill all duplicate bot processes")
        print("  python3 trading_guard.py --status   Show guard status")
        print("  python3 trading_guard.py --reset    Reset guard state")
        print("\nImport in your bot:")
        print("  from trading_guard import TradingGuard")
