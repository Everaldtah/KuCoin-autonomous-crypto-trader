"""
Risk Manager Module for KuCoin Autonomous Crypto Trader

Professional risk management with Kelly Criterion position sizing,
ATR-based stops, daily loss limits, and portfolio drawdown protection.

No external dependencies beyond the Python standard library.
"""

import math
import time
from datetime import datetime, timedelta


class KellyCriterion:
    """Kelly Criterion for optimal position sizing in crypto trading.

    The Kelly Criterion determines the theoretically optimal fraction
    of a bankroll to risk on a given bet/trade. In practice, fractional
    Kelly (e.g. half-Kelly) is used to reduce volatility.
    """

    @staticmethod
    def optimal_fraction(wins: int, losses: int, win_rate: float = None) -> float:
        """Calculate the Kelly optimal fraction.

        Uses the simplified Kelly formula:
            f* = p - q
        where p = win rate, q = 1 - p.
        For a more general form with average win/loss sizes:
            f* = (p * b - q) / b
        where b = average win / average loss ratio (default assumes b=1).

        Args:
            wins: Number of winning trades.
            losses: Number of losing trades.
            win_rate: Optional pre-calculated win rate (0.0 to 1.0).
                      If None, it is computed from wins and losses.

        Returns:
            Kelly fraction (may be negative, meaning no edge).
            Clamped to [-1.0, 1.0].
        """
        total = wins + losses
        if total == 0:
            return 0.0

        if win_rate is not None:
            p = max(0.0, min(1.0, win_rate))
        else:
            p = wins / total

        q = 1.0 - p

        # Simplified Kelly with even payoff (b=1)
        kelly = p - q

        return max(-1.0, min(1.0, kelly))

    @staticmethod
    def safe_fraction(wins: int, losses: int, fraction: float = 0.5) -> float:
        """Calculate a fractional Kelly for safer position sizing.

        Half-Kelly is a widely used approach that sacrifices some growth
        for dramatically reduced variance and drawdowns.

        Args:
            wins: Number of winning trades.
            losses: Number of losing trades.
            fraction: Fraction of Kelly to use (default 0.5 = half-Kelly).
                      Common values: 0.25 (quarter), 0.5 (half), 0.33 (third).

        Returns:
            Adjusted Kelly fraction, clamped to [0.0, 1.0].
            Returns 0.0 if the full Kelly is negative (no edge).
        """
        if fraction <= 0:
            return 0.0

        full_kelly = KellyCriterion.optimal_fraction(wins, losses)
        if full_kelly <= 0:
            return 0.0

        safe = full_kelly * fraction
        return max(0.0, min(1.0, safe))

    @staticmethod
    def position_size_from_kelly(
        balance: float,
        kelly_fraction: float,
        price: float,
        max_risk_pct: float = 2.0,
    ) -> float:
        """Calculate position size in base currency units using Kelly fraction.

        The position size is derived from the Kelly fraction of the balance,
        capped by a maximum risk percentage to prevent overexposure.

        Args:
            balance: Total account balance in quote currency (e.g. USDT).
            kelly_fraction: The Kelly fraction (0.0 to 1.0).
            price: Current price of the asset.
            max_risk_pct: Maximum percentage of balance to risk per trade.

        Returns:
            Position size in base currency units (e.g. ETH).
            Returns 0.0 if inputs are invalid.
        """
        if balance <= 0 or price <= 0 or kelly_fraction <= 0:
            return 0.0

        # Amount of balance to allocate based on Kelly
        kelly_amount = balance * kelly_fraction

        # Cap by max risk
        max_risk_amount = balance * (max_risk_pct / 100.0)
        allocated = min(kelly_amount, max_risk_amount)

        # Convert to base currency units
        position_size = allocated / price
        return max(0.0, position_size)


