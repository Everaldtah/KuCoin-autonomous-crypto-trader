#!/usr/bin/env python3
"""
Phase 1: Data Collection & Preparation
======================================
Pulls historical OHLCV data, fee schedules, and catalogues pair characteristics.
"""

import json
import time
import math
import hmac
import base64
import hashlib
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np

# ─── KuCoin HTTP Client ─────────────────────────────────────────────

class KuCoinClient:
    BASE_URL = "https://api.kucoin.com"
    
    def __init__(self, api_key: str, api_secret: str, passphrase: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        
    def _sign(self, method: str, endpoint: str, body: str = "") -> dict:
        now = int(time.time() * 1000)
        str_to_sign = f"{now}{method.upper()}{endpoint}{body}"
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode(), str_to_sign.encode(), hashlib.sha256).digest()
        ).decode()
        encrypted_pass = base64.b64encode(
            hmac.new(self.api_secret.encode(), self.passphrase.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": signature,
            "KC-API-PASSPHRASE": encrypted_pass,
            "KC-API-TIMESTAMP": str(now),
            "KC-API-KEY-VERSION": "2",
            "Content-Type": "application/json"
        }
    
    def _get(self, endpoint: str, params: dict = None) -> Tuple[bool, dict]:
        import requests
        try:
            headers = self._sign("GET", endpoint)
            resp = requests.get(f"{self.BASE_URL}{endpoint}", headers=headers, params=params, timeout=30)
            data = resp.json()
            if data.get("code") == "200000":
                return True, data.get("data", {})
            return False, data
        except Exception as e:
            return False, {"error": str(e)}
    
    def _get_public(self, endpoint: str, params: dict = None) -> Tuple[bool, dict]:
        import requests
        try:
            resp = requests.get(f"{self.BASE_URL}{endpoint}", params=params, timeout=30)
            data = resp.json()
            if data.get("code") == "200000":
                return True, data.get("data", {})
            return False, data
        except Exception as e:
            return False, {"error": str(e)}

    # ─── Historical OHLCV ─────────────────────────────────────────
    
    def get_historical_candles(self, symbol: str, interval: str = "1hour", 
                               start: int = None, end: int = None, 
                               limit: int = 2000) -> List[Dict]:
        """
        Get historical candlestick (OHLCV) data.
        interval: 1min, 5min, 15min, 30min, 1hour, 4hour, 1day, 1week
        Returns list of [timestamp, open, high, low, close, volume]
        """
        endpoint = "/api/v1/market/candles"
        params = {"symbol": symbol, "type": interval, "limit": limit}
        if start:
            params["startAt"] = start
        if end:
            params["endAt"] = end
            
        success, data = self._get_public(endpoint, params)
        if not success:
            print(f"[ERROR] Failed to get candles for {symbol}: {data}")
            return []
        
        # KuCoin returns data directly as a list, not wrapped in "data" key
        candles = data if isinstance(data, list) else data.get("data", [])
        if not candles:
            return []
        
        # Reverse to chronological order (oldest first)
        candles = list(reversed(candles))
        return candles
    
    def get_24hr_stats(self, symbol: str) -> Dict:
        """Get 24-hour trading statistics for a symbol."""
        endpoint = "/api/v1/market/stats"
        success, data = self._get_public(endpoint, {"symbol": symbol})
        if success:
            return data
        return {}
    
    def get_symbol_info(self, symbol: str) -> Dict:
        """Get trading rules for a symbol."""
        endpoint = "/api/v1/symbols"
        success, data = self._get_public(endpoint)
        if success:
            for s in data:
                if s.get("symbol") == symbol:
                    return {
                        "symbol": s.get("symbol"),
                        "base": s.get("baseCurrency"),
                        "quote": s.get("quoteCurrency"),
                        "base_increment": float(s.get("baseIncrement", 1)),
                        "base_min": float(s.get("baseMinSize", 0)),
                        "quote_min": float(s.get("quoteMinSize", 0)),
                        "maker_fee": float(s.get("makerFee", 0.001)),
                        "taker_fee": float(s.get("takerFee", 0.001)),
                    }
        return {}
    
    def get_account_balance(self) -> Dict:
        """Get account balances."""
        endpoint = "/api/v1/accounts"
        success, data = self._get(endpoint)
        if success:
            accounts = {}
            for acc in data:
                if acc.get("type") == "trade":
                    accounts[acc["currency"]] = {
                        "available": float(acc["available"]),
                        "balance": float(acc["balance"])
                    }
            return accounts
        return {}

# ─── Configuration ─────────────────────────────────────────────────

def load_env(path="/root/.env"):
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip("'\"")
    return env

def main():
    env = load_env()
    client = KuCoinClient(
        api_key=env.get("KUCOIN_API_KEY", ""),
        api_secret=env.get("KUCOIN_API_SECRET", ""),
        passphrase=env.get("KUCOIN_PASSPHRASE", "")
    )
    
    # ─── Trading Pairs (from bot) ───────────────────────────────
    PAIRS = [
        "BTC-USDT", "ETH-USDT", "KCS-USDT", "XRP-USDT", "ADA-USDT",
        "XLM-USDT", "DOT-USDT", "LINK-USDT", "BCH-USDT", "UNI-USDT",
        "AAVE-USDT", "EOS-USDT", "ATOM-USDT", "TRX-USDT", "SOL-USDT",
        "MATIC-USDT", "AVAX-USDT", "DOGE-USDT", "SHIB-USDT", "APE-USDT"
    ]
    
    INTERVAL = "1hour"  # Bot uses 1-hour candles
    MONTHS_DATA = 12
    LIMIT = 2000  # Max per request
    
    output_dir = "/root/trading_analysis"
    os.makedirs(output_dir, exist_ok=True)
    
    # ─── Pull Historical Data ────────────────────────────────────
    print("=" * 60)
    print("PHASE 1: DATA COLLECTION")
    print("=" * 60)
    
    all_candle_data = {}
    end_time = int(datetime.now().timestamp())
    start_time = int((datetime.now() - timedelta(days=30 * MONTHS_DATA)).timestamp())
    
    for symbol in PAIRS:
        print(f"\n[FETCHING] {symbol} ({MONTHS_DATA} months of {INTERVAL} data)...")
        
        # KuCoin returns max 2000 candles per request
        # We need to fetch in chunks
        all_candles = []
        current_end = end_time
        
        while current_end > start_time:
            candles = client.get_historical_candles(
                symbol=symbol,
                interval=INTERVAL,
                start=start_time,
                end=current_end,
                limit=LIMIT
            )
            
            if not candles:
                break
            
            all_candles.extend(candles)
            
            # Move to next chunk (oldest timestamp - 1)
            oldest_ts = int(candles[0][0])
            current_end = oldest_ts - 1
            
            # Respect rate limits
            time.sleep(0.2)
        
        if all_candles:
            # Convert to structured format
            structured = []
            for c in all_candles:
                structured.append({
                    "timestamp": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "turnover": float(c[6]) if len(c) > 6 else 0
                })
            
            all_candle_data[symbol] = structured
            print(f"  → Got {len(structured)} candles " +
                  f"({datetime.fromtimestamp(structured[0]['timestamp']).strftime('%Y-%m-%d')} to " +
                  f"{datetime.fromtimestamp(structured[-1]['timestamp']).strftime('%Y-%m-%d')})")
        else:
            print(f"  → No data retrieved")
        
        time.sleep(0.3)  # Rate limit respect
    
    # ─── Save Raw Data ───────────────────────────────────────────
    with open(f"{output_dir}/raw_candles.json", "w") as f:
        json.dump(all_candle_data, f, indent=2)
    print(f"\n[DONE] Saved raw candles to {output_dir}/raw_candles.json")
    
    # ─── Get 24hr Stats for All Pairs ───────────────────────────
    print("\n[FETCHING] 24-hour statistics...")
    stats_24h = {}
    for symbol in PAIRS:
        stats = client.get_24hr_stats(symbol)
        if stats:
            stats_24h[symbol] = stats
            print(f"  {symbol}: Vol=${float(stats.get('vol', 0)):,.0f}, " +
                  f"Change={stats.get('changePrice', 'N/A')}%, " +
                  f"Bid=${stats.get('bestBid', 'N/A')}, Ask=${stats.get('bestAsk', 'N/A')}")
        time.sleep(0.2)
    
    with open(f"{output_dir}/stats_24h.json", "w") as f:
        json.dump(stats_24h, f, indent=2)
    
    # ─── Get Symbol Trading Rules ────────────────────────────────
    print("\n[FETCHING] Symbol trading rules...")
    trading_rules = {}
    for symbol in PAIRS:
        info = client.get_symbol_info(symbol)
        if info:
            trading_rules[symbol] = info
            print(f"  {symbol}: baseMin={info['base_min']}, " +
                  f"quoteMin=${info['quote_min']}, " +
                  f"maker={info['maker_fee']*100}%, taker={info['taker_fee']*100}%")
        time.sleep(0.2)
    
    with open(f"{output_dir}/trading_rules.json", "w") as f:
        json.dump(trading_rules, f, indent=2)
    
    # ─── Get Account Balance ────────────────────────────────────
    print("\n[FETCHING] Account balance...")
    balance = client.get_account_balance()
    print(f"  Balances: {balance}")
    
    with open(f"{output_dir}/account_balance.json", "w") as f:
        json.dump(balance, f, indent=2)
    
    # ─── Bot Strategy Parameters ────────────────────────────────
    print("\n[EXTRACTING] Bot strategy parameters...")
    strategy_params = {
        "version": "v5.0 - Hephaestus",
        "exchange": "KuCoin",
        "initial_capital_default": 500.0,
        "max_pairs": 5,
        "max_position_pct": 15.0,
        "min_position_pct": 3.0,
        "portfolio_drawdown_limit": 8.0,
        "buy_signal_threshold": 0.55,
        "sell_signal_threshold": 0.35,
        "trailing_stop_pct": 1.0,
        "take_profit_pct_base": 3.0,
        "stop_loss_pct_base": 1.5,
        "atr_period": 14,
        "interval": "1hour",
        "indicators": [
            "RSI (period=14, weight=0.20)",
            "EMA (fast/slow crossover, weight=0.20)",
            "MFI - Money Flow Index (period=14, weight=0.15)",
            "MACD (weight=0.15)",
            "Bollinger Bands (weight=0.15)",
            "Super Trend (period=10, multiplier=3, weight=0.10)",
            "ADX - Average Directional Index (period=14, weight=0.05)"
        ],
        "position_sizing": "Kelly Criterion (conservative fraction)",
        "leverage": "None (spot trading)",
        "correlation_matrix": "Enabled for position sizing",
        "market_regime_detection": "BULL/BEAR/RANGING"
    }
    
    with open(f"{output_dir}/strategy_params.json", "w") as f:
        json.dump(strategy_params, f, indent=2)
    print(f"  Saved to {output_dir}/strategy_params.json")
    
    print("\n" + "=" * 60)
    print("PHASE 1 COMPLETE")
    print("=" * 60)
    print(f"Candles collected: {len(all_candle_data)} pairs")
    print(f"Output directory: {output_dir}")

if __name__ == "__main__":
    main()
