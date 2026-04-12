#!/usr/bin/env python3
"""
Position Synchronization - Reconcile bot state with actual KuCoin account
"""
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any


class PositionSync:
    """
    Syncs internal position tracking with actual KuCoin account state.
    Resolves discrepancies caused by:
    - Manual trades
    - Partial fills
    - Bot restarts
    - Version upgrades (v4 -> v5)
    """
    
    def __init__(self, pair: str, state_file: str = None):
        self.pair = pair
        self.base, self.quote = pair.split("-")
        self.state_file = state_file
        
    def sync(self, client, current_position: Optional[Dict] = None) -> Optional[Dict]:
        """
        Synchronize position with actual account balances.
        
        Returns corrected position or None if flat.
        """
        # Get actual balances
        success, data = client.get("/api/v1/accounts", params={"type": "trade"}, auth=True)
        if not success:
            return current_position  # Can't sync, return existing
            
        # Parse balances
        balances = {acc["currency"]: float(acc.get("available", 0)) for acc in data}
        base_balance = balances.get(self.base, 0)
        quote_balance = balances.get(self.quote, 0)
        
        # Get current price for valuation
        price_success, price_data = client.get(
            "/api/v1/market/orderbook/level1",
            params={"symbol": self.pair},
            auth=False
        )
        current_price = float(price_data.get("price", 0)) if price_success else 0
        
        # Determine actual position state
        is_long = base_balance > 0.001  # Minimum tradable amount
        
        if current_position and current_position.get("side") == "long":
            # Currently tracking a long position
            if not is_long:
                # Position was closed externally
                print(f"[SYNC] Position closed externally: {base_balance:.6f} {self.base}")
                return None
                
            # Update position size if changed
            if abs(current_position.get("amount", 0) - base_balance) > 0.0001:
                print(f"[SYNC] Position size updated: {current_position.get('amount', 0):.6f} -> {base_balance:.6f}")
                current_position["amount"] = base_balance
                
            # Recalculate unrealized PnL
            entry = current_position.get("entry", 0)
            if entry > 0 and current_price > 0:
                current_position["unrealized_pnl"] = (current_price - entry) * base_balance
                current_position["unrealized_pct"] = ((current_price - entry) / entry) * 100
                
            return current_position
            
        elif is_long and not current_position:
            # Found position not tracked - auto-import
            print(f"[SYNC] Found existing position: {base_balance:.6f} {self.base}")
            
            # Try to reconstruct from fill history
            entry_price = self._estimate_entry_price(client, base_balance)
            
            return {
                "side": "long",
                "entry": entry_price or current_price,
                "amount": base_balance,
                "timestamp": datetime.now().isoformat(),
                "synced": True,
                "note": "Auto-synced from account balance"
            }
            
        return current_position  # No changes needed
        
    def _estimate_entry_price(self, client, position_size: float) -> Optional[float]:
        """Try to find entry price from recent fill history."""
        try:
            success, fills = client.get(
                "/api/v1/fills",
                params={
                    "symbol": self.pair,
                    "side": "buy",
                    "limit": 10
                },
                auth=True
            )
            if success and fills:
                # Average recent buy fills
                total_cost = 0
                total_size = 0
                for fill in fills:
                    size = float(fill.get("size", 0))
                    price = float(fill.get("price", 0))
                    if size > 0 and price > 0:
                        total_cost += size * price
                        total_size += size
                        
                if total_size > 0 and total_size >= position_size * 0.5:
                    return total_cost / total_size
        except:
            pass
        return None
        
    def save_synced_state(self, position: Optional[Dict], pnl: float = 0, trades: int = 0):
        """Save synchronized state to file."""
        if not self.state_file:
            return
            
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump({
                "position": position,
                "pnl": pnl,
                "trades": trades,
                "timestamp": datetime.now().isoformat(),
                "version": "5.0",
                "synced": True
            }, f)
            

if __name__ == "__main__":
    # Test
    sync = PositionSync("ETH-USDT", "/tmp/test_sync.json")
    print("Position sync module ready")
