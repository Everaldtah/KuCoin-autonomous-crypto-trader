#!/usr/bin/env python3
"""
Phase 5: Sensitivity Analysis & Phase 6: Position Sizing
=========================================================
Combines Phase 5 (sensitivity) already done in Phase 4 scenarios,
with Phase 6 Kelly Criterion analysis and final recommendations.
"""

import json, math, os
import numpy as np
from collections import defaultdict

DATA_DIR = "/root/trading_analysis"

def main():
    print("=" * 60)
    print("PHASE 5 & 6: SENSITIVITY + POSITION SIZING")
    print("=" * 60)

    with open(f"{DATA_DIR}/phases/master_trade_log.json") as f:
        trades = json.load(f)
    with open(f"{DATA_DIR}/phases/pair_stats.json") as f:
        pair_stats = json.load(f)
    with open(f"{DATA_DIR}/phases/correlation_data.json") as f:
        corr_data = json.load(f)
    with open(f"{DATA_DIR}/phases/monte_carlo_results.json") as f:
        mc_results = json.load(f)

    INITIAL_CAPITAL_GBP = 1000.0

    # ─── Phase 6: Kelly Criterion ─────────────────────────────
    print("\n[PHASE 6] Kelly Criterion Analysis")
    print("-" * 50)

    kelly_by_pair = {}
    for sym, stats in pair_stats.items():
        wr = stats["win_rate"] / 100
        avg_win = stats["avg_win_pct"] / 100
        avg_loss = abs(stats["avg_loss_pct"]) / 100

        if avg_loss > 0:
            b = avg_win / avg_loss
            q = 1 - wr
            full_kelly = (b * wr - q) / b if b > 0 else 0
            half_kelly = full_kelly / 2
            quarter_kelly = full_kelly / 4
        else:
            full_kelly = half_kelly = quarter_kelly = 0

        kelly_by_pair[sym] = {
            "win_rate": wr,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "reward_risk_ratio": b if avg_loss > 0 else 0,
            "full_kelly_pct": max(0, full_kelly * 100),
            "half_kelly_pct": max(0, half_kelly * 100),
            "quarter_kelly_pct": max(0, quarter_kelly * 100),
        }

    print("\nPer-Pair Kelly Criterion:")
    print(f"  {'Pair':<12} {'Win%':>7} {'AvgWin':>8} {'AvgLoss':>8} {'R:R':>6} {'FullK%':>8} {'HalfK%':>8} {'QtrK%':>8}")
    print(f"  {'─'*68}")
    for sym, k in sorted(kelly_by_pair.items(), key=lambda x: -x[1]["win_rate"]):
        print(f"  {sym:<12} {k['win_rate']*100:>6.1f}% {k['avg_win']*100:>7.2f}% {k['avg_loss']*100:>7.2f}% {k['reward_risk_ratio']:>6.2f} {k['full_kelly_pct']:>7.1f}% {k['half_kelly_pct']:>7.1f}% {k['quarter_kelly_pct']:>7.1f}%")

    all_returns = [t["return_pct"] / 100 for t in trades]
    wins = [r for r in all_returns if r > 0]
    losses = [r for r in all_returns if r <= 0]
    wr_blended = len(wins) / len(all_returns)
    avg_win_blended = np.mean(wins) if wins else 0
    avg_loss_blended = abs(np.mean(losses)) if losses else 0

    if avg_loss_blended > 0:
        b_blended = avg_win_blended / avg_loss_blended
        q_blended = 1 - wr_blended
        full_k_blended = (b_blended * wr_blended - q_blended) / b_blended if b_blended > 0 else 0
    else:
        full_k_blended = 0

    half_k_blended = max(0, full_k_blended / 2)
    quarter_k_blended = max(0, full_k_blended / 4)

    print(f"\n  Blended Kelly (all pairs):")
    print(f"    Win rate:     {wr_blended*100:.1f}%")
    print(f"    Avg win:      {avg_win_blended*100:.2f}%")
    print(f"    Avg loss:     {avg_loss_blended*100:.2f}%")
    print(f"    Reward:Risk:  {b_blended:.3f}")
    print(f"    Full Kelly:   {full_k_blended*100:.1f}%  ← CANCEL (too aggressive)")
    print(f"    Half Kelly:   {half_k_blended*100:.1f}%  ← Recommended starting point")
    print(f"    Quarter Kelly:{quarter_k_blended*100:.1f}% ← Conservative / low capital")

    # ─── Phase 5: Sensitivity Summary ──────────────────────────
    print("\n[PHASE 5] Sensitivity Analysis Summary")
    print("-" * 50)

    for scenario, label in [("base", "Base Case"), ("conservative", "Conservative (30% drag)"), ("adverse", "Adverse (loss oversample)")]:
        r = mc_results[scenario]
        p = r["percentiles_GBP"]
        print(f"\n  {label}:")
        print(f"    6-month median: £{p['50th']:,.0f} ({r['percentiles_pct']['50th']:+.1f}%)")
        print(f"    6-month 5th pct: £{p['5th']:,.0f} ({r['percentiles_pct']['5th']:+.1f}%)")
        print(f"    6-month 95th pct: £{p['95th']:,.0f} ({r['percentiles_pct']['95th']:+.1f}%)")
        print(f"    Risk of ruin: {r['risk_of_ruin']:.1f}%")
        print(f"    Prob 30%+ drawdown: {r['prob_30pct_drawdown']:.1f}%")

    # ─── Risk Assessment ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("RISK ASSESSMENT FLAGS")
    print("=" * 60)

    base = mc_results["base"]
    conservative = mc_results["conservative"]

    flags = []

    negative_pairs = [sym for sym, s in pair_stats.items() if s["profit_factor"] < 1.0]
    if negative_pairs:
        flags.append(f"NEGATIVE EXPECTED VALUE: {len(negative_pairs)} pairs have PF < 1.0: {', '.join(negative_pairs)}")

    if base["risk_of_ruin"] > 10:
        flags.append(f"HIGH RISK OF RUIN: {base['risk_of_ruin']:.1f}% (threshold: 10%)")

    if base["prob_30pct_drawdown"] > 20:
        flags.append(f"HIGH DRAWDOWN RISK: {base['prob_30pct_drawdown']:.1f}% probability of 30%+ drawdown")

    if conservative["percentiles_GBP"]["50th"] < INITIAL_CAPITAL_GBP:
        flags.append(f"NEGATIVE BASE-CASE EDGE: Median 6-month return is £{conservative['percentiles_GBP']['50th'] - INITIAL_CAPITAL_GBP:.0f} (loss)")

    win_rates = [s["win_rate"] for s in pair_stats.values()]
    if all(wr < 40 for wr in win_rates):
        flags.append("LOW WIN RATES: All pairs WR < 40% — strategy relies on R:R > 1.0 to be profitable")

    clusters = corr_data.get("clusters", [])
    large_clusters = [c for c in clusters if len(c) >= 4]
    if large_clusters:
        flags.append(f"CORRELATION CLUSTER RISK: {len(large_clusters)} clusters with 4+ pairs — diversification is limited")

    if flags:
        print("\n  FLAGS (issues requiring attention before deployment):")
        for i, flag in enumerate(flags, 1):
            print(f"  {i}. {flag}")
    else:
        print("\n  No critical flags")

    # ─── Save comprehensive results ─────────────────────────
    results = {
        "kelly_analysis": {
            "by_pair": kelly_by_pair,
            "blended": {
                "win_rate": wr_blended,
                "avg_win": avg_win_blended,
                "avg_loss": avg_loss_blended,
                "reward_risk_ratio": b_blended,
                "full_kelly_pct": full_k_blended * 100,
                "half_kelly_pct": half_k_blended * 100,
                "quarter_kelly_pct": quarter_k_blended * 100,
            }
        },
        "flags": flags,
        "pair_stats": pair_stats,
    }

    os.makedirs(f"{DATA_DIR}/phases", exist_ok=True)
    with open(f"{DATA_DIR}/phases/phases_5_6_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n[DONE] Saved to {DATA_DIR}/phases/phases_5_6_results.json")

if __name__ == "__main__":
    main()
