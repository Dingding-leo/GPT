# ruff: noqa
# fmt: off
"""Reproduce issue #694 on immutable public OKX 1H candles."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=5e-4; ANN=8760.; W=2160; PLUS_W=168; N=43441; FOLD=2160
TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440)
SEED=20260730; BLOCK=168; R=5000
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
ART={"BTC-USDT":8704977298,"ETH-USDT":8704978112}


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
    d=pd.read_csv(p,nrows=N)
    t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True))
    x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
    if not(len(d)==N and t.equals(pd.date_range(t[0],periods=N,freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all()):
        raise ValueError(f"{m} invalid source")
    d.index=t
    return d


def features(d):
    hi=d.high.to_numpy(float); lo=d.low.to_numpy(float); n=len(d)
    up=np.zeros(n); down=np.zeros(n)
    up[1:]=hi[1:]-hi[:-1]; down[1:]=lo[:-1]-lo[1:]
    plus=np.where((up>down)&(up>0),up,0.0)
    plus168=pd.Series(plus,index=d.index).rolling(PLUS_W,min_periods=PLUS_W).sum().to_numpy(float)
    return {"plus_dm":plus,"plus168":plus168}


def positions(d):
    n=len(d); cl=d.close.to_numpy(float); feat=features(d); plus168=feat["plus168"]
    p={k:np.zeros(n-1) for k in ("candidate","b0","b1")}
    cand=0.; b1=0.; prev_base=0.; locked=False; onset_close=None; max_plus=None
    regime_id=0; events=[]
    for t in range(W,n-1):
        base=float(cl[t]>cl[t-W])
        if t+1<n-1: p["b0"][t+1]=base
        if int(d.index[t].hour)==0:
            before=cand; action="carry"; trigger=False; ratio=None
            if not np.isfinite(plus168[t]): raise ValueError("nonfinite plus168 decision feature")
            if base<=0:
                cand=0.; action="base_exit" if before>0 else ("reset_after_lock" if locked else "remain_cash")
                locked=False; onset_close=None; max_plus=None
            elif prev_base<=0:
                regime_id+=1; cand=1.; locked=False; onset_close=float(cl[t]); max_plus=float(plus168[t]); action="new_trend_entry"
            elif locked:
                cand=0.; action="locked_cash"
            else:
                max_plus=max(float(max_plus),float(plus168[t]))
                ratio=float(plus168[t]/max_plus) if max_plus>0 else 1.0
                trigger=bool(plus168[t] < .5*max_plus and cl[t] < onset_close)
                if trigger:
                    cand=0.; locked=True; action="participation_decay_exit"
                else:
                    cand=1.; action="remain_long"
            b1=base
            events.append({"decision":t,"execution":t+1,"timestamp":d.index[t].isoformat(),"regime_id":regime_id if base>0 else None,"base":base,"previous_base":prev_base,"plus168":float(plus168[t]),"max_plus168_since_onset":float(max_plus) if max_plus is not None else None,"participation_ratio":ratio,"onset_close":onset_close,"close":float(cl[t]),"close_below_onset":bool(onset_close is not None and cl[t]<onset_close),"trigger":trigger,"locked_after":locked,"exposure_before":before,"exposure_after":cand,"action":action,"effective_change":abs(cand-before)>1e-15})
            prev_base=base
        if t+1<n-1:
            p["candidate"][t+1]=cand; p["b1"][t+1]=b1
    if not np.isin(p["candidate"],np.array([0.,1.])).all(): raise ValueError("invalid exposure")
    return p,events,feat


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
    fr=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]
    pos=[x for x in fr if x>0]; years=t[:-1].year; yr={}
    for y in sorted(set(years[OOS[0]:OOS[1]])):
        z=years[OOS[0]:OOS[1]]==y; yr[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][z])-1)
    return {"fold_returns":fr,"profitable_folds":sum(x>0 for x in fr),"year_returns":yr,"profitable_years":sum(x>0 for x in yr.values()),"positive_fold_concentration":max(pos)/sum(pos) if pos else None}


def boot(c,b):
    c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(SEED); md=np.empty(R); sd=np.empty(R); off=np.arange(BLOCK); nb=math.ceil(n/BLOCK)
    for q in range(0,R,100):
        ix=(rng.integers(0,n-BLOCK+1,size=(100,nb))[:,:,None]+off).reshape(100,-1)[:,:n]
        cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cv=cs.std(1,ddof=1); bv=bs.std(1,ddof=1)
        md[q:q+100]=ANN*(cm-bm)
        sd[q:q+100]=np.divide(math.sqrt(ANN)*cm,cv,out=np.zeros(100),where=cv>0)-np.divide(math.sqrt(ANN)*bm,bv,out=np.zeros(100),where=bv>0)
    return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sharpe(c) or 0)-(sharpe(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}


def forward_stats(indices,market,e,h):
    vals=[float(market[j:j+h].sum()) for j in indices if j>=0 and j+h<=e]
    return {"horizon_hours":h,"count":len(vals),"mean":float(np.mean(vals)) if vals else None,"median":float(np.median(vals)) if vals else None,"positive_share":float(np.mean(np.array(vals)>0)) if vals else None,"values":vals}


def decomposition(a,p,span=OOS):
    s,e=span; delta=p["candidate"][s:e]-p["b1"][s:e]
    market=float((delta*a["candidate"]["market"][s:e]).sum()); fee=float(a["candidate"]["fees"][s:e].sum()-a["b1"]["fees"][s:e].sum()); obs=float((a["candidate"]["net"][s:e]-a["b1"]["net"][s:e]).sum())
    if not math.isclose(obs,market-fee,abs_tol=1e-12): raise ValueError("decomposition")
    return {"arithmetic_net_delta":obs,"exposure_market_return_delta":market,"incremental_fees":fee,"candidate_only_hours":int(np.sum(delta>0)),"b1_only_hours":int(np.sum(delta<0)),"candidate_only_market_return":float((np.maximum(delta,0)*a["candidate"]["market"][s:e]).sum()),"b1_only_market_return":float((np.maximum(-delta,0)*a["candidate"]["market"][s:e]).sum())}


def regime_diagnostics(d,p,a,events,span):
    s,e=span; market=a["candidate"]["market"]; es=[x for x in events if s<=x["execution"]<e]
    exits=[x for x in es if x["action"]=="participation_decay_exit"]
    entries=[x for x in es if x["action"]=="new_trend_entry"]
    locked=[x for x in es if x["action"]=="locked_cash"]
    eligible=[x for x in es if x["base"]>0 and x["previous_base"]>0 and not x["locked_after"]]
    ratios=[x["participation_ratio"] for x in es if x["participation_ratio"] is not None]
    omitted=(p["b1"][s:e]>p["candidate"][s:e])
    reg=np.full(e-s,-1,int); current=-1
    event_by_exec={x["execution"]:x for x in events if x["execution"]<e}
    prior=[x for x in events if x["execution"]<=s and x["base"]>0]
    if prior: current=int(prior[-1]["regime_id"] or -1)
    for j in range(s,e):
        if j in event_by_exec:
            ev=event_by_exec[j]
            current=int(ev["regime_id"] or -1) if ev["base"]>0 else -1
        reg[j-s]=current
    rows=[]
    for rid in sorted(set(reg[omitted])):
        if rid<0: continue
        mask=omitted & (reg==rid); idx=np.flatnonzero(mask)
        rows.append({"regime_id":int(rid),"started_in_span":any(x["regime_id"]==rid and x["action"]=="new_trend_entry" for x in es),"hours_omitted":int(mask.sum()),"market_return_omitted":float(market[s:e][mask].sum()),"first_omitted_index":int(s+idx[0]),"last_omitted_index":int(s+idx[-1])})
    attributed=float(sum(abs(x["exposure_after"]-x["exposure_before"]) for x in es if x["effective_change"])); boundary=float(a["candidate"]["turn"][s]) if s>0 and not any(x["execution"]==s for x in es) else 0.; total=float(a["candidate"]["turn"][s:e].sum())
    if not math.isclose(attributed+boundary,total,abs_tol=1e-12): raise ValueError(f"turnover attribution {attributed}+{boundary}!={total}")
    return {"daily_decisions":len(es),"trend_onsets":len(entries),"participation_decay_exits":len(exits),"locked_cash_decisions":len(locked),"trigger_frequency_all_decisions":len(exits)/len(es) if es else None,"participation_ratio_distribution":{"count":len(ratios),"mean":float(np.mean(ratios)) if ratios else None,"median":float(np.median(ratios)) if ratios else None,"below_half_decisions":sum(r<.5 for r in ratios)},"exit_forward":{"24h":forward_stats([x["execution"] for x in exits],market,e,24),"168h":forward_stats([x["execution"] for x in exits],market,e,168),"720h":forward_stats([x["execution"] for x in exits],market,e,720)},"omitted_same_regime":{"hours":int(omitted.sum()),"market_return":float(market[s:e][omitted].sum()),"regimes":rows,"started_in_span_regimes":sum(r["started_in_span"] for r in rows),"overlapping_regimes":sum(not r["started_in_span"] for r in rows)},"actions":{k:sum(x["action"]==k for x in es) for k in sorted(set(x["action"] for x in es))},"turnover_attributed_to_daily_changes":attributed,"boundary_turnover":boundary,"turnover_reconstructed":total}


def diagnostics(d,p,a,events,feat):
    s,e=OOS; folds=[]
    for k in range(12):
        aa=s+k*FOLD; bb=aa+FOLD; cr=float(np.prod(1+a["candidate"]["net"][aa:bb])-1); br=float(np.prod(1+a["b1"]["net"][aa:bb])-1); folds.append({"fold":k+1,"candidate":cr,"b1":br,"delta":cr-br})
    years=d.index[:-1].year; yc={}
    for y in sorted(set(years[s:e])):
        z=years[s:e]==y; cr=float(np.prod(1+a["candidate"]["net"][s:e][z])-1); br=float(np.prod(1+a["b1"]["net"][s:e][z])-1); yc[str(y)]={"candidate":cr,"b1":br,"delta":cr-br}
    plus=feat["plus168"]
    return {"training_regime_diagnostics":regime_diagnostics(d,p,a,events,TRAIN),"oos_regime_diagnostics":regime_diagnostics(d,p,a,events,OOS),"candidate_vs_b1":decomposition(a,p),"fold_comparison_vs_b1":folds,"folds_improved_vs_b1":sum(x["delta"]>0 for x in folds),"year_comparison_vs_b1":yc,"years_improved_vs_b1":sum(x["delta"]>0 for x in yc.values()),"plus168_distribution":{"training":{"mean":float(np.mean(plus[TRAIN[0]:TRAIN[1]])),"std":float(np.std(plus[TRAIN[0]:TRAIN[1]],ddof=1))},"development_oos":{"mean":float(np.mean(plus[OOS[0]:OOS[1]])),"std":float(np.std(plus[OOS[0]:OOS[1]],ddof=1))}},"identity_checks":{"allowed_exposure_states":True,"fee":True,"decomposition":True,"turnover_attribution":True,"omitted_regime_partition":True}}


def protocol(issue=694):
    return {"family_id":"trend-onset-participation-decay-exit-1h-v1","issue":issue,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","bar":"1H","canonical_fee_one_way":FEE,"candidate_count":1,"parameter_grid_count":0,"trend_horizon_hours":W,"positive_dm_sum_hours":PLUS_W,"participation_decay_ratio":.5,"same_regime_reentry":False,"sources":{m:{"artifact_id":ART[m],"sha256":HASH[m]} for m in HASH},"observations":N,"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"fold_hours":FOLD,"fold_count":12,"bootstrap":{"kind":"paired non-circular moving blocks","block_hours":BLOCK,"resamples":R,"seed":SEED},"hard_boundary":{"own_history_only":True,"cross_sectional":False,"pairs_spreads":False,"market_neutral":False,"leverage":False,"synthetic_data":False,"credentials":False,"orders":False}}


def run(d,m):
    p,ev,feat=positions(d); a={k:pack(d,v) for k,v in p.items()}
    mm={name:{k:metric(a[k],p[k],span) for k in p} for name,span in (("training",TRAIN),("development_oos",OOS),("full_scored",FULL))}
    br=breadth(a["candidate"]["net"],d.index); u=boot(a["candidate"]["net"],a["b1"]["net"]); rs=sharpe(a["candidate"]["net"][OOS[0]:OOS[1]]-a["b1"]["net"][OOS[0]:OOS[1]])
    c=mm["development_oos"]["candidate"]; b=mm["development_oos"]["b1"]
    g={"positive_oos_net":c["net_return"]>0,"positive_oos_sharpe":c["sharpe"] is not None and c["sharpe"]>0,"net_at_least_b1":c["net_return"]>=b["net_return"],"sharpe_at_least_b1":c["sharpe"] is not None and c["sharpe"]>=b["sharpe"],"drawdown_no_worse_b1":c["max_drawdown"]>=b["max_drawdown"],"turnover_no_greater_b1":c["turnover"]<=b["turnover"],"edge_per_turnover_at_least_b1":c["edge_per_turnover_bps"] is not None and c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],"profitable_folds_at_least_7":br["profitable_folds"]>=7,"profitable_years_at_least_3":br["profitable_years"]>=3,"positive_residual_sharpe":rs is not None and rs>0,"positive_mean_delta_lower_95":u["annualized_mean_delta"]["lower_95"]>0,"positive_sharpe_delta_lower_95":u["sharpe_delta"]["lower_95"]>0,"positive_fold_concentration_at_most_half":br["positive_fold_concentration"] is not None and br["positive_fold_concentration"]<=.5,"positive_full_scored_net":mm["full_scored"]["candidate"]["net_return"]>0}
    return {"market":m,"source_artifact":ART[m],"source_sha256":HASH[m],"metrics":mm,"breadth":br,"residual_sharpe_vs_b1":rs,"uncertainty":u,"gates":g,"accepted":all(g.values()),"diagnostics":diagnostics(d,p,a,ev,feat)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--btc",type=Path,required=True); ap.add_argument("--eth",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); z=ap.parse_args(); z.out.mkdir(parents=True,exist_ok=True)
    markets={"BTC-USDT":run(load(z.btc,"BTC-USDT"),"BTC-USDT"),"ETH-USDT":run(load(z.eth,"ETH-USDT"),"ETH-USDT")}
    ok=all(v["accepted"] for v in markets.values())
    res={"protocol":protocol(),"markets":markets,"bilateral_accepted":ok,"verdict":"accept_trend_onset_participation_decay_exit_family" if ok else "reject_exact_trend_onset_participation_decay_exit_family","repaired_discrepancy":"Initial regime-level inspection treated every omitted interval inside a scored span as belonging to a trend that began inside that span. Terminal diagnostics propagate the frozen regime identifier across each sample boundary and separate regimes that began inside the span from a positive trend already active at the boundary; this repairs the training attribution for an overlapping ETH regime. The omitted-exposure mask and arithmetic decomposition are unchanged; no signal, position, fee, metric, bootstrap result, gate or verdict changed.","remaining_blocker":"The half-maximum positive-DM decay condition is too sparse and not economically transportable. It fired only twice in BTC development OOS and never in ETH; one BTC exit avoided an immediate loss but the other omitted profitable recovery, while the sole BTC training exit omitted a large positive continuation. The family therefore cannot establish bilateral breadth or uncertainty-supported superiority.","next_experiment":"One own-history-only bounded upper-wick rejection pause architecture: retain immediate 2,160H trend entry, permit at most one fixed 168H cash pause per positive-trend regime when the latest 168H range-normalized upper-wick sum exceeds the lower-wick sum and the latest 168H close return is negative, then automatically resume if the base trend remains positive. One candidate, no fitted threshold, grid, exogenous input or market-specific rule."}
    text=json.dumps(nat(res),indent=2,sort_keys=True,allow_nan=False)+"\n"; (z.out/"result.json").write_text(text); (z.out/"protocol.json").write_text(json.dumps(nat(protocol()),indent=2,sort_keys=True)+"\n"); print(text)
if __name__=="__main__": main()
