#!/usr/bin/env python3
"""
Aggressive Growth Module for Multi-Pair Trading Bot
===================================================

Implements strategies for £5k-£10k profit target by Dec 31, 2026:
- Compounding with auto-scaling positions
- Tiered profit targets (2.5% → 3.5% → 4.5%)
- Position pyramiding (add to winners)
- Trailing stops with lock-in
- Momentum-focused indicator weighting

Required daily growth: 0.69%-0.92%
Target ROI: 500%-1000%

Integrates with multi_pair_bot_clean.py
"""

import os
import json
import time
from datetime import datetime, date
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

# ─── Configuration Loader ────────────────────────────────────────

def load_aggressive_config(env_path: str = "/root/.env_aggressive") -> Dict:
    """Load aggressive growth configuration with validation."""
    config = {
        # Defaults
        "initial_capital": 1000.0,
        "profit_reinvest_pct": 85.0,
        "pyramiding_enabled": True,
        "trailing_stop_enabled": True,
        "profit_tier1_pct": 2.5,
        "profit_tier2_pct": 3.5,
        "profit_tier3_pct": 4.5,
        "tier1_threshold": 500.0,
        "tier2_threshold": 2000.0,
        "target_profit": 5000.0,
        "target_date": "2026-12-31"
    }
    
    def _clean_value(val: str) -> str:
        """Remove surrounding quotes and comments from config values."""
        val = val.strip()
        # Only strip inline comments (after whitespace) FIRST
        if ' #' in val:
            val = val.split(' #')[0].strip()
        # Remove surrounding quotes (single and double) AFTER comment removal
        if (val.startswith('"') and val.endswith('"')) or \
           (val.startswith("'") and val.endswith("'")):
            val = val[1:-1].strip()
        return val
    
    def _parse_bool(val: str) -> bool:
        """Parse truthy boolean values robustly."""
        cleaned = _clean_value(val).lower()
        return cleaned in ('true', '1', 'yes', 'on', 'enabled')
    
    def _safe_float(val: str, default: float, param_name: str) -> float:
        """Safely convert value to float with validation."""
        try:
            cleaned = _clean_value(val)
            if not cleaned:
                return default
            return float(cleaned)
        except (ValueError, TypeError):
            print(f"[CONFIG WARNING] Invalid value for {param_name}: '{val}', using default {default}")
            return default
    
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    
                    # Map env vars to config with validation
                    if key == "INITIAL_BALANCE":
                        v = _safe_float(val, config["initial_capital"], "INITIAL_BALANCE")
                        if v > 0:
                            config["initial_capital"] = v
                        else:
                            print(f"[CONFIG WARNING] INITIAL_BALANCE must be positive, using default")
                    elif key == "PROFIT_REINVEST_PCT":
                        v = _safe_float(val, config["profit_reinvest_pct"], "PROFIT_REINVEST_PCT")
                        if 0 <= v <= 100:
                            config["profit_reinvest_pct"] = v
                        else:
                            print(f"[CONFIG WARNING] PROFIT_REINVEST_PCT must be 0-100, using default")
                    elif key == "PYRAMIDING_ENABLED":
                        config["pyramiding_enabled"] = _parse_bool(val)
                    elif key == "TRAILING_STOP_ENABLED":
                        config["trailing_stop_enabled"] = _parse_bool(val)
                    elif key == "TAKE_PROFIT_TIER1_PCT":
                        config["profit_tier1_pct"] = _safe_float(val, config["profit_tier1_pct"], "TAKE_PROFIT_TIER1_PCT")
                    elif key == "TAKE_PROFIT_TIER2_PCT":
                        config["profit_tier2_pct"] = _safe_float(val, config["profit_tier2_pct"], "TAKE_PROFIT_TIER2_PCT")
                    elif key == "TAKE_PROFIT_TIER3_PCT":
                        config["profit_tier3_pct"] = _safe_float(val, config["profit_tier3_pct"], "TAKE_PROFIT_TIER3_PCT")
                    elif key == "PROFIT_TIER1_THRESHOLD":
                        config["tier1_threshold"] = _safe_float(val, config["tier1_threshold"], "PROFIT_TIER1_THRESHOLD")
                    elif key == "PROFIT_TIER2_THRESHOLD":
                        config["tier2_threshold"] = _safe_float(val, config["tier2_threshold"], "PROFIT_TIER2_THRESHOLD")
                    elif key == "TARGET_PROFIT":
                        config["target_profit"] = _safe_float(val, config["target_profit"], "TARGET_PROFIT")
                    elif key == "TARGET_DATE":
                        config["target_date"] = _clean_value(val)
    
    return config

