# ruff: noqa
# fmt: off
"""Reproduce issue #717 on immutable public OKX 1H candles."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=5e-4; ANN=8760.; W=2160; N=28081; FOLD=2160
WARM=(0,2160); REPL=(2160,28080); FULL=REPL
PHASES=(0,6,12,18); SEED=20260730; BLOCK=168; R=5000
MARKETS=("SOL-USDT","XRP-USDT","LTC-USDT","DOGE-USDT")
HASH={
"SOL-USDT":"57954fa6f0af09866787a6e622040bf1254c776b78a7c09860491d12d57428d9",
"XRP-USDT":"9047ced1f34d3a684c297a65b169c355a68a7906788d930c0916851a4d979e93",
"LTC-USDT":"c9f7f8c2a7f709518d1fd3211b8bc0281809e77ba06a7128d6fa3a46b7981e0c",
"DOGE-USDT":"715f3ed0952ce19734625dbb13b40d09f9ba2c4ad17e6bfdcdd54a0fa329fb18",
}
ARTIFACT_ID=8691110722; ARTIFACT_SHA="d9d686f4abd2c740044079b287802ef3e8c4f032c316035a95a2bb40ae2b7822"


def nat(x):
    if isinstance(x,(np.integer,np.bool_)): return x.item()
    if isinstance(x,np.floating): return float(x)
    if isinstance(x,np.ndarray): return x.tolist()
    if isinstance(x,dict): return {str(k):nat(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [nat(v) for v in x]
    return x


def load(p,m):
    raw=Path(p).read_bytes(); h=hashlib.sha256(raw).hexdigest()
    if h!=HASH[m]: raise ValueError(f"{m} hash {h}")
    d=pd.read_csv(p)
    t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True))
    x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
    expected=pd.date_range("2023-04-25T00:00:00Z",periods=N,freq="1h",tz="UTC")
    if not(len(d)==N and t.equals(expected) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all()):
        raise ValueError(f"{m} invalid source")
    d.index=t
    return d


def positions(d):
    n=len(d); cl=d.close.to_numpy(float)
    p={k:np.zeros(n-1) for k in ("candidate","b0","b1")}
    states={h:0. for h in PHASES}; b0=0.; b1=0.; events=[]
    # Return interval t is open[t] -> open[t+1]. A completed candle d=t-1
    # may update the target for open[t].
    for t in range(n-1):
        decision=t-1
        before=float(sum(states.values())/len(PHASES))
        updated_phase=None; old_state=None; new_state=None
        if decision>=W:
            base=float(cl[decision]>cl[decision-W])
            b0=base
            hour=int(d.index[decision].hour)
            if hour==0: b1=base
            if hour in PHASES:
                updated_phase=hour; old_state=states[hour]; new_state=base; states[hour]=new_state
        candidate=float(sum(states.values())/len(PHASES))
        p["candidate"][t]=candidate; p["b0"][t]=b0; p["b1"][t]=b1
        if updated_phase is not None:
            events.append({"decision":decision,"execution":t,"phase":updated_phase,"phase_state_before":old_state,"phase_state_after":new_state,"exposure_before":before,"exposure_after":candidate,"effective_phase_change":abs(new_state-old_state)>1e-15,"effective_exposure_change":abs(candidate-before)>1e-15,"phase_states":{str(h):states[h] for h in PHASES}})
    allowed=np.array([0.,.25,.5,.75,1.])
    if not np.all(np.isclose(p["candidate"][:,None],allowed[None,:],atol=1e-15).any(axis=1)): raise ValueError("invalid exposure state")
    reference=np.zeros((len(PHASES),n-1))
    for q,h in enumerate(PHASES):
        state=0.
        for t in range(n-1):
            decision=t-1
            if decision>=W and int(d.index[decision].hour)==h: state=float(cl[decision]>cl[decision-W])
            reference[q,t]=state
    if not np.array_equal(p["candidate"],reference.mean(axis=0)): raise ValueError("independent phase reconstruction")
    return p,events


def pack(d,p):
    o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1
    turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; fees=FEE*turn; net=p*market-fees
    if not np.array_equal(net,p*market-FEE*turn): raise ValueError("fee identity")
    return {"market":market,"turn":turn,"fees":fees,"net":net}


def sharpe(x):
    s=float(np.std(x,ddof=1)); return None if s<=0 or not np.isfinite(s) else float(math.sqrt(ANN)*np.mean(x)/s)


def metric(a,p,span):
    s,e=span; n=a["net"][s:e]; x=p[s:e]; wealth=np.cumprod(1+n); path=np.r_[1.,wealth]; to=float(a["turn"][s:e].sum())
    return {"net_return":float(wealth[-1]-1),"arithmetic_net_return":float(n.sum()),"sharpe":sharpe(n),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":to,"fees":float(a["fees"][s:e].sum()),"edge_per_turnover_bps":float(n.sum()/to*1e4) if to else None,"mean_exposure":float(x.mean()),"exposure_hours":float(x.sum())}


def breadth(net,t):
    s,e=REPL; fr=[float(np.prod(1+net[s+k*FOLD:s+(k+1)*FOLD])-1) for k in range(12)]
    pos=[x for x in fr if x>0]; years=t[:-1].year; yr={}
    for y in sorted(set(years[s:e])):
        z=years[s:e]==y; yr[str(y)]=float(np.prod(1+net[s:e][z])-1)
    return {"fold_returns":fr,"profitable_folds":sum(x>0 for x in fr),"year_returns":yr,"profitable_years":sum(x>0 for x in yr.values()),"positive_fold_concentration":max(pos)/sum(pos) if pos else None}


def boot(c,b,seed=SEED):
    c=c[REPL[0]:REPL[1]]; b=b[REPL[0]:REPL[1]]; n=len(c); rng=np.random.default_rng(seed); md=np.empty(R); sd=np.empty(R); off=np.arange(BLOCK); nb=math.ceil(n/BLOCK)
    for q in range(0,R,100):
        size=min(100,R-q); ix=(rng.integers(0,n-BLOCK+1,size=(size,nb))[:,:,None]+off).reshape(size,-1)[:,:n]
        cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cv=cs.std(1,ddof=1); bv=bs.std(1,ddof=1)
        md[q:q+size]=ANN*(cm-bm)
        sd[q:q+size]=np.divide(math.sqrt(ANN)*cm,cv,out=np.zeros(size),where=cv>0)-np.divide(math.sqrt(ANN)*bm,bv,out=np.zeros(size),where=bv>0)
    return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sharpe(c) or 0)-(sharpe(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}


def cross_market_boot(series):
    # Common block starts preserve synchronous market shocks while each policy
    # remains instrument-local. This is inference only, not portfolio construction.
    names=list(MARKETS); n=REPL[1]-REPL[0]; rng=np.random.default_rng(SEED); off=np.arange(BLOCK); nb=math.ceil(n/BLOCK)
    md=np.empty(R); sd=np.empty(R)
    c=np.stack([series[m][0][REPL[0]:REPL[1]] for m in names]); b=np.stack([series[m][1][REPL[0]:REPL[1]] for m in names])
    for q in range(0,R,50):
        size=min(50,R-q); ix=(rng.integers(0,n-BLOCK+1,size=(size,nb))[:,:,None]+off).reshape(size,-1)[:,:n]
        cms=[]; sds=[]
        for j in range(size):
            cs=c[:,ix[j]]; bs=b[:,ix[j]]
            cm=cs.mean(1); bm=bs.mean(1); cv=cs.std(1,ddof=1); bv=bs.std(1,ddof=1)
            cms.append(np.median(ANN*(cm-bm)))
            sc=np.divide(math.sqrt(ANN)*cm,cv,out=np.zeros(len(names)),where=cv>0)
            sb=np.divide(math.sqrt(ANN)*bm,bv,out=np.zeros(len(names)),where=bv>0)
            sds.append(np.median(sc-sb))
        md[q:q+size]=cms; sd[q:q+size]=sds
    points_mean=[ANN*np.mean(c[i]-b[i]) for i in range(len(names))]
    points_sh=[(sharpe(c[i]) or 0)-(sharpe(b[i]) or 0) for i in range(len(names))]
    return {"median_annualized_mean_delta":{"point":float(np.median(points_mean)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"median_sharpe_delta":{"point":float(np.median(points_sh)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}


def decomposition(a,p):
    s,e=REPL; delta=p["candidate"][s:e]-p["b1"][s:e]
    market=float((delta*a["candidate"]["market"][s:e]).sum())
    fee=float(a["candidate"]["fees"][s:e].sum()-a["b1"]["fees"][s:e].sum())
    obs=float((a["candidate"]["net"][s:e]-a["b1"]["net"][s:e]).sum())
    if not math.isclose(obs,market-fee,abs_tol=1e-12): raise ValueError("decomposition")
    return {"arithmetic_net_delta":obs,"exposure_market_return_delta":market,"incremental_fees":fee,"candidate_only_full_exposure_equivalent_hours":float(np.maximum(delta,0).sum()),"b1_only_full_exposure_equivalent_hours":float(np.maximum(-delta,0).sum()),"candidate_only_market_return":float((np.maximum(delta,0)*a["candidate"]["market"][s:e]).sum()),"b1_only_market_return":float((np.maximum(-delta,0)*a["candidate"]["market"][s:e]).sum())}


def episode_stats(mask,market,s):
    x=np.asarray(mask,bool); starts=np.flatnonzero(x & ~np.r_[False,x[:-1]]); ends=np.flatnonzero(x & ~np.r_[x[1:],False])+1
    rows=[{"start":int(s+a),"end":int(s+b),"hours":int(b-a),"market_return":float(market[s+a:s+b].sum())} for a,b in zip(starts,ends)]
    hours=sum(z["hours"] for z in rows); absret=sum(abs(z["market_return"]) for z in rows)
    return {"count":len(rows),"positive_episodes":sum(z["market_return"]>0 for z in rows),"negative_episodes":sum(z["market_return"]<0 for z in rows),"largest_duration_concentration":max((z["hours"] for z in rows),default=0)/hours if hours else None,"largest_abs_return_concentration":max((abs(z["market_return"]) for z in rows),default=0)/absret if absret else None,"events":rows}


def diagnostics(d,p,a,events):
    s,e=REPL; es=[x for x in events if s<=x["execution"]<e]
    attr={str(h):0. for h in PHASES}; changes={str(h):0 for h in PHASES}; directions={}
    for h in PHASES:
        z=[x for x in es if x["phase"]==h]; eff=[x for x in z if x["effective_exposure_change"]]
        attr[str(h)]=float(sum(abs(x["exposure_after"]-x["exposure_before"]) for x in z)); changes[str(h)]=len(eff)
        directions[str(h)]={"adds":sum(x["phase_state_after"]>x["phase_state_before"] for x in eff),"cuts":sum(x["phase_state_after"]<x["phase_state_before"] for x in eff)}
    total=float(a["candidate"]["turn"][s:e].sum()); boundary=float(abs(p["candidate"][s]-p["candidate"][s-1]))
    reconstructed=sum(attr.values())
    if not math.isclose(reconstructed,total,abs_tol=1e-12): raise ValueError(f"turnover attribution {reconstructed}!={total}, boundary={boundary}")
    folds=[]
    for k in range(12):
        aa=s+k*FOLD; bb=aa+FOLD; cr=float(np.prod(1+a["candidate"]["net"][aa:bb])-1); br=float(np.prod(1+a["b1"]["net"][aa:bb])-1); folds.append({"fold":k+1,"candidate":cr,"b1":br,"delta":cr-br})
    years=d.index[:-1].year; yc={}
    for y in sorted(set(years[s:e])):
        z=years[s:e]==y; cr=float(np.prod(1+a["candidate"]["net"][s:e][z])-1); br=float(np.prod(1+a["b1"]["net"][s:e][z])-1); yc[str(y)]={"candidate":cr,"b1":br,"delta":cr-br}
    disagreement=np.logical_and(p["candidate"][s:e]>0,p["candidate"][s:e]<1)
    delta=p["candidate"][s:e]-p["b1"][s:e]; market=a["candidate"]["market"][s:e]
    rel={}
    for name,mask in (("candidate_above_b1",delta>0),("candidate_below_b1",delta<0)):
        rel[name]={"hours":int(mask.sum()),"full_exposure_equivalent_hours":float(np.abs(delta[mask]).sum()),"full_market_return":float(market[mask].sum()),"exposure_weighted_market_contribution":float((delta[mask]*market[mask]).sum()),"episodes":episode_stats(mask,a["candidate"]["market"],s)}
    return {"candidate_vs_b1":decomposition(a,p),"fold_comparison_vs_b1":folds,"folds_improved_vs_b1":sum(x["delta"]>0 for x in folds),"year_comparison_vs_b1":yc,"years_improved_vs_b1":sum(x["delta"]>0 for x in yc.values()),"phase_effective_changes":changes,"phase_change_directions":directions,"turnover_attribution_by_phase":attr,"fractional_exposure_hours":int(disagreement.sum()),"fractional_exposure_share":float(disagreement.mean()),"fractional_exposure_episodes":episode_stats(disagreement,a["candidate"]["market"],s),"relative_exposure_diagnostics":rel,"effective_exposure_changes":sum(x["effective_exposure_change"] for x in es),"identity_checks":{"allowed_exposure_states":True,"independent_phase_reconstruction":True,"next_open_alignment":True,"fee":True,"decomposition":True,"turnover_attribution":True}}


def run(d,m):
    p,ev=positions(d); a={k:pack(d,v) for k,v in p.items()}
    mm={"training":{"applicable":False,"reason":"exact rule frozen on consumed BTC/ETH development evidence; no replication-market fitting"},"development_oos":{k:metric(a[k],p[k],REPL) for k in p},"full_scored":{k:metric(a[k],p[k],FULL) for k in p}}
    br=breadth(a["candidate"]["net"],d.index); u=boot(a["candidate"]["net"],a["b1"]["net"]); rs=sharpe(a["candidate"]["net"][REPL[0]:REPL[1]]-a["b1"]["net"][REPL[0]:REPL[1]])
    c=mm["development_oos"]["candidate"]; b=mm["development_oos"]["b1"]
    g={"positive_oos_net":c["net_return"]>0,"net_at_least_b1":c["net_return"]>=b["net_return"],"sharpe_at_least_b1":c["sharpe"] is not None and c["sharpe"]>=b["sharpe"],"drawdown_no_worse_b1":c["max_drawdown"]>=b["max_drawdown"]-1e-12,"turnover_no_greater_b1":c["turnover"]<=b["turnover"]+1e-12,"edge_per_turnover_at_least_b1":c["edge_per_turnover_bps"] is not None and c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],"profitable_folds_at_least_7":br["profitable_folds"]>=7,"profitable_years_at_least_3":br["profitable_years"]>=3,"positive_fold_concentration_at_most_half":br["positive_fold_concentration"] is not None and br["positive_fold_concentration"]<=.5,"positive_residual_sharpe":rs is not None and rs>0,"positive_mean_delta_lower_95":u["annualized_mean_delta"]["lower_95"]>0,"positive_sharpe_delta_lower_95":u["sharpe_delta"]["lower_95"]>0,"positive_full_scored_net":mm["full_scored"]["candidate"]["net_return"]>0,"all_identities":True}
    return {"market":m,"source_artifact":ARTIFACT_ID,"source_sha256":HASH[m],"metrics":mm,"breadth":br,"residual_sharpe_vs_b1":rs,"uncertainty":u,"gates":g,"accepted":all(g.values()),"diagnostics":diagnostics(d,p,a,ev),"_series":(a["candidate"]["net"],a["b1"]["net"])}


def protocol(issue=717):
    return {"family_id":"four-phase-daily-trend-ensemble-cross-market-replication-1h-v1","source_family":"four-phase-daily-trend-ensemble-1h-v1","issue":issue,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","bar":"1H","canonical_fee_one_way":FEE,"candidate_count":1,"parameter_grid_count":0,"phase_hours_utc":list(PHASES),"trend_horizon_hours":W,"exposure_mapping":"fraction of four latest completed positive phase states","source_artifact":{"workflow_run":30364475418,"artifact_id":ARTIFACT_ID,"artifact_sha256":ARTIFACT_SHA},"sources":{m:{"sha256":HASH[m],"rows":N} for m in MARKETS},"warmup":list(WARM),"development_oos":list(REPL),"full_scored":list(FULL),"fold_hours":FOLD,"fold_count":12,"bootstrap":{"kind":"paired non-circular moving blocks","block_hours":BLOCK,"resamples":R,"seed":SEED},"hard_boundary":{"own_history_only":True,"cross_sectional":False,"pairs_spreads":False,"market_neutral":False,"leverage":False,"synthetic_data":False,"credentials":False,"orders":False}}


def main():
    ap=argparse.ArgumentParser();
    for m in MARKETS: ap.add_argument("--"+m.split("-")[0].lower(),type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True); z=ap.parse_args(); z.out.mkdir(parents=True,exist_ok=True)
    paths={m:getattr(z,m.split("-")[0].lower()) for m in MARKETS}
    markets={m:run(load(paths[m],m),m) for m in MARKETS}
    series={m:markets[m].pop("_series") for m in MARKETS}; cross=cross_market_boot(series)
    passed=sum(v["accepted"] for v in markets.values())
    transport=passed>=3 and cross["median_annualized_mean_delta"]["lower_95"]>0 and cross["median_sharpe_delta"]["lower_95"]>0
    res={"protocol":protocol(),"markets":markets,"markets_passing_all_original_gates":passed,"cross_market_uncertainty":cross,"transportability_supported":transport,"verdict":"cross_market_replication_supported_for_four_phase_ensemble" if transport else "reject_cross_market_transportability_of_four_phase_ensemble"}
    text=json.dumps(nat(res),indent=2,sort_keys=True,allow_nan=False)+"\n"; (z.out/"result.json").write_text(text); (z.out/"protocol.json").write_text(json.dumps(nat(protocol()),indent=2,sort_keys=True)+"\n"); print(text)

if __name__=="__main__": main()
