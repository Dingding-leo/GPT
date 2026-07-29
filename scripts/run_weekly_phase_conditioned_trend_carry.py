#!/usr/bin/env python3
"""Deterministic real-data reproducer for issue #617.

Uses immutable public OKX SPOT confirmed 1H CSV artifacts only.
No network, credentials, accounts, private endpoints, orders, leverage,
synthetic data, or 15m data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG = {'family_id': 'weekly-phase-conditioned-trend-carry-1h-v1', 'issue': 617, 'research_parent': '5a0fcc97d1a882f8223656c51f5bb8055f534e38', 'fee_one_way': 0.0005, 'warmup': [0, 2880], 'training': [2880, 17520], 'oos': [17520, 43440], 'required_rows': 43442, 'fold_hours': 2160, 'fold_count': 12, 'fourier_harmonics': 3, 'favourable_weekdays': 2, 'min_hold_hours': 168, 'bootstrap': {'resamples': 5000, 'block_hours': 168, 'seed': 20260729, 'confidence': 0.95}}
WEEKDAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

def load_prefix(path, expected_hash):
    data=open(path,'rb').read()
    sha=hashlib.sha256(data).hexdigest()
    assert sha==expected_hash,(sha,expected_hash)
    df=pd.read_csv(path,nrows=CONFIG["required_rows"])
    df["timestamp"]=pd.to_datetime(df["timestamp"],utc=True)
    assert len(df)==CONFIG["required_rows"]
    assert df["confirm"].eq(1).all()
    assert df["timestamp"].is_monotonic_increasing and df["timestamp"].is_unique
    dt=df["timestamp"].diff().dropna()
    assert dt.eq(pd.Timedelta(hours=1)).all()
    for col in ["open","high","low","close"]:
        assert np.isfinite(df[col].to_numpy(float)).all()
        assert (df[col].to_numpy(float)>0).all()
    return df,sha


def design(h,k=3):
    h=np.asarray(h,float)
    cols=[np.ones_like(h)]
    for j in range(1,k+1):
        cols.extend([np.sin(2*np.pi*j*h/168.0),np.cos(2*np.pi*j*h/168.0)])
    return np.column_stack(cols)


def fit_model(df):
    t=np.arange(CONFIG["training"][0], CONFIG["training"][1]-2)
    c=df["close"].to_numpy(float); o=df["open"].to_numpy(float)
    tr=np.log(c[t]/c[t-2160])
    valid=t[tr>0]
    y=np.log(o[valid+2]/o[valid+1])
    ets=df["timestamp"].iloc[valid+1]
    h=(ets.dt.weekday.to_numpy()*24+ets.dt.hour.to_numpy()).astype(int)
    X=design(h,CONFIG["fourier_harmonics"])
    coef=np.linalg.lstsq(X,y,rcond=None)[0]
    profile=design(np.arange(168),CONFIG["fourier_harmonics"])@coef
    scores=[]
    phase_hours=[]
    for d in range(7):
        inds=(np.arange(d*24+1,d*24+25)%168).astype(int)
        phase_hours.append(inds.tolist())
        scores.append(float(profile[inds].sum()))
    order=sorted(range(7),key=lambda d:(-scores[d],d))
    fav=order[:CONFIG["favourable_weekdays"]]
    return {
        "support":int(len(valid)),
        "coefficients":[float(x) for x in coef],
        "profile":[float(x) for x in profile],
        "weekday_scores":[float(x) for x in scores],
        "weekday_phase_hours":phase_hours,
        "favourable_weekday_indices":[int(x) for x in fav],
        "favourable_weekdays":[WEEKDAYS[x] for x in fav],
        "training_target_mean":float(y.mean()),
        "training_target_std":float(y.std(ddof=1)),
    }


def returns(df):
    o=df["open"].to_numpy(float)
    return o[2:]/o[1:-1]-1


def trend_pos(df,daily):
    n=len(df)-2;c=df["close"].to_numpy(float)
    pos=np.zeros(n);cur=0
    for t in range(n):
        if t>=2160 and (not daily or df["timestamp"].iloc[t].hour==0):
            cur=int(np.log(c[t]/c[t-2160])>0)
        pos[t]=cur
    return pos


def candidate_pos(df,fav):
    n=len(df)-2;c=df["close"].to_numpy(float)
    pos=np.zeros(n);cur=0;entry_t=None
    for t in range(n):
        if t>=2160 and df["timestamp"].iloc[t].hour==0:
            tr=np.log(c[t]/c[t-2160])
            wd=int(df["timestamp"].iloc[t].weekday())
            if cur==0:
                if tr>0 and wd in fav:
                    cur=1;entry_t=t
            else:
                if (t-entry_t)>=CONFIG["min_hold_hours"] and tr<=0:
                    cur=0;entry_t=None
        pos[t]=cur
    return pos


def net_series(pos,r):
    changes=np.abs(np.diff(np.r_[0.0,pos]))
    return pos*r-CONFIG["fee_one_way"]*changes,changes


def sharpe(x):
    x=np.asarray(x,float); sd=x.std(ddof=1)
    if len(x)<2 or sd==0 or not np.isfinite(sd): return None
    return float(x.mean()/sd*np.sqrt(8760))


def segment_metrics(net,pos,changes,start,end):
    x=net[start:end]; p=pos[start:end]; ch=changes[start:end]
    wealth=np.cumprod(1+x)
    total=float(wealth[-1]-1)
    peak=np.maximum.accumulate(np.r_[1.0,wealth])
    dd=np.r_[1.0,wealth]/peak-1
    turn=float(ch.sum())
    return {
        "net_return":total,
        "sharpe":sharpe(x),
        "max_drawdown":float(dd.min()),
        "turnover":turn,
        "fees":float(turn*CONFIG["fee_one_way"]),
        "edge_per_turnover_bps":float(x.sum()/turn*10000) if turn>0 else None,
        "exposure":float(p.mean()),
        "arithmetic_net_sum":float(x.sum()),
        "entries":int(((np.diff(np.r_[0.0,pos])>0)[start:end]).sum()),
        "exits":int(((np.diff(np.r_[0.0,pos])<0)[start:end]).sum()),
    }


def breadth(df,net,pos,changes):
    s,e=CONFIG["oos"]
    fold=[]
    for i in range(CONFIG["fold_count"]):
        a=s+i*CONFIG["fold_hours"];b=a+CONFIG["fold_hours"]
        m=segment_metrics(net,pos,changes,a,b)
        fold.append(m["net_return"])
    posfold=[x for x in fold if x>0]
    conc=max(posfold)/sum(posfold) if posfold else None
    exec_ts=df["timestamp"].iloc[1:len(net)+1].reset_index(drop=True)
    yrs={}
    for yr in sorted(exec_ts.iloc[s:e].dt.year.unique()):
        idx=np.flatnonzero((exec_ts.dt.year.to_numpy()==yr)&(np.arange(len(net))>=s)&(np.arange(len(net))<e))
        if len(idx):
            x=net[idx]
            yrs[str(int(yr))]=float(np.prod(1+x)-1)
    return {
        "fold_returns":fold,
        "profitable_folds":int(sum(x>0 for x in fold)),
        "positive_fold_concentration":float(conc) if conc is not None else None,
        "year_returns":yrs,
        "profitable_years":int(sum(x>0 for x in yrs.values())),
    }


def residual_sharpe(a,b,start,end):
    return sharpe(a[start:end]-b[start:end])


def bootstrap(cand,b1):
    s,e=CONFIG["oos"];a=cand[s:e];b=b1[s:e];n=len(a)
    block=CONFIG["bootstrap"]["block_hours"];nb=math.ceil(n/block)
    rng=np.random.default_rng(CONFIG["bootstrap"]["seed"])
    means=np.empty(CONFIG["bootstrap"]["resamples"])
    shd=np.empty_like(means)
    for i in range(len(means)):
        starts=rng.integers(0,n-block+1,size=nb)
        idx=np.concatenate([np.arange(z,z+block) for z in starts])[:n]
        x=a[idx];y=b[idx]
        means[i]=(x.mean()-y.mean())*8760
        sx=sharpe(x);sy=sharpe(y)
        shd[i]=(0.0 if sx is None else sx)-(0.0 if sy is None else sy)
    q=[0.025,0.5,0.975]
    return {
        "annualised_mean_delta_quantiles":[float(x) for x in np.quantile(means,q)],
        "sharpe_delta_quantiles":[float(x) for x in np.quantile(shd,q)],
    }


def phase_persistence(df,model):
    c=df["close"].to_numpy(float);o=df["open"].to_numpy(float)
    s,e=CONFIG["oos"]
    vals={d:[] for d in range(7)}
    for t in range(s,e-25):
        if df["timestamp"].iloc[t].hour!=0: continue
        if np.log(c[t]/c[t-2160])<=0: continue
        wd=int(df["timestamp"].iloc[t].weekday())
        vals[wd].append(float(np.log(o[t+25]/o[t+1])))
    means=np.array([np.mean(vals[d]) if vals[d] else np.nan for d in range(7)])
    scores=np.array(model["weekday_scores"])
    mask=np.isfinite(means)
    pear=float(np.corrcoef(scores[mask],means[mask])[0,1]) if mask.sum()>1 else None
    def rankdata(x):
        order=np.argsort(x,kind='mergesort');r=np.empty(len(x),float);r[order]=np.arange(len(x))
        return r
    spear=float(np.corrcoef(rankdata(scores[mask]),rankdata(means[mask]))[0,1]) if mask.sum()>1 else None
    realized_order=sorted(range(7),key=lambda d:(-means[d],d))
    frozen=set(model["favourable_weekday_indices"]); realtop=set(realized_order[:2])
    return {
        "oos_positive_trend_daily_support":[len(vals[d]) for d in range(7)],
        "oos_realised_24h_log_return_mean":[float(x) for x in means],
        "pearson_training_model_vs_oos":pear,
        "spearman_training_model_vs_oos":spear,
        "frozen_top2_overlap_with_oos_top2":len(frozen&realtop),
        "oos_top2_indices":realized_order[:2],
        "oos_top2_weekdays":[WEEKDAYS[d] for d in realized_order[:2]],
        "frozen_selected_mean":float(np.nanmean([means[d] for d in frozen])),
        "unselected_mean":float(np.nanmean([means[d] for d in range(7) if d not in frozen])),
    }


def hold_stats(pos):
    d=np.diff(np.r_[0.0,pos,0.0])
    starts=np.flatnonzero(d>0);ends=np.flatnonzero(d<0)
    durations=(ends-starts).astype(int)
    return {"count":int(len(durations)),"mean_hours":float(durations.mean()) if len(durations) else None,
            "median_hours":float(np.median(durations)) if len(durations) else None,
            "min_hours":int(durations.min()) if len(durations) else None,
            "max_hours":int(durations.max()) if len(durations) else None}


def run(btc_csv: str, eth_csv: str) -> dict:
    sources = {
        "BTC-USDT": (btc_csv,"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",8704977298),
        "ETH-USDT": (eth_csv,"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",8704978112),
    }
    result = {"family_id": CONFIG["family_id"],"issue":617,"accepted":True,"candidate_count":1,"parameter_grid_count":0,"canonical_fee_one_way":CONFIG["fee_one_way"],"markets":{},"verdict":None}
    for instrument, (path, expected_hash, artifact_id) in sources.items():
        df, source_hash = load_prefix(path, expected_hash)
        model = fit_model(df)
        r = returns(df)
        candidate_position = candidate_pos(df, model["favourable_weekday_indices"])
        b0_position = trend_pos(df, False)
        b1_position = trend_pos(df, True)
        candidate_net, candidate_changes = net_series(candidate_position, r)
        b0_net, b0_changes = net_series(b0_position, r)
        b1_net, b1_changes = net_series(b1_position, r)
        policies = {}
        for name, net, position, changes in [("candidate", candidate_net, candidate_position, candidate_changes),("b0_hourly_2160h_trend", b0_net, b0_position, b0_changes),("b1_daily_2160h_trend", b1_net, b1_position, b1_changes)]:
            policies[name] = {segment: segment_metrics(net, position, changes, *CONFIG[segment]) for segment in ["training", "oos"]}
            policies[name]["full"] = segment_metrics(net, position, changes, CONFIG["training"][0], CONFIG["oos"][1])
        breadth_result = breadth(df, candidate_net, candidate_position, candidate_changes)
        residual_b0 = residual_sharpe(candidate_net, b0_net, *CONFIG["oos"])
        residual_b1 = residual_sharpe(candidate_net, b1_net, *CONFIG["oos"])
        bootstrap_result = bootstrap(candidate_net, b1_net)
        persistence = phase_persistence(df, model)
        candidate_oos = policies["candidate"]["oos"]
        b1_oos = policies["b1_daily_2160h_trend"]["oos"]
        gates = {
            "positive_net_return": candidate_oos["net_return"] > 0,
            "finite_sharpe_and_exceeds_b1": candidate_oos["sharpe"] is not None and candidate_oos["sharpe"] > b1_oos["sharpe"],
            "edge_per_turnover_exceeds_b1": candidate_oos["edge_per_turnover_bps"] is not None and candidate_oos["edge_per_turnover_bps"] > b1_oos["edge_per_turnover_bps"],
            "max_drawdown_no_worse_than_b1": candidate_oos["max_drawdown"] >= b1_oos["max_drawdown"],
            "long_entries_at_least_8": candidate_oos["entries"] >= 8,
            "profitable_folds_at_least_7_of_12": breadth_result["profitable_folds"] >= 7,
            "profitable_year_segments_at_least_3": breadth_result["profitable_years"] >= 3,
            "positive_fold_concentration_at_most_50pct": breadth_result["positive_fold_concentration"] is not None and breadth_result["positive_fold_concentration"] <= 0.5,
            "positive_residual_sharpe_vs_b0": residual_b0 is not None and residual_b0 > 0,
            "positive_residual_sharpe_vs_b1": residual_b1 is not None and residual_b1 > 0,
            "bootstrap_mean_delta_lower_bound_positive": bootstrap_result["annualised_mean_delta_quantiles"][0] > 0,
            "bootstrap_sharpe_delta_lower_bound_positive": bootstrap_result["sharpe_delta_quantiles"][0] > 0,
            "hash_chronology_timing_fee_checks": True,
        }
        accepted = all(gates.values())
        result["accepted"] = result["accepted"] and accepted
        result["markets"][instrument] = {"source":{"artifact_id":artifact_id,"csv_sha256":source_hash,"rows_loaded":len(df),"later_suffix_unread":True},"model":model,"policies":policies,"breadth":breadth_result,"residual_sharpe":{"vs_b0":residual_b0,"vs_b1":residual_b1},"bootstrap_vs_b1":bootstrap_result,"phase_persistence":persistence,"holding_periods":hold_stats(candidate_position),"acceptance_gates":gates,"accepted":accepted}
    result["verdict"] = "accept_weekly_phase_conditioned_trend_carry" if result["accepted"] else "reject_exact_weekly_phase_conditioned_trend_carry_family"
    result["discrepancy_repair"] = {"initial_issue":"The first phase-persistence diagnostic grouped all OOS weekdays, although the frozen Fourier model was fitted only on hours whose 2160H slow trend was positive.","repair":"Condition the OOS 24H weekday-persistence diagnostic on the identical positive-2160H-trend state and rerun the complete experiment.","strategy_outputs_changed":False,"metrics_changed":False,"diagnostic_only":True}
    result["exact_head_gates"] = {"status":"not_yet_available","note":"Populate from GitHub after evidence publication."}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", required=True)
    parser.add_argument("--eth-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = run(args.btc_csv, args.eth_csv)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"verdict":result["verdict"],"BTC-USDT":result["markets"]["BTC-USDT"]["policies"]["candidate"]["oos"],"ETH-USDT":result["markets"]["ETH-USDT"]["policies"]["candidate"]["oos"]},indent=2,sort_keys=True))


if __name__ == "__main__":
    main()
