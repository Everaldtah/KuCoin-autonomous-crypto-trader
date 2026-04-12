"""Risk Manager Module for KuCoin Autonomous Crypto Trader

Professional risk management with Kelly Criterion position sizing,
ATR-based stops, daily loss limits, and portfolio drawdown protection.
"""

import math
import time
from datetime import datetime, timedelta


class KellyCriterion:
    """Kelly Criterion for optimal position sizing."""
    
    @staticmethod
    def optimal_fraction(wins: int, losses: int, win_rate: float = None) -> float:
        total = wins + losses
        if total == 0:
            return 0.0
        if win_rate is not None:
            p = max(0.0, min(1.0, win_rate))
        else:
            p = wins / total
        q = 1.0 - p
        kelly = p - q
        return max(-1.0, min(1.0, kelly))
    
    @staticmethod
    def safe_fraction(wins: int, losses: int, fraction: float = 0.5) -> float:
        if fraction <= 0:
            return 0.0
        full_kelly = KellyCriterion.optimal_fraction(wins, losses)
        if full_kelly <= 0:
            return 0.0
        safe = full_kelly * fraction
        return max(0.0, min(1.0, safe))
    
    @staticmethod
    def position_size_from_kelly(balance: float, kelly_fraction: float, price: float, max_risk_pct: float = 2.0) -> float:
        if balance <= 0 or price <= 0 or kelly_fraction <= 0:
            return 0.0
        kelly_amount = balance * kelly_fraction
        max_risk_amount = balance * (max_risk_pct / 100.0)
        allocated = min(kelly_amount, max_risk_amount)
        position_size = allocated / price
        return max(0.0, position_size)


class ATRStops:
    """ATR-based stop loss, take profit, and trailing stop calculations."""
    
    @staticmethod
    def compute_stop_loss(price: float, atr: float, side: str = "long", multiplier: float = 2.0) -> float:
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
    def compute_take_profit(price: float, atr: float, side: str = "long", risk_reward_ratio: float = 2.0) -> float:
        if price <= 0 or atr <= 0 or risk_reward_ratio <= 0:
            return 0.0
        risk_distance = atr * 2.0
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
    def compute_trailing_stop(price: float, atr: float, highest_since_entry: float, multiplier: float = 2.0) -> float:
        if atr <= 0 or multiplier <= 0 or highest_since_entry <= 0:
            return 0.0
        trail = highest_since_entry - (atr * multiplier)
        return max(0.0, trail)