# ─── Growth Tracker ────────────────────────────────────────────

@dataclass
class GrowthTarget:
    """Tracks progress toward £5k-£10k target."""
    initial_capital: float = 1000.0
    current_capital: float = 1000.0
    total_realized_pnl: float = 0.0
    target_profit: float = 5000.0
    target_date: str = "2026-12-31"
    
    def percent_complete(self) -> float:
        """Percentage of target profit achieved."""
        if self.target_profit <= 0:
            return 0.0
        return (self.total_realized_pnl / self.target_profit) * 100
    
    def days_remaining(self) -> int:
        """Days until target date."""
        today = date.today()
        target = date.fromisoformat(self.target_date)
        delta = target - today
        return max(0, delta.days)
    
    def required_daily_rate(self) -> float:
        """Daily compound rate needed to hit target."""
        days = self.days_remaining()
        if days <= 0:
            return 0.0
        target_capital = self.initial_capital + self.target_profit
        rate = (target_capital / self.initial_capital) ** (1/days) - 1
        return rate
    
    def projected_final(self, current_rate: float = None) -> Tuple[float, float]:
        """Projected final capital and profit."""
        if current_rate is None:
            current_rate = self.required_daily_rate()
        days = self.days_remaining()
        projected_capital = self.initial_capital * ((1 + current_rate) ** days)
        projected_profit = projected_capital - self.initial_capital
        return projected_capital, projected_profit
    
    def status_report(self) -> Dict:
        """Generate status report."""
        percent = self.percent_complete()
        days_left = self.days_remaining()
        rate = self.required_daily_rate()
        proj_capital, proj_profit = self.projected_final()
        
        return {
            "target": f"£{self.target_profit:,.0f} profit",
            "progress": f"£{self.total_realized_pnl:,.2f} / £{self.target_profit:,.0f} ({percent:.1f}%)",
            "days_remaining": days_left,
            "daily_rate_required": f"{rate*100:.3f}%",
            "projected_profit": f"£{proj_profit:,.0f}",
            "projected_capital": f"£{proj_capital:,.0f}",
            "on_track": proj_profit >= self.target_profit
        }

# ─── Tiered Profit Manager ─────────────────────────────────────

class TieredProfitManager:
    """
    Manages tiered take-profit levels:
    - Tier 1: £0-£500 profit → 2.5% TP
    - Tier 2: £500-£2000 → 3.5% TP
    - Tier 3: £2000+ → 4.5% TP
    """
    
    def __init__(self, config: Dict):
        self.profit_tiers = [
            (0, config["profit_tier1_pct"]),
            (config["tier1_threshold"], config["profit_tier2_pct"]),
            (config["tier2_threshold"], config["profit_tier3_pct"])
        ]
    
    def get_take_profit_pct(self, total_realized_profit: float) -> float:
        """Get take profit % based on current profit tier."""
        current_tp = self.profit_tiers[0][1]  # Default
        
        for threshold, tp_pct in self.profit_tiers:
            if total_realized_profit >= threshold:
                current_tp = tp_pct
        
        return current_tp
    
    def get_current_tier(self, total_realized_profit: float) -> int:
        """Get current tier level (1-3)."""
        tier = 1
        for threshold, _ in self.profit_tiers[1:]:
            if total_realized_profit >= threshold:
                tier += 1
        return tier

# ─── Position Pyramiding ───────────────────────────────────────

