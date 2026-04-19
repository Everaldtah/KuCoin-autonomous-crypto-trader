#!/usr/bin/env python3
"""
Phase 2: Walk-Forward Backtesting
=================================
Slides a 6-month train / 2-month test window across 12 months of 1h candle data.
Records every simulated OOS trade and computes per-pair stats.
"""

import json, os, sys
import numpy as np

# ── Bot Config (from v5.0 Hephaestus) ───────────────────────────────
BUY_THRESHOLD  = 0.55
SELL_THRESHOLD = 0.35
TP_PCT         = 3.0
SL_PCT         = 1.5
MAX_PAIRS      = 5
INITIAL_CAPITAL = 500.0
MAKER_FEE      = 0.001
TAKER_FEE      = 0.001
SLIPPAGE_LIQ   = 0.0005
KELLY_FRAC     = 0.25

TRAIN_MONTHS   = 6
TEST_MONTHS    = 2
LOOKBACK       = 50

DATA_DIR = "/root/trading_analysis"

def ema(arr, n):
    if len(arr) < n:
        return arr[:]
    m = 2.0 / (n + 1)
    out = [float(np.mean(arr[:n]))]
    for p in arr[n:]:
        out.append(float(p) * m + out[-1] * (1.0 - m))
    return out

def compute_composite(closes, highs, lows, volumes):
    n = len(closes)
    if n < 50:
        return 0.5, {}

    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    v = np.array(volumes,dtype=float)

    deltas = np.diff(c)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    av_gain = float(np.mean(gains[-14:]))
    av_loss = float(np.mean(losses[-14:]))
    rs = av_gain / av_loss if av_loss != 0 else 100.0
    rsi = 100.0 - (100.0 / (1.0 + rs))

    ema9  = ema(c.tolist(), 9)
    ema21 = ema(c.tolist(), 21)
    ema_fast = ema9[-1]
    ema_slow = ema21[-1]
    ema_signal = 1.0 if ema_fast > ema_slow else 0.0

    tp = (h + l + c) / 3.0
    mf = tp * v
    i_start = max(1, len(mf) - 14)
    pos = sum(mf[i] for i in range(i_start, len(mf)) if c[i] > c[i-1])
    neg = sum(mf[i] for i in range(i_start, len(mf)) if c[i] < c[i-1])
    mfr = pos / neg if neg != 0 else 100.0
    mfi = 100.0 - (100.0 / (1.0 + mfr))

    macd_line_all = [f - s for f, s in zip(ema(c.tolist(), 12), ema(c.tolist(), 26))]
    macd_sig_all  = ema(macd_line_all, 9)
    macd  = macd_line_all[-1] if macd_line_all else 0.0
    msig  = macd_sig_all[-1]  if macd_sig_all  else 0.0
    macd_hist = macd - msig

    recent = c[-20:]
    sma   = float(np.mean(recent))
    std   = float(np.std(recent))
    bb_up  = sma + 2.0 * std
    bb_low = sma - 2.0 * std
    bb_pct = (c[-1] - bb_low) / (bb_up - bb_low) * 100.0 if bb_up != bb_low else 50.0

    tr_list = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, n)]
    atr = float(np.mean(tr_list[-14:])) if len(tr_list) >= 14 else 0.0
    atr_pct = atr / c[-1] * 100.0 if c[-1] != 0 else 0.0
    adx = min(100.0, max(0.0, atr_pct * 8))

    scores = {}
    scores["rsi"]  = 1.0 if rsi < 30 else (0.0 if rsi > 70 else (70.0 - rsi) / 40.0)
    scores["ema"]  = 1.0 if ema_signal == 1.0 else 0.0
    scores["mfi"]  = 1.0 if mfi < 20 else (0.0 if mfi > 80 else (80.0 - mfi) / 60.0)
    macd_max = 0.05 * sma if sma > 0 else 1.0
    scores["macd"] = float(np.clip((macd_hist + macd_max) / (2.0 * macd_max), 0.0, 1.0))
    scores["bb"]   = 1.0 if bb_pct < 10 else (0.0 if bb_pct > 90 else (50.0 - abs(bb_pct - 50.0)) / 50.0)
    scores["super_trend"] = 0.5
    scores["adx"]  = min(1.0, adx / 50.0)

    weights = {"rsi":0.20,"ema":0.20,"mfi":0.15,"macd":0.15,"bb":0.15,"super_trend":0.10,"adx":0.05}
    total_w = sum(weights.get(k, 0.15) for k in scores)
    composite = sum(scores.get(k, 0.5) * weights.get(k, 0.15) for k in scores) / total_w if total_w else 0.5
    composite = float(np.clip(composite, 0.0, 1.0))

    return composite, scores


