#!/usr/bin/env python3
"""
Correlation Tracker - Multi-Asset Correlation Analysis

Tracks price correlation between trading pairs to avoid overconcentration
in highly correlated assets and to enable pair-trading strategies.
"""

import json
import time
import math
from collections import deque
from typing import Dict, List, Optional, Tuple
from datetime import datetime


class CorrelationTracker:
    """
    Tracks price correlation between multiple trading pairs.
    
    Uses rolling Pearson correlation to detect correlated/anti-correlated
    movements. Helps prevent risk concentration in correlated assets.
    """
    
    def __init__(
        self,
        pairs: List[str],
        window: int = 100,  # Price history window
        min_samples: int = 30,  # Minimum samples for correlation
    ):
        """
        Initialize correlation tracker.
        
        Args:
            pairs: List of trading pairs to track (e.g., ["ETH-USDT", "BTC-USDT"])
            window: Rolling window size for price history
            min_samples: Minimum samples needed before computing correlation
        """
        self.pairs = pairs
        self.window = window
        self.min_samples = min_samples
        self.price_history = {pair: deque(maxlen=window) for pair in pairs}
        self.price_times = {pair: deque(maxlen=window) for pair in pairs}
        self.correlation_matrix = {}
        self.last_update = None
        
    def update(self, pair: str, price: float, timestamp: float = None):
        """
        Add price update for a pair.
        
        Args:
            pair: Trading pair symbol
            price: Current price
            timestamp: Unix timestamp (defaults to time.time())
        """
        if pair not in self.pairs:
            return
            
        if timestamp is None:
            timestamp = time.time()
            
        self.price_history[pair].append(price)
        self.price_times[pair].append(timestamp)
        self.last_update = datetime.now().isoformat()
        
        # Recalculate correlations if we have enough data
        if len(self.price_history[pair]) >= self.min_samples:
            self._compute_correlations()
            
    def _compute_correlations(self):
        """Compute pairwise correlations."""
        returns = {}
        
        # Calculate returns for each pair
        for pair in self.pairs:
            prices = list(self.price_history[pair])
            if len(prices) < self.min_samples:
                continue
            # Log returns
            pair_returns = [math.log(prices[i] / prices[i-1]) 
                         for i in range(1, len(prices))]
            returns[pair] = pair_returns
            
        # Compute pairwise correlations
        self.correlation_matrix = {}
        for i, pair1 in enumerate(self.pairs):
            self.correlation_matrix[pair1] = {}
            for pair2 in self.pairs:
                if pair1 == pair2:
                    self.correlation_matrix[pair1][pair2] = 1.0
                elif pair1 in returns and pair2 in returns:
                    corr = self._pearson_correlation(
                        returns[pair1], returns[pair2]
                    )
                    self.correlation_matrix[pair1][pair2] = corr
                    
    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        n = min(len(x), len(y))
        if n == 0:
            return 0.0
            
        x = x[-n:]
        y = y[-n:]
        
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        denom_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
        
        if denom_x == 0 or denom_y == 0:
            return 0.0
            
        return numerator / (denom_x * denom_y)
        
    def get_correlation(self, pair1: str, pair2: str) -> float:
        """
        Get correlation between two pairs.
        
        Returns:
            Correlation coefficient (-1.0 to +1.0), 0.0 if unavailable
        """
        if pair1 not in self.correlation_matrix:
            return 0.0
        return self.correlation_matrix[pair1].get(pair2, 0.0)
        
    def get_highly_correlated(self, pair: str, threshold: float = 0.7) -> List[str]:
        """
        Find pairs highly correlated with given pair.
        
        Args:
            pair: Reference pair
            threshold: Correlation threshold (0.7 = 70% correlation)
            
        Returns:
            List of other pairs above threshold
        """
        if pair not in self.correlation_matrix:
            return []
            
        correlated = []
        for other_pair, corr in self.correlation_matrix[pair].items():
            if other_pair != pair and abs(corr) >= threshold:
                correlated.append((other_pair, corr))
                
        return sorted(correlated, key=lambda x: abs(x[1]), reverse=True)
        
    def is_diversified(self, held_positions: List[str], threshold: float = 0.7) -> Tuple[bool, str]:
        """
        Check if positions are sufficiently diversified.
        
        Args:
            held_positions: List of pairs with open positions
            threshold: Max allowed correlation
            
        Returns:
            Tuple of (is_diversified: bool, reason: str)
        """
        if len(held_positions) < 2:
            return True, "Single position, no correlation risk"
            
        for i, pos1 in enumerate(held_positions):
            for pos2 in held_positions[i+1:]:
                corr = self.get_correlation(pos1, pos2)
                if abs(corr) >= threshold:
                    return False, f"{pos1} and {pos2} {corr:.0%} correlated"
                    
        return True, "Diversified"
        
    def get_portfolio_risk_factor(
        self,
        positions: Dict[str, float],  # pair -> weight
    ) -> float:
        """
        Calculate portfolio risk factor considering correlations.
        
        Higher value = more concentrated risk from correlations.
        
        Args:
            positions: Dict mapping pair to weight (0.0 to 1.0)
            
        Returns:
            Risk factor (1.0 = uncorrelated, higher = more risk)
        """
        pairs = list(positions.keys())
        if len(pairs) == 0:
            return 1.0
            
        if len(pairs) == 1:
            return 1.0
            
        total_weight = sum(positions.values())
        if total_weight == 0:
            return 1.0
            
        # Normalize weights
        weights = {p: w / total_weight for p, w in positions.items()}
        
        # Portfolio variance with correlations
        portfolio_variance = 0
        for i, p1 in enumerate(pairs):
            w1 = weights[p1]
            for j, p2 in enumerate(pairs):
                w2 = weights[p2]
                corr = self.get_correlation(p1, p2) if i != j else 1.0
                portfolio_variance += w1 * w2 * corr
                
        # Risk factor relative to uncorrelated case
        uncorrelated_var = sum(w ** 2 for w in weights.values())
        if uncorrelated_var == 0:
            return 1.0
            
        risk_factor = portfolio_variance / uncorrelated_var
        
        # Cap at reasonable bounds
        return max(0.5, min(3.0, risk_factor))
        
    def add_pair(self, pair: str):
        """Dynamically add a pair to track."""
        if pair not in self.pairs:
            self.pairs.append(pair)
            self.price_history[pair] = deque(maxlen=self.window)
            self.price_times[pair] = deque(maxlen=self.window)
            
    def to_dict(self) -> dict:
        """Serialize state."""
        return {
            "pairs": self.pairs,
            "window": self.window,
            "min_samples": self.min_samples,
            "correlation_matrix": self.correlation_matrix,
            "last_update": self.last_update,
        }
        
    def get_summary(self) -> str:
        """Get human-readable summary."""
        lines = ["Correlation Matrix:"]
        for pair1 in self.pairs:
            row = []
            for pair2 in self.pairs:
                if pair1 == pair2:
                    row.append("1.00")
                else:
                    corr = self.get_correlation(pair1, pair2)
                    row.append(f"{corr:+.2f}")
            lines.append(f"  {pair1}: " + " | ".join(row))
        return "\n".join(lines)


if __name__ == "__main__":
    # Demo
    tracker = CorrelationTracker(["ETH-USDT", "BTC-USDT", "SOL-USDT"])
    
    # Simulate correlated prices
    prices = {
        "ETH-USDT": 2000,
        "BTC-USDT": 40000,
        "SOL-USDT": 100,
    }
    
    for i in range(50):
        # ETH and BTC move together
        prices["ETH-USDT"] *= (1 + math.sin(i / 10) * 0.01)
        prices["BTC-USDT"] *= (1 + math.sin(i / 10) * 0.008)
        prices["SOL-USDT"] *= (1 + math.cos(i / 8) * 0.012)
        
        for pair, price in prices.items():
            tracker.update(pair, price)
            
    print(tracker.get_summary())
    print(f"\nETH-BTC correlation: {tracker.get_correlation('ETH-USDT', 'BTC-USDT'):.2f}")