class ATRStops:
    """ATR-based stop loss, take profit, and trailing stop calculations.

    Average True Range (ATR) is a volatility measure. Using ATR multiples
    for stops adapts to current market conditions — wider stops in volatile
    markets, tighter in calm ones.
    """

    @staticmethod
    def compute_stop_loss(
        price: float, atr: float, side: str = "long", multiplier: float = 2.0
    ) -> float:
        """Compute ATR-based stop loss price.

        Args:
            price: Entry price.
            atr: Current Average True Range value.
            side: 'long' or 'short'.
            multiplier: ATR multiplier (default 2.0).

        Returns:
            Stop loss price. Returns 0.0 if inputs are invalid.
        """
        if price <= 0 or atr <= 0 or multiplier <= 0:
            return 0.0

        side_lower = side.lower().strip()
        if side_lower == "long":
            stop = price - (atr * multiplier)
        elif side_lower == "short":
            stop = price + (atr * multiplier)
        else:
            return 0.0

        return max(0.0, stop)

    @staticmethod
    def compute_take_profit(
        price: float,
        atr: float,
        side: str = "long",
        risk_reward_ratio: float = 2.0,
    ) -> float:
        """Compute ATR-based take profit price.

        The take profit is set at a distance of (ATR * multiplier * risk_reward_ratio)
        from entry, where the default multiplier is embedded to keep risk/reward
        proportional to the stop distance.

        Args:
            price: Entry price.
            atr: Current Average True Range value.
            side: 'long' or 'short'.
            risk_reward_ratio: Desired reward relative to risk (default 2.0).

        Returns:
            Take profit price. Returns 0.0 if inputs are invalid.
        """
        if price <= 0 or atr <= 0 or risk_reward_ratio <= 0:
            return 0.0

        # Use a base ATR distance (1x ATR as the risk unit)
        risk_distance = atr * 2.0  # consistent with default SL multiplier
        reward_distance = risk_distance * risk_reward_ratio

        side_lower = side.lower().strip()
        if side_lower == "long":
            tp = price + reward_distance
        elif side_lower == "short":
            tp = price - reward_distance
        else:
            return 0.0

        return max(0.0, tp)

    @staticmethod
    def compute_trailing_stop(
        price: float,
        atr: float,
        highest_since_entry: float,
        multiplier: float = 2.0,
    ) -> float:
        """Compute trailing stop price for a long position.

        The trailing stop ratchets upward as price makes new highs,
        but never moves downward.

        Args:
            price: Current price (unused directly, kept for API consistency).
            atr: Current Average True Range value.
            highest_since_entry: Highest price observed since entry.
            multiplier: ATR multiplier for trail distance.

        Returns:
            Trailing stop price. Returns 0.0 if inputs are invalid.
        """
        if atr <= 0 or multiplier <= 0 or highest_since_entry <= 0:
            return 0.0

        trail = highest_since_entry - (atr * multiplier)
        return max(0.0, trail)

    @staticmethod
    def should_trail(
        current_price: float,
        highest_since_entry: float,
        current_trail: float,
        atr: float,
        multiplier: float = 2.5,
    ) -> tuple:
        """Determine whether the trailing stop should be updated.

        The trail is updated when price has moved sufficiently far from
        the current trail to warrant tightening.

        Args:
            current_price: Current market price.
            highest_since_entry: Highest price since entry.
            current_trail: Current trailing stop level.
            atr: Current Average True Range value.
            multiplier: ATR multiplier for the new trail distance.

        Returns:
            Tuple of (should_update: bool, new_trail: float).
            new_trail is the proposed new trail level regardless of
            whether an update is warranted.
        """
        if current_price <= 0 or atr <= 0 or multiplier <= 0:
            return (False, current_trail)

        new_trail = highest_since_entry - (atr * multiplier)
        new_trail = max(0.0, new_trail)

        # Only trail upward (tighten) — never loosen
        if current_trail <= 0:
            # No existing trail, set one
            return (True, new_trail)

        if new_trail > current_trail:
            return (True, new_trail)

        return (False, current_trail)