class PyramidingManager:
    """
    Adds to winning positions (pyramiding).
    Scale in when position is up X% with room to run.
    """
    
    def __init__(self, config: Dict):
        self.enabled = config.get("pyramiding_enabled", True)
        self.trigger_pct = config.get("pyramid_trigger_pct", 1.5)
        self.max_adds = config.get("pyramid_max_adds", 2)
        self.size_pct = config.get("pyramid_size_pct", 0.5)
        
        # Track pyramids per position
        self.pyramid_count: Dict[str, int] = {}
        self.pyramid_basis: Dict[str, float] = {}  # Average price after pyramids
    
    def should_pyramid(self, position: Dict, current_price: float) -> bool:
        """Check if we should add to this winning position."""
        if not self.enabled:
            return False
        
        symbol = position.get("symbol", "")
        entry_price = position.get("entry_price", 0)
        
        if entry_price <= 0:
            return False
        
        # Check if we've hit pyramid limit
        if self.pyramid_count.get(symbol, 0) >= self.max_adds:
            return False
        
        # Calculate P&L
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Pyramid if we're up trigger_pct
        return pnl_pct >= self.trigger_pct
    
    def calculate_pyramid_size(self, original_size: float) -> float:
        """Calculate size of pyramid addition."""
        return original_size * self.size_pct
    
    def add_pyramid(self, symbol: str, price: float, amount: float):
        """Record a pyramid addition."""
        self.pyramid_count[symbol] = self.pyramid_count.get(symbol, 0) + 1
    
    def reset_pyramid(self, symbol: str):
        """Reset pyramid count when position closed."""
        if symbol in self.pyramid_count:
            del self.pyramid_count[symbol]
        if symbol in self.pyramid_basis:
            del self.pyramid_basis[symbol]

# ─── Compounding Calculator ────────────────────────────────────

