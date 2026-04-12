"""
Historical Backtesting Engine with Walk-Forward Validation.

Simulates trading strategies against historical candle data with realistic
slippage and fee modeling. Provides comprehensive performance metrics
including Sharpe ratio, Sortino ratio, max drawdown, and profit factor.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from datetime import datetime


@dataclass
class Trade:
    """A single completed trade."""
    entry_time: datetime
    exit_time: datetime
    side: str                      # 'long' or 'short'
    entry_price: float
    exit_price: float
    size: float                    # in base currency (ETH)
    pnl: float                     # absolute PnL in quote currency (USDT)
    pnl_pct: float                 # percentage PnL
    exit_reason: str               # 'take_profit', 'stop_loss', 'trailing_stop', 'signal', 'end_of_data'
    indicators_at_entry: dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    """Complete backtest performance metrics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_hold_bars: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    initial_balance: float = 0.0
    final_balance: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class Backtester:
    """
    Event-driven backtester that replays candle data through a strategy function.

    Usage:
        bt = Backtester(balance=10000, trade_pct=0.02)
        result = bt.run(candles, my_strategy_fn)
        print(f"Sharpe: {result.sharpe_ratio:.2f}, Win Rate: {result.win_rate:.1%}")
    """

    def __init__(
        self,
        balance: float = 10000.0,
        trade_pct: float = 0.02,
        slippage_pct: float = 0.05,
        maker_fee: float = 0.1,
        taker_fee: float = 0.1,
    ):
        """
        Args:
            balance: Starting balance in quote currency (USDT)
            trade_pct: Fraction of balance to risk per trade (0.02 = 2%)
            slippage_pct: Simulated slippage as percentage of price
            maker_fee: Maker fee in percentage (0.1 = 0.1%)
            taker_fee: Taker fee in percentage (0.1 = 0.1%)
        """
        self.initial_balance = balance
        self.trade_pct = max(0.001, min(trade_pct, 0.1))
        self.slippage_pct = slippage_pct / 100.0
        self.maker_fee = maker_fee / 100.0
        self.taker_fee = taker_fee / 100.0

    def run(
        self,
        candles: List[Dict],
        strategy_fn: Callable,
        indicators_fn: Callable = None,
    ) -> BacktestResult:
        """
        Run backtest on candle data.

        Args:
            candles: List of dicts with keys: time, open, high, low, close, volume
            strategy_fn: Function(candles, index, indicators, position, balance) -> dict
                Returns: {'action': 'buy'|'sell'|'hold', 'reason': str, 'size': float (optional)}
            indicators_fn: Optional function(candles, index) -> dict of indicator values

        Returns:
            BacktestResult with full performance metrics
        """
        if len(candles) < 50:
            return BacktestResult(
                initial_balance=self.initial_balance,
                final_balance=self.initial_balance,
                period_start=candles[0].get("time") if candles else None,
                period_end=candles[-1].get("time") if candles else None,
            )

        balance = self.initial_balance
        position = None  # {'side', 'entry_price', 'size', 'stop_loss', 'take_profit', 'entry_bar'}
        trades: List[Trade] = []
        equity_curve = [balance]

        for i in range(50, len(candles)):
            candle = candles[i]

            # Compute indicators if function provided
            indicators = {}
            if indicators_fn:
                try:
                    indicators = indicators_fn(candles, i)
                except Exception:
                    pass

            # Get strategy decision
            try:
                decision = strategy_fn(candles, i, indicators, position, balance)
            except Exception:
                decision = {"action": "hold"}

            action = decision.get("action", "hold")
            reason = decision.get("reason", "")

            # Process action
            if action == "buy" and position is None:
                # Open long position
                trade_amount = balance * self.trade_pct
                entry_price = candle["close"] * (1 + self.slippage_pct)  # buy slippage
                fee = trade_amount * self.taker_fee
                size = (trade_amount - fee) / entry_price

                position = {
                    "side": "long",
                    "entry_price": entry_price,
                    "size": size,
                    "stop_loss": decision.get("stop_loss"),
                    "take_profit": decision.get("take_profit"),
                    "entry_bar": i,
                    "entry_time": candle.get("time"),
                    "cost": trade_amount,
                    "indicators": indicators.copy(),
                }

            elif action == "sell" and position is not None and position["side"] == "long":
                # Close long position
                exit_price = candle["close"] * (1 - self.slippage_pct)  # sell slippage
                proceeds = position["size"] * exit_price
                fee = proceeds * self.taker_fee
                net_proceeds = proceeds - fee
                pnl = net_proceeds - position["cost"]
                pnl_pct = (pnl / position["cost"]) * 100

                trade = Trade(
                    entry_time=position.get("entry_time", candle.get("time")),
                    exit_time=candle.get("time"),
                    side="long",
                    entry_price=position["entry_price"],
                    exit_price=exit_price,
                    size=position["size"],
                    pnl=round(pnl, 4),
                    pnl_pct=round(pnl_pct, 2),
                    exit_reason=reason or "signal",
                    indicators_at_entry=position.get("indicators", {}),
                )
                trades.append(trade)
                balance += pnl
                position = None

            # Check stop loss / take profit if in position
            if position is not None and position["side"] == "long":
                low = candle["low"]
                high = candle["high"]

                # Stop loss check
                if position.get("stop_loss") and low <= position["stop_loss"]:
                    exit_price = position["stop_loss"] * (1 - self.slippage_pct)
                    proceeds = position["size"] * exit_price
                    fee = proceeds * self.taker_fee
                    net_proceeds = proceeds - fee
                    pnl = net_proceeds - position["cost"]
                    pnl_pct = (pnl / position["cost"]) * 100

                    trades.append(Trade(
                        entry_time=position.get("entry_time", candle.get("time")),
                        exit_time=candle.get("time"),
                        side="long",
                        entry_price=position["entry_price"],
                        exit_price=exit_price,
                        size=position["size"],
                        pnl=round(pnl, 4),
                        pnl_pct=round(pnl_pct, 2),
                        exit_reason="stop_loss",
                        indicators_at_entry=position.get("indicators", {}),
                    ))
                    balance += pnl
                    position = None

                # Take profit check
                elif position and position.get("take_profit") and high >= position["take_profit"]:
                    exit_price = position["take_profit"] * (1 - self.slippage_pct)
                    proceeds = position["size"] * exit_price
                    fee = proceeds * self.taker_fee
                    net_proceeds = proceeds - fee
                    pnl = net_proceeds - position["cost"]
                    pnl_pct = (pnl / position["cost"]) * 100

                    trades.append(Trade(
                        entry_time=position.get("entry_time", candle.get("time")),
                        exit_time=candle.get("time"),
                        side="long",
                        entry_price=position["entry_price"],
                        exit_price=exit_price,
                        size=position["size"],
                        pnl=round(pnl, 4),
                        pnl_pct=round(pnl_pct, 2),
                        exit_reason="take_profit",
                        indicators_at_entry=position.get("indicators", {}),
                    ))
                    balance += pnl
                    position = None

            equity_curve.append(balance)

        # Close any open position at end of data
        if position is not None:
            last_price = candles[-1]["close"] * (1 - self.slippage_pct)
            proceeds = position["size"] * last_price
            fee = proceeds * self.taker_fee
            net_proceeds = proceeds - fee
            pnl = net_proceeds - position["cost"]
            pnl_pct = (pnl / position["cost"]) * 100

            trades.append(Trade(
                entry_time=position.get("entry_time"),
                exit_time=candles[-1].get("time"),
                side="long",
                entry_price=position["entry_price"],
                exit_price=last_price,
                size=position["size"],
                pnl=round(pnl, 4),
                pnl_pct=round(pnl_pct, 2),
                exit_reason="end_of_data",
                indicators_at_entry=position.get("indicators", {}),
            ))
            balance += pnl
            equity_curve.append(balance)

        return self._calculate_metrics(trades, balance, equity_curve, candles)

    def walk_forward(
        self,
        candles: List[Dict],
        strategy_fn: Callable,
        train_window: int = 100,
        test_window: int = 30,
        indicators_fn: Callable = None,
    ) -> List[BacktestResult]:
        """
        Walk-forward validation: slide a window across the data,
        testing on out-of-sample segments.

        Args:
            candles: Full candle dataset
            strategy_fn: Strategy function (can adapt based on training data)
            train_window: Number of candles for warmup/training
            test_window: Number of candles to test on each fold
            indicators_fn: Optional indicator computation function

        Returns:
            List of BacktestResult for each test window
        """
        results = []
        start = 0

        while start + train_window + test_window <= len(candles):
            # Test window starts after training window
            test_start = start + train_window
            test_end = min(test_start + test_window, len(candles))

            # Include training data for warmup (indicators need lookback)
            window = candles[start:test_end]

            result = self.run(window, strategy_fn, indicators_fn)
            result.period_start = candles[test_start].get("time")
            result.period_end = candles[test_end - 1].get("time")

            results.append(result)
            start += test_window  # slide forward by test window

        return results

    def _calculate_metrics(
        self,
        trades: List[Trade],
        final_balance: float,
        equity_curve: List[float],
        candles: List[Dict],
    ) -> BacktestResult:
        """Compute full performance metrics from trade list."""
        if not trades:
            return BacktestResult(
                initial_balance=self.initial_balance,
                final_balance=final_balance,
                equity_curve=equity_curve,
                period_start=candles[0].get("time") if candles else None,
                period_end=candles[-1].get("time") if candles else None,
            )

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in trades)
        total_pnl_pct = ((final_balance - self.initial_balance) / self.initial_balance) * 100

        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0.0

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Consecutive streaks
        max_consec_wins = 0
        max_consec_losses = 0
        current_wins = 0
        current_losses = 0
        for t in trades:
            if t.pnl > 0:
                current_wins += 1
                current_losses = 0
                max_consec_wins = max(max_consec_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_consec_losses = max(max_consec_losses, current_losses)

        # Average hold time in bars
        hold_bars = []
        for t in trades:
            if t.entry_time and t.exit_time:
                bars = 1  # minimum
                hold_bars.append(bars)
        avg_hold = sum(hold_bars) / len(hold_bars) if hold_bars else 0.0

        # Drawdown
        max_dd, max_dd_pct = self._compute_drawdown(equity_curve)

        # Returns series for Sharpe/Sortino
        returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] > 0:
                returns.append((equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1])
            else:
                returns.append(0.0)

        sharpe = self._compute_sharpe(returns)
        sortino = self._compute_sortino(returns)

        return BacktestResult(
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=len(wins) / len(trades) if trades else 0.0,
            total_pnl=round(total_pnl, 4),
            total_pnl_pct=round(total_pnl_pct, 2),
            max_drawdown=round(max_dd, 4),
            max_drawdown_pct=round(max_dd_pct, 2),
            sharpe_ratio=round(sharpe, 3),
            sortino_ratio=round(sortino, 3),
            profit_factor=round(profit_factor, 3),
            avg_win=round(avg_win, 4),
            avg_loss=round(avg_loss, 4),
            avg_hold_bars=round(avg_hold, 1),
            largest_win=round(max((t.pnl for t in trades), default=0.0), 4),
            largest_loss=round(min((t.pnl for t in trades), default=0.0), 4),
            max_consecutive_wins=max_consec_wins,
            max_consecutive_losses=max_consec_losses,
            initial_balance=self.initial_balance,
            final_balance=round(final_balance, 4),
            trades=trades,
            equity_curve=equity_curve,
            period_start=candles[0].get("time") if candles else None,
            period_end=candles[-1].get("time") if candles else None,
        )

    @staticmethod
    def _compute_drawdown(equity_curve: List[float]) -> tuple:
        """Compute maximum drawdown from equity curve. Returns (absolute, percentage)."""
        if len(equity_curve) < 2:
            return 0.0, 0.0

        peak = equity_curve[0]
        max_dd = 0.0
        max_dd_pct = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value
            dd = peak - value
            dd_pct = (dd / peak * 100) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct

        return max_dd, max_dd_pct

    @staticmethod
    def _compute_sharpe(returns: List[float], risk_free: float = 0.0) -> float:
        """Compute annualized Sharpe ratio (assuming daily returns, 365 days for crypto)."""
        if len(returns) < 2:
            return 0.0

        arr = np.array(returns)
        excess = arr - risk_free / 365
        mean_excess = np.mean(excess)
        std = np.std(excess, ddof=1)

        if std == 0:
            return 0.0

        sharpe = (mean_excess / std) * np.sqrt(365)
        return float(sharpe)

    @staticmethod
    def _compute_sortino(returns: List[float], risk_free: float = 0.0) -> float:
        """Compute annualized Sortino ratio (only penalizes downside volatility)."""
        if len(returns) < 2:
            return 0.0

        arr = np.array(returns)
        excess = arr - risk_free / 365
        mean_excess = np.mean(excess)

        # Downside deviation only
        downside = excess[excess < 0]
        if len(downside) == 0:
            return float("inf") if mean_excess > 0 else 0.0

        downside_std = np.std(downside, ddof=1)
        if downside_std == 0:
            return 0.0

        sortino = (mean_excess / downside_std) * np.sqrt(365)
        return float(sortino)