class RiskManager:
    """Centralized risk management for the trading bot.

    Enforces per-trade risk limits, daily loss caps, portfolio drawdown
    thresholds, and maximum concurrent positions.

    Attributes:
        max_risk_per_trade_pct: Maximum % of balance risked per trade.
        max_daily_loss_pct: Maximum daily loss as % of starting balance.
        max_portfolio_drawdown_pct: Maximum drawdown from equity peak.
        max_open_positions: Maximum number of simultaneous open trades.
    """

    def __init__(
        self,
        balance: float,
        max_risk_per_trade_pct: float = 2.0,
        max_daily_loss_pct: float = 5.0,
        max_portfolio_drawdown_pct: float = 15.0,
        max_open_positions: int = 3,
    ):
        """Initialize the RiskManager.

        Args:
            balance: Starting account balance in quote currency (USDT).
            max_risk_per_trade_pct: Max % of balance to risk on a single trade.
            max_daily_loss_pct: Max % of daily starting balance allowed as loss.
            max_portfolio_drawdown_pct: Max drawdown from peak balance.
            max_open_positions: Max number of concurrent open positions.
        """
        self.max_risk_per_trade_pct = max(0.1, min(10.0, max_risk_per_trade_pct))
        self.max_daily_loss_pct = max(0.5, min(20.0, max_daily_loss_pct))
        self.max_portfolio_drawdown_pct = max(1.0, min(50.0, max_portfolio_drawdown_pct))
        self.max_open_positions = max(1, min(20, max_open_positions))

        # Internal tracking
        self._initial_balance = max(0.0, balance)
        self._peak_balance = self._initial_balance
        self._current_balance = self._initial_balance

        # Daily tracking
        self._daily_start_balance = self._initial_balance
        self._daily_pnl = 0.0
        self._last_daily_reset = datetime.utcnow()

        # Trade history stats
        self._total_trades = 0
        self._total_wins = 0
        self._total_losses = 0
        self._total_pnl = 0.0
        self._largest_win = 0.0
        self._largest_loss = 0.0
        self._consecutive_losses = 0
        self._max_consecutive_losses = 0

        # Circuit breaker
        self._circuit_breaker_active = False
        self._circuit_breaker_reason = ""
        self._circuit_breaker_until = None

        self._atr_stops = ATRStops()
        self._kelly = KellyCriterion()

    def calculate_position_size(
        self,
        price: float,
        atr: float,
        account_balance: float,
    ) -> dict:
        """Calculate position size, stop loss, and take profit for a trade.

        Uses ATR-based stops and accounts for max risk per trade.

        Args:
            price: Current asset price.
            atr: Current Average True Range.
            account_balance: Current account balance (overrides internal if given).

        Returns:
            Dictionary with keys:
                - size_base: Position size in base currency (ETH).
                - size_quote: Position size in quote currency (USDT).
                - risk_amount: Dollar amount at risk.
                - stop_loss: ATR-based stop loss price.
                - take_profit: ATR-based take profit price.
                - risk_reward_ratio: Effective R:R of the trade.
                - atr_used: The ATR value used.
                - valid: Whether the calculation produced valid results.
        """
        result = {
            "size_base": 0.0,
            "size_quote": 0.0,
            "risk_amount": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "risk_reward_ratio": 0.0,
            "atr_used": atr,
            "valid": False,
        }

        if price <= 0 or atr <= 0 or account_balance <= 0:
            return result

        # Compute stops
        stop_loss = self._atr_stops.compute_stop_loss(
            price, atr, side="long", multiplier=2.0
        )
        take_profit = self._atr_stops.compute_take_profit(
            price, atr, side="long", risk_reward_ratio=2.0
        )

        if stop_loss <= 0:
            return result

        # Risk per unit
        risk_per_unit = price - stop_loss
        if risk_per_unit <= 0:
            return result

        # Total risk amount based on max risk percentage
        risk_amount = account_balance * (self.max_risk_per_trade_pct / 100.0)

        # Position size in base currency
        size_base = risk_amount / risk_per_unit

        # Convert to quote
        size_quote = size_base * price

        # Don't exceed available balance
        if size_quote > account_balance:
            size_quote = account_balance * 0.95  # leave 5% buffer
            size_base = size_quote / price
            risk_amount = size_base * risk_per_unit

        # R:R ratio
        reward_per_unit = take_profit - price
        if risk_per_unit > 0:
            rr_ratio = reward_per_unit / risk_per_unit
        else:
            rr_ratio = 0.0

        result["size_base"] = round(size_base, 8)
        result["size_quote"] = round(size_quote, 2)
        result["risk_amount"] = round(risk_amount, 2)
        result["stop_loss"] = round(stop_loss, 6)
        result["take_profit"] = round(take_profit, 6)
        result["risk_reward_ratio"] = round(max(0.0, rr_ratio), 2)
        result["valid"] = True

        return result

    def check_daily_loss(self, today_pnl: float) -> bool:
        """Check whether the daily loss is within acceptable limits.

        Args:
            today_pnl: Total PnL for the current trading day.

        Returns:
            True if within daily loss limits (trading allowed).
            False if daily loss limit has been exceeded.
        """
        self._check_daily_reset()

        if self._daily_start_balance <= 0:
            return False

        max_daily_loss_amount = self._daily_start_balance * (
            self.max_daily_loss_pct / 100.0
        )

        # today_pnl is negative when losing
        if today_pnl < 0 and abs(today_pnl) >= max_daily_loss_amount:
            return False

        return True

    def check_drawdown(self, peak_balance: float, current_balance: float) -> bool:
        """Check whether the portfolio drawdown is within limits.

        Args:
            peak_balance: Highest balance observed.
            current_balance: Current account balance.

        Returns:
            True if within drawdown limits (trading allowed).
            False if max drawdown has been exceeded.
        """
        if peak_balance <= 0:
            return False

        drawdown_pct = ((peak_balance - current_balance) / peak_balance) * 100.0

        if drawdown_pct >= self.max_portfolio_drawdown_pct:
            return False

        return True

    def get_trade_risk_report(
        self,
        entry: float,
        current_price: float,
        position_size: float,
        atr: float,
    ) -> dict:
        """Generate a risk report for an open or proposed trade.

        Args:
            entry: Entry price of the position.
            current_price: Current market price.
            position_size: Size of the position in base currency.
            atr: Current Average True Range.

        Returns:
            Dictionary with keys:
                - unrealized_pnl: Unrealized profit/loss in quote.
                - unrealized_pnl_pct: Unrealized PnL as percentage.
                - current_stop: Current recommended stop loss.
                - current_take_profit: Current recommended take profit.
                - trailing_stop: Current trailing stop level.
                - risk_remaining: Remaining risk in quote currency.
                - atr_distance: Distance from entry in ATR units.
                - status: One of 'profit', 'loss', 'breakeven'.
        """
        report = {
            "unrealized_pnl": 0.0,
            "unrealized_pnl_pct": 0.0,
            "current_stop": 0.0,
            "current_take_profit": 0.0,
            "trailing_stop": 0.0,
            "risk_remaining": 0.0,
            "atr_distance": 0.0,
            "status": "breakeven",
        }

        if entry <= 0 or position_size <= 0:
            return report

        # Unrealized PnL
        pnl = (current_price - entry) * position_size
        pnl_pct = ((current_price - entry) / entry) * 100.0

        # Stops
        stop = self._atr_stops.compute_stop_loss(current_price, atr, side="long")
        tp = self._atr_stops.compute_take_profit(current_price, atr, side="long")
        trail = self._atr_stops.compute_trailing_stop(
            current_price, atr, max(current_price, entry)
        )

        # Risk remaining (distance to stop * size)
        if stop > 0:
            risk_remaining = abs(current_price - stop) * position_size
        else:
            risk_remaining = 0.0

        # ATR distance from entry
        if atr > 0:
            atr_distance = (current_price - entry) / atr
        else:
            atr_distance = 0.0

        # Status
        if pnl > 0:
            status = "profit"
        elif pnl < 0:
            status = "loss"
        else:
            status = "breakeven"

        report["unrealized_pnl"] = round(pnl, 4)
        report["unrealized_pnl_pct"] = round(pnl_pct, 2)
        report["current_stop"] = round(stop, 6)
        report["current_take_profit"] = round(tp, 6)
        report["trailing_stop"] = round(trail, 6)
        report["risk_remaining"] = round(risk_remaining, 4)
        report["atr_distance"] = round(atr_distance, 4)
        report["status"] = status

        return report

    def validate_trade(
        self,
        trade_amount: float,
        current_balance: float,
        open_positions: int,
    ) -> tuple:
        """Validate whether a trade should be placed based on risk rules.

        Args:
            trade_amount: Proposed trade size in quote currency (USDT).
            current_balance: Current account balance.
            open_positions: Number of currently open positions.

        Returns:
            Tuple of (is_valid: bool, reason: str).
            reason explains why the trade was rejected, or 'Approved' if valid.
        """
        # Check circuit breaker
        if self._circuit_breaker_active:
            if self._circuit_breaker_until and datetime.utcnow() < self._circuit_breaker_until:
                return (
                    False,
                    f"Circuit breaker active: {self._circuit_breaker_reason}. "
                    f"Resumes after {self._circuit_breaker_until.isoformat()}",
                )
            else:
                self._circuit_breaker_active = False
                self._circuit_breaker_reason = ""

        # Balance check
        if current_balance <= 0:
            return (False, "Current balance is zero or negative.")

        # Trade amount check
        if trade_amount <= 0:
            return (False, "Trade amount must be positive.")

        # Max position check
        if open_positions >= self.max_open_positions:
            return (
                False,
                f"Maximum open positions reached ({self.max_open_positions}).",
            )

        # Single trade risk check
        max_risk_amount = current_balance * (self.max_risk_per_trade_pct / 100.0)
        if trade_amount > max_risk_amount * 5:
            # Allow up to 5x risk amount for position (since stop limits actual risk)
            return (
                False,
                f"Trade amount ${trade_amount:.2f} exceeds 5x max risk "
                f"${max_risk_amount * 5:.2f}.",
            )

        # Don't allow trading more than 50% of balance on a single trade
        if trade_amount > current_balance * 0.5:
            return (
                False,
                f"Trade amount ${trade_amount:.2f} exceeds 50% of balance "
                f"${current_balance:.2f}.",
            )

        # Consecutive loss circuit breaker
        if self._consecutive_losses >= 5:
            cooldown_minutes = min(60, self._consecutive_losses * 10)
            self._activate_circuit_breaker(
                f"{self._consecutive_losses} consecutive losses",
                cooldown_minutes,
            )
            return (
                False,
                f"Circuit breaker: {self._consecutive_losses} consecutive losses. "
                f"Cooldown {cooldown_minutes} minutes.",
            )

        return (True, "Approved")

    def update_after_trade(self, pnl: float) -> None:
        """Update internal tracking after a trade closes.

        Args:
            pnl: Realized profit/loss for the closed trade (positive or negative).
        """
        self._total_trades += 1
        self._total_pnl += pnl
        self._daily_pnl += pnl

        # Update balance
        self._current_balance += pnl

        # Update peak
        if self._current_balance > self._peak_balance:
            self._peak_balance = self._current_balance

        if pnl > 0:
            self._total_wins += 1
            self._consecutive_losses = 0
            if pnl > self._largest_win:
                self._largest_win = pnl
        elif pnl < 0:
            self._total_losses += 1
            self._consecutive_losses += 1
            if self._consecutive_losses > self._max_consecutive_losses:
                self._max_consecutive_losses = self._consecutive_losses
            if abs(pnl) > self._largest_loss:
                self._largest_loss = abs(pnl)

        # Check if drawdown circuit breaker should activate
        if not self._check_drawdown_internal():
            self._activate_circuit_breaker(
                f"Portfolio drawdown exceeded {self.max_portfolio_drawdown_pct}%",
                120,  # 2 hour cooldown
            )

        # Check if daily loss circuit breaker should activate
        if not self.check_daily_loss(self._daily_pnl):
            self._activate_circuit_breaker(
                f"Daily loss limit reached ({self.max_daily_loss_pct}%)",
                60,
            )

    def get_status(self) -> dict:
        """Get current risk management status and metrics.

        Returns:
            Dictionary with comprehensive risk metrics:
                - balance: Current balance.
                - peak_balance: Highest balance seen.
                - initial_balance: Starting balance.
                - daily_pnl: PnL for the current day.
                - total_pnl: Cumulative PnL.
                - total_trades: Total number of trades.
                - win_rate: Win rate as a fraction (0.0 to 1.0).
                - total_wins / total_losses: Win/loss counts.
                - largest_win / largest_loss: Largest individual outcomes.
                - consecutive_losses: Current consecutive loss streak.
                - max_consecutive_losses: Worst loss streak recorded.
                - drawdown_pct: Current drawdown from peak.
                - daily_loss_pct: Today's loss as % of daily start.
                - circuit_breaker_active: Whether trading is halted.
                - circuit_breaker_reason: Why trading is halted.
                - circuit_breaker_until: When trading can resume.
                - kelly_fraction: Current Kelly optimal fraction.
                - safe_kelly_fraction: Half-Kelly fraction.
                - risk_per_trade_pct: Configured max risk per trade.
                - max_open_positions: Configured max positions.
        """
        # Win rate
        total = self._total_wins + self._total_losses
        win_rate = self._total_wins / total if total > 0 else 0.0

        # Drawdown
        if self._peak_balance > 0:
            drawdown_pct = (
                (self._peak_balance - self._current_balance) / self._peak_balance
            ) * 100.0
        else:
            drawdown_pct = 0.0

        # Daily loss %
        if self._daily_start_balance > 0:
            daily_loss_pct = (
                abs(self._daily_pnl) / self._daily_start_balance
            ) * 100.0 if self._daily_pnl < 0 else 0.0
        else:
            daily_loss_pct = 0.0

        # Kelly
        kelly = self._kelly.optimal_fraction(self._total_wins, self._total_losses)
        safe_kelly = self._kelly.safe_fraction(self._total_wins, self._total_losses)

        return {
            "balance": round(self._current_balance, 2),
            "peak_balance": round(self._peak_balance, 2),
            "initial_balance": round(self._initial_balance, 2),
            "daily_pnl": round(self._daily_pnl, 4),
            "total_pnl": round(self._total_pnl, 4),
            "total_trades": self._total_trades,
            "win_rate": round(win_rate, 4),
            "total_wins": self._total_wins,
            "total_losses": self._total_losses,
            "largest_win": round(self._largest_win, 4),
            "largest_loss": round(self._largest_loss, 4),
            "consecutive_losses": self._consecutive_losses,
            "max_consecutive_losses": self._max_consecutive_losses,
            "drawdown_pct": round(drawdown_pct, 2),
            "daily_loss_pct": round(daily_loss_pct, 2),
            "circuit_breaker_active": self._circuit_breaker_active,
            "circuit_breaker_reason": self._circuit_breaker_reason,
            "circuit_breaker_until": (
                self._circuit_breaker_until.isoformat()
                if self._circuit_breaker_until
                else None
            ),
            "kelly_fraction": round(kelly, 4),
            "safe_kelly_fraction": round(safe_kelly, 4),
            "risk_per_trade_pct": self.max_risk_per_trade_pct,
            "max_open_positions": self.max_open_positions,
        }

    # ---- Internal helpers ----

    def _check_daily_reset(self) -> None:
        """Reset daily counters if a new UTC day has started."""
        now = datetime.utcnow()
        if now.date() > self._last_daily_reset.date():
            self._daily_start_balance = self._current_balance
            self._daily_pnl = 0.0
            self._last_daily_reset = now

    def _check_drawdown_internal(self) -> bool:
        """Internal drawdown check using tracked balances."""
        return self.check_drawdown(self._peak_balance, self._current_balance)

    def _activate_circuit_breaker(
        self, reason: str, cooldown_minutes: int
    ) -> None:
        """Activate the circuit breaker to halt trading.

        Args:
            reason: Human-readable reason for the halt.
            cooldown_minutes: Minutes until trading can resume.
        """
        self._circuit_breaker_active = True
        self._circuit_breaker_reason = reason
        self._circuit_breaker_until = datetime.utcnow() + timedelta(
            minutes=cooldown_minutes
        )
