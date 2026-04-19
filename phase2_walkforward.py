#!/usr/bin/env python3
import json, os, pickle, numpy as np
from typing import Dict, List, Tuple, Any
from collections import defaultdict

class TI:
    @staticmethod
    def rsi(c, p=14):
        if len(c) < p+1: return np.full(len(c), 50.0)
        d = np.diff(c); g = np.where(d>0, d, 0); l = np.where(d<0, -d, 0)
        ag = np.convolve(g, np.ones(p)/p, mode='valid'); al = np.convolve(l, np.ones(p)/p, mode='valid')
        rs = ag/(al+1e-10); rsi = 100-(100/(1+rs))
        return np.concatenate([np.full(p, 50.0), rsi])[:len(c)]

    @staticmethod
    def ema(c, p):
        if len(c) < p: return np.full(len(c), c[0])
        e = np.zeros(len(c)); e[:p] = c[:p].mean(); m = 2/(p+1)
        for i in range(p, len(c)): e[i] = (c[i]-e[i-1])*m + e[i-1]
        return e

    @staticmethod
    def macd(c, f=12, s=26, sig=9):
        ef = TI.ema(c, f); es = TI.ema(c, s); ml = ef-es; sl = TI.ema(ml, sig); hist = ml-sl
        return ml, sl, hist

    @staticmethod
    def bb(c, p=20, sd=2.0):
        if len(c) < p: m = np.full(len(c), c.mean()); return m, m, m
        mid = np.convolve(c, np.ones(p)/p, mode='valid')
        std = np.array([c[max(0,i-p+1):i+1].std() for i in range(p-1, len(c))])
        u = np.concatenate([np.full(p-1, mid[0]), mid+sd*std])
        m = np.concatenate([np.full(p-1, mid[0]), mid])
        l = np.concatenate([np.full(p-1, mid[0]), mid-sd*std])
        return u[:len(c)], m[:len(c)], l[:len(c)]

    @staticmethod
    def atr(h, l, c, p=14):
        if len(c) < 2: return np.zeros(len(c))
        tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
        a = np.zeros(len(c)); a[p] = tr[:p].mean()
        for i in range(p+1, len(c)): a[i] = (a[i-1]*(p-1)+tr[i-1])/p
        a[:p] = a[p]; return a

    @staticmethod
    def st(h, l, c, p=10, m=3):
        a = TI.atr(h, l, c, p); hl = (h+l)/2
        ub = hl+m*a; lb = hl-m*a; d = np.zeros(len(c))
        for i in range(1, len(c)):
            d[i] = 1 if c[i]>ub[i-1] else (-1 if c[i]<lb[i-1] else d[i-1])
        return d

    @staticmethod
    def adx(h, l, c, p=14):
        if len(c) < p*2: return np.full(len(c), 25.0)
        tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
        pdm = np.maximum(h[1:]-h[:-1], 0); mdm = np.maximum(l[:-1]-l[1:], 0)
        pdm = np.where((pdm>mdm)&(pdm>0), pdm, 0); mdm = np.where((mdm>pdm)&(mdm>0), mdm, 0)
        a = np.zeros(len(c)); a[p*2] = 25.0
        for i in range(p*2, len(c)):
            av = tr[i-p:i].mean() if tr[i-p:i].sum()>0 else 1
            di = 100*pdm[i-p:i].mean()/av; di_n = 100*mdm[i-p:i].mean()/av
            dx = 100*abs(di-di_n)/(di+di_n+1e-10)
            a[i] = a[i-1]*0.9+dx*0.1
        a[:p*2] = a[p*2]; return a

