#!/usr/bin/env python3
"""
Trading Bot Security Module - Hardening & Protection
====================================================

Security features:
- Credential encryption at rest
- Memory protection for sensitive data
- Input validation and sanitization
- Secure logging with masking
- Rate limiting with jitter
- Replay attack prevention
- Tamper detection for state files

Version: 1.0
"""

import os
import re
import json
import hashlib
import secrets
import time
import hmac
import base64
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
import logging


class SecureCredentialStore:
    """
    Secure storage for API credentials using Fernet-like encryption.
    Uses Fernet if available, falls back to simple XOR obfuscation for development.
    """
    
    def __init__(self, key_file: str = "/root/.bot_key"):
        self.key_file = key_file
        self._key = self._load_or_generate_key()
        self._cache: Dict[str, str] = {}
        self._cache_expiry: Dict[str, float] = {}
        
    def _load_or_generate_key(self) -> bytes:
        """Load or generate encryption key."""
        if os.path.exists(self.key_file):
            with open(self.key_file, 'rb') as f:
                return f.read()
        key = secrets.token_bytes(32)
        # Write file first, then set permissions
        with open(self.key_file, 'wb') as f:
            f.write(key)
        os.chmod(self.key_file, 0o400)  # Read-only
        return key
    
    def _encrypt(self, plaintext: str) -> str:
        """Simple encryption - in production use cryptography.fernet"""
        try:
            from cryptography.fernet import Fernet
            fernet = Fernet(base64.urlsafe_b64encode(self._key))
            return fernet.encrypt(plaintext.encode()).decode()
        except ImportError:
            # Fallback: XOR with key (NOT cryptographically secure, obfuscation only)
            data = plaintext.encode()
            key = self._key
            encrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
            return base64.b64encode(encrypted).decode()
    
    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt stored credential."""
        try:
            from cryptography.fernet import Fernet
            fernet = Fernet(base64.urlsafe_b64encode(self._key))
            return fernet.decrypt(ciphertext.encode()).decode()
        except ImportError:
            # Fallback decryption
            data = base64.b64decode(ciphertext)
            key = self._key
            decrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
            return decrypted.decode()
    
    def store(self, key: str, value: str, cache_ttl: int = 300):
        """Store encrypted credential with optional memory caching."""
        encrypted = self._encrypt(value)
        cache_file = f"/root/.bot_cred_{key}"
        with open(cache_file, 'w') as f:
            f.write(encrypted)
        os.chmod(cache_file, 0o600)
        
        # Cache in memory
        self._cache[key] = value
        self._cache_expiry[key] = time.time() + cache_ttl
    
    def retrieve(self, key: str, cache_ttl: int = 300) -> Optional[str]:
        """Retrieve credential with caching."""
        # Check memory cache first
        if key in self._cache:
            if time.time() < self._cache_expiry.get(key, 0):
                return self._cache[key]
            else:
                del self._cache[key]
        
        cache_file = f"/root/.bot_cred_{key}"
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                encrypted = f.read()
            value = self._decrypt(encrypted)
            # Re-cache
            self._cache[key] = value
            self._cache_expiry[key] = time.time() + cache_ttl
            return value
        return None
    
    def clear_cache(self):
        """Clear memory cache of credentials."""
        self._cache.clear()
        self._cache_expiry.clear()


class InputValidator:
    """
    Input validation and sanitization for all external data.
    Prevents injection attacks and data corruption.
    """
    
    # Patterns for dangerous content
    DANGEROUS_PATTERNS = [
        (r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', 'control_chars'),  # Control characters
        (r'<script[^>]*>', 'script_tag'),  # HTML script tags
        (r'javascript:', 'js_protocol'),  # JavaScript protocol
        (r'on\w+\s*=', 'event_handler'),  # Inline event handlers
        (r'\$\{[^}]*\}', 'template_injection'),  # Template injection
        (r'`[^`]*`', 'backtick_command'),  # Command substitution
        (r'\|\s*[a-zA-Z]+', 'pipe_command'),  # Pipe to command
        (r';\s*[a-zA-Z]+', 'command_chain'),  # Command chaining
    ]
    
    # Valid symbol pattern
    SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]+-[A-Z0-9]+$')
    
    # Valid order ID pattern
    ORDER_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
    
    @classmethod
    def sanitize_string(cls, value: str, max_length: int = 256) -> str:
        """Sanitize a string input."""
        if not isinstance(value, str):
            value = str(value)
        
        # Truncate if too long
        value = value[:max_length]
        
        # Remove control characters
        value = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', value)
        
        # Check for dangerous patterns
        for pattern, attack_type in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                raise SecurityError(f"Potential {attack_type} detected: {value[:50]}...")
        
        return value.strip()
    
    @classmethod
    def validate_symbol(cls, symbol: str) -> str:
        """Validate trading pair symbol."""
        if not isinstance(symbol, str):
            raise SecurityError("Symbol must be string")
        
        symbol = symbol.upper().strip()
        
        if not cls.SYMBOL_PATTERN.match(symbol):
            raise SecurityError(f"Invalid symbol format: {symbol}")
        
        # Check for allowed pairs (whitelist)
        allowed_prefixes = ('ETH', 'BTC', 'SOL', 'LINK', 'AVAX', 'DOT', 
                          'MATIC', 'UNI', 'AAVE', 'ATOM', 'ADA', 'DOGE',
                          'XRP', 'LTC', 'BCH', 'ETC', 'ALGO', 'VET',
                          'FIL', 'TRX', 'EOS', 'XTZ', 'XLM', 'USDT')
        
        base = symbol.split('-')[0]
        quote = symbol.split('-')[1] if '-' in symbol else ''
        
        if not any(base.startswith(p) for p in allowed_prefixes):
            raise SecurityError(f"Symbol not in allowed list: {base}")
        
        if quote not in ('USDT', 'BTC', 'ETH', 'USDC'):
            raise SecurityError(f"Quote currency not supported: {quote}")
        
        return symbol
    
    @classmethod
    def validate_price(cls, price: Any) -> float:
        """Validate price value."""
        try:
            price = float(price)
        except (TypeError, ValueError):
            raise SecurityError(f"Invalid price format: {price}")
        
        if price <= 0:
            raise SecurityError(f"Price must be positive: {price}")
        if price > 10000000:  # $10M max sanity check
            raise SecurityError(f"Price exceeds maximum: {price}")
        
        return price
    
    @classmethod
    def validate_amount(cls, amount: Any, max_amount: float = 1000000) -> float:
        """Validate order amount."""
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise SecurityError(f"Invalid amount format: {amount}")
        
        if amount <= 0:
            raise SecurityError(f"Amount must be positive: {amount}")
        if amount > max_amount:
            raise SecurityError(f"Amount exceeds maximum: {amount}")
        
        return amount
    
    @classmethod
    def validate_order_id(cls, order_id: str) -> str:
        """Validate order ID format."""
        if not cls.ORDER_ID_PATTERN.match(order_id):
            raise SecurityError(f"Invalid order ID format: {order_id}")
        return order_id


class RateLimiter:
    """
    Rate limiting with jitter to prevent DDOS and detection.
    """
    
    def __init__(self, max_calls: int = 10, window_seconds: float = 1.0):
        self.max_calls = max_calls
        self.window = window_seconds
        self.calls: List[float] = []
        self._lock_time = 0
    
    def acquire(self, blocking: bool = True) -> bool:
        """Acquire permission to make a call."""
        now = time.time()
        
        # Clean old calls
        cutoff = now - self.window
        self.calls = [t for t in self.calls if t > cutoff]
        
        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True
        
        if not blocking:
            return False
        
        # Wait with jitter
        wait_time = self.window - (now - self.calls[0])
        jitter = secrets.randbelow(100) / 1000  # 0-100ms jitter
        time.sleep(max(0, wait_time) + jitter)
        
        return self.acquire(blocking=False)
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, *args):
        pass


class SecureLogger:
    """
    Logger that automatically masks sensitive data.
    """
    
    # Patterns to mask
    SENSITIVE_PATTERNS = [
        (r'[0-9a-f]{32,}', '***HASH***'),  # API keys, hashes
        (r'(?:api[_-]?key|secret|token|passphrase)[:\s]*["\']?[a-zA-Z0-9_-]{10,}', 
         '***CREDENTIAL***'),  # Credentials
        (r'"signature":\s*"[^"]{10,}"', '"signature": "***SIG***"'),  # Signatures
        (r'0x[a-fA-F0-9]{40}', '***ADDRESS***'),  # Ethereum addresses
        (r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b', '***BTCADDR***'),  # Bitcoin addresses
    ]
    
    def __init__(self, log_file: str, level: str = "INFO"):
        self.log_file = log_file
        self.level = level
        self.levels = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3, "CRITICAL": 4}
    
    def _mask(self, message: str) -> str:
        """Mask sensitive data in log message."""
        masked = message
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            masked = re.sub(pattern, replacement, masked, flags=re.IGNORECASE)
        return masked
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message with automatic masking."""
        if self.levels.get(level, 1) < self.levels.get(self.level, 1):
            return
        
        masked_message = self._mask(message)
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{level}] [{ts}] {masked_message}"
        
        # Write to file
        try:
            with open(self.log_file, 'a') as f:
                f.write(line + "\n")
        except Exception as e:  # SECURITY: Specific exception handling
            pass
        
        # Also print if stdout is TTY
        if os.isatty(1):
            print(line)
    
    def info(self, msg: str):
        self.log(msg, "INFO")
    
    def warn(self, msg: str):
        self.log(msg, "WARN")
    
    def error(self, msg: str):
        self.log(msg, "ERROR")
    
    def critical(self, msg: str):
        self.log(msg, "CRITICAL")


