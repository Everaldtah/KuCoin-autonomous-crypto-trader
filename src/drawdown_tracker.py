#!/usr/bin/env python3
"""
Drawdown Tracker - True peak-to-trough portfolio monitoring

Tracks:
- Running account balance equity curve
- Maximum drawdown (peak to trough)
- Drawdown duration (how long underwater)
- Recovery status

Unlike single-trade P&L tracks total portfolio health.
"""

import json
import math
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from collections import deque


class DrawdownTracker:
    """
    Peak-to-trough drawdown calculator for portfolio equity curve.
    
    Proper drawdown is defined as:
    RunningMaximum(t) = max(value[0:t+1])
    Drawdown(t) = (value[t] - RunningMaximum(t)) / RunningMaximum(t)
    
    This tracks the actual pain of holding a portfolio through peak-to-trough declines.
    """
    
    def __init__(self, max_points: int = 10000):
        """
        Initialize drawdown tracker.
        
        Args:
            max_points: Maximum equity points to keep in memory
        """
        self.max_points = max_points
        self.equity_curve: deque = deque(maxlen=max_points)
        self.peak = 0.0
        self.peak_time = None
        self.trough = 0.0
        self.trough_time = None
        self.max_drawdown_pct = 0.0
        self.max_drawdown_duration = timedelta(0)
        self.current_drawdown_pct = 0.0
        self.underwater_start = None
        self.current_underwater_duration = timedelta(0)
        self.recovered = True
        
    def update(self, equity: float, timestamp: datetime = None):
        """
        Update with new equity value.
        
        Args:
            equity: Current total portfolio value
            timestamp: When measurement taken
        """
        if timestamp is None:
            timestamp = datetime.now()
            
        # First update
        if not self.equity_curve:
            self.peak = equity
            self.peak_time = timestamp
            self.equity_curve.append((timestamp, equity))
            return
            
        # Add to curve
        self.equity_curve.append((timestamp, equity))
        
        # Update peak
        if equity >= self.peak:
            self.peak = equity
            self.peak_time = timestamp
            
            # If we were underwater, record recovery
            if self.underwater_start is not None:
                duration = timestamp - self.underwater_start
                if duration > self.max_drawdown_duration:
                    self.max_drawdown_duration = duration
                self.underwater_start = None
                self.recovered = True
                self.current_underwater_duration = timedelta(0)
                
            self.current_drawdown_pct = 0.0
            
        else:
            # Calculate current drawdown
            dd = (self.peak - equity) / self.peak
            self.current_drawdown_pct = dd * 100
            
            if not self.underwater_start:
                self.underwater_start = timestamp
                self.recovered = False
                
            self.current_underwater_duration = timestamp - self.underwater_start
            
            # Update maximum drawdown
            if dd > self.max_drawdown_pct:
                self.max_drawdown_pct = dd
                self.trough = equity
                self.trough_time = timestamp
                
    def get_current_drawdown(self) -> Tuple[float, timedelta]:
        """
        Get current drawdown percentage and duration.
        
        Returns:
            Tuple of (drawdown_pct: float, duration: timedelta)
        """
        return self.current_drawdown_pct, self.current_underwater_duration
        
    def get_max_drawdown(self) -> Tuple[float, timedelta]:
        """
        Get maximum drawdown percentage and duration.
        
        Returns:
            Tuple of (max_dd_pct: float, max_dd_duration: timedelta)
        """
        return self.max_drawdown_pct * 100, self.max_drawdown_duration
        
    def is_underwater(self) -> bool:
        """Check if currently in drawdown."""
        return self.current_drawdown_pct > 0
        
    def time_to_recovery_estimate(self) -> Optional[timedelta]:
        """
        Estimate recovery time based on historical volatility.
        
        Returns:
            Estimated timedelta or None if not underwater
        """
        if not self.is_underwater():
            return None
            
        # Calculate average daily volatility
        if len(self.equity_curve) < 10:
            return timedelta(days=7)  # Conservative estimate
            
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev = self.equity_curve[i-1][1]
            curr = self.equity_curve[i][1]
            if prev > 0:
                returns.append((curr - prev) / prev)
                
        if not returns:
            return timedelta(days=7)
            
        volatility = math.sqrt(sum(r**2 for r in returns) / len(returns))
        if volatility == 0:
            return timedelta(days=30)  # Couldn't calculate
            
        # To recover from X% drawdown, need X/(1-X) gain
        recovery_needed = self.current_drawdown_pct / 100
        recovery_needed = recovery_needed / (1 - recovery_needed)
        
        # Number of periods needed at average volatility
        import math
        if volatility <= 0:
            return timedelta(days=30)
            
        periods = recovery_needed / (volatility * 0.5)  # Conservative 50% of vol
        days = max(1, int(periods / 24))  # Assuming hourly measurements (adjust as needed)
        
        return timedelta(days=min(days, 365))  # Cap at 1 year
        
    def get_recovery_factor(self) -> float:
        """
        Recovery factor = Return / MaxDrawdown.
        
        Higher is better. > 3.0 is considered good.
        Shows how fast you make back losses.
        """
        if self.max_drawdown_pct == 0:
            return float('inf')  # No drawdown, infinite recovery
            
        # Calculate total return from first measurement
        if len(self.equity_curve) < 2:
            return 1.0
            
        start_equity = self.equity_curve[0][1]
        current_equity = self.equity_curve[-1][1]
        
        if start_equity <= 0:
            return 1.0
            
        total_return = (current_equity - start_equity) / start_equity
        
        return total_return / self.max_drawdown_pct if self.max_drawdown_pct > 0 else 1.0
        
    def calmar_ratio(self, trading_days: int = 252) -> float:
        """
        Calmar Ratio = Annualized Return / Max Drawdown.
        
        Args:
            trading_days: Trading days per year (252 for traditional markets)
            
        Returns:
            Calmar ratio value
        """
        if len(self.equity_curve) < 2:
            return 0.0
            
        start_val = self.equity_curve[0][1]
        end_val = self.equity_curve[-1][1]
        days = (self.equity_curve[-1][0] - self.equity_curve[0][0]).days
        
        if start_val <= 0 or days <= 0 or self.max_drawdown_pct <= 0:
            return 0.0
            
        total_return = (end_val - start_val) / start_val
        annualized = total_return * (trading_days / days) if days > 0 else 0
        
        return annualized / self.max_drawdown_pct
        
    def get_fabric(self) -> dict:
        """Get all statistics in serializable format."""
        return {
            "peak": self.peak,
            "trough": self.trough,
            "max_drawdown_pct": round(self.max_drawdown_pct * 100, 4),
            "max_drawdown_duration": str(self.max_drawdown_duration),
            "current_drawdown_pct": round(self.current_drawdown_pct, 4),
            "underwater": self.is_underwater(),
            "current_underwater_duration": str(self.current_underwater_duration),
            "recovery_factor": round(self.get_recovery_factor(), 2),
            "calmar_ratio": round(self.calmar_ratio(), 2),
            "recovered": self.recovered,
        }
        
    def to_dict(self) -> dict:
        """Serialize full state."""
        return {
            "equity_curve": [(t.isoformat(), v) for t, v in self.equity_curve],
            "peak": self.peak,
            "peak_time": self.peak_time.isoformat() if self.peak_time else None,
            "trough": self.trough,
            "trough_time": self.trough_time.isoformat() if self.trough_time else None,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_drawdown_duration_seconds": self.max_drawdown_duration.total_seconds(),
        }
        
    @classmethod
    def from_dict(cls, data: dict) -> "DrawdownTracker":
        """Restore from serialized state."""
        tracker = cls(max_points=data.get("max_points", 10000))
        tracker.peak = data["peak"]
        tracker.trough = data["trough"]
        tracker.max_drawdown_pct = data["max_drawdown_pct"]
        tracker.max_drawdown_duration = timedelta(seconds=data["max_drawdown_duration_seconds"])
        
        if data.get("peak_time"):
            tracker.peak_time = datetime.fromisoformat(data["peak_time"])
        if data.get("trough_time"):
            tracker.trough_time = datetime.fromisoformat(data["trough_time"])
            
        # Restore equity curve
        for t_str, v in data.get("equity_curve", []):
            tracker.equity_curve.append((datetime.fromisoformat(t_str), v))
            
        return tracker
        
    def get_summary(self) -> str:
        """Get human-readable summary."""
        stats = self.get_fabric()
        
        lines = [
            "Drawdown Statistics:",
            f"  Peak Value: ${stats['peak']:.2f}",
            f"  Trough Value: ${stats['trough']:.2f}",
            f"  Max Drawdown: {stats['max_drawdown_pct']:.2f}%",
            f"  Max DD Duration: {stats['max_drawdown_duration']}",
            f"  Current DD: {stats['current_drawdown_pct']:.2f}%",
            f"  Underwater: {stats['underwater']} ({stats['current_underwater_duration']})",
            f"  Recovery Factor: {stats['recovery_factor']:.2f}",
            f"  Calmar Ratio: {stats['calmar_ratio']:.2f}",
        ]
        return "\n".join(lines)


if __name__ == "__main__":
    # Demo: Simulate equity curve with drawdown
    from datetime import timedelta
    
    tracker = DrawdownTracker()
    base = 1000
    
    # Simulate 60 days
    for day in range(60):
        date = datetime.now() - timedelta(days=60-day)
        
        # Creates a drawdown pattern
        if day < 20:
            equity = base * (1 + day * 0.01)  # Up 20%
        elif day < 35:
            equity = base * 1.2 * (1 - (day-20) * 0.03)  # Down 15%
        else:
            equity = base * 1.2 * 0.85 * (1 + (day-35) * 0.015)  # Recover
            
        tracker.update(equity, date)
        
    print(tracker.get_summary())