class TrailingStopManager:
    """Manages trailing stop state for open positions."""
    
    def __init__(self, entry_price: float, atr: float, side: str = "long", 
                 atr_multiplier: float = 2.0, activation_pct: float = 1.0, 
                 min_trail_pct: float = 0.5):
        self.entry_price = entry_price
        self.initial_stop = ATRStops.compute_stop_loss(entry_price, atr, side, atr_multiplier)
        self.current_stop = self.initial_stop
        self.atr = atr
        self.side = side.lower().strip()
        self.atr_multiplier = atr_multiplier
        self.activation_pct = activation_pct
        self.min_trail_pct = min_trail_pct
        self.highest_price = entry_price if side == "long" else 0
        self.lowest_price = entry_price if side != "long" else float('inf')
        self.activated = False
        self.lock_time = datetime.now()
        self.lock_duration = timedelta(seconds=30)
    
    def update(self, current_price: float, current_atr: float = None) -> dict:
        moved = False
        triggered = False
        locked = False
        profit_pct = 0.0
        
        if current_atr is not None and current_atr > 0:
            self.atr = current_atr
        
        if datetime.now() - self.lock_time < self.lock_duration:
            locked = True
        
        if self.side == "long":
            profit_pct = ((current_price - self.entry_price) / self.entry_price) * 100
            if current_price > self.highest_price:
                self.highest_price = current_price
            if profit_pct >= self.activation_pct:
                self.activated = True
            if self.activated and not locked:
                new_stop = ATRStops.compute_trailing_stop(current_price, self.atr, self.highest_price, self.atr_multiplier)
                min_trail = current_price * (self.min_trail_pct / 100)
                if new_stop > self.current_stop and (current_price - new_stop) >= min_trail:
                    self.current_stop = new_stop
                    self.lock_time = datetime.now()
                    moved = True
            if current_price <= self.current_stop:
                triggered = True
        else:  # short
            profit_pct = ((self.entry_price - current_price) / self.entry_price) * 100
            if current_price < self.lowest_price:
                self.lowest_price = current_price
            if profit_pct >= self.activation_pct:
                self.activated = True
            if self.activated and not locked:
                new_stop = self.lowest_price + (self.atr * self.atr_multiplier)
                min_trail = current_price * (self.min_trail_pct / 100)
                if new_stop < self.current_stop and (new_stop - current_price) >= min_trail:
                    self.current_stop = new_stop
                    self.lock_time = datetime.now()
                    moved = True
            if current_price >= self.current_stop:
                triggered = True
        
        return {
            "stop_price": self.current_stop,
            "initial_stop": self.initial_stop,
            "triggered": triggered,
            "activated": self.activated,
            "moved": moved,
            "locked": locked,
            "profit_pct": profit_pct,
            "highest_price": self.highest_price,
            "lowest_price": self.lowest_price,
        }
    
    def to_dict(self) -> dict:
        return {
            "entry_price": self.entry_price,
            "initial_stop": self.initial_stop,
            "current_stop": self.current_stop,
            "atr": self.atr,
            "side": self.side,
            "atr_multiplier": self.atr_multiplier,
            "activation_pct": self.activation_pct,
            "min_trail_pct": self.min_trail_pct,
            "highest_price": self.highest_price,
            "lowest_price": self.lowest_price,
            "activated": self.activated,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TrailingStopManager":
        obj = cls(
            entry_price=data["entry_price"],
            atr=data["atr"],
            side=data["side"],
            atr_multiplier=data["atr_multiplier"],
            activation_pct=data["activation_pct"],
            min_trail_pct=data["min_trail_pct"],
        )
        obj.current_stop = data["current_stop"]
        obj.highest_price = data["highest_price"]
        obj.lowest_price = data["lowest_price"]
        obj.activated = data["activated"]
        return obj


class RiskManager:
    """Central risk manager for position sizing and exposure."""
    
    def __init__(self, balance: float, max_risk_per_trade_pct: float = 2.0,
                 max_daily_loss_pct: float = 5.0, max_portfolio_drawdown_pct: float = 15.0,
                 max_open_positions: int = 1):
        self.balance = balance
        self.initial_balance = balance
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_portfolio_drawdown_pct = max_portfolio_drawdown_pct
        self.max_open_positions = max_open_positions
        self.daily_pnl = 0.0
        self.trade_history = []
        self.open_positions = {}
        
    def can_trade(self, new_trade_risk_usd: float) -> tuple[bool, str]:
        if self.daily_pnl <= -self.balance * (self.max_daily_loss_pct / 100):
            return False, "Daily loss limit reached"
        drawdown = (self.initial_balance - self.balance) / self.initial_balance * 100
        if drawdown >= self.max_portfolio_drawdown_pct:
            return False, "Max drawdown reached"
        if len(self.open_positions) >= self.max_open_positions:
            return False, "Max positions open"
        return True, "OK"
    
    def calculate_position_size(self, price: float, stop_distance: float, win_rate: float = 0.55) -> float:
        if stop_distance <= 0 or price <= 0:
            return 0.0
        wins = int(win_rate * 100)
        losses = 100 - wins
        kelly = KellyCriterion.safe_fraction(wins, losses, fraction=0.5)
        risk_amount = self.balance * (self.max_risk_per_trade_pct / 100) * kelly
        position_size = risk_amount / stop_distance
        return position_size
    
    def update_after_trade(self, pnl: float):
        self.daily_pnl += pnl
        self.balance += pnl
        self.trade_history.append({"pnl": pnl, "time": datetime.now().isoformat()})
    
    def add_position(self, pair: str, amount: float, entry: float):
        self.open_positions[pair] = {"amount": amount, "entry": entry, "time": datetime.now().isoformat()}
    
    def remove_position(self, pair: str):
        if pair in self.open_positions:
            del self.open_positions[pair]
    
    def get_stats(self) -> dict:
        return {
            "balance": self.balance,
            "daily_pnl": self.daily_pnl,
            "open_positions": len(self.open_positions),
            "max_drawdown_pct": ((self.initial_balance - self.balance) / self.initial_balance * 100) if self.balance < self.initial_balance else 0,
        }


if __name__ == "__main__":
    print("Risk Manager module ready")
