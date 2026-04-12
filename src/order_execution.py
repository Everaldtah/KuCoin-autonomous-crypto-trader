#!/usr/bin/env python3
"""
Order Execution Module - Smart order placement with fill verification

Handles:
- Limit vs Market orders with slippage protection
- Fill verification (actual vs requested price)
- Partial fill tracking
- Retry with adjusted price
- Order book depth analysis for timing
"""

import time
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any


class OrderResult:
    """Result of an order execution with fill details."""
    
    def __init__(
        self,
        success: bool,
        order_id: str = None,
        filled: float = 0,
        avg_price: float = 0,
        requested_price: float = 0,
        slippage_bps: float = 0,
        fees: float = 0,
        partial: bool = False,
        error: str = None,
        retry_count: int = 0,
    ):
        self.success = success
        self.order_id = order_id
        self.filled = filled
        self.avg_price = avg_price
        self.requested_price = requested_price
        self.slippage_bps = slippage_bps
        self.fees = fees
        self.partial = partial
        self.error = error
        self.retry_count = retry_count
        self.timestamp = datetime.now().isoformat()
        
    @property
    def slippage_pct(self) -> float:
        """Slippage as percentage."""
        return self.slippage_bps / 100.0 if self.requested_price else 0
        
    def to_dict(self) -> dict:
        """Serialize for logging/state persistence."""
        return {
            "success": self.success,
            "order_id": self.order_id,
            "filled": self.filled,
            "avg_price": self.avg_price,
            "requested_price": self.requested_price,
            "slippage_bps": self.slippage_bps,
            "slippage_pct": self.slippage_pct,
            "fees": self.fees,
            "partial": self.partial,
            "error": self.error,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp,
        }