def walk_forward_test(symbol, candles):
    if len(candles) < 300:
        return []

    timestamps = [c["timestamp"] for c in candles]
    closes     = [c["close"]     for c in candles]
    highs      = [c["high"]      for c in candles]
    lows       = [c["low"]       for c in candles]
    volumes    = [c["volume"]    for c in candles]
    t_start    = timestamps[0]
    t_end      = timestamps[-1]

    MONTH_SEC = 30 * 24 * 3600
    all_trades = []
    window_num = 0

    cursor = t_start
    while True:
        train_end  = cursor + TRAIN_MONTHS * MONTH_SEC
        test_start = train_end
        test_end   = test_start + TEST_MONTHS * MONTH_SEC

        if test_end > t_end:
            break

        train_idxs = [i for i, ts in enumerate(timestamps) if cursor <= ts < train_end]
        if len(train_idxs) < 200:
            cursor = test_start
            continue

        # ── Derive win rate from training window score series ─────────────
        train_scores = []
        for i in range(LOOKBACK, len(train_idxs)):
            idx_slice = train_idxs[i-LOOKBACK:i]
            comp, _ = compute_composite(
                [closes[j]  for j in idx_slice],
                [highs[j]   for j in idx_slice],
                [lows[j]    for j in idx_slice],
                [volumes[j] for j in idx_slice],
            )
            train_scores.append((train_idxs[i], comp))

        wins, losses, win_vals, loss_vals = 0, 0, [], []
        for global_idx, comp in train_scores:
            if comp >= BUY_THRESHOLD:
                entry = closes[global_idx]
                for j in range(global_idx + 1, min(global_idx + 25, len(closes))):
                    ret = (closes[j] - entry) / entry * 100.0
                    if ret >= TP_PCT:
                        wins += 1; win_vals.append(ret); break
                    elif ret <= -SL_PCT:
                        losses += 1; loss_vals.append(abs(ret)); break

        total_signals = wins + losses
        if total_signals < 5:
            cursor = test_start
            continue

        win_rate = wins / total_signals
        avg_win  = float(np.mean(win_vals))  if win_vals  else TP_PCT
        avg_loss = float(np.mean(loss_vals)) if loss_vals else SL_PCT

        # ── Test window simulation ──────────────────────────────────────────
        test_idxs = [i for i, ts in enumerate(timestamps) if test_start <= ts < test_end]
        if len(test_idxs) < 50:
            cursor = test_start
            continue

        window_num += 1
        capital   = INITIAL_CAPITAL
        positions = {}   # sym -> {amount, entry, entry_bar}

        for offset, global_idx in enumerate(test_idxs):
            lb_start = max(0, global_idx - LOOKBACK)
            lb_idxs  = list(range(lb_start, global_idx + 1))
            if len(lb_idxs) < LOOKBACK:
                continue

            comp, _ = compute_composite(
                [closes[j]  for j in lb_idxs],
                [highs[j]   for j in lb_idxs],
                [lows[j]    for j in lb_idxs],
                [volumes[j] for j in lb_idxs],
            )
            price = closes[global_idx]

            # Exit open positions
            for pos_sym, pos in list(positions.items()):
                entry     = pos["entry"]
                amount    = pos["amount"]
                entry_bar = pos["entry_bar"]
                elapsed   = offset - entry_bar
                ret_pct   = (price - entry) / entry * 100.0

                hit_tp   = ret_pct >= TP_PCT
                hit_sl   = ret_pct <= -SL_PCT
                hit_time = elapsed >= 24

                if hit_tp or hit_sl or hit_time:
                    reason = "TP" if hit_tp else ("SL" if hit_sl else "TIME")
                    exit_val  = amount * price  * (1.0 - TAKER_FEE - SLIPPAGE_LIQ)
                    entry_val = amount * entry  * (1.0 + MAKER_FEE + SLIPPAGE_LIQ)
                    pnl       = exit_val - entry_val
                    pnl_pct   = pnl / entry_val * 100.0
                    capital  += exit_val
                    all_trades.append({
                        "symbol":         pos_sym,
                        "side":           "LONG",
                        "entry_price":    entry,
                        "exit_price":     price,
                        "pnl_pct":        pnl_pct,
                        "pnl_usdt":       pnl,
                        "duration_bars":  elapsed,
                        "exit_reason":    reason,
                        "window":         window_num,
                        "turnover":       entry_val + exit_val,
                    })
                    del positions[pos_sym]

            # Enter new positions
            if (comp >= BUY_THRESHOLD and len(positions) < MAX_PAIRS
                    and symbol not in positions):
                if win_rate > 0 and avg_loss > 0:
                    ratio = avg_win / avg_loss
                    kelly_full = (win_rate * ratio - (1.0 - win_rate)) / ratio
                    kelly_frac = max(0.0, kelly_full * KELLY_FRAC)
                else:
                    kelly_frac = 0.02

                size = min(capital * kelly_frac, capital * 0.15)
                if size >= 10.0:
                    amount = size / price
                    cost   = amount * price * (1.0 + MAKER_FEE + SLIPPAGE_LIQ)
                    if cost <= capital:
                        positions[symbol] = {"entry": price, "amount": amount, "entry_bar": offset}
                        capital -= cost

        # Close open at window end
        final_price = closes[test_idxs[-1]]
        for pos_sym, pos in positions.items():
            amount    = pos["amount"]
            entry     = pos["entry"]
            exit_val  = amount * final_price * (1.0 - TAKER_FEE - SLIPPAGE_LIQ)
            entry_val = amount * entry       * (1.0 + MAKER_FEE + SLIPPAGE_LIQ)
            pnl       = exit_val - entry_val
            pnl_pct   = pnl / entry_val * 100.0
            capital  += exit_val
            all_trades.append({
                "symbol":         pos_sym, "side": "LONG",
                "entry_price":    entry,   "exit_price": final_price,
                "pnl_pct":        pnl_pct, "pnl_usdt": pnl,
                "duration_bars":  -1,      "exit_reason": "WINDOW_END",
                "window":         window_num,
                "turnover":       entry_val + exit_val,
            })

        cursor = test_start

    return all_trades