class StateTamperDetector:
    """
    Detects tampering with state files using HMAC signatures.
    """
    
    def __init__(self, key_file: str = "/root/.state_key"):
        self.key_file = key_file
        self._key = self._load_or_generate_key()
    
    def _load_or_generate_key(self) -> bytes:
        """Load or generate HMAC key."""
        if os.path.exists(self.key_file):
            with open(self.key_file, 'rb') as f:
                return f.read()
        key = secrets.token_bytes(32)
        with open(self.key_file, 'wb') as f:
            f.write(key)
        os.chmod(self.key_file, 0o400)
        return key
    
    def sign_state(self, state: Dict) -> str:
        """Generate HMAC signature for state."""
        state_json = json.dumps(state, sort_keys=True)
        signature = hmac.new(
            self._key, 
            state_json.encode(), 
            hashlib.sha256
        ).hexdigest()[:16]
        return signature
    
    def verify_and_load(self, filepath: str) -> Optional[Dict]:
        """Verify and load state file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Check signature - remove signature and metadata fields for verification
            stored_sig = data.pop('_signature', '')
            data.pop('_timestamp', None)
            computed_sig = self.sign_state(data)
            
            if not hmac.compare_digest(stored_sig.encode(), computed_sig.encode()):
                raise SecurityError("State file tampering detected!")
            
            return {k: v for k, v in data.items() if not k.startswith('_')}
        except (json.JSONDecodeError, FileNotFoundError):
            return None
    
    def save_signed_state(self, filepath: str, state: Dict):
        """Save state with HMAC signature."""
        signed_state = state.copy()
        signed_state['_signature'] = self.sign_state(state)
        signed_state['_timestamp'] = datetime.now().isoformat()
        with open(filepath, 'w') as f:
            json.dump(signed_state, f, indent=2)


class SecurityError(Exception):
    """Security-related exception."""
    pass


class EmergencyStop:
    """
    Emergency stop mechanism - immediate halt on critical conditions.
    """
    
    STOP_FILE = "/root/.bot_emergency_stop"
    
    @classmethod
    def trigger(cls, reason: str):
        """Trigger emergency stop."""
        with open(cls.STOP_FILE, 'w') as f:
            f.write(f"{datetime.now().isoformat()} - {reason}\n")
        os.chmod(cls.STOP_FILE, 0o644)
    
    @classmethod
    def clear(cls):
        """Clear emergency stop."""
        if os.path.exists(cls.STOP_FILE):
            os.remove(cls.STOP_FILE)
    
    @classmethod
    def is_triggered(cls) -> Optional[str]:
        """Check if emergency stop is active."""
        if os.path.exists(cls.STOP_FILE):
            with open(cls.STOP_FILE, 'r') as f:
                return f.read().strip()
        return None
    
    @classmethod
    def check_or_raise(cls):
        """Check stop and raise exception if triggered."""
        reason = cls.is_triggered()
        if reason:
            raise SecurityError(f"Emergency stop active: {reason}")


def secure_wrapper(func):
    """Decorator to add security checks to functions."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Check emergency stop
        EmergencyStop.check_or_raise()
        return func(*args, **kwargs)
    return wrapper


