#!/usr/bin/env python3
"""
Phase 5: Position Sizing & Kelly Criterion
============================================
Calculate optimal Kelly fraction from OOS data.
Recommend fractional Kelly given £1,000 capital.
Risk of ruin analysis.
"""

import json
import numpy as np
from collections import defaultdict

DATA_DIR = "/root/trading_analysis"

def main():
    print("=" * 60)
    print("PHASE 5: POSITION SIZING & KELLY ANALYSIS")
    print("=" * 60)
    
    with open(f"{DATA_DIR}/phases/master_trade_log.json") as f:
        trades = json.load(f)
    with open(f"{DATA_DIR}/phases/pair_stats.json") as f:
        pair_stats = json.load(f)
    
    if not trades:
        print("[ERROR] No trades. Run phase2 first.")
        return
    
    # ─── Global win rate & avg win/loss ────────────────────────────────
    all_rets = [t["return_pct"] for t in trades]
    wins     = [r for r in all_rets if r > 0]
    losses   = [r for r in all_rets if r <= 0]
    
    win_rate = len(wins) / len(all_rets) if all_rets else 0
    avg_win  = np.mean(wins) / 100 if wins else 0
    avg_loss = abs(np.mean(losses)) / 100 if losses else 0
    
    # Full Kelly
    if avg_loss > 0:
        b = avg_win / avg_loss  # win/loss ratio
        q = 1 - win_rate
        full_kelly = (b * win_rate - q) / b
    else:
        full_kelly = 0
    
    print(f"\n[OOS Trade Statistics]")
    print(f"  Total trades:     {len(all_rets)}")
    print(f"  Win rate:         {win_rate*100:.1f}%")
    print(f"  Avg win:          {np.mean(wins):.3f}%" if wins else "  Avg win: N/A")
    print(f"  Avg loss:         {np.mean(losses):.3f}%" if losses else "  Avg loss: N/A")
    print(f"  Profit factor:    {sum(wins)/abs(sum(losses)):.2f}" if losses and sum(losses) != 0 else "  Profit factor: N/A")
    print(f"  Full Kelly:       {full_kelly*100:.2f}%")
    
    # ─── Per-pair Kelly ─────────────────────────────────────────────────
    print(f"\n[Per-Pair Kelly Analysis]")
    kelly_by_pair = {}
    for sym, stats in pair_stats.items():
        wr = stats["win_rate"] / 100
        aw = stats["avg_win_pct"] / 100
        al = abs(stats["avg_loss_pct"]) / 100
        if al > 0:
            b = aw / al
            fk = max(0, (b * wr - (1 - wr)) / b)
        else:
            fk = 0
        
        # Recommended: half-Kelly or quarter-Kelly
        half_k = fk * 0.5
        quarter_k = fk * 0.25
        
        kelly_by_pair[sym] = {
            "full_kelly": fk,
            "half_kelly": half_k,
            "quarter_kelly": quarter_k,
            "recommended": "half_Kelly" if fk > 0.1 else "quarter_Kelly",
            "wr": stats["win_rate"],
            "pf": stats["profit_factor"]
        }
        
        flag = "⚠️ NEGATIVE" if fk < 0 else "✅"
        print(f"  {flag} {sym:<10} WR:{stats['win_rate']:.0f}% PF:{stats['profit_factor']:.2f} "
              f"Kelly:{fk*100:.1f}% → half:{half_k*100:.1f}% quarter:{quarter_k*100:.1f}%")
    
    # ─── Kelly for blended portfolio ─────────────────────────────────────
    blended_kelly = full_kelly
    recommended_fraction = "half_Kelly"
    recommended_pct = blended_kelly * 0.5
    
    if recommended_pct > 0.15:
        recommended_pct = 0.10  # Cap at 10% per pair
        recommended_fraction = "capped_10%"
    
    # ─── Risk of Ruin Analysis ──────────────────────────────────────────
    print(f"\n[Risk of Ruin Simulation]")
    capital_gbp = 1000.0
    num_sims = 5000
    ruin_thresholds = [0.20, 0.30, 0.50]  # 20%, 30%, 50% loss
    
    for threshold in ruin_thresholds:
        ruin_count = 0
        for _ in range(num_sims):
            capital = capital_gbp
            peak = capital
            for _ in range(180):  # 6 months of daily trades
                if np.random.random() < win_rate:
                    ret = np.random.choice(wins) / 100
                else:
                    ret = np.random.choice(losses) / 100
                
                pos = capital * recommended_pct
                capital += pos * ret
                peak = max(peak, capital)
                
                if capital <= capital_gbp * (1 - threshold):
                    break
            
            if capital < capital_gbp * (1 - threshold):
                ruin_count += 1
        
        print(f"  Prob of >{threshold*100:.0f}% loss: {ruin_count/num_sims*100:.2f}%")
    
    # ─── Position sizing recommendation ────────────────────────────────
    print(f"\n[POSITION SIZING RECOMMENDATION]")
    print(f"  Starting capital:     £{capital_gbp:,.0f}")
    print(f"  Blended win rate:     {win_rate*100:.1f}%")
    print(f"  Blended Kelly:        {blended_kelly*100:.2f}%")
    print(f"  Recommended fraction: {recommended_fraction}")
    print(f"  Max position size:    {recommended_pct*100:.1f}% of portfolio per pair")
    print(f"  Max £ per trade:      £{capital_gbp * recommended_pct:,.2f}")
    
    # If risk of ruin > 10%, recommend reducing further
    ruin_30pct = sum(1 for _ in range(5000) for threshold in [0.30] 
                     if (lambda: (capital := capital_gbp, 
                                  [capital := capital + capital * recommended_pct * 
                                   (np.random.choice(wins)/100 if np.random.random() < win_rate 
                                    else np.random.choice(losses)/100) 
                                   for _ in range(180)], capital < capital_gbp * 0.7))()[-1]) / 5000
    
    result = {
        "global_win_rate": win_rate,
        "avg_win_pct": float(np.mean(wins)) if wins else 0,
        "avg_loss_pct": float(np.mean(losses)) if losses else 0,
        "full_kelly": float(blended_kelly),
        "recommended_fraction": recommended_fraction,
        "recommended_pct": float(recommended_pct),
        "kelly_by_pair": kelly_by_pair,
        "pair_stats": pair_stats
    }
    
    with open(f"{DATA_DIR}/phases/position_sizing.json", "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\n[DONE] Saved → {DATA_DIR}/phases/position_sizing.json")

if __name__ == "__main__":
    main()
