"""
Multi-Timeframe Confluence Engine with Signal Scoring & Regime-Aware Strategy Switching.

Combines indicators from multiple timeframes (1H, 4H, 1D) into scored trading signals.
Uses weighted confluence to generate high-confidence entry/exit decisions with
automatic regime detection that adjusts strategy parameters.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum


class Signal(Enum):
    """Trading signal with numeric score for confluence calculation."""
    STRONG_BUY = 2
    BUY = 1
    NEUTRAL = 0
    SELL = -1
    STRONG_SELL = -2

    @property
    def direction(self) -> str:
        if self.value > 0:
            return "bullish"
        elif self.value < 0:
            return "bearish"
        return "neutral"

    @classmethod
    def from_score(cls, score: float) -> "Signal":
        if score >= 1.5:
            return cls.STRONG_BUY
        elif score >= 0.5:
            return cls.BUY
        elif score > -0.5:
            return cls.NEUTRAL
        elif score > -1.5:
            return cls.SELL
        else:
            return cls.STRONG_SELL


@dataclass
class TimeframeData:
    """Indicator snapshot for a single timeframe."""
    timeframe: str          # e.g. '1H', '4H', '1D'
    indicators: dict        # output from AdvancedIndicators.compute_all()
    weight: float           # higher timeframes weighted more (e.g. 1H=1.0, 4H=1.5, 1D=2.0)


@dataclass
class ConfluenceResult:
    """Output from the confluence engine."""
    action: Signal
    score: float            # weighted average of all timeframe scores (-2 to +2)
    confidence: float       # 0.0 to 1.0 — how strong the agreement is
    reasons: List[str]      # human-readable explanations
    timeframe_scores: Dict[str, float]  # per-timeframe breakdown
    regime: str             # detected market regime
    strategy_params: dict   # recommended TP/SL/position adjustments


class ConfluenceEngine:
    """
    Scores individual indicators and combines them across timeframes
    to produce a single high-quality trading signal.
    """

    # Weight of each indicator in the final score (sums to 1.0)
    INDICATOR_WEIGHTS = {
        "rsi": 0.15,
        "macd": 0.20,
        "bollinger": 0.12,
        "ema_crossover": 0.18,
        "adx": 0.10,
        "volume": 0.10,
        "stoch_rsi": 0.08,
        "ichimoku": 0.07,
    }

    def score_rsi(self, rsi: float, regime: str = "") -> float:
        """
        Score RSI based on value and current regime.
        Returns -1.0 to +1.0.
        """
        if rsi is None or not (0 <= rsi <= 100):
            return 0.0

        if regime in ("ranging",):
            # In ranging markets, RSI extremes are more meaningful
            if rsi < 25:
                return 1.0
            elif rsi < 35:
                return 0.7
            elif rsi > 75:
                return -1.0
            elif rsi > 65:
                return -0.7
        else:
            # In trending markets, moderate RSI signals are stronger
            if rsi < 30:
                return 0.8
            elif rsi < 40:
                return 0.4
            elif rsi > 70:
                return -0.8
            elif rsi > 60:
                return -0.4

        return 0.0

    def score_macd(self, macd_line: float, signal_line: float,
                   histogram: float) -> float:
        """
        Score MACD crossover and momentum.
        Returns -1.0 to +1.0.
        """
        if any(v is None for v in (macd_line, signal_line, histogram)):
            return 0.0

        score = 0.0

        # Crossover signal
        if macd_line > signal_line:
            score += 0.5
        elif macd_line < signal_line:
            score -= 0.5

        # Histogram direction and magnitude
        if histogram > 0:
            score += min(histogram * 10, 0.5)  # cap at 0.5
        elif histogram < 0:
            score -= min(abs(histogram) * 10, 0.5)

        return max(-1.0, min(1.0, score))

    def score_bollinger(self, price: float, upper: float, lower: float,
                        percent_b: float) -> float:
        """
        Score Bollinger Band position.
        Returns -1.0 to +1.0. Buying near lower band, selling near upper.
        """
        if any(v is None for v in (price, upper, lower, percent_b)):
            return 0.0

        if percent_b is not None:
            # %B < 0 = below lower band (oversold), %B > 1 = above upper (overbought)
            if percent_b < 0:
                return 1.0   # strong buy signal
            elif percent_b < 0.2:
                return 0.6
            elif percent_b > 1:
                return -1.0  # strong sell signal
            elif percent_b > 0.8:
                return -0.6

        return 0.0

    def score_ema_crossover(self, ema_fast: float, ema_slow: float) -> float:
        """
        Score EMA fast/slow crossover.
        Returns -1.0 to +1.0.
        """
        if ema_fast is None or ema_slow is None:
            return 0.0

        diff_pct = ((ema_fast - ema_slow) / ema_slow) * 100

        if diff_pct > 1.0:
            return 1.0
        elif diff_pct > 0.3:
            return 0.5
        elif diff_pct < -1.0:
            return -1.0
        elif diff_pct < -0.3:
            return -0.5

        return 0.0

    def score_adx(self, adx: float, plus_di: float, minus_di: float) -> float:
        """
        Score ADX trend strength with DI direction.
        Returns -1.0 to +1.0. High ADX = strong trend, DI direction = signal.
        """
        if adx is None:
            return 0.0

        # Trend strength multiplier — below 20 is no trend, scale up from there
        strength = min((adx - 20) / 30, 1.0) if adx > 20 else 0.0

        if plus_di is not None and minus_di is not None:
            if plus_di > minus_di:
                return strength  # bullish trend
            else:
                return -strength  # bearish trend

        return 0.0

    def score_volume(self, volume_ratio: float, is_spike: bool) -> float:
        """
        Score volume confirmation.
        Returns -1.0 to +1.0. High volume confirms moves.
        """
        if volume_ratio is None:
            return 0.0

        score = 0.0

        if volume_ratio > 2.0:
            score = 0.8  # very high volume confirms
        elif volume_ratio > 1.5:
            score = 0.5
        elif volume_ratio < 0.5:
            score = -0.3  # low volume = weak conviction

        if is_spike:
            score = min(score + 0.2, 1.0)

        return score

    def score_stoch_rsi(self, k: float, d: float) -> float:
        """
        Score Stochastic RSI crossover.
        Returns -1.0 to +1.0.
        """
        if k is None or d is None:
            return 0.0

        score = 0.0

        # Oversold/overbought zones
        if k < 20 and d < 20:
            score = 0.8  # oversold — buy signal
        elif k > 80 and d > 80:
            score = -0.8  # overbought — sell signal
        # Crossover direction
        elif k > d and k < 50:
            score = 0.3  # bullish crossover in lower zone
        elif k < d and k > 50:
            score = -0.3  # bearish crossover in upper zone

        return score

    def score_ichimoku(self, tenkan: float, kijun: float, price: float,
                       senkou_a: float = None, senkou_b: float = None) -> float:
        """
        Score Ichimoku Cloud position.
        Returns -1.0 to +1.0.
        """
        if tenkan is None or kijun is None or price is None:
            return 0.0

        score = 0.0

        # TK cross
        if tenkan > kijun:
            score += 0.4
        else:
            score -= 0.4

        # Price vs cloud
        if senkou_a is not None and senkou_b is not None:
            cloud_top = max(senkou_a, senkou_b)
            cloud_bottom = min(senkou_a, senkou_b)

            if price > cloud_top:
                score += 0.6   # above cloud — bullish
            elif price < cloud_bottom:
                score -= 0.6   # below cloud — bearish
            # Inside cloud is neutral

        return max(-1.0, min(1.0, score))

    def _score_single_timeframe(self, tf: TimeframeData) -> Tuple[float, List[str]]:
        """Compute weighted indicator score for one timeframe. Returns (score, reasons)."""
        ind = tf.indicators
        reasons = []
        scores = {}

        # RSI
        rsi = ind.get("rsi")
        regime = ind.get("regime", "")
        rsi_score = self.score_rsi(rsi, regime)
        scores["rsi"] = rsi_score
        if rsi is not None:
            if rsi < 30:
                reasons.append(f"RSI({rsi:.0f}) oversold")
            elif rsi > 70:
                reasons.append(f"RSI({rsi:.0f}) overbought")

        # MACD
        macd_data = ind.get("macd", {})
        macd_score = self.score_macd(
            macd_data.get("macd_line"),
            macd_data.get("signal_line"),
            macd_data.get("histogram")
        )
        scores["macd"] = macd_score
        if macd_data.get("histogram", 0) > 0:
            reasons.append("MACD bullish momentum")
        elif macd_data.get("histogram", 0) < 0:
            reasons.append("MACD bearish momentum")

        # Bollinger
        bb = ind.get("bollinger", {})
        bb_score = self.score_bollinger(
            ind.get("price"),
            bb.get("upper"),
            bb.get("lower"),
            bb.get("percent_b")
        )
        scores["bollinger"] = bb_score
        if bb.get("percent_b") is not None:
            if bb["percent_b"] < 0:
                reasons.append("Price below lower Bollinger band")
            elif bb["percent_b"] > 1:
                reasons.append("Price above upper Bollinger band")

        # EMA crossover
        ema_score = self.score_ema_crossover(
            ind.get("ema_fast"),
            ind.get("ema_slow")
        )
        scores["ema_crossover"] = ema_score

        # ADX
        adx_data = ind.get("adx", {})
        adx_score = self.score_adx(
            adx_data.get("adx"),
            adx_data.get("plus_di"),
            adx_data.get("minus_di")
        )
        scores["adx"] = adx_score
        if adx_data.get("adx", 0) > 25:
            reasons.append(f"ADX({adx_data['adx']:.0f}) strong trend")

        # Volume
        vol_data = ind.get("volume", {})
        vol_score = self.score_volume(
            vol_data.get("volume_ratio"),
            vol_data.get("is_spike", False)
        )
        scores["volume"] = vol_score
        if vol_data.get("is_spike"):
            reasons.append("Volume spike detected")

        # Stochastic RSI
        stoch = ind.get("stochastic_rsi", {})
        stoch_score = self.score_stoch_rsi(
            stoch.get("k"),
            stoch.get("d")
        )
        scores["stoch_rsi"] = stoch_score

        # Ichimoku
        ich = ind.get("ichimoku", {})
        ich_score = self.score_ichimoku(
            ich.get("tenkan"),
            ich.get("kijun"),
            ind.get("price"),
            ich.get("senkou_a"),
            ich.get("senkou_b")
        )
        scores["ichimoku"] = ich_score

        # Weighted sum
        total_weight = 0.0
        weighted_score = 0.0
        for key, weight in self.INDICATOR_WEIGHTS.items():
            if key in scores:
                weighted_score += scores[key] * weight
                total_weight += weight

        final = weighted_score / total_weight if total_weight > 0 else 0.0
        return final, reasons

    def generate_signal(self, timeframes: List[TimeframeData]) -> ConfluenceResult:
        """
        Generate a confluence signal from multiple timeframe data.
        Higher timeframes have more weight in the final decision.
        """
        if not timeframes:
            return ConfluenceResult(
                action=Signal.NEUTRAL, score=0.0, confidence=0.0,
                reasons=["No timeframe data"], timeframe_scores={},
                regime="unknown", strategy_params={}
            )

        all_reasons = []
        tf_scores = {}
        weighted_total = 0.0
        weight_sum = 0.0

        for tf in timeframes:
            score, reasons = self._score_single_timeframe(tf)
            tf_scores[tf.timeframe] = round(score, 3)
            weighted_total += score * tf.weight
            weight_sum += tf.weight

            for r in reasons:
                all_reasons.append(f"[{tf.timeframe}] {r}")

        final_score = weighted_total / weight_sum if weight_sum > 0 else 0.0
        final_score = max(-2.0, min(2.0, final_score))

        # Confidence = agreement level across timeframes
        if len(tf_scores) > 1:
            scores_list = list(tf_scores.values())
            all_same_sign = all(s >= 0 for s in scores_list) or all(s <= 0 for s in scores_list)
            if all_same_sign:
                confidence = min(abs(final_score) / 2.0, 1.0)
            else:
                confidence = min(abs(final_score) / 2.0, 0.5)  # conflicting signals
        else:
            confidence = min(abs(final_score) / 2.0, 1.0)

        action = Signal.from_score(final_score)

        # Detect regime from the longest timeframe
        regime = "unknown"
        for tf in sorted(timeframes, key=lambda t: t.weight, reverse=True):
            regime = tf.indicators.get("regime", "unknown")
            if regime != "unknown":
                break

        # Get strategy params for regime
        switcher = RegimeSwitcher()
        strategy_params = switcher.get_strategy_params(regime)

        return ConfluenceResult(
            action=action,
            score=round(final_score, 3),
            confidence=round(confidence, 3),
            reasons=all_reasons,
            timeframe_scores=tf_scores,
            regime=regime,
            strategy_params=strategy_params,
        )


class RegimeSwitcher:
    """
    Detects market regime and adjusts strategy parameters accordingly.
    Uses ADX for trend strength and Bollinger bandwidth for volatility.
    """

    # Strategy adjustments per regime
    REGIME_PARAMS = {
        "strong_trend": {
            "tp_atr_multiplier": 3.0,
            "sl_atr_multiplier": 1.5,
            "position_scale": 1.0,       # full position
            "min_confidence": 0.4,       # lower bar in strong trends
            "trailing_stop": True,
            "trailing_atr_mult": 2.5,
            "description": "Strong trend — ride with trailing stops",
        },
        "weak_trend": {
            "tp_atr_multiplier": 2.0,
            "sl_atr_multiplier": 1.8,
            "position_scale": 0.75,
            "min_confidence": 0.5,
            "trailing_stop": True,
            "trailing_atr_mult": 2.0,
            "description": "Weak trend — reduced size, tighter management",
        },
        "ranging": {
            "tp_atr_multiplier": 1.5,
            "sl_atr_multiplier": 2.0,
            "position_scale": 0.5,
            "min_confidence": 0.6,       # need higher confidence in chop
            "trailing_stop": False,      # trailing stops get chopped in ranges
            "trailing_atr_mult": 1.5,
            "description": "Ranging — mean-reversion, reduced size, no trailing",
        },
        "volatile": {
            "tp_atr_multiplier": 2.5,
            "sl_atr_multiplier": 2.0,
            "position_scale": 0.7,
            "min_confidence": 0.5,
            "trailing_stop": True,
            "trailing_atr_mult": 3.0,    # wider trail to avoid shakeouts
            "description": "Volatile — wider stops, reduced size",
        },
        "trending_up": {
            "tp_atr_multiplier": 3.0,
            "sl_atr_multiplier": 1.5,
            "position_scale": 1.0,
            "min_confidence": 0.4,
            "trailing_stop": True,
            "trailing_atr_mult": 2.5,
            "description": "Uptrend — full size, trail profits",
        },
        "trending_down": {
            "tp_atr_multiplier": 2.0,
            "sl_atr_multiplier": 1.5,
            "position_scale": 0.6,
            "min_confidence": 0.5,
            "trailing_stop": True,
            "trailing_atr_mult": 2.0,
            "description": "Downtrend — cautious, reduced size",
        },
        "quiet": {
            "tp_atr_multiplier": 1.5,
            "sl_atr_multiplier": 1.5,
            "position_scale": 0.0,       # SKIP trades in quiet markets
            "min_confidence": 0.8,       # very high bar
            "trailing_stop": False,
            "trailing_atr_mult": 1.5,
            "description": "Quiet — skip trading, await volatility",
        },
    }

    def detect_regime(self, timeframes: List[TimeframeData]) -> str:
        """
        Detect market regime from multi-timeframe data.
        Uses ADX + Bollinger bandwidth from the highest-weighted timeframe.
        """
        if not timeframes:
            return "unknown"

        # Use the highest-weighted timeframe for regime detection
        primary = max(timeframes, key=lambda t: t.weight)
        ind = primary.indicators

        adx_data = ind.get("adx", {})
        adx = adx_data.get("adx", 0)
        bb = ind.get("bollinger", {})
        bandwidth = bb.get("bandwidth", 0)
        regime = ind.get("regime", "unknown")

        # Refine regime with ADX and bandwidth
        if adx > 40 and regime in ("trending_up", "trending_down"):
            return "strong_trend"
        elif adx > 25:
            if regime == "trending_up":
                return "trending_up"
            elif regime == "trending_down":
                return "trending_down"
            else:
                return "weak_trend"
        elif bandwidth and bandwidth > 0.08:
            return "volatile"
        elif regime == "ranging":
            return "ranging"
        elif adx < 15:
            return "quiet"
        else:
            return "weak_trend"

    def get_strategy_params(self, regime: str) -> dict:
        """Get recommended strategy parameters for a given regime."""
        return self.REGIME_PARAMS.get(regime, self.REGIME_PARAMS["weak_trend"])

    def should_skip_trade(self, regime: str) -> bool:
        """Check if trading should be paused for the current regime."""
        params = self.get_strategy_params(regime)
        return params.get("position_scale", 1.0) <= 0.0