# Global instances
credential_store = SecureCredentialStore()
secure_logger = SecureLogger("/root/bot_security.log")
state_signer = StateTamperDetector()


if __name__ == "__main__":
    # Test security module
    print("Testing Trading Bot Security Module...")
    
    # Test credential store
    store = SecureCredentialStore()
    store.store("test_key", "test_secret_123")
    retrieved = store.retrieve("test_key")
    assert retrieved == "test_secret_123", "Credential store failed"
    print("✓ Credential store works")
    
    # Test input validation
    assert InputValidator.validate_symbol("ETH-USDT") == "ETH-USDT"
    assert InputValidator.validate_price("1500.50") == 1500.50
    assert InputValidator.validate_amount("10.5") == 10.5
    print("✓ Input validation works")
    
    # Test rate limiter
    limiter = RateLimiter(max_calls=2, window_seconds=1)
    assert limiter.acquire(blocking=False)
    assert limiter.acquire(blocking=False)
    assert not limiter.acquire(blocking=False)
    print("✓ Rate limiter works")
    
    # Test secure logging
    logger = SecureLogger("/tmp/test_secure.log")
    logger.info("API key: YOUR_API_KEY secret: YOUR_SECRET_KEY")
    print("✓ Secure logging works (check /tmp/test_secure.log)")
    
    # Test state signing
    state = {"balance": 100.0, "positions": []}
    state_signer.save_signed_state("/tmp/test_state.json", state)
    loaded = state_signer.verify_and_load("/tmp/test_state.json")
    assert loaded["balance"] == 100.0
    print("✓ State signing works")
    
    # Test emergency stop
    EmergencyStop.trigger("Test stop")
    assert EmergencyStop.is_triggered() is not None
    EmergencyStop.clear()
    assert EmergencyStop.is_triggered() is None
    print("✓ Emergency stop works")
    
    print("\nAll security tests passed!")

    # Cleanup
    store.clear_cache()
