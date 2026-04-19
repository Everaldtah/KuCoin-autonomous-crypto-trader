#!/usr/bin/env python3
"""
Phase 4: Monte Carlo Simulation (FIXED)
=========================================
10,000 simulations of 6-month trading from £1,000.
Proper position sizing, trade-level resampling.
"""

import json
import random
import numpy as np
from collections import defaultdict

DATA_DIR = "/root/trading_analysis"
OUTPUT_FILE = f"{DATA_DIR}/phases/monte_carlo_results.json"
NUM_SIMS = 10_000

def load_data():
    with open(f"{DATA_DIR}/phases/master_trade_log.json") as f:
        trades = json.load(f)
    with open(f"{DATA_DIR}/phases/correlation_data.json") as f:
        corr_data = json.load(f)
    with open(f"{DATA_DIR}/phases/pair_stats.json") as f:
        pair_stats = json.load(f)
    return trades, corr_data, pair_stats

def estimate_strategy_params(trades):
    """Estimate win rate and avg win/loss from OOS trade log."""
    rets = [t["return_pct"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    n = len(rets)
    wr = len(wins) / n if n > 0 else 0.35
    avg_win = np.mean(wins) if wins else 1.0
    avg_loss = abs(np.mean(losses)) if losses else 1.0
    b = avg_win / avg_loss
    full_k = max(0, (b * wr - (1 - wr)) / b)
    return wr, avg_win, avg_loss, full_k

def run_single_sim(trades, clusters, initial_capital=1000.0, kelly_frac=0.10):
    """Run one 6-month simulation. Returns (final_capital, max_drawdown)."""
    num_trades_total = len(trades)
    num_windows = len(set(t["window_idx"] for t in trades))
    hours_per_window = 2 * 30 * 24
    total_hours = num_windows * hours_per_window
    days_total = total_hours / 24
    trades_per_day = num_trades_total / days_total

    capital = initial_capital
    peak = capital
    max_dd = 0.0

    num_sim_trades = int(trades_per_day * days_total)

    for _ in range(num_sim_trades):
        t = random.choice(trades)
        ret = t["return_pct"] / 100.0

        # Position sizing: kelly_frac of capital, clamped 5-15%
        pos_frac = max(0.05, min(0.15, kelly_frac))
        pos_dollars = capital * pos_frac
        pnl = pos_dollars * ret
        capital += pnl

        peak = max(peak, capital)
        dd = (peak - capital) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

        if capital < 50:
            break

    return capital, max_dd

def run_scenario(trades, clusters, scenario_name="BASE", drag=0.0, adverse=False, kelly_frac=0.10):
    print(f"\n  Running {scenario_name} ({NUM_SIMS:,} sims, Kelly={kelly_frac*100:.1f}%)...")

    capitals = []
    max_dds = []

    for i in range(NUM_SIMS):
        sim_trades = trades[:]

        if adverse:
            sim_trades = []
            for t in trades:
                t_copy = t.copy()
                if random.random() < 0.4:
                    t_copy["return_pct"] = -abs(t["return_pct"]) * 1.5
                sim_trades.append(t_copy)
        elif drag > 0:
            for t in sim_trades:
                t["return_pct"] *= (1 - drag)

        cap, dd = run_single_sim(sim_trades, clusters, kelly_frac=kelly_frac)
        capitals.append(cap)
        max_dds.append(dd)

        if (i + 1) % 2000 == 0:
            print(f"    {i+1:,} / {NUM_SIMS:,}")

    capitals_sorted = sorted(capitals)
    max_dds_sorted = sorted(max_dds)

    def pct(p):
        idx = int(p / 100 * len(capitals_sorted))
        idx = min(idx, len(capitals_sorted) - 1)
        return capitals_sorted[idx]

    def pct_dd(p):
        idx = int(p / 100 * len(max_dds_sorted))
        idx = min(idx, len(max_dds_sorted) - 1)
        return max_dds_sorted[idx]

    capital_table = {}
    for pkey, pval in [("p5", 5), ("p25", 25), ("p50", 50), ("p75", 75), ("p95", 95)]:
        cap = pct(pval)
        ret = (cap - 1000) / 1000 * 100
        capital_table[pkey] = {"capital": cap, "return_pct": ret}

    risk = {
        "prob_20_pct_drawdown": sum(1 for d in max_dds if d >= 20) / len(max_dds) * 100,
        "prob_30_pct_drawdown": sum(1 for d in max_dds if d >= 30) / len(max_dds) * 100,
        "prob_50_pct_drawdown": sum(1 for d in max_dds if d >= 50) / len(max_dds) * 100,
        "prob_50_pct_capital_loss": sum(1 for c in capitals if c < 500) / len(capitals) * 100,
        "median_max_drawdown": pct_dd(50),
        "p95_max_drawdown": pct_dd(95),
    }

    return {
        "scenario": scenario_name,
        "capital_table": capital_table,
        "risk_metrics": risk,
        "kelly_used": kelly_frac
    }

def main():
    print("=" * 60)
    print("PHASE 4: MONTE CARLO SIMULATION (FIXED)")
    print(f"Simulations: {NUM_SIMS:,} | Capital: £1,000 | Period: 6 months")
    print("=" * 60)

    trades, corr_data, pair_stats = load_data()
    clusters = corr_data.get("clusters", [])

    wr, avg_win, avg_loss, full_k = estimate_strategy_params(trades)
    print(f"\n[OOS Statistics]")
    print(f"  Trades: {len(trades)}")
    print(f"  Win rate: {wr*100:.1f}%")
    print(f"  Avg win: {avg_win:.3f}%")
    print(f"  Avg loss: {avg_loss:.3f}%")
    print(f"  Full Kelly: {full_k*100:.2f}%")

    Kelly = max(0.05, min(0.15, full_k * 0.25))
    print(f"  Using Kelly: {Kelly*100:.2f}% per trade")

    base = run_scenario(trades, clusters, "BASE", kelly_frac=Kelly)
    conservative = run_scenario(trades, clusters, "CONSERVATIVE", drag=0.30, kelly_frac=Kelly)
    adverse = run_scenario(trades, clusters, "ADVERSE", adverse=True, kelly_frac=Kelly)

    results = {
        "num_sims": NUM_SIMS,
        "initial_capital_gbp": 1000.0,
        "kelly_estimate": full_k,
        "kelly_used": Kelly,
        "win_rate": wr,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "scenarios": {"base": base, "conservative": conservative, "adverse": adverse}
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 70)
    print("MONTE CARLO RESULTS (£1,000 starting capital)")
    print("=" * 70)

    for scenario_name, scenario in results["scenarios"].items():
        kelly = scenario.get("kelly_used", Kelly)
        print(f"\n{'─' * 60}")
        print(f"  {scenario_name.upper()} SCENARIO (Kelly={kelly*100:.1f}%/trade)")
        print(f"{'─' * 60}")
        print(f"  {'Percentile':<22} {'1 Month':>15} {'3 Months':>15} {'6 Months':>15}")
        print(f"  {'─'*22} {'─'*15} {'─'*15} {'─'*15}")

        pct_labels = {
            "p5": "5th (low-end)",
            "p25": "25th",
            "p50": "50th (median/average)",
            "p75": "75th",
            "p95": "95th (high-end)"
        }

        for pkey, label in pct_labels.items():
            pdata = scenario["capital_table"][pkey]
            ret = pdata["return_pct"]
            m1 = 1000 * (1 + ret / 100 / 6)
            m3 = 1000 * (1 + ret / 100 / 2)
            m6 = pdata["capital"]
            print(f"  {label:<22} £{m1:>13,.2f} £{m3:>13,.2f} £{m6:>13,.2f}")

        r = scenario["risk_metrics"]
        print(f"\n  Risk Metrics:")
        print(f"    Prob ≥20% drawdown:     {r['prob_20_pct_drawdown']:.1f}%")
        print(f"    Prob ≥30% drawdown:     {r['prob_30_pct_drawdown']:.1f}%")
        print(f"    Prob ≥50% drawdown:     {r['prob_50_pct_drawdown']:.1f}%")
        print(f"    Prob losing >50%:       {r['prob_50_pct_capital_loss']:.1f}%")
        print(f"    Median max drawdown:     {r['median_max_drawdown']:.1f}%")
        print(f"    95th pct max drawdown:  {r['p95_max_drawdown']:.1f}%")

    print(f"\n[DONE] Full results → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