print("=" * 60)
print("PHASE 2: WALK-FORWARD BACKTESTING")
print("=" * 60)

with open(f"{DATA_DIR}/raw_candles.json") as f:
    raw = json.load(f)

print(f"Loaded {len(raw)} pairs")

master_trades = []
pair_stats    = {}

for symbol, candles in raw.items():
    trades = walk_forward_test(symbol, candles)
    print(f"[WF] {symbol}: {len(trades)} OOS trades")
    master_trades.extend(trades)
    if trades:
        pcts = [t["pnl_pct"] for t in trades]
        wins  = [t for t in trades if t["pnl_pct"] > 0]
        losss = [t for t in trades if t["pnl_pct"] <= 0]
        wr    = len(wins) / len(trades) * 100.0
        aw    = float(np.mean([t["pnl_pct"] for t in wins]))  if wins  else 0.0
        al    = float(np.mean([t["pnl_pct"] for t in losss])) if losss else 0.0
        pf    = (len(wins)*aw)/(len(losss)*abs(al)) if losss and al != 0 else 999.0
        pair_stats[symbol] = {
            "n_trades":       len(trades),
            "win_rate":       wr,
            "avg_win_pct":    aw,
            "avg_loss_pct":   al,
            "profit_factor":  pf,
            "total_pnl":      sum(t["pnl_usdt"] for t in trades),
            "avg_trades_day": len(trades) / (TEST_MONTHS * 30 * 3),  # ~hours/day
        }

os.makedirs(f"{DATA_DIR}/phases", exist_ok=True)
with open(f"{DATA_DIR}/phases/master_trades.json", "w") as f:
    json.dump(master_trades, f, indent=2)

with open(f"{DATA_DIR}/phases/pair_stats.json", "w") as f:
    json.dump(pair_stats, f, indent=2)

print(f"\n[DONE] {len(master_trades)} total OOS trades saved")
print("Phase 2 complete.")
