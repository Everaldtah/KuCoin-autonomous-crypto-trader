#!/usr/bin/env python3
import json, random, math
import numpy as np
from collections import defaultdict

DATA_DIR = '/root/trading_analysis'
OUTPUT_FILE = f'{DATA_DIR}/phases/monte_carlo_results.json'
NUM_SIMS = 10_000

def load_data():
    with open(f'{DATA_DIR}/phases/master_trade_log.json') as f:
        trades = json.load(f)
    with open(f'{DATA_DIR}/phases/correlation_data.json') as f:
        corr_data = json.load(f)
    with open(f'{DATA_DIR}/phases/pair_stats.json') as f:
        pair_stats = json.load(f)
    return trades, corr_data, pair_stats

def run_single_sim(trades, clusters, capital=1000.0, sim_trades=None):
    if sim_trades is None:
        sim_trades = trades

    # Build indexed trades per window for block resampling
    by_window = defaultdict(list)
    for t in sim_trades:
        by_window[t['window_idx']].append(t)

    window_keys = list(by_window.keys())
    total_trades = len(sim_trades)
    n_windows = len(window_keys)

    # Estimate trades per simulation run
    # 1136 (win0) + 902 (win1) + 895 (win2) = 2933 trades over ~6 months (3 x 2-month windows)
    # = ~977 trades per 2-month window = ~16.3 trades/day
    trades_per_day = total_trades / (n_windows * 60)  # 60 days per 2-month window
    trades_per_sim = int(trades_per_day * 180)  # 180 days = 6 months

    capital = float(capital)
    peak = capital
    max_dd = 0.0

    for _ in range(trades_per_sim):
        # Pick random window
        win = random.choice(window_keys)
        win_trades = by_window[win]
        if not win_trades:
            continue

        # Pick random trade from that window
        t = random.choice(win_trades)

        # Find correlated cluster
        sym = t['symbol']
        cluster = None
        for c in clusters:
            if sym in c:
                cluster = c
                break
        if cluster is None:
            cluster = [sym]

        # Apply trade to correlated pairs (block resampling)
        cluster_trades = [x for x in win_trades if x['symbol'] in cluster]
        if cluster_trades:
            # Resample one correlated trade per pair in cluster (up to 3 max)
            for ct in cluster_trades[:3]:
                ret_pct = ct['return_pct']
                ret = ret_pct / 100.0

                # Position sizing: volatility-adjusted Kelly fraction
                # Use 8% of capital per trade (half-Kelly approximation)
                # Cap at 15% max as per bot config
                pos_pct = min(0.15, 0.08)
                pnl = capital * pos_pct * ret
                capital += pnl

                peak = max(peak, capital)
                dd = (peak - capital) / peak * 100
                max_dd = max(max_dd, dd)

                # Hard stop: if capital drops 50%, stop trading
                if capital < 500:
                    return capital, max_dd

    return capital, max_dd

def run_scenario(trades, clusters, scenario_name, drag=0.0, adverse=False, num_sims=NUM_SIMS):
    print(f'  Running {scenario_name} scenario ({num_sims:,} sims)...')

    capitals = []
    max_dds = []

    for i in range(num_sims):
        sim_trades = []
        for t in trades:
            t_copy = t.copy()
            ret = t_copy['return_pct']

            if adverse:
                # Convert non-losses to small losses, inflate existing losses
                if ret > 0:
                    ret = random.uniform(-0.5, 0.0)  # winning trades become small losses
                else:
                    ret = ret * random.uniform(1.5, 2.0)  # losses become 1.5-2x bigger
            elif drag > 0:
                ret *= (1.0 - drag)

            t_copy['return_pct'] = ret
            sim_trades.append(t_copy)

        cap, dd = run_single_sim(trades, clusters, capital=1000.0, sim_trades=sim_trades)
        capitals.append(cap)
        max_dds.append(dd)

        if (i + 1) % 2000 == 0:
            print(f'    {i+1:,} / {num_sims:,}')

    return capitals, max_dds