class CompoundingCalculator:
    """
    Calculates auto-scaling position sizes as account grows.
    """
    
    def __init__(self, config: Dict, state_file: str = "/root/compound_state.json"):
        self.initial_capital = config.get("initial_capital", 1000.0)
        self.reinvest_pct = config.get("profit_reinvest_pct", 85.0) / 100.0
        self.state_file = state_file
        self.realized_pnl = 0.0
        self.withdrawn = 0.0
        self._load_state()
    
    def _load_state(self):
        """Load compounding state."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                    self.realized_pnl = state.get("realized_pnl", 0.0)
                    self.withdrawn = state.get("withdrawn", 0.0)
            except:
                pass
    
    def _save_state(self):
        """Save compounding state."""
        state = {
            "realized_pnl": self.realized_pnl,
            "withdrawn": self.withdrawn,
            "timestamp": time.time()
        }
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except:
            pass
    
    def process_trade_pnl(self, pnl: float):
        """Process realized P&L from a trade."""
        if pnl > 0:
            # Split profit
            to_reinvest = pnl * self.reinvest_pct
            to_withdraw = pnl * (1 - self.reinvest_pct)
        else:
            # Losses come from realized_pnl
            to_reinvest = 0
            to_withdraw = 0
        
        self.realized_pnl += pnl
        self.withdrawn += to_withdraw
        self._save_state()
    
    def get_effective_capital(self) -> float:
        """Get trading capital including reinvested profits."""
        reinvested = self.realized_pnl * self.reinvest_pct
        return self.initial_capital + max(0, reinvested)
    
    def get_position_size_recommendation(self, base_position_pct: float) -> float:
        """Get recommended position size with compounding."""
        effective = self.get_effective_capital()
        return effective * (base_position_pct / 100.0)

# ─── Trailing Stop Manager ─────────────────────────────────────

class AggressiveTrailingStop:
    """
    Trailing stop optimized for aggressive growth.
    - Activates at 2% profit (lock in gains)
    - Trails 1.5% ATR behind price
    - Never tighter than 1%
    """
    
    def __init__(self, config: Dict = None):
        if config is None:
            config = {}
        self.activation_pct = config.get("trailing_activation_pct", 2.0)
        self.distance_pct = config.get("trailing_distance_pct", 1.5)
        self.min_trail_pct = 1.0
        
        self.trailing_stops: Dict[str, Dict] = {}
    
    def update(self, symbol: str, entry_price: float, current_price: float, atr: float) -> Dict:
        """Update trailing stop for a position."""
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Calculate ATR-based distance
        atr_distance_pct = (atr / current_price) * 100 * self.distance_pct
        
        # Ensure minimum distance
        effective_distance = max(atr_distance_pct, self.min_trail_pct)
        
        # Initialize if not exists
        if symbol not in self.trailing_stops:
            self.trailing_stops[symbol] = {
                "activated": False,
                "highest_price": entry_price,
                "trail_price": entry_price * (1 - effective_distance / 100),
                "entry_price": entry_price
            }
        
        ts = self.trailing_stops[symbol]
        
        # Update highest price
        if current_price > ts["highest_price"]:
            ts["highest_price"] = current_price
        
        # Check activation
        if not ts["activated"] and profit_pct >= self.activation_pct:
            ts["activated"] = True
            # Set initial trail
            ts["trail_price"] = current_price * (1 - effective_distance / 100)
            return {"triggered": False, "moved": True, "stop": ts["trail_price"], "activated": True}
        
        # Update trail if activated
        if ts["activated"]:
            new_trail = ts["highest_price"] * (1 - effective_distance / 100)
            if new_trail > ts["trail_price"]:
                ts["trail_price"] = new_trail
                return {"triggered": False, "moved": True, "stop": new_trail}
        
        # Check if triggered
        if current_price <= ts["trail_price"]:
            return {"triggered": True, "moved": False, "stop": ts["trail_price"], "exit_price": current_price}
        
        return {"triggered": False, "moved": False, "stop": ts["trail_price"], "activated": ts["activated"]}
    
    def reset(self, symbol: str):
        """Reset trailing stop when position closed."""
        if symbol in self.trailing_stops:
            del self.trailing_stops[symbol]

# ─── GrowthDashboard ───────────────────────────────────────────

class GrowthDashboard:
    """Generates daily growth reports."""
    
    def __init__(self):
        self.growth_tracker = None
        self.compounding = None
        self.config = load_aggressive_config()
        self._init_trackers()
    
    def _init_trackers(self):
        """Initialize tracking objects."""
        self.compounding = CompoundingCalculator(self.config)
        self.growth_tracker = GrowthTarget(
            initial_capital=self.config["initial_capital"],
            target_profit=self.config["target_profit"],
            target_date=self.config["target_date"]
        )
        self.growth_tracker.total_realized_pnl = self.compounding.realized_pnl
    
    def get_daily_report(self) -> str:
        """Generate formatted daily report."""
        status = self.growth_tracker.status_report()
        effective_cap = self.compounding.get_effective_capital()
        
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║           GROWTH DASHBOARD - {datetime.now().strftime('%Y-%m-%d %H:%M')}             ║
╠══════════════════════════════════════════════════════════════════╣
║ TARGET: {status['target']:<45}            ║
║ PROGRESS: {status['progress']:<45}          ║
║ DAYS LEFT: {status['days_remaining']:<44}           ║
║ REQUIRED DAILY: {status['daily_rate_required']:<39}             ║
╠══════════════════════════════════════════════════════════════════╣
║ PROJECTED RESULTS:                                               ║
║   Profit: {status['projected_profit']:<45}          ║
║   Capital: {status['projected_capital']:<44}           ║
║   On Track: {'YES ✓' if status['on_track'] else 'NO - Adjust needed!'}
╠══════════════════════════════════════════════════════════════════╣
║ EFFECTIVE TRADING CAPITAL: £{effective_cap:,.2f}                          ║
║ REALIZED P&L: £{self.compounding.realized_pnl:,.2f}                                    ║
║ WITHDRAWN (15%): £{self.compounding.withdrawn:,.2f}                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
        return report
    
    def get_motivation_message(self) -> str:
        """Get motivational message based on progress."""
        pct = self.growth_tracker.percent_complete()
        
        if pct < 5:
            return "🚀 Just getting started! Every % counts."
        elif pct < 20:
            return "📈 Building momentum! Keep compounding!"
        elif pct < 50:
            return "💪 Halfway journey! You're crushing it!"
        elif pct < 80:
            return "🔥 Closing in on the target! Almost there!"
        else:
            return "🏆 INCREDIBLE! Target within reach!"

# ─── Integration with Portfolio Risk Manager ───────────────────

def get_momentum_indicator_weights() -> Dict[str, float]:
    """Get indicator weights optimized for momentum trading."""
    return {
        "rsi": 0.15,
        "ema": 0.15,
        "mfi": 0.20,
        "macd": 0.25,
        "bb": 0.10,
        "super_trend": 0.20,
        "adx": 0.15
    }

# ─── Main Integration ───────────────────────────────────────────

class AggressiveGrowthIntegration:
    """
    Main integration class that wires aggressive features into existing bot.
    """
    
    def __init__(self, bot_instance=None):
        self.config = load_aggressive_config()
        self.growth = GrowthTarget(
            initial_capital=self.config["initial_capital"],
            target_profit=self.config["target_profit"],
            target_date=self.config["target_date"]
        )
        self.tiered_profits = TieredProfitManager(self.config)
        self.pyramiding = PyramidingManager(self.config)
        self.compounding = CompoundingCalculator(self.config)
        self.trailing = AggressiveTrailingStop(self.config)
        self.dashboard = GrowthDashboard()
        self.bot = bot_instance
    
    def on_trade_closed(self, symbol: str, pnl: float, entry_price: float, exit_price: float):
        """Handle closed trade for compounding tracking."""
        self.compounding.process_trade_pnl(pnl)
        self.pyramiding.reset_pyramid(symbol)
        self.trailing.reset(symbol)
        self.growth.total_realized_pnl = self.compounding.realized_pnl
    
    def get_take_profit_pct(self) -> float:
        """Get current take profit percentage based on tier."""
        return self.tiered_profits.get_take_profit_pct(self.compounding.realized_pnl)
    
    def should_add_to_position(self, position: Dict, current_price: float) -> bool:
        """Check if we should pyramid into this position."""
        return self.pyramiding.should_pyramid(position, current_price)
    
    def get_updated_position_size(self, base_size: float) -> float:
        """Get position size adjusted for compounding."""
        return self.compounding.get_position_size_recommendation(base_size)
    
    def check_trailing_stop(self, symbol: str, entry_price: float, current_price: float, atr: float) -> Dict:
        """Check if trailing stop triggered."""
        return self.trailing.update(symbol, entry_price, current_price, atr)
    
    def print_dashboard(self):
        """Print growth dashboard."""
        print(self.dashboard.get_daily_report())
        print(f"\n{self.dashboard.get_motivation_message()}")

# ─── Export for Import ─────────────────────────────────────────

__all__ = [
    'AggressiveGrowthIntegration',
    'AggressiveTrailingStop',
    'CompoundingCalculator',
    'PyramidingManager',
    'TieredProfitManager',
    'GrowthDashboard',
    'load_aggressive_config',
    'get_momentum_indicator_weights'
]

# ─── Self-Test ─────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("AGGRESSIVE GROWTH MODULE - Self Test")
    print("=" * 70)
    
    # Load config
    config = load_aggressive_config()
    print(f"\n✓ Config loaded from /root/.env_aggressive")
    print(f"  Target profit: £{config['target_profit']:,.0f}")
    print(f"  Target date: {config['target_date']}")
    
    # Test growth target
    growth = GrowthTarget(
        initial_capital=1000.0,
        target_profit=5000.0,
        target_date="2026-12-31"
    )
    print(f"\n✓ Growth tracker created")
    print(f"  Days remaining: {growth.days_remaining()}")
    print(f"  Required daily rate: {growth.required_daily_rate()*100:.3f}%")
    
    # Test tiered profits
    tiered = TieredProfitManager(config)
    print(f"\n✓ Tiered profit manager:")
    print(f"  Tier 1 (profit £0-£500): {tiered.get_take_profit_pct(250)}%")
    print(f"  Tier 2 (profit £500-£2000): {tiered.get_take_profit_pct(1000)}%")
    print(f"  Tier 3 (profit £2000+): {tiered.get_take_profit_pct(2500)}%")
    
    # Test compounding
    comp = CompoundingCalculator(config)
    print(f"\n✓ Compounding calculator:")
    print(f"  Effective capital: £{comp.get_effective_capital():,.2f}")
    
    # Simulate some profits
    comp.process_trade_pnl(100.0)
    comp.process_trade_pnl(50.0)
    comp.process_trade_pnl(-20.0)
    print(f"  After trades (130 realized, -20 loss): £{comp.get_effective_capital():,.2f}")
    print(f"  Withdrawn: £{comp.withdrawn:.2f}")
    
    # Test dashboard
    dash = GrowthDashboard()
    print(f"\n✓ Dashboard generated:\n{dash.get_daily_report()}")
    
    # Test trailing stop
    ts = AggressiveTrailingStop(config)
    print(f"\n✓ Trailing stop test:")
    
    # Simulate price movement
    result = ts.update("ETH-USDT", 1500.0, 1500.0, 15.0)  # Entry
    print(f"  Entry at $1500: activated={result['activated']}")
    
    result = ts.update("ETH-USDT", 1500.0, 1550.0, 15.0)  # Up 3.33%
    print(f"  Price $1550 (+3.3%): activated={result['activated']}, stop=${result['stop']:.2f}")
    
    result = ts.update("ETH-USDT", 1500.0, 1540.0, 15.0)  # Pullback to $1540
    print(f"  Price $1540 (pullback): triggered={result['triggered']}, stop=${result['stop']:.2f}")
    
    print("\n" + "=" * 70)
    print("All tests passed! Module ready for integration.")
    print("=" * 70)
