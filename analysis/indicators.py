"""Technical indicators for backtesting - mirrors bot's indicator logic."""
import numpy as np
from typing import List, Tuple


class Indicators:
    """Technical indicators matching multi_pair_bot_clean.py logic."""

    @staticmethod
    def compute_rsi(closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        closes_arr = np.asarray(closes, dtype=np.float64)
        deltas = np.diff(closes_arr)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(np.clip(100.0 - 100.0 / (1.0 + rs), 0.0, 100.0))

    @staticmethod
    def compute_ema(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return prices
        prices_arr = np.asarray(prices, dtype=np.float64)
        multiplier = 2.0 / (period + 1)
        ema = [float(prices_arr[0])]
        for p in prices_arr[1:]:
            ema.append((p - ema[-1]) * multiplier + ema[-1])
        return ema

    @staticmethod
    def compute_ema_single(prices: List[float], period: int) -> float:
        ema = Indicators.compute_ema(prices, period)
        return ema[-1] if ema else 0.0

    @staticmethod
    def compute_macd(closes: List[float], fast: int = 12, slow: int = 26,
                      signal: int = 9) -> Tuple[float, float, float]:
        if len(closes) < slow + signal:
            return 0.0, 0.0, 0.0
        ema_fast = Indicators.compute_ema(closes, fast)
        ema_slow = Indicators.compute_ema(closes, slow)
        macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
        sig_line = Indicators.compute_ema(macd_line, signal)
        hist = macd_line[-1] - sig_line[-1]
        return macd_line[-1], sig_line[-1], hist

    @staticmethod
    def compute_bollinger(closes: List[float], period: int = 20,
                          mult: float = 2.0) -> Tuple[float, float, float, float]:
        if len(closes) < period:
            last_price = closes[-1] if closes else 0
            return last_price, last_price, last_price, 0.5
        closes_arr = np.asarray(closes[-period:], dtype=np.float64)
        sma = float(np.mean(closes_arr))
        std = float(np.std(closes_arr))
        upper = sma + mult * std
        lower = sma - mult * std
        if (upper - lower) > 0:
            percent_b = (closes[-1] - lower) / (upper - lower)
        else:
            percent_b = 0.5
        return upper, lower, sma, percent_b

    @staticmethod
    def compute_atr(highs: List[float], lows: List[float], closes: List[float],
                     period: int = 14) -> float:
        if len(closes) < period + 1:
            return 0.0
        tr_list = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            tr_list.append(tr)
        return float(np.mean(tr_list[-period:]))

    @staticmethod
    def ema_crossover_signal(ema_fast: List[float], ema_slow: List[float]) -> int:
        """1=bullish, -1=bearish, 0=neutral"""
        if len(ema_fast) < 2 or len(ema_slow) < 2:
            return 0
        f1, f0 = ema_fast[-2], ema_fast[-1]
        s1, s0 = ema_slow[-2], ema_slow[-1]
        if f1 <= s1 and f0 > s0:
            return 1
        elif f1 >= s1 and f0 < s0:
            return -1
        return 0

    @staticmethod
    def composite_score(closes: List[float], highs: List[float] = None,
                         lows: List[float] = None) -> float:
        """
        Compute 0-1 composite score matching bot's ScoreCalculator.
        Bot thresholds: BUY >= 0.55, SELL <= 0.35
        """
        if len(closes) < 27:
            return 0.5

        highs = highs or closes
        lows = lows or closes

        rsi = Indicators.compute_rsi(closes)
        ema_fast = Indicators.compute_ema(closes, 9)
        ema_slow = Indicators.compute_ema(closes, 21)
        macd_line, sig_line, hist = Indicators.compute_macd(closes)
        upper, lower, sma, bb_percent = Indicators.compute_bollinger(closes)
        atr = Indicators.compute_atr(highs, lows, closes)

        # RSI score
        if rsi < 30:
            rsi_score = 1.0
        elif rsi > 70:
            rsi_score = 0.0
        else:
            rsi_score = (70 - rsi) / 40.0

        # EMA score
        ema_sig = Indicators.ema_crossover_signal(ema_fast, ema_slow)
        ema_score = 1.0 if ema_sig == 1 else 0.0

        # MACD score
        macd_score = 0.5 + float(np.clip(hist / (closes[-1] * 0.01), -0.5, 0.5))

        # Bollinger score
        if bb_percent < 0.2:
            bb_score = 1.0
        elif bb_percent > 0.8:
            bb_score = 0.0
        else:
            bb_score = 1.0 - bb_percent

        # Volatility score
        vol_score = float(np.clip(atr / (closes[-1] * 0.02), 0, 1))

        weights = {"rsi": 0.20, "ema": 0.20, "macd": 0.15, "bb": 0.20, "vol": 0.25}
        score = (rsi_score * weights["rsi"] + ema_score * weights["ema"] +
                 macd_score * weights["macd"] + bb_score * weights["bb"] +
                 vol_score * weights["vol"])
        return float(np.clip(score, 0.0, 1.0))
