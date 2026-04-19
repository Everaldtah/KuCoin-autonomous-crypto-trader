#!/usr/bin/env python3
"""
Phase 3: Correlation Analysis
===============================
Calculate pairwise return correlations between traded pairs.
Cluster by correlation for Monte Carlo block resampling.
"""

import json
import numpy as np
from collections import defaultdict

DATA_DIR = "/root/trading_analysis"
OUTPUT_FILE = f"{DATA_DIR}/phases/correlation_data.json"

def main():
    print("=" * 60)
    print("PHASE 3: CORRELATION ANALYSIS")
    print("=" * 60)
    
    # Load master trade log
    with open(f"{DATA_DIR}/phases/master_trade_log.json") as f:
        trades = json.load(f)
    
    if not trades:
        print("[ERROR] No trades found. Run phase2 first.")
        return
    
    # Build return series per pair per window
    pair_window_returns = defaultdict(lambda: defaultdict(list))
    
    for t in trades:
        sym = t["symbol"]
        win = t["window_idx"]
        pair_window_returns[sym][win].append(t["return_pct"])
    
    # Average return per pair per window
    pair_avg_returns = {}
    for sym, windows in pair_window_returns.items():
        pair_avg_returns[sym] = {}
        for win, rets in windows.items():
            pair_avg_returns[sym][win] = np.mean(rets)
    
    symbols = list(pair_avg_returns.keys())
    windows = sorted(set(w for sym_d in pair_avg_returns.values() for w in sym_d.keys()))
    
    print(f"\n[Pairs] {symbols}")
    print(f"[Windows] {len(windows)} test windows")
    
    # Pairwise correlation matrix
    n = len(symbols)
    corr_matrix = np.eye(n)
    
    for i, sym_i in enumerate(symbols):
        for j, sym_j in enumerate(symbols):
            if i >= j:
                continue
            
            # Align by window
            rets_i = [pair_avg_returns[sym_i].get(w, 0) for w in windows]
            rets_j = [pair_avg_returns[sym_j].get(w, 0) for w in windows]
            
            corr = np.corrcoef(rets_i, rets_j)[0, 1]
            if np.isnan(corr):
                corr = 0.0
            
            corr_matrix[i, j] = corr
            corr_matrix[j, i] = corr
    
    # Cluster pairs by correlation (> 0.6 = correlated)
    clusters = []
    assigned = set()
    
    for i, sym_i in enumerate(symbols):
        if sym_i in assigned:
            continue
        cluster = [sym_i]
        for j, sym_j in enumerate(symbols):
            if i != j and corr_matrix[i, j] > 0.6:
                cluster.append(sym_j)
                assigned.add(sym_j)
        assigned.add(sym_i)
        clusters.append(cluster)
    
    # Summary
    print("\n[CORRELATION MATRIX]")
    header = f"{'Symbol':<12}" + "".join([f"{s[:6]:>8}" for s in symbols])
    print(header)
    for i, sym in enumerate(symbols):
        row = f"{sym:<12}" + "".join([f"{corr_matrix[i,j]:>8.3f}" for j in range(n)])
        print(row)
    
    print(f"\n[CORRELATION CLUSTERS] (threshold > 0.6)")
    for idx, cluster in enumerate(clusters):
        print(f"  Cluster {idx+1}: {cluster}")
    
    # Save
    result = {
        "symbols": symbols,
        "windows": windows,
        "corr_matrix": corr_matrix.tolist(),
        "clusters": clusters,
        "pair_avg_returns": {sym: {str(w): v for w, v in wins.items()} 
                            for sym, wins in pair_avg_returns.items()}
    }
    
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\n[DONE] Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