class SignalGen:
    def __init__(self, bt=0.55, st=0.35, w=None):
        self.bt = bt; self.st = st; self.w = w or {
            \"rsi\":0.20,\"ema\":0.20,\"mfi\":0.15,\"macd\":0.15,\"bb\":0.15,\"st\":0.10,\"adx\":0.05}

    def composite(self, ind):
        s = {}
        rsi = ind.get(\"rsi\", 50)
        s[\"rsi\"] = 1.0 if rsi<30 else (0.0 if rsi>70 else (70-rsi)/40)
        s[\"ema\"] = 1.0 if ind.get(\"ema_signal\",0.5)==1 else 0.0
        mfi = ind.get(\"mfi\", 50)
        s[\"mfi\"] = 1.0 if mfi<20 else (0.0 if mfi>80 else (80-mfi)/60)
        mh = ind.get(\"hist\", 0); mm = 0.05*ind.get(\"bb_m\", ind.get(\"rsi\",1))
        s[\"macd\"] = min(1.0, max(0.0, (mh+mm)/(2*mm+1e-10)))
        bb = ind.get(\"bb_pct\", 50)
        s[\"bb\"] = 1.0 if bb<10 else (0.0 if bb>90 else (50-abs(bb-50))/50)
        stv = ind.get(\"st\", 0)
        s[\"st\"] = 1.0 if stv>0 else (0.0 if stv<0 else 0.5)
        adx = min(1.0, ind.get(\"adx\",25)/50)
        tw = sum(self.w.get(k,0.15) for k in s)
        ws = sum(s.get(k,0.5)*self.w.get(k,0.15) for k in s)
        comp = ws/tw if tw>0 else 0.5
        if comp > 0.6: comp = min(1.0, comp*(0.7+0.3*adx))
        elif comp < 0.4: comp = max(0.0, comp*(1.3-0.3*adx))
        return comp, s

    def compute_all(self, o):
        c, h, l, v = o[\"c\"], o[\"h\"], o[\"l\"], o[\"v\"]
        ef = TI.ema(c,12); es = TI.ema(c,26); ml,sl,hist = TI.macd(c)
        bu,bm,bl = TI.bb(c); bbp = np.where(bu!=bl, (c-bl)/(bu-bl)*100, 50.0)
        return {
            \"rsi\": TI.rsi(c), \"ema_f\": ef, \"ema_s\": es, \"ema_sig\": (ef>es).astype(float),
            \"macd_ml\": ml, \"macd_sl\": sl, \"hist\": hist, \"bu\": bu, \"bm\": bm, \"bl\": bl,
            \"bb_pct\": bbp, \"atr\": TI.atr(h,l,c), \"st\": TI.st(h,l,c), \"adx\": TI.adx(h,l,c)}

    def signals(self, o):
        ind = self.compute_all(o); n = len(o[\"c\"])
        comp = np.zeros(n); sig = np.zeros(n)
        for i in range(n):
            d = {k:(v[i] if isinstance(v,np.ndarray) else v) for k,v in ind.items()}
            cm, _ = self.composite(d); comp[i] = cm
            sig[i] = 1 if cm>=self.bt else (-1 if cm<=self.st else 0)
        return {\"comp\": comp, \"sig\": sig, \"ind\": ind}

class WFB:
    def __init__(self, train_days=180, test_days=60, step_days=60, maker=0.001, taker=0.001):
        self.train_days = train_days; self.test_days = test_days; self.step_days = step_days
        self.maker = maker; self.taker = taker

    def run(self, o, pair, capital=1000.0):
        n = len(o)
        if n < 200: return {\"error\": f\"Only {n} bars\"}
        ts = o[\"t\"]; c = o[\"c\"]
        total_days = (ts[-1]-ts[0])/(1000*60*60*24)
        if total_days < 200: return {\"error\": f\"Only {total_days:.0f} days\"}
        
        # Walk-forward windows
        bar_per_day = 24
        train_bars = int(self.train_days * bar_per_day)
        test_bars = int(self.test_days * bar_per_day)
        step_bars = int(self.step_days * bar_per_day)
        
        start_test = train_bars
        windows = []
        while start_test + test_bars <= n:
            windows.append((start_test, start_test + test_bars))
            start_test += step_bars
        
        if not windows: return {\"error\": \"No valid windows\"}
        
        sg = SignalGen()
        all_trades = []
        
        for w_idx, (start, end) in enumerate(windows):
            test_data = o[start:end]
            test_c = test_data[\"c\"]
            
            capital_ = capital; trades = []
            in_pos = False; entry_p = 0.0; entry_i = 0
            
            for i in range(len(test_c)):
                bar = np.array([(test_data[\"t\"][i], test_data[\"o\"][i], test_data[\"h\"][i],
                                 test_data[\"l\"][i], test_data[\"c\"][i], test_data[\"v\"][i])],
                               dtype=[(\"t\",\"i8\"),(\"o\",\"f8\"),(\"h\",\"f8\"),(\"l\",\"f8\"),(\"c\",\"f8\"),(\"v\",\"f8\")])
                sig_data = sg.signals(bar)
                sig = sig_data[\"sig\"][0]; comp = sig_data[\"comp\"][0]
                
                if not in_pos:
                    if sig == 1:
                        price = test_c[i] * 1.0005  # small slippage
                        fee = price * self.taker
                        in_pos = True; entry_p = price; entry_i = i
                else:
                    pnl_pct = (test_c[i] - entry_p) / entry_p * 100
                    exit_sig = sig == -1
                    tp_hit = pnl_pct >= 3.0
                    sl_hit = pnl_pct <= -1.5
                    
                    if exit_sig or tp_hit or sl_hit:
                        price = test_c[i] * 0.9995
                        fee = price * self.taker
                        net_pnl = pnl_pct - 2*(fee/entry_p*100)
                        trades.append({
                            \"pair\": pair, \"entry\": entry_p, \"exit\": price,
                            \"pnl_pct\": net_pnl, \"duration\": i - entry_i,
                            \"exit_reason\": \"signal\" if exit_sig else (\"tp\" if tp_hit else \"sl\"),
                            \"comp\": comp, \"window\": w_idx})
                        capital_ *= (1 + net_pnl/100)
                        in_pos = False
            
            all_trades.extend(trades)
        
        if not all_trades: return {\"pair\": pair, \"trades\": [], \"metrics\": {\"win_rate\": 0, \"profit_factor\": 0}}
        
        wins = [t for t in all_trades if t[\"pnl_pct\"] > 0]
        losses = [t for t in all_trades if t[\"pnl_pct\"] <= 0]
        gross_wins = sum(t[\"pnl_pct\"] for t in wins)
        gross_losses = abs(sum(t[\"pnl_pct\"] for t in losses))
        
        returns = [t[\"pnl_pct\"] for t in all_trades]
        peak = capital; equity = capital; max_dd = 0
        for t in returns:
            equity *= (1 + t/100)
            peak = max(peak, equity); dd = (peak-equity)/peak*100
            max_dd = max(max_dd, dd)
        
        return {
            \"pair\": pair, \"windows\": len(windows), \"n_trades\": len(all_trades), \"trades\": all_trades,
            \"metrics\": {
                \"win_rate\": len(wins)/len(all_trades)*100,
                \"avg_win\": np.mean([t[\"pnl_pct\"] for t in wins]) if wins else 0,
                \"avg_loss\": np.mean([t[\"pnl_pct\"] for t in losses]) if losses else 0,
                \"profit_factor\": gross_wins/gross_losses if gross_losses > 0 else float('inf'),
                \"avg_trades_per_day\": len(all_trades)/(len(windows)*self.test_days),
                \"max_consecutive_losses\": self._max_consec(all_trades),
                \"max_drawdown\": max_dd,
                \"total_return\": (capital_-capital)/capital*100}}

    def _max_consec(self, trades):
        if not trades: return 0
        max_c = cur_c = 1 if trades[0][\"pnl_pct\"] < 0 else 0
        for t in trades[1:]:
            if t[\"pnl_pct\"] < 0: cur_c += 1
            else: cur_c = 0
            max_c = max(max_c, cur_c)
        return max_c

def run_all():
    print(\"Loading Phase 1 data...\")
    try:
        with open(\"/root/trading_analysis/phase1_data.pkl\",\"rb\") as f:
            data = pickle.load(f)
    except Exception as e:
        print(f\"Error loading: {e}\")
        return
    
    wfb = WFB(); results = {}
    
    for pair, pd in data[\"pairs\"].items():
        print(f\"  Backtesting {pair}...\", end=\" \", flush=True)
        try:
            o = pd[\"ohlcv\"]
            r = wfb.run(o, pair)
            results[pair] = r
            if \"error\" not in r:
                m = r[\"metrics\"]
                print(f\"{r['n_trades']} trades | Win: {m['win_rate']:.1f}% | PF: {m['profit_factor']:.2f} | DD: {m['max_drawdown']:.1f}%\")
            else:
                print(f\"ERROR: {r['error']}\")
        except Exception as e:
            results[pair] = {\"error\": str(e)}
            print(f\"ERROR: {e}\")
    
    with open(\"/root/trading_analysis/phase2_results.pkl\",\"wb\") as f:
        pickle.dump(results, f)
    
    summary = {}
    for pair, r in results.items():
        if \"error\" in r:
            summary[pair] = {\"error\": r[\"error\"]}
        else:
            m = r[\"metrics\"]
            summary[pair] = {\"n_trades\": r[\"n_trades\"], \"windows\": r[\"windows\"],
                \"win_rate\": round(m[\"win_rate\"],2), \"avg_win\": round(m[\"avg_win\"],4),
                \"avg_loss\": round(m[\"avg_loss\"],4), \"pf\": round(m[\"profit_factor\"],4),
                \"max_dd\": round(m[\"max_drawdown\"],2), \"total_ret\": round(m[\"total_return\"],2)}
    
    with open(\"/root/trading_analysis/phase2_summary.json\",\"w\") as f:
        json.dump(summary, f, indent=2)
    
    # Master trade log
    all_t = []
    for r in results.values():
        if \"error\" not in r:
            all_t.extend(r[\"trades\"])
    
    with open(\"/root/trading_analysis/master_trade_log.json\",\"w\") as f:
        json.dump(all_t, f, default=str)
    
    print(f\"\nDone. {len(all_t)} total trades saved.\")

if __name__ == \"__main__\": run_all()
