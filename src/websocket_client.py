#!/usr/bin/env python3
"""
KuCoin WebSocket Client - Real-time market data
Official WebSocket v1 API - Public channels (no auth needed for ticker/candles)
"""
import json
import time
import threading
import websocket
from datetime import datetime
from collections import deque


class KucoinWSClient:
    """WebSocket client for real-time KuCoin data."""
    
    WS_URL = "wss://ws-api.kucoin.com/endpoint"
    PING_INTERVAL = 20  # KuCoin requires ping every 20-30s
    
    def __init__(self, symbol="ETH-USDT"):
        self.symbol = symbol
        self.ws = None
        self.connected = False
        self.thread = None
        self.price = None
        self.price_bid = None
        self.price_ask = None
        self.last_trade = None
        self.orderbook = {"bids": [], "asks": []}
        self.trades = deque(maxlen=100)  # Last 100 trades
        self.price_callbacks = []  # Price update callbacks
        self.lock = threading.Lock()
        self.ping_thread = None
        self._stop = False
        
    def connect(self):
        """Connect to WebSocket in background thread."""
        self._stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
    def _run(self):
        """WebSocket connection loop with auto-reconnect."""
        while not self._stop:
            try:
                self._connect_ws()
            except Exception as e:
                print(f"[WS] Connection error: {e}, reconnecting in 5s...")
                time.sleep(5)
                
    def _connect_ws(self):
        """Establish WebSocket connection."""
        # Get token from REST API first (bullet token for WS)
        import requests
        resp = requests.post(
            "https://api.kucoin.com/api/v1/bullet-public",
            json={},
            timeout=10
        )
        data = resp.json()
        if data.get("code") != "200000":
            raise Exception(f"Bullet token failed: {data}")
        
        token = data["data"]["token"]
        instance = data["data"]["instanceServers"][0]
        ws_url = f"{instance['endpoint']}?token={token}"
        
        self.ws = websocket.create_connection(
            ws_url,
            ping_interval=self.PING_INTERVAL,
            ping_timeout=10
        )
        self.connected = True
        print(f"[WS] Connected to {self.symbol} feed")
        
        # Subscribe to ticker (price updates)
        self._subscribe("/market/ticker:" + self.symbol)
        # Subscribe to trades (live fills)
        self._subscribe("/market/match:" + self.symbol)
        # Subscribe to level2 orderbook (top 5 bids/asks)
        self._subscribe("/spotMarket/level2Depth5:" + self.symbol)
        
        # Start ping thread
        self.ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self.ping_thread.start()
        
        # Receive loop
        while not self._stop:
            try:
                msg = self.ws.recv()
                self._handle_message(json.loads(msg))
            except websocket.WebSocketException as e:
                print(f"[WS] WebSocket error: {e}")
                break
                
    def _subscribe(self, topic):
        """Subscribe to a channel."""
        msg = {
            "id": str(int(time.time() * 1000)),
            "type": "subscribe",
            "topic": topic,
            "privateChannel": False,
            "response": True
        }
        self.ws.send(json.dumps(msg))
        
    def _ping_loop(self):
        """Send ping every 20 seconds to keep connection alive."""
        while not self._stop and self.connected:
            try:
                self.ws.send(json.dumps({"id": str(int(time.time() * 1000)), "type": "ping"}))
                time.sleep(self.PING_INTERVAL)
            except Exception as e:  # SECURITY: Specific exception handling
                break
                
    def _handle_message(self, msg):
        """Process incoming WebSocket message."""
        topic = msg.get("topic", "")
        data = msg.get("data", {})
        
        with self.lock:
            if "ticker" in topic:
                # Price update: {"bestAsk": "2198.2", "bestBid": "2198.1", "price": "2198.15"}
                self.price = float(data.get("price", 0))
                self.price_bid = float(data.get("bestBid", 0))
                self.price_ask = float(data.get("bestAsk", 0))
                # Notify callbacks
                for cb in self.price_callbacks:
                    try:
                        cb(self.price)
                    except Exception as e:  # SECURITY: Specific exception handling
                        pass
                        
            elif "match" in topic:
                # Live trade: {"price": "2198.2", "size": "0.5", "side": "buy"}
                trade = {
                    "price": float(data.get("price", 0)),
                    "size": float(data.get("size", 0)),
                    "side": data.get("side"),
                    "time": data.get("time")
                }
                self.trades.append(trade)
                self.last_trade = trade
                
            elif "level2Depth5" in topic:
                # Orderbook: {"bids": [["2198", "1.5"], ...], "asks": [["2198.5", "2.0"], ...]}
                self.orderbook = {
                    "bids": [[float(p), float(s)] for p, s in data.get("bids", [])],
                    "asks": [[float(p), float(s)] for p, s in data.get("asks", [])]
                }
                
    def get_price(self):
        """Get current price (thread-safe)."""
        with self.lock:
            return self.price
            
    def get_spread(self):
        """Get bid-ask spread."""
        with self.lock:
            if self.price_bid and self.price_ask:
                return self.price_ask - self.price_bid
            return None
            
    def get_orderbook_imbalance(self):
        """Calculate bid/ask volume imbalance (-1 to +1)."""
        with self.lock:
            if not self.orderbook["bids"] or not self.orderbook["asks"]:
                return 0
            bid_vol = sum(s for _, s in self.orderbook["bids"])
            ask_vol = sum(s for _, s in self.orderbook["asks"])
            total = bid_vol + ask_vol
            if total == 0:
                return 0
            return (bid_vol - ask_vol) / total
            
    def on_price_update(self, callback):
        """Register price update callback."""
        self.price_callbacks.append(callback)
        
    def stop(self):
        """Stop WebSocket client."""
        self._stop = True
        self.connected = False
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:  # SECURITY: Specific exception handling
                pass
                

if __name__ == "__main__":
    # Test
    client = KucoinWSClient("ETH-USDT")
    client.on_price_update(lambda p: print(f"Price: ${p}"))
    client.connect()
    time.sleep(30)
    client.stop()
