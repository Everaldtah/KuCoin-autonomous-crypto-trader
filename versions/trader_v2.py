#!/usr/bin/env python3
"""
LIVE ETH-USDT Trading Bot v2.5 - Always-On Edition
- Auto-recovers from crashes
- Saves state between restarts
- Persistent logging
"""

import json
import time
import hashlib
import hmac
import math
import base64
import subprocess
import sys
import os
from datetime import datetime, timedelta
from threading import Thread

# Bot configuration
CREDS = {
    "api_key": "YOUR_API_KEY",
    "api_secret": "YOUR_API_SECRET",
    "passphrase": "YOUR_PASSPHRASE"
}

PAIR = "ETH-USDT"
INITIAL_BALANCE = 72.982119
TRADE_AMOUNT = 25.0
TAKE_PROFIT_PCT = 2.5
STOP_LOSS_PCT = 1.5
STATE_FILE = "/root/trader_state.json"
LOG_FILE = "/root/bot.log"

class RobustTrader:
    def __init__(self):
        self.position = None
        self.trades_executed = 0
        self.total_pnl = 0.0
        self.running = True
        self.load_state()
        
    def load_state(self):
        """Load saved state from file"""
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                    self.position = state.get('position')
                    self.trades_executed = state.get('trades', 0)
                    self.total_pnl = state.get('pnl', 0.0)
                    self.log("🔄 State restored from previous session", "INFO")
        except Exception as e:
            self.log(f"Could not load state: {e}", "WARN")
    
    def save_state(self):
        """Save current state to file"""
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump({
                    'position': self.position,
                    'trades': self.trades_executed,
                    'pnl': self.total_pnl,
                    'timestamp': datetime.now().isoformat()
                }, f)
            # Also save dashboard-friendly state
            self.save_dashboard_state()
        except Exception as e:
            pass  # Silent fail on save state
    
    def save_dashboard_state(self):
        """Save dashboard-readable state"""
        try:
            balance = self.get_balance()
            current_price = self.get_price() or 0
            
            state = {
                'connected': True,
                'pair': PAIR,
                'balance_usdt': balance.get('USDT', 0),
                'balance_eth': balance.get('ETH', 0),
                'total_balance': balance.get('USDT', 0) + (balance.get('ETH', 0) * current_price),
                'current_price': current_price,
                'total_pnl': self.total_pnl,
                'trades_today': self.trades_executed,
                'position': self.position,
                'last_update': datetime.now().isoformat(),
                'bot_status': 'active' if self.running else 'stopped'
            }
            
            with open('/root/bot_state.json', 'w') as f:
                json.dump(state, f)
        except Exception as e:
            pass
    
    def log(self, message, level="INFO"):
        """Log to file and display"""
        ts = datetime.now().strftime("%H:%M:%S")
        icons = {
            "INFO": "ℹ️", "BUY": "🟢", "SELL": "🔴", "PROFIT": "💰",
            "LOSS": "⚠️", "ALERT": "🚨", "WARN": "⚡", "OK": "✅"
        }
        log_line = f"{icons.get(level, '•')} [{ts}] {message}"
        
        # Print to console
        print(log_line)
        sys.stdout.flush()
        
        # Append to log file
        try:
            with open(LOG_FILE, 'a') as f:
                f.write(log_line + "\n")
        except:
            pass
        
        # Send Termux notification for important events
        if level in ["BUY", "SELL", "PROFIT", "LOSS", "ALERT"]:
            try:
                subprocess.run([
                    "termux-notification",
                    "--title", "ETH Trader",
                    "--content", message,
                    "--priority", "high" if level in ["ALERT", "PROFIT", "LOSS"] else "default",
                    "--id", "1000"
                ], check=False)
            except:
                pass
    
    def get_kucoin_timestamp(self):
        """Fetch KuCoin server timestamp for accurate signing"""
        try:
            result = subprocess.run(
                ["curl", "-s", "https://api.kucoin.com/api/v1/timestamp"],
                capture_output=True, text=True, timeout=10
            )
            return json.loads(result.stdout)["data"]
        except:
            return int(time.time() * 1000)

    def get_signature(self, endpoint, method="GET", body=""):
        now = self.get_kucoin_timestamp()
        str_to_sign = str(now) + method.upper() + endpoint + body
        signature = base64.b64encode(
            hmac.new(CREDS["api_secret"].encode(), str_to_sign.encode(), hashlib.sha256).digest()
        ).decode()
        passphrase_sig = base64.b64encode(
            hmac.new(CREDS["api_secret"].encode(), CREDS["passphrase"].encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "KC-API-KEY": CREDS["api_key"],
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": str(now),
            "KC-API-PASSPHRASE": passphrase_sig,
            "KC-API-KEY-VERSION": "2"
        }
    
    def api_call(self, command_str):
        """Make API call with retry"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    command_str,
                    capture_output=True, text=True, timeout=30, shell=True
                )
                data = json.loads(result.stdout)
                if data.get("code") == "200000":
                    return True, data["data"]
                if attempt == max_retries - 1:
                    return False, data
            except Exception as e:
                if attempt == max_retries - 1:
                    return False, str(e)
                time.sleep(1)
        return False, "Max retries exceeded"
    
    def get_price(self):
        """Current ETH price"""
        cmd = f"curl -s 'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={PAIR}'"
        success, data = self.api_call(cmd)
        if success:
            return float(data.get("price", 0))
        return None
    
    def get_balance(self):
        """Get account balances using list-based curl (no shell escaping issues)"""
        # Note: KuCoin requires full endpoint including query params for signature
        headers = self.get_signature("/api/v1/accounts?type=trade")
        
        cmd = [
            "curl", "-s",
            "-H", f"KC-API-KEY: {headers['KC-API-KEY']}",
            "-H", f"KC-API-SIGN: {headers['KC-API-SIGN']}",
            "-H", f"KC-API-TIMESTAMP: {headers['KC-API-TIMESTAMP']}",
            "-H", f"KC-API-PASSPHRASE: {headers['KC-API-PASSPHRASE']}",
            "-H", "KC-API-KEY-VERSION: 2",
            "https://api.kucoin.com/api/v1/accounts?type=trade"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            if data.get("code") == "200000":
                balances = {"ETH": 0.0, "USDT": 0.0}
                for acc in data["data"]:
                    if acc["currency"] in balances:
                        balances[acc["currency"]] = float(acc.get("available", 0))
                return balances
        except Exception as e:
            self.log(f"Balance fetch error: {e}", "WARN")
        return {"ETH": 0.0, "USDT": 0.0}
    
    def place_order(self, side, amount):
        """Place market order using list-based curl"""
        body_dict = {
            "symbol": PAIR,
            "side": side,
            "type": "market",
            "clientOid": f"trader_{int(time.time() * 1000)}"
        }
        if side == "buy":
            body_dict["funds"] = str(amount)
        else:
            # If amount looks like a USDT value (small number, not ETH qty),
            # use funds; otherwise use size with proper rounding for ETH increment
            if amount < 1.0:
                # Treat as ETH quantity - round to KuCoin baseIncrement (0.00001)
                rounded = math.floor(amount * 100000) / 100000
                body_dict["size"] = str(rounded)
            else:
                # Treat as USDT funds value
                body_dict["funds"] = str(round(amount, 2))
        
        body = json.dumps(body_dict)
        headers = self.get_signature("/api/v1/orders", "POST", body)
        
        cmd = [
            "curl", "-s", "-X", "POST",
            "-H", f"KC-API-KEY: {headers['KC-API-KEY']}",
            "-H", f"KC-API-SIGN: {headers['KC-API-SIGN']}",
            "-H", f"KC-API-TIMESTAMP: {headers['KC-API-TIMESTAMP']}",
            "-H", f"KC-API-PASSPHRASE: {headers['KC-API-PASSPHRASE']}",
            "-H", "KC-API-KEY-VERSION: 2",
            "-H", "Content-Type: application/json",
            "-d", body,
            "https://api.kucoin.com/api/v1/orders"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            if data.get("code") == "200000":
                return True, data["data"]
            return False, data.get("msg", "Unknown error")
        except Exception as e:
            return False, str(e)
    
    def run(self):
        """Main trading loop"""
        self.log("="*60, "INFO")
        self.log("🚀 ROBUST ETH-USDT TRADER STARTED v2.5", "OK")
        self.log("="*60, "INFO")
        self.log(f"Balance: ${INITIAL_BALANCE:.2f} | Trade: ${TRADE_AMOUNT} | TP:{TAKE_PROFIT_PCT}% SL:{STOP_LOSS_PCT}%", "INFO")
        
        if self.position:
            self.log(f"🔄 RESUMED: Open position {self.position['amount']:.6f} ETH @ ${self.position['entry']:.2f}", "INFO")
        
        cycle = 0
        last_status_time = 0
        
        while self.running:
            try:
                main_loop_start = time.time()
                
                # Get latest data
                price = self.get_price()
                balances = self.get_balance()
                
                if not price:
                    self.log("⚡ Network error, retrying in 10s...", "WARN")
                    time.sleep(10)
                    continue
                
                eth_value = balances["ETH"] * price
                total = balances["USDT"] + eth_value
                pnl = total - INITIAL_BALANCE
                
                # Show status every 60 seconds or on important events
                if time.time() - last_status_time >= 60:
                    self.log(f"💰 Balance: ${total:.2f} | ETH: ${price:.2f} | P&L: ${pnl:+.2f}", "INFO")
                    last_status_time = time.time()
                
                # TRADING LOGIC
                if not self.position:
                    # NO POSITION - Look for entry
                    # Simple strategy: Enter after 6 cycles (60 seconds warm-up)
                    # Or enter on pullback logic
                    if cycle >= 6 and balances["USDT"] >= TRADE_AMOUNT * 1.05:  # 5% buffer
                        # Place buy order
                        eth_qty = TRADE_AMOUNT / price
                        self.log(f"🎯 ENTRY SIGNAL: Price ${price:.2f}", "INFO")
                        
                        success, result = self.place_order("buy", TRADE_AMOUNT)
                        if success:
                            self.position = {
                                "side": "long",
                                "entry": price,
                                "amount": eth_qty,
                                "timestamp": datetime.now().isoformat()
                            }
                            self.save_state()
                            self.log(f"🟢 BUY: {eth_qty:.6f} ETH @ ${price:.2f}", "BUY")
                            self.log(f"🎯 TP: ${price * (1 + TAKE_PROFIT_PCT/100):.2f} | 🛑 SL: ${price * (1 - STOP_LOSS_PCT/100):.2f}", "INFO")
                        else:
                            self.log(f"❌ Buy failed: {result}", "ALERT")
                            time.sleep(30)
                    else:
                        if cycle < 6:
                            self.log("⏳ Warm-up phase...", "INFO")
                        elif balances["USDT"] < TRADE_AMOUNT:
                            self.log("⚡ Insufficient USDT, waiting...", "WARN")
                else:
                    # HAVE POSITION - Monitor for exit
                    entry = self.position["entry"]
                    current_pnl_pct = ((price - entry) / entry) * 100
                    unrealized = (price - entry) * self.position["amount"]
                    
                    # Check exit conditions
                    if current_pnl_pct >= TAKE_PROFIT_PCT:
                        success, result = self.place_order("sell", self.position["amount"])
                        if success:
                            profit = unrealized
                            self.total_pnl += profit
                            self.trades_executed += 1
                            self.position = None
                            self.save_state()
                            self.log(f"💰 TAKE PROFIT! +{current_pnl_pct:.2f}% (+${profit:.2f})", "PROFIT")
                            self.log(f"📊 Total Trades: {self.trades_executed} | Total P&L: ${self.total_pnl:+.2f}", "INFO")
                        else:
                            self.log(f"❌ Sell failed (TP): {result}", "ALERT")
                            time.sleep(30)  # Cooldown before retry
                            
                    elif current_pnl_pct <= -STOP_LOSS_PCT:
                        success, result = self.place_order("sell", self.position["amount"])
                        if success:
                            loss = abs(unrealized)
                            self.total_pnl -= loss
                            self.trades_executed += 1
                            self.position = None
                            self.save_state()
                            self.log(f"🛑 STOP LOSS: {current_pnl_pct:.2f}% (-${loss:.2f})", "LOSS")
                            self.log(f"📊 Total Trades: {self.trades_executed} | Total P&L: ${self.total_pnl:+.2f}", "INFO")
                        else:
                            self.log(f"❌ Sell failed (SL): {result}", "ALERT")
                            # Fallback: try selling with funds (USDT value) instead of size
                            if "increment" in str(result).lower():
                                funds_val = round(self.position["amount"] * price, 2)
                                self.log(f"🔄 Retrying sell with funds=${funds_val}...", "INFO")
                                success2, result2 = self.place_order("sell", funds_val)
                                if success2:
                                    loss = abs(unrealized)
                                    self.total_pnl -= loss
                                    self.trades_executed += 1
                                    self.position = None
                                    self.save_state()
                                    self.log(f"🛑 STOP LOSS (fallback): {current_pnl_pct:.2f}%", "LOSS")
                                else:
                                    self.log(f"❌ Fallback sell also failed: {result2}", "ALERT")
                                    time.sleep(60)  # Longer cooldown to avoid log spam
                    else:
                        # Position running normally
                        if cycle % 6 == 0:  # Every 60 seconds
                            self.log(f"📈 Position: {current_pnl_pct:+.2f}% (U:${unrealized:+.2f} E:${price:.2f})", "INFO")
                
                cycle += 1
                self.save_state()  # Regular state save
                
                # Calculate sleep to maintain 10s cycle
                elapsed = time.time() - main_loop_start
                sleep_time = max(0, 10 - elapsed)
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                self.log("🛑 BOT STOPPED BY USER", "ALERT")
                self.save_state()
                break
            except Exception as e:
                self.log(f"🚨 ERROR: {str(e)[:100]}", "ALERT")
                self.save_state()
                time.sleep(10)  # Wait before retrying
                
        self.log("💾 Final state saved. Bot stopped.", "INFO")

if __name__ == "__main__":
    trader = RobustTrader()
    trader.run()