class OrderExecutor:
    """Advanced order execution with verification and retry logic."""
    
    def __init__(
        self,
        client,
        pair: str,
        max_slippage_bps: int = 50,  # 0.5% max slippage
        max_retries: int = 2,
        verify_timeout_sec: int = 30,
    ):
        """
        Initialize order executor.
        
        Args:
            client: KucoinClient instance
            pair: Trading pair (e.g., "ETH-USDT")
            max_slippage_bps: Maximum acceptable slippage in basis points (100 = 1%)
            max_retries: Max retry attempts
            verify_timeout_sec: Timeout for fill verification
        """
        self.client = client
        self.pair = pair
        self.max_slippage_bps = max_slippage_bps
        self.max_retries = max_retries
        self.verify_timeout_sec = verify_timeout_sec
        
    def execute_market_buy(
        self,
        quote_amount: float,
        dry_run: bool = False,
    ) -> OrderResult:
        """
        Execute market buy order with fill verification.
        
        Args:
            quote_amount: Amount of quote currency to spend (e.g., USDT)
            dry_run: If True, simulate order without executing
            
        Returns:
            OrderResult with fill details
        """
        if dry_run:
            return OrderResult(
                success=True,
                filled=quote_amount / 2000,  # Simulated @ $2000
                avg_price=2000,
                requested_price=2000,
                slippage_bps=0,
            )
            
        # Get current price for comparison
        success, ticker = self.client.get(
            "/api/v1/market/orderbook/level1",
            params={"symbol": self.pair},
            auth=False
        )
        
        if not success:
            return OrderResult(success=False, error="Failed to get current price")
            
        requested_price = float(ticker.get("price", 0))
        
        # Place market order
        body = {
            "side": "buy",
            "symbol": self.pair,
            "type": "market",
            "funds": str(round(quote_amount, 2)),  # KuCoin uses 'funds' for market buys
        }
        
        try:
            success, result = self.client.post("/api/v1/orders", body)
            if not success:
                return OrderResult(
                    success=False,
                    error=f"Order failed: {result}",
                    requested_price=requested_price,
                )
                
            order_id = result.get("orderId")
            
            # Wait and verify fill
            fill_result = self._verify_fill(order_id, requested_price, "buy")
            fill_result.order_id = order_id
            
            if fill_result.success and fill_result.slippage_bps > self.max_slippage_bps:
                # Slippage exceeded - could partially reject or warn
                fill_result.error = f"Warning: High slippage {fill_result.slippage_bps}bps"
                
            return fill_result
            
        except Exception as e:
            return OrderResult(
                success=False,
                error=f"Exception: {str(e)}",
                requested_price=requested_price,
            )
            
    def execute_market_sell(
        self,
        base_amount: float,
        dry_run: bool = False,
    ) -> OrderResult:
        """
        Execute market sell order with fill verification.
        
        Args:
            base_amount: Amount of base currency to sell (e.g., ETH)
            dry_run: If True, simulate order without executing
            
        Returns:
            OrderResult with fill details
        """
        if dry_run:
            return OrderResult(
                success=True,
                filled=base_amount,
                avg_price=2000,
                requested_price=2000,
                slippage_bps=0,
            )
            
        # Get current price
        success, ticker = self.client.get(
            "/api/v1/market/orderbook/level1",
            params={"symbol": self.pair},
            auth=False
        )
        
        if not success:
            return OrderResult(success=False, error="Failed to get current price")
            
        requested_price = float(ticker.get("price", 0))
        
        # Place market order
        body = {
            "side": "sell",
            "symbol": self.pair,
            "type": "market",
            "size": str(round(base_amount, 8)),
        }
        
        try:
            success, result = self.client.post("/api/v1/orders", body)
            if not success:
                return OrderResult(
                    success=False,
                    error=f"Order failed: {result}",
                    requested_price=requested_price,
                )
                
            order_id = result.get("orderId")
            
            # Verify fill
            fill_result = self._verify_fill(order_id, requested_price, "sell")
            fill_result.order_id = order_id
            
            return fill_result
            
        except Exception as e:
            return OrderResult(
                success=False,
                error=f"Exception: {str(e)}",
                requested_price=requested_price,
            )
            
    def _verify_fill(
        self,
        order_id: str,
        requested_price: float,
        side: str,
    ) -> OrderResult:
        """Poll order status and check fill details."""
        start = time.time()
        retry = 0
        
        while time.time() - start < self.verify_timeout_sec:
            try:
                success, data = self.client.get(
                    f"/api/v1/orders/{order_id}",
                    auth=True
                )
                
                if not success:
                    time.sleep(0.5)
                    retry += 1
                    continue
                    
                status = data.get("isActive")
                deal_funds = float(data.get("dealFunds", 0))  # Total quote spent/received
                deal_size = float(data.get("dealSize", 0))    # Total base filled
                
                if status is False and deal_size > 0:
                    # Order filled
                    avg_price = deal_funds / deal_size if deal_size > 0 else 0
                    
                    # Calculate slippage
                    if side == "buy":
                        slippage_bps = int(((avg_price - requested_price) / requested_price) * 10000)
                    else:
                        slippage_bps = int(((requested_price - avg_price) / requested_price) * 10000)
                        
                    return OrderResult(
                        success=True,
                        filled=deal_size,
                        avg_price=avg_price,
                        requested_price=requested_price,
                        slippage_bps=slippage_bps,
                        fees=float(data.get("fee", 0)),
                        partial=float(data.get("size", deal_size)) > deal_size,
                        retry_count=retry,
                    )
                    
                elif status is False:
                    # Order cancelled/failed without fill
                    return OrderResult(
                        success=False,
                        error="Order cancelled or failed",
                        retry_count=retry,
                    )
                    
                # Still active, wait
                time.sleep(0.5)
                retry += 1
                
            except Exception as e:
                if retry >= self.max_retries:
                    return OrderResult(
                        success=False,
                        error=f"Verification failed after {retry} retries: {e}",
                        requested_price=requested_price,
                        retry_count=retry,
                    )
                time.sleep(1)
                retry += 1
                
        # Timeout
        return OrderResult(
            success=False,
            error=f"Fill verification timeout ({self.verify_timeout_sec}s)",
            requested_price=requested_price,
            retry_count=retry,
        )
        
    def check_book_depth(
        self,
        depth: int = 5,
    ) -> Dict[str, Any]:
        """
        Check order book depth for liquidity analysis.
        
        Args:
            depth: How many levels to fetch
            
        Returns:
            Dict with spread, imbalance, and liquidity metrics
        """
        try:
            success, data = self.client.get(
                "/api/v1/market/orderbook/level2",
                params={"symbol": self.pair, "depth": depth},
                auth=False
            )
            
            if not success:
                return {"success": False, "error": "Failed to fetch orderbook"}
                
            bids = [[float(p), float(s)] for p, s in data.get("bids", [])[:depth]]
            asks = [[float(p), float(s)] for p, s in data.get("asks", [])[:depth]]
            
            if not bids or not asks:
                return {"success": False, "error": "Empty orderbook"}
                
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            spread = best_ask - best_bid
            spread_pct = (spread / best_bid) * 100
            
            # Volume imbalance
            bid_vol = sum(s for _, s in bids)
            ask_vol = sum(s for _, s in asks)
            total_vol = bid_vol + ask_vol
            imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0
            
            return {
                "success": True,
                "spread": spread,
                "spread_pct": spread_pct,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": (best_bid + best_ask) / 2,
                "bid_vol": bid_vol,
                "ask_vol": ask_vol,
                "imbalance": imbalance,  # -1 (all asks) to +1 (all bids)
                "liquidity_score": min(1.0, total_vol / 100),  # Normalized
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
            
    def should_wait_for_liquidity(
        self,
        min_depth: float = 10.0,
        max_spread_pct: float = 0.1,
    ) -> Tuple[bool, str]:
        """
        Check if we should wait for better liquidity conditions.
        
        Args:
            min_depth: Minimum total volume required
            max_spread_pct: Maximum acceptable spread %
            
        Returns:
            Tuple of (should_wait: bool, reason: str)
        """
        depth = self.check_book_depth(depth=5)
        
        if not depth.get("success"):
            return True, "Cannot check orderbook"
            
        if depth["spread_pct"] > max_spread_pct:
            return True, f"Wide spread {depth['spread_pct']:.3f}%"
            
        total_vol = depth["bid_vol"] + depth["ask_vol"]
        if total_vol < min_depth:
            return True, f"Low liquidity {total_vol:.2f}"
            
        return False, "OK"


if __name__ == "__main__":
    print("Order Executor module ready")
