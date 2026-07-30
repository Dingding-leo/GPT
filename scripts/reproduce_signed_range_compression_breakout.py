# ruff: noqa
# fmt: off
"""Reproduce issue #673 from immutable public OKX 1H candles."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=5e-4; ANN=8760.; W=2160; BASE=720; S=168; N=43441; FOLD=2160
TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); SEED=20260730
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
ART={"BTC-USDT":8704977298,"ETH-USDT":8704978112}


def load(path:Path,m:str)->pd.DataFrame:
    raw=path.read_bytes(); got=hashlib.sha256(raw).hexdigest()
    if got!=HASH[m]: raise ValueError(f"{m} hash {got}")
    d=pd.read_csv(path,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True))
    x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
    if not (len(d)==N and t.equals(pd.date_range(t[0],periods=N,freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all()): raise ValueError(f"{m} invalid source")
    d.index=t; return d


def lagged_sum(x:np.ndarray,h:int,lag:int)->np.ndarray:
    z=np.full(len(x),np.nan); cs=np.r_[0.,np.cumsum(x)]; t=np.arange(h+lag-1,len(x)); end=t-lag
    z[t]=cs[end+1]-cs[end+1-h]; return z


def features(d:pd.DataFrame):
    c=d.close.to_numpy(float); hi=d.high.to_numpy(float); lo=d.low.to_numpy(float)
    pv=np.square(np.log(hi/lo))/(4*math.log(2))
    baseline_sum=lagged_sum(pv,BASE,2*S); prior_sum=lagged_sum(pv,S,S); recent_sum=lagged_sum(pv,S,0)
    baseline=baseline_sum/BASE; prior_pv=prior_sum/S; recent_pv=recent_sum/S
    prior_ret=np.full(len(c),np.nan); recent_ret=np.full(len(c),np.nan)
    prior_ret[2*S:]=np.log(c[S:-S]/c[:-2*S]); recent_ret[S:]=np.log(c[S:]/c[:-S])
    prior_eff=np.divide(prior_ret,np.sqrt(prior_sum),out=np.full(len(c),np.nan),where=prior_sum>0)
    recent_eff=np.divide(recent_ret,np.sqrt(recent_sum),out=np.full(len(c),np.nan),where=recent_sum>0)
    margin=np.full(len(c),np.nan); margin[W:]=np.log(c[W:]/c[:-W])
    valid=np.isfinite(baseline)&np.isfinite(prior_pv)&np.isfinite(recent_pv)&np.isfinite(prior_eff)&np.isfinite(recent_eff)
    compression=valid&(prior_pv<baseline); breakout=valid&(recent_eff>0)&(recent_eff>prior_eff); entry=valid&compression&breakout
    return dict(pv=pv,baseline=baseline,prior_pv=prior_pv,recent_pv=recent_pv,prior_eff=prior_eff,recent_eff=recent_eff,margin=margin,compression=compression,breakout=breakout,entry=entry)


def positions(d,f):
    n=len(d); p={k:np.zeros(n-1) for k in ("candidate","b0","b1")}; c=b0=b1=0.; rows=[]
    for t in range(W,n-1):
        base=bool(f["margin"][t]>0); b0=float(base)
        if d.index[t].hour==0:
            prev=c; state=bool(f["entry"][t]); comp=bool(f["compression"][t]); brk=bool(f["breakout"][t])
            if not base: c=0.
            elif c>0: c=1.
            elif state: c=1.
            else: c=0.
            b1=float(base)
            rows.append((t,t+1,base,comp,brk,state,prev,c,float(f["baseline"][t]),float(f["prior_pv"][t]),float(f["recent_pv"][t]),float(f["prior_eff"][t]),float(f["recent_eff"][t])))
        if t+1<n-1: p["candidate"][t+1]=c; p["b0"][t+1]=b0; p["b1"][t+1]=b1
    if np.any(p["candidate"]>p["b1"]+1e-15): raise ValueError("candidate exceeds B1")
    return p,rows


def packed(d,p):
    o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; fees=FEE*turn; net=p*market-fees
    if not np.array_equal(net,p*market-FEE*turn): raise ValueError("fee identity")
    return dict(market=market,turn=turn,fees=fees,net=net)


def shp(x):
    s=float(np.std(x,ddof=1)); return None if s<=0 or not np.isfinite(s) else float(math.sqrt(ANN)*np.mean(x)/s)


def metrics(a,p,span):
    s,e=span; n=a["net"][s:e]; x=p[s:e]; w=np.cumprod(1+n); path=np.r_[1.,w]; turn=float(a["turn"][s:e].sum())
    return dict(net_return=float(w[-1]-1),arithmetic_net_return=float(n.sum()),sharpe=shp(n),max_drawdown=float(np.min(path/np.maximum.accumulate(path)-1)),turnover=turn,fees=float(a["fees"][s:e].sum()),edge_per_turnover_bps=float(n.sum()/turn*1e4) if turn else None,mean_exposure=float(x.mean()),exposure_hours=float(x.sum()))


def breadth(net,t):
    fr=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in fr if x>0]; years=t[:-1].year; yr={}
    for y in sorted(set(years[OOS[0]:OOS[1]])):
        z=years[OOS[0]:OOS[1]]==y; yr[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][z])-1)
    return dict(fold_returns=fr,profitable_folds=sum(x>0 for x in fr),year_returns=yr,profitable_years=sum(x>0 for x in yr.values()),positive_fold_concentration=max(pos)/sum(pos) if pos else None)


def bootstrap(c,b):
    c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(SEED); md=np.empty(5000); sd=np.empty(5000); off=np.arange(S); blocks=math.ceil(n/S)
    for q in range(0,5000,100):
        idx=(rng.integers(0,n-S+1,size=(100,blocks))[:,:,None]+off).reshape(100,-1)[:,:n]; cs=c[idx]; bs=b[idx]; cm=cs.mean(1); bm=bs.mean(1); cv=cs.std(1,ddof=1); bv=bs.std(1,ddof=1)
        md[q:q+100]=ANN*(cm-bm); sd[q:q+100]=np.divide(math.sqrt(ANN)*cm,cv,out=np.zeros(100),where=cv>0)-np.divide(math.sqrt(ANN)*bm,bv,out=np.zeros(100),where=bv>0)
    return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((shp(c) or 0)-(shp(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}


def build_regimes(rows,last_index):
    regimes=[]; active=None
    for r in rows:
        t,_,base,_,_,state,prev,c,*_=r
        if base and active is None: active={"start":t,"entry":None,"state_days":0}
        if active is not None and base:
            active["state_days"]+=int(state)
            if active["entry"] is None and prev==0 and c==1: active["entry"]=t
        if active is not None and not base:
            active["end"]=t; regimes.append(active); active=None
    if active is not None: active["end"]=last_index; regimes.append(active)
    return regimes

def regime_diagnostics(rows,span,last_index):
    regimes=[r for r in build_regimes(rows,last_index) if span[0]<=r["start"]<span[1]]
    qualified=[r for r in regimes if r["entry"] is not None]
    delays=[(r["entry"]-r["start"])/24 for r in qualified]
    return dict(regimes=len(regimes),qualified_regimes=len(qualified),skipped_regimes=len(regimes)-len(qualified),median_entry_delay_days=float(np.median(delays)) if delays else None,max_entry_delay_days=float(np.max(delays)) if delays else None,regimes_with_any_entry_state=sum(r["state_days"]>0 for r in regimes))

def omitted_exposure_attribution(rows,p,a):
    n=len(p["candidate"]); delay=np.zeros(n); skipped=np.zeros(n)
    for r in build_regimes(rows,n-1):
        start=r["start"]+1; stop=(r["entry"]+1) if r["entry"] is not None else (r["end"]+1)
        stop=min(stop,n)
        if stop<=start: continue
        (delay if r["entry"] is not None else skipped)[start:stop]=1
    actual=np.maximum(p["b1"]-p["candidate"],0)
    if not np.array_equal(delay+skipped,actual): raise ValueError("regime omission attribution")
    m=a["candidate"]["market"]; s,e=OOS
    return dict(delay_exposure_hours=float(delay[s:e].sum()),skipped_exposure_hours=float(skipped[s:e].sum()),delay_omitted_market_return=float((delay[s:e]*m[s:e]).sum()),skipped_omitted_market_return=float((skipped[s:e]*m[s:e]).sum()))


def diagnostics(rows,p,a):
    train=[r for r in rows if TRAIN[0]<=r[0]<TRAIN[1] and r[2]]; oos=[r for r in rows if OOS[0]<=r[0]<OOS[1] and r[2]]
    c=p["candidate"][OOS[0]:OOS[1]]; b=p["b1"][OOS[0]:OOS[1]]; m=a["candidate"]["market"][OOS[0]:OOS[1]]
    fee=float(a["candidate"]["fees"][OOS[0]:OOS[1]].sum()-a["b1"]["fees"][OOS[0]:OOS[1]].sum()); exposure=float(((c-b)*m).sum()); observed=float((a["candidate"]["net"][OOS[0]:OOS[1]]-a["b1"]["net"][OOS[0]:OOS[1]]).sum())
    if not math.isclose(observed,exposure-fee,abs_tol=1e-12): raise ValueError("decomposition")
    candidate_only=np.maximum(c-b,0); b1_only=np.maximum(b-c,0)
    entries=[]
    for r in oos:
        if r[6]==0 and r[7]==1:
            t=r[0]; rec={"t":t}
            for h in (24,168):
                if t+1+h<=OOS[1]: rec[str(h)]=float(np.prod(1+a["candidate"]["market"][t+1:t+1+h])-1)
            entries.append(rec)
    def entry_stats(h):
        vals=[r[str(h)] for r in entries if str(h) in r]
        return dict(events=len(vals),mean=float(np.mean(vals)) if vals else None,positive_rate=float(np.mean(np.array(vals)>0)) if vals else None)
    cn=a["candidate"]["net"][OOS[0]:OOS[1]]; bn=a["b1"]["net"][OOS[0]:OOS[1]]
    return dict(
        conditional_feature_rates={
            "training":{"compression":float(np.mean([r[3] for r in train])),"breakout":float(np.mean([r[4] for r in train])),"entry_state":float(np.mean([r[5] for r in train]))},
            "development_oos":{"compression":float(np.mean([r[3] for r in oos])),"breakout":float(np.mean([r[4] for r in oos])),"entry_state":float(np.mean([r[5] for r in oos]))},
        },
        training_regimes=regime_diagnostics(rows,TRAIN,len(p["candidate"])-1),development_oos_regimes=regime_diagnostics(rows,OOS,len(p["candidate"])-1),
        omitted_exposure_attribution=omitted_exposure_attribution(rows,p,a),
        candidate_only_exposure_hours=float(candidate_only.sum()),b1_only_exposure_hours=float(b1_only.sum()),
        candidate_only_market_return=float((candidate_only*m).sum()),b1_only_market_return=float((b1_only*m).sum()),
        exposure_delta_market_arithmetic_return=exposure,incremental_fees_candidate_minus_b1=fee,
        entry_forward_24h=entry_stats(24),entry_forward_168h=entry_stats(168),
        improved_arithmetic_net_folds_vs_b1=sum(float((cn-bn)[k*FOLD:(k+1)*FOLD].sum())>0 for k in range(12)),decomposition_identity_passes=True)


def run(d,m):
    f=features(d); p,rows=positions(d,f); a={k:packed(d,v) for k,v in p.items()}; mm={name:{k:metrics(a[k],p[k],span) for k in p} for name,span in (("training",TRAIN),("development_oos",OOS),("full_scored",FULL))}; br=breadth(a["candidate"]["net"],d.index); u=bootstrap(a["candidate"]["net"],a["b1"]["net"]); rs=shp(a["candidate"]["net"][OOS[0]:OOS[1]]-a["b1"]["net"][OOS[0]:OOS[1]])
    c=mm["development_oos"]["candidate"]; b=mm["development_oos"]["b1"]
    gates=dict(positive_oos_net=c["net_return"]>0,positive_oos_sharpe=c["sharpe"] is not None and c["sharpe"]>0,net_at_least_b1=c["net_return"]>=b["net_return"],sharpe_at_least_b1=c["sharpe"] is not None and c["sharpe"]>=b["sharpe"],drawdown_no_worse_b1=c["max_drawdown"]>=b["max_drawdown"],turnover_no_greater_b1=c["turnover"]<=b["turnover"],edge_per_turnover_at_least_b1=c["edge_per_turnover_bps"] is not None and c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],profitable_folds_at_least_7=br["profitable_folds"]>=7,profitable_years_at_least_3=br["profitable_years"]>=3,positive_residual_sharpe_b1=rs is not None and rs>0,mean_delta_lower_95_positive=u["annualized_mean_delta"]["lower_95"]>0,sharpe_delta_lower_95_positive=u["sharpe_delta"]["lower_95"]>0,positive_fold_concentration_at_most_half=br["positive_fold_concentration"] is not None and br["positive_fold_concentration"]<=.5,positive_full_scored_net=mm["full_scored"]["candidate"]["net_return"]>0)
    return dict(source={"artifact_id":ART[m],"csv_sha256":HASH[m],"observations":len(d)},metrics=mm,breadth=br,uncertainty=u,residual_sharpe_vs_b1=rs,diagnostics=diagnostics(rows,p,a),acceptance=gates,passes_all=all(gates.values()))


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--btc",type=Path,required=True); ap.add_argument("--eth",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); x=ap.parse_args()
    markets={"BTC-USDT":run(load(x.btc,"BTC-USDT"),"BTC-USDT"),"ETH-USDT":run(load(x.eth,"ETH-USDT"),"ETH-USDT")}; accepted=all(v["passes_all"] for v in markets.values()); out={"issue":673,"family_id":"signed-range-compression-breakout-entry-1h-v1","candidate_count":1,"parameter_grid_count":0,"markets":markets,"accepted":accepted,"verdict":"accept_exact_signed_range_compression_breakout_entry_family" if accepted else "reject_exact_signed_range_compression_breakout_entry_family"}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n"); print(json.dumps({"accepted":accepted,"verdict":out["verdict"],"summary":{m:{"oos":r["metrics"]["development_oos"]["candidate"],"b1":r["metrics"]["development_oos"]["b1"],"breadth":r["breadth"],"uncertainty":r["uncertainty"],"diagnostics":r["diagnostics"]} for m,r in markets.items()}},indent=2))
if __name__=="__main__": main()