def summarize(capitals, max_dds, starting=1000.0):
    cap_sorted = sorted(capitals)
    dd_sorted = sorted(max_dds)

    def pct(p):
        idx = min(int(p / 100 * len(cap_sorted)), len(cap_sorted) - 1)
        return cap_sorted[idx]

    p5  = pct(5)
    p25 = pct(25)
    p50 = pct(50)
    p75 = pct(75)
    p95 = pct(95)

    # Monthly scaling
    results = {}
    for label, val in [('5th', p5), ('25th', p25), ('50th (median)', p50), ('75th', p75), ('95th', p95)]:
        ret = (val - starting) / starting
        m1  = starting * (1 + ret / 6)
        m3  = starting * (1 + ret / 2)
        m6  = val
        results[label] = {
            'GBP_1m': round(m1, 2),
            'GBP_3m': round(m3, 2),
            'GBP_6m': round(m6, 2),
            'ret_pct_6m': round(ret * 100, 2)
        }

    risk = {
        'prob_20pct_drawdown': round(sum(1 for d in max_dds if d >= 20) / len(max_dds) * 100, 2),
        'prob_30pct_drawdown': round(sum(1 for d in max_dds if d >= 30) / len(max_dds) * 100, 2),
        'prob_50pct_drawdown': round(sum(1 for d in max_dds if d >= 50) / len(max_dds) * 100, 2),
        'prob_lose_50pct_capital': round(sum(1 for c in capitals if c < 500) / len(capitals) * 100, 2),
        'median_max_drawdown': round(np.median(max_dds), 2),
        'p95_max_drawdown': round(np.percentile(max_dds, 95), 2),
    }

    return results, risk

def main():
    print('=' * 60)
    print('PHASE 4 (FIXED): MONTE CARLO SIMULATION')
    print(f'Sims: {NUM_SIMS:,} | Capital: £1000 | Period: 6 months')
    print('=' * 60)

    trades, corr_data, pair_stats = load_data()
    clusters = corr_data.get('clusters', [])
    print(f'[Data] {len(trades)} OOS trades, {len(clusters)} correlation clusters')
    print(f'[Clusters] {clusters}')

    # Base scenario
    base_caps, base_dds = run_scenario(trades, clusters, 'BASE')
    base_res, base_risk = summarize(base_caps, base_dds)

    # Conservative: 30% drag on returns
    cons_caps, cons_dds = run_scenario(trades, clusters, 'CONSERVATIVE', drag=0.30)
    cons_res, cons_risk = summarize(cons_caps, cons_dds)

    # Adverse: oversample losses
    adv_caps, adv_dds = run_scenario(trades, clusters, 'ADVERSE', adverse=True)
    adv_res, adv_risk = summarize(adv_caps, adv_dds)

    results = {
        'base': {'projection_table': base_res, 'risk_metrics': base_risk},
        'conservative': {'projection_table': cons_res, 'risk_metrics': cons_risk},
        'adverse': {'projection_table': adv_res, 'risk_metrics': adv_risk},
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    # Print summary
    print('\n' + '=' * 70)
    print('MONTHLY PROJECTION TABLES (£1,000 starting capital)')
    print('=' * 70)

    for scenario_name, data in results.items():
        res = data['projection_table']
        risk = data['risk_metrics']
        sep = '─' * 60
        print(f'\n{sep}')
        print(f'  {scenario_name.upper()} SCENARIO')
        print(f'{sep}')
        hdr = '  {:<22} {:>12} {:>12} {:>12}'.format("Percentile", "1 Month", "3 Months", "6 Months")
        print(hdr)
        print(f'  {"─"*22} {"─"*12} {"─"*12} {"─"*12}')

        labels = [('5th (low-end)', '5th'), ('25th', '25th'), ('50th (median)', '50th (median)'), ('75th', '75th'), ('95th (high-end)', '95th')]

        for label, key in labels:
            m1 = res[key]['GBP_1m']
            m3 = res[key]['GBP_3m']
            m6 = res[key]['GBP_6m']
            ret = res[key]['ret_pct_6m']
            print(f'  {label:<22} £{m1:>10,.2f} £{m3:>10,.2f} £{m6:>10,.2f}  ({ret:+.1f}%)')

        print(f'\n  Risk Metrics:')
        print(f'    Prob ≥20% drawdown:     {risk["prob_20pct_drawdown"]:.1f}%')
        print(f'    Prob ≥30% drawdown:     {risk["prob_30pct_drawdown"]:.1f}%')
        print(f'    Prob ≥50% drawdown:     {risk["prob_50pct_drawdown"]:.1f}%')
        print(f'    Prob losing >50%:       {risk["prob_lose_50pct_capital"]:.1f}%')
        print(f'    Median max drawdown:    {risk["median_max_drawdown"]:.1f}%')
        print(f'    95th pct max drawdown:  {risk["p95_max_drawdown"]:.1f}%')

    print(f'\n[DONE] Full results → {OUTPUT_FILE}')

if __name__ == '__main__':
    main()