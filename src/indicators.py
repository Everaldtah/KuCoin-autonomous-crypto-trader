"""
Advanced Technical Indicators Module for KuCoin Crypto Trading Bot.

Provides professional-grade technical analysis indicators computed with numpy.
All methods are static and designed for ETH-USDT trading on KuCoin.
Each method handles edge cases (insufficient data) by returning neutral defaults.
"""

import numpy as np


class AdvancedIndicators:
    """Comprehensive static technical indicator library for crypto trading."""

    # ------------------------------------------------------------------ #
    #  Helper utilities                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_input(data, min_length=1):
        """Convert data to a numpy float64 array and return it, or None if invalid."""
        arr = np.asarray(data, dtype=np.float64)
        if arr.size < min_length or np.any(~np.isfinite(arr)):
            return None
        return arr

    # ------------------------------------------------------------------ #
    #  1. Relative Strength Index (Wilder's Smoothing)                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_rsi(prices, period=14):
        """Compute Wilder's smoothed Relative Strength Index.

        Args:
            prices: Array-like of closing prices.
            period: Look-back period (default 14).

        Returns:
            float: RSI value clamped to [0, 100]. Returns 50.0 on insufficient data.
        """
        prices = AdvancedIndicators._validate_input(prices, period + 1)
        if prices is None:
            return 50.0

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # Seed with simple average of first `period` values
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        # Wilder's exponential smoothing for the rest
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(np.clip(rsi, 0.0, 100.0))

    # ------------------------------------------------------------------ #
    #  2. Exponential Moving Average                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_ema(prices, period):
        """Compute the Exponential Moving Average.

        Args:
            prices: Array-like of prices.
            period: EMA look-back period.

        Returns:
            float: Latest EMA value. Returns last price on insufficient data.
        """
        prices = AdvancedIndicators._validate_input(prices, period)
        if prices is None:
            prices_raw = np.asarray(prices, dtype=np.float64)
            if prices_raw.size > 0:
                return float(prices_raw[-1])
            return 0.0

        multiplier = 2.0 / (period + 1)
        ema = float(prices[0])
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return float(ema)

    # ------------------------------------------------------------------ #
    #  3. Simple Moving Average                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_sma(prices, period):
        """Compute the Simple Moving Average.

        Args:
            prices: Array-like of prices.
            period: SMA look-back period.

        Returns:
            float: Latest SMA value. Returns last price on insufficient data.
        """
        prices = AdvancedIndicators._validate_input(prices, period)
        if prices is None:
            prices_raw = np.asarray(prices, dtype=np.float64)
            if prices_raw.size > 0:
                return float(prices_raw[-1])
            return 0.0
        return float(np.mean(prices[-period:]))

    # ------------------------------------------------------------------ #
    #  4. MACD (Moving Average Convergence Divergence)                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_macd(prices, fast=12, slow=26, signal=9):
        """Compute MACD line, signal line, and histogram.

        Args:
            prices: Array-like of closing prices.
            fast: Fast EMA period (default 12).
            slow: Slow EMA period (default 26).
            signal: Signal line EMA period (default 9).

        Returns:
            tuple: (macd_line, signal_line, histogram).
                   Returns (0.0, 0.0, 0.0) on insufficient data.
        """
        prices = AdvancedIndicators._validate_input(prices, slow + signal)
        if prices is None:
            return (0.0, 0.0, 0.0)

        # Compute fast and slow EMA arrays
        multiplier_fast = 2.0 / (fast + 1)
        multiplier_slow = 2.0 / (slow + 1)

        ema_fast = np.empty_like(prices)
        ema_slow = np.empty_like(prices)

        ema_fast[0] = prices[0]
        ema_slow[0] = prices[0]

        for i in range(1, len(prices)):
            ema_fast[i] = (prices[i] - ema_fast[i - 1]) * multiplier_fast + ema_fast[i - 1]
            ema_slow[i] = (prices[i] - ema_slow[i - 1]) * multiplier_slow + ema_slow[i - 1]

        macd_line_arr = ema_fast - ema_slow

        # Signal line is EMA of MACD line
        if len(macd_line_arr) < signal:
            return (float(macd_line_arr[-1]), 0.0, float(macd_line_arr[-1]))

        multiplier_sig = 2.0 / (signal + 1)
        signal_arr = np.empty_like(macd_line_arr)
        signal_arr[:signal] = macd_line_arr[:signal]
        # Seed signal with SMA of first `signal` MACD values
        signal_arr[signal - 1] = np.mean(macd_line_arr[:signal])
        for i in range(signal, len(macd_line_arr)):
            signal_arr[i] = (macd_line_arr[i] - signal_arr[i - 1]) * multiplier_sig + signal_arr[i - 1]

        macd_val = float(macd_line_arr[-1])
        signal_val = float(signal_arr[-1])
        histogram = float(macd_val - signal_val)

        return (macd_val, signal_val, histogram)

    # ------------------------------------------------------------------ #
    #  5. Bollinger Bands                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_bollinger_bands(prices, period=20, std_dev=2):
        """Compute Bollinger Bands with bandwidth and %B.

        Args:
            prices: Array-like of closing prices.
            period: Moving average period (default 20).
            std_dev: Standard deviation multiplier (default 2).

        Returns:
            tuple: (upper, middle, lower, bandwidth, percent_b).
                   Returns symmetric band around last price on insufficient data.
        """
        prices = AdvancedIndicators._validate_input(prices, period)
        if prices is None:
            last = float(prices[-1]) if prices.size > 0 else 0.0
            return (last, last, last, 0.0, 0.5)

        window = prices[-period:]
        middle = float(np.mean(window))
        std = float(np.std(window, ddof=1))
        upper = middle + std_dev * std
        lower = middle - std_dev * std

        bandwidth = (upper - lower) / middle if middle != 0 else 0.0
        percent_b = (float(prices[-1]) - lower) / (upper - lower) if (upper - lower) != 0 else 0.5

        return (float(upper), float(middle), float(lower), float(bandwidth), float(percent_b))

    # ------------------------------------------------------------------ #
    #  6. Average True Range (ATR)                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_atr(highs, lows, closes, period=14):
        """Compute Average True Range using Wilder's smoothing.

        Args:
            highs: Array-like of high prices.
            lows: Array-like of low prices.
            highs: Array-like of close prices.
            period: Look-back period (default 14).

        Returns:
            float: Latest ATR value. Returns 0.0 on insufficient data.
        """
        highs = AdvancedIndicators._validate_input(highs, 2)
        lows = AdvancedIndicators._validate_input(lows, 2)
        closes = AdvancedIndicators._validate_input(closes, 2)
        if highs is None or lows is None or closes is None:
            return 0.0

        n = min(len(highs), len(lows), len(closes))
        highs = highs[:n]
        lows = lows[:n]
        closes = closes[:n]

        # True Range components
        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum(tr1, np.maximum(tr2, tr3))

        if len(tr) < period:
            return float(np.mean(tr)) if len(tr) > 0 else 0.0

        # Wilder's smoothing
        atr = float(np.mean(tr[:period]))
        for i in range(period, len(tr)):
            atr = (atr * (period - 1) + tr[i]) / period

        return float(atr)

    # ------------------------------------------------------------------ #
    #  7. Stochastic RSI                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_stochastic_rsi(prices, rsi_period=14, stoch_period=14, k_smooth=3, d_smooth=3):
        """Compute Stochastic RSI (%K and %D).

        First computes RSI over a rolling window, then applies the stochastic
        oscillator formula to the resulting RSI series.

        Args:
            prices: Array-like of closing prices.
            rsi_period: RSI look-back period (default 14).
            stoch_period: Stochastic look-back period (default 14).
            k_smooth: %K smoothing period (default 3).
            d_smooth: %D smoothing period (default 3).

        Returns:
            tuple: (k_value, d_value) in [0, 100].
                   Returns (50.0, 50.0) on insufficient data.
        """
        prices = AdvancedIndicators._validate_input(prices, rsi_period + stoch_period + k_smooth + d_smooth)
        if prices is None:
            return (50.0, 50.0)

        # Build rolling RSI series
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        rsi_values = []
        for start in range(0, len(deltas) - rsi_period + 1):
            g = gains[start:start + rsi_period]
            l = losses[start:start + rsi_period]
            avg_g = np.mean(g)
            avg_l = np.mean(l)
            if avg_l == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_g / avg_l
                rsi_values.append(100.0 - 100.0 / (1.0 + rs))

        if len(rsi_values) < stoch_period:
            return (50.0, 50.0)

        rsi_arr = np.array(rsi_values)

        # Rolling stochastic on RSI values
        raw_k = []
        for i in range(stoch_period - 1, len(rsi_arr)):
            window = rsi_arr[i - stoch_period + 1:i + 1]
            low = np.min(window)
            high = np.max(window)
            if high == low:
                raw_k.append(50.0)
            else:
                raw_k.append((rsi_arr[i] - low) / (high - low) * 100.0)

        if len(raw_k) < k_smooth:
            return (50.0, 50.0)

        # Smooth %K with SMA
        raw_k_arr = np.array(raw_k)
        k_vals = np.convolve(raw_k_arr, np.ones(k_smooth) / k_smooth, mode='valid')

        if len(k_vals) < d_smooth:
            return (float(k_vals[-1]) if len(k_vals) > 0 else 50.0, 50.0)

        # %D is SMA of %K
        d_vals = np.convolve(k_vals, np.ones(d_smooth) / d_smooth, mode='valid')

        k_final = float(k_vals[-1])
        d_final = float(d_vals[-1]) if len(d_vals) > 0 else k_final

        return (k_final, d_final)

    # ------------------------------------------------------------------ #
    #  8. Average Directional Index (ADX)                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_adx(highs, lows, closes, period=14):
        """Compute ADX, +DI, and -DI for trend strength analysis.

        Args:
            highs: Array-like of high prices.
            lows: Array-like of low prices.
            closes: Array-like of close prices.
            period: Look-back period (default 14).

        Returns:
            tuple: (adx, plus_di, minus_di).
                   adx in [0, 100]; DI values in [0, 100].
                   Returns (25.0, 25.0, 25.0) on insufficient data.
        """
        highs = AdvancedIndicators._validate_input(highs, period + 1)
        lows = AdvancedIndicators._validate_input(lows, period + 1)
        closes = AdvancedIndicators._validate_input(closes, period + 1)
        if highs is None or lows is None or closes is None:
            return (25.0, 25.0, 25.0)

        n = min(len(highs), len(lows), len(closes))
        highs = highs[:n]
        lows = lows[:n]
        closes = closes[:n]

        # True Range
        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum(tr1, np.maximum(tr2, tr3))

        # Directional Movement
        up_move = highs[1:] - highs[:-1]
        down_move = lows[:-1] - lows[1:]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        if len(tr) < period:
            return (25.0, 25.0, 25.0)

        # Wilder's smoothing initialization
        atr = float(np.sum(tr[:period]))
        plus_dm_sum = float(np.sum(plus_dm[:period]))
        minus_dm_sum = float(np.sum(minus_dm[:period]))

        plus_di_arr = []
        minus_di_arr = []
        dx_arr = []

        # First DI values
        if atr != 0:
            plus_di_val = 100.0 * plus_dm_sum / atr
            minus_di_val = 100.0 * minus_dm_sum / atr
        else:
            plus_di_val = 0.0
            minus_di_val = 0.0

        plus_di_arr.append(plus_di_val)
        minus_di_arr.append(minus_di_val)

        di_sum = plus_di_val + minus_di_val
        dx = 100.0 * abs(plus_di_val - minus_di_val) / di_sum if di_sum != 0 else 0.0
        dx_arr.append(dx)

        # Subsequent values with Wilder's smoothing
        for i in range(period, len(tr)):
            atr = atr - atr / period + tr[i]
            plus_dm_sum = plus_dm_sum - plus_dm_sum / period + plus_dm[i]
            minus_dm_sum = minus_dm_sum - minus_dm_sum / period + minus_dm[i]

            plus_di_val = 100.0 * plus_dm_sum / atr if atr != 0 else 0.0
            minus_di_val = 100.0 * minus_dm_sum / atr if atr != 0 else 0.0

            plus_di_arr.append(plus_di_val)
            minus_di_arr.append(minus_di_val)

            di_sum = plus_di_val + minus_di_val
            dx = 100.0 * abs(plus_di_val - minus_di_val) / di_sum if di_sum != 0 else 0.0
            dx_arr.append(dx)

        # ADX is smoothed DX
        if len(dx_arr) < period:
            adx_val = float(np.mean(dx_arr))
        else:
            adx_val = float(np.mean(dx_arr[:period]))
            for i in range(period, len(dx_arr)):
                adx_val = (adx_val * (period - 1) + dx_arr[i]) / period

        return (
            float(np.clip(adx_val, 0.0, 100.0)),
            float(np.clip(plus_di_arr[-1], 0.0, 100.0)),
            float(np.clip(minus_di_arr[-1], 0.0, 100.0)),
        )

    # ------------------------------------------------------------------ #
    #  9. Ichimoku Cloud                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_ichimoku(highs, lows, closes):
        """Compute Ichimoku Cloud components.

        Standard periods: tenkan=9, kijun=26, senkou_b=52.

        Args:
            highs: Array-like of high prices.
            lows: Array-like of low prices.
            closes: Array-like of close prices.

        Returns:
            tuple: (tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span).
                   Returns zeros on insufficient data.
        """
        highs = AdvancedIndicators._validate_input(highs, 9)
        lows = AdvancedIndicators._validate_input(lows, 9)
        closes = AdvancedIndicators._validate_input(closes, 9)
        if highs is None or lows is None or closes is None:
            return (0.0, 0.0, 0.0, 0.0, 0.0)

        n = min(len(highs), len(lows), len(closes))
        highs = highs[:n]
        lows = lows[:n]
        closes = closes[:n]

        def _midpoint(high_arr, low_arr, period):
            if len(high_arr) < period:
                return float(high_arr[-1] + low_arr[-1]) / 2.0
            h = float(np.max(high_arr[-period:]))
            l = float(np.min(low_arr[-period:]))
            return (h + l) / 2.0

        # Tenkan-sen (Conversion Line) — period 9
        tenkan = _midpoint(highs, lows, 9)

        # Kijun-sen (Base Line) — period 26
        kijun = _midpoint(highs, lows, 26) if n >= 26 else tenkan

        # Senkou Span A (Leading Span A) — average of tenkan & kijun
        senkou_a = (tenkan + kijun) / 2.0

        # Senkou Span B (Leading Span B) — period 52
        senkou_b = _midpoint(highs, lows, 52) if n >= 52 else senkou_a

        # Chikou Span (Lagging Span) — close shifted back 26 periods
        chikou = float(closes[-1])

        return (
            float(tenkan),
            float(kijun),
            float(senkou_a),
            float(senkou_b),
            float(chikou),
        )

    # ------------------------------------------------------------------ #
    #  10. Volume Weighted Average Price (VWAP)                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_vwap(highs, lows, closes, volumes):
        """Compute cumulative Volume Weighted Average Price.

        Args:
            highs: Array-like of high prices.
            lows: Array-like of low prices.
            closes: Array-like of close prices.
            volumes: Array-like of trade volumes.

        Returns:
            float: VWAP value. Returns last close on insufficient data.
        """
        highs = AdvancedIndicators._validate_input(highs, 1)
        lows = AdvancedIndicators._validate_input(lows, 1)
        closes = AdvancedIndicators._validate_input(closes, 1)
        volumes = AdvancedIndicators._validate_input(volumes, 1)
        if highs is None or lows is None or closes is None or volumes is None:
            return 0.0

        n = min(len(highs), len(lows), len(closes), len(volumes))
        typical_prices = (highs[:n] + lows[:n] + closes[:n]) / 3.0
        cum_volume = np.sum(volumes[:n])

        if cum_volume == 0:
            return float(closes[-1])

        vwap = float(np.sum(typical_prices * volumes[:n]) / cum_volume)
        return vwap

    # ------------------------------------------------------------------ #
    #  11. Volume Analysis                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def analyze_volume(volumes, period=20):
        """Analyze volume for ratio, spike detection, and trend.

        Args:
            volumes: Array-like of volume data.
            period: Look-back period for average (default 20).

        Returns:
            dict: {
                'volume_ratio': float — current / average,
                'is_spike': bool — True if ratio > 2.0,
                'trend': str — 'increasing', 'decreasing', or 'stable'
            }
        """
        volumes = AdvancedIndicators._validate_input(volumes, period)
        if volumes is None:
            return {'volume_ratio': 1.0, 'is_spike': False, 'trend': 'stable'}

        vol = volumes
        avg_volume = float(np.mean(vol[-period:]))
        current_volume = float(vol[-1])

        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        is_spike = volume_ratio > 2.0

        # Determine trend from last 5 candles vs the 5 before that
        if len(vol) >= 10:
            recent = float(np.mean(vol[-5:]))
            older = float(np.mean(vol[-10:-5]))
            if older > 0:
                ratio = recent / older
                if ratio > 1.2:
                    trend = 'increasing'
                elif ratio < 0.8:
                    trend = 'decreasing'
                else:
                    trend = 'stable'
            else:
                trend = 'stable'
        else:
            trend = 'stable'

        return {
            'volume_ratio': float(volume_ratio),
            'is_spike': bool(is_spike),
            'trend': trend,
        }

    # ------------------------------------------------------------------ #
    #  12. Market Regime Detection                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def detect_regime(closes, period=50):
        """Detect current market regime from price action.

        Uses a combination of linear regression slope and volatility to
        classify the market as trending up, trending down, ranging, or volatile.

        Args:
            closes: Array-like of closing prices.
            period: Look-back period (default 50).

        Returns:
            str: One of 'trending_up', 'trending_down', 'ranging', 'volatile'.
        """
        closes = AdvancedIndicators._validate_input(closes, period)
        if closes is None:
            return 'ranging'

        window = closes[-period:]

        # Linear regression slope (normalised by mean price)
        x = np.arange(len(window), dtype=np.float64)
        slope, _ = np.polyfit(x, window, 1)
        normalized_slope = slope / np.mean(window) if np.mean(window) != 0 else 0.0

        # Coefficient of variation as volatility proxy
        cv = float(np.std(window, ddof=1) / np.mean(window)) if np.mean(window) != 0 else 0.0

        # Thresholds
        slope_threshold = 0.005  # 0.5 % per-bar normalised drift
        volatility_threshold = 0.03  # 3 % coefficient of variation

        if cv > volatility_threshold:
            return 'volatile'
        elif normalized_slope > slope_threshold:
            return 'trending_up'
        elif normalized_slope < -slope_threshold:
            return 'trending_down'
        else:
            return 'ranging'

    # ------------------------------------------------------------------ #
    #  13. Compute All Indicators                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_all(highs, lows, closes, volumes):
        """Run every indicator and return a comprehensive dict.

        This is the primary entry point for the trading bot — call it once
        per bar to get a full snapshot of all technical indicators.

        Args:
            highs: Array-like of high prices.
            lows: Array-like of low prices.
            closes: Array-like of close prices.
            volumes: Array-like of trade volumes.

        Returns:
            dict: Nested dictionary with keys for each indicator group:
                - rsi, ema, sma, macd, bollinger, atr, stochastic_rsi,
                  adx, ichimoku, vwap, volume, regime
        """
        closes_arr = np.asarray(closes, dtype=np.float64)
        highs_arr = np.asarray(highs, dtype=np.float64)
        lows_arr = np.asarray(lows, dtype=np.float64)
        volumes_arr = np.asarray(volumes, dtype=np.float64)

        # Core indicators
        rsi = AdvancedIndicators.compute_rsi(closes_arr)
        ema_9 = AdvancedIndicators.compute_ema(closes_arr, 9)
        ema_21 = AdvancedIndicators.compute_ema(closes_arr, 21)
        sma_20 = AdvancedIndicators.compute_sma(closes_arr, 20)
        sma_50 = AdvancedIndicators.compute_sma(closes_arr, 50)

        macd_line, signal_line, macd_histogram = AdvancedIndicators.compute_macd(closes_arr)
        upper, middle, lower, bandwidth, percent_b = AdvancedIndicators.compute_bollinger_bands(closes_arr)

        atr = AdvancedIndicators.compute_atr(highs_arr, lows_arr, closes_arr)
        stoch_k, stoch_d = AdvancedIndicators.compute_stochastic_rsi(closes_arr)
        adx, plus_di, minus_di = AdvancedIndicators.compute_adx(highs_arr, lows_arr, closes_arr)

        tenkan, kijun, senkou_a, senkou_b, chikou = AdvancedIndicators.compute_ichimoku(
            highs_arr, lows_arr, closes_arr
        )

        vwap = AdvancedIndicators.compute_vwap(highs_arr, lows_arr, closes_arr, volumes_arr)
        volume_info = AdvancedIndicators.analyze_volume(volumes_arr)
        regime = AdvancedIndicators.detect_regime(closes_arr)

        last_close = float(closes_arr[-1]) if closes_arr.size > 0 else 0.0

        return {
            'price': last_close,
            'rsi': rsi,
            'ema': {
                'ema_9': ema_9,
                'ema_21': ema_21,
            },
            'sma': {
                'sma_20': sma_20,
                'sma_50': sma_50,
            },
            'macd': {
                'macd_line': macd_line,
                'signal_line': signal_line,
                'histogram': macd_histogram,
            },
            'bollinger': {
                'upper': upper,
                'middle': middle,
                'lower': lower,
                'bandwidth': bandwidth,
                'percent_b': percent_b,
            },
            'atr': atr,
            'stochastic_rsi': {
                'k': stoch_k,
                'd': stoch_d,
            },
            'adx': {
                'adx': adx,
                'plus_di': plus_di,
                'minus_di': minus_di,
            },
            'ichimoku': {
                'tenkan': tenkan,
                'kijun': kijun,
                'senkou_a': senkou_a,
                'senkou_b': senkou_b,
                'chikou': chikou,
            },
            'vwap': vwap,
            'volume': volume_info,
            'regime': regime,
        }
