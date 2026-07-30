# ruff: noqa
# fmt: off
"""Reproduce issue #691 on immutable public OKX 1H candles."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=5e-4; ANN=8760.; W=2160; DM_W=720; N=43441; FOLD=2160
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

def directional_balance(d):
    hi=d.high.to_numpy(float); lo=d.low.to_numpy(float); n=len(d)
    up=np.zeros(n); down=np.zeros(n)
    up[1:]=hi[1:]-hi[:-1]; down[1:]=lo[:-1]-lo[1:]
    plus=np.where((up>down)&(up>0),up,0.0)
    minus=np.where((down>up)&(down>0),down,0.0)
    ps=np.full(n,np.nan); ms=np.full(n,np.nan); bal=np.full(n,np.nan)
    # Exactly 720 completed DM observations: indices 1..720, balance first available at 720.
    ps[DM_W]=plus[1:DM_W+1].sum(); ms[DM_W]=minus[1:DM_W+1].sum()
    den=ps[DM_W]+ms[DM_W]; bal[DM_W]=(ps[DM_W]-ms[DM_W])/den if den>0 else 0.0
    for t in range(DM_W+1,n):
        ps[t]=ps[t-1]-ps[t-1]/DM_W+plus[t]
        ms[t]=ms[t-1]-ms[t-1]/DM_W+minus[t]
        den=ps[t]+ms[t]; bal[t]=(ps[t]-ms[t])/den if den>0 else 0.0
    return {"plus_dm":plus,"minus_dm":minus,"plus720":ps,"minus720":ms,"balance":bal}

def positions(d):
    n=len(d); cl=d.close.to_numpy(float); feat=directional_balance(d); bal=feat["balance"]
    p={k:np.zeros(n-1) for k in ("candidate","b0","b1")}
    cand=0.; b1=0.; prev_base=0.; events=[]
    for t in range(W,n-1):
        base=float(cl[t]>cl[t-W])
        if t+1<n-1: p["b0"][t+1]=base
        before=cand; risk=False; recovery=False; latest_mean=None; prior_mean=None; action="carry"
        if int(d.index[t].hour)==0:
            latest=bal[t-167:t+1]; prior=bal[t-335:t-167]
            if not(np.isfinite(latest).all() and np.isfinite(prior).all() and np.isfinite(bal[t])): raise ValueError("nonfinite decision feature")
            latest_mean=float(latest.mean()); prior_mean=float(prior.mean())
            risk=bool(bal[t]<0 and latest_mean<prior_mean)
            recovery=bool(bal[t]>0 and latest_mean>prior_mean)
            if base<=0:
                cand=0.; action="base_exit" if before>0 else "remain_cash"
            elif prev_base<=0:
                cand=1.; action="new_trend_entry"
            elif risk:
                cand=.5; action="risk_to_half" if before!=.5 else "repeat_risk"
            elif recovery:
                cand=1.; action="recovery_to_full" if before!=1. else "repeat_recovery"
            else:
                action="ambiguous_hold"
            b1=base
            events.append({"decision":t,"execution":t+1,"timestamp":d.index[t].isoformat(),"base":base,"previous_base":prev_base,"balance":float(bal[t]),"latest168_mean":latest_mean,"preceding168_mean":prior_mean,"risk":risk,"recovery":recovery,"exposure_before":before,"exposure_after":cand,"action":action,"effective_change":abs(cand-before)>1e-15})
            prev_base=base
        if t+1<n-1:
            p["candidate"][t+1]=cand; p["b1"][t+1]=b1
    if not np.isin(p["candidate"],np.array([0.,.5,1.])).all(): raise ValueError("invalid exposure")
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
    vals=[float(market[j:min(j+h,e)].sum()) for j in indices if j<e and min(j+h,e)-j==h]
    return {"horizon_hours":h,"count":len(vals),"mean":float(np.mean(vals)) if vals else None,"median":float(np.median(vals)) if vals else None,"positive_share":float(np.mean(np.array(vals)>0)) if vals else None}

def episode_stats(mask,market,s):
    x=np.asarray(mask,bool); starts=np.flatnonzero(x & ~np.r_[False,x[:-1]]); ends=np.flatnonzero(x & ~np.r_[x[1:],False])+1
    rows=[{"start":int(s+a),"end":int(s+b),"hours":int(b-a),"market_return":float(market[s+a:s+b].sum())} for a,b in zip(starts,ends)]
    hours=sum(z["hours"] for z in rows); absret=sum(abs(z["market_return"]) for z in rows)
    return {"count":len(rows),"positive_episodes":sum(z["market_return"]>0 for z in rows),"negative_episodes":sum(z["market_return"]<0 for z in rows),"largest_duration_concentration":max((z["hours"] for z in rows),default=0)/hours if hours else None,"largest_abs_return_concentration":max((abs(z["market_return"]) for z in rows),default=0)/absret if absret else None,"episodes":rows}

def sample_diag(events,a,p,span):
    s,e=span; es=[x for x in events if s<=x["execution"]<e]; market=a["candidate"]["market"]
    risks=[x for x in es if x["risk"]]; rec=[x for x in es if x["recovery"]]
    eligible=[x for x in es if x["base"]>0 and x["previous_base"]>0]
    eligible_risks=[x for x in eligible if x["risk"]]
    eligible_rec=[x for x in eligible if x["recovery"]]
    risk_eff=[x for x in es if x["action"]=="risk_to_half"]
    rec_eff=[x for x in es if x["action"]=="recovery_to_full"]
    half=np.isclose(p["candidate"][s:e],.5); full=np.isclose(p["candidate"][s:e],1.); cash=np.isclose(p["candidate"][s:e],0.)
    occupancy={}
    for name,mask,level in (("cash",cash,0.),("half",half,.5),("full",full,1.)):
        z=market[s:e][mask]
        occupancy[name]={"hours":int(mask.sum()),"share":float(mask.mean()),"arithmetic_market_return":float(z.sum()),"strategy_market_contribution":float((level*z).sum()),"conditional_market_sharpe":sharpe(z) if len(z)>1 else None}
    actions={k:sum(x["action"]==k for x in es) for k in sorted(set(x["action"] for x in es))}
    attributed=float(sum(abs(x["exposure_after"]-x["exposure_before"]) for x in es if x["effective_change"]))
    boundary=float(a["candidate"]["turn"][s]) if s>0 and not any(x["execution"]==s for x in es) else 0.
    total=float(a["candidate"]["turn"][s:e].sum())
    if not math.isclose(attributed+boundary,total,abs_tol=1e-12): raise ValueError(f"turnover attribution {attributed}+{boundary}!={total}")
    return {"daily_decisions":len(es),"risk_triggers":len(risks),"recovery_triggers":len(rec),"effective_risk_transitions":len(risk_eff),"effective_recovery_transitions":len(rec_eff),"repeated_or_ineligible_risk_triggers":len(risks)-len(risk_eff),"repeated_or_ineligible_recovery_triggers":len(rec)-len(rec_eff),"risk_trigger_frequency_unconditional":len(risks)/len(es) if es else None,"recovery_trigger_frequency_unconditional":len(rec)/len(es) if es else None,"eligible_positive_trend_decisions":len(eligible),"risk_trigger_frequency_eligible":len(eligible_risks)/len(eligible) if eligible else None,"recovery_trigger_frequency_eligible":len(eligible_rec)/len(eligible) if eligible else None,"effective_transition_frequency":(len(risk_eff)+len(rec_eff))/len(es) if es else None,"actions":actions,"risk_transition_forward":{"24h":forward_stats([x["execution"] for x in risk_eff],market,e,24),"168h":forward_stats([x["execution"] for x in risk_eff],market,e,168)},"recovery_transition_forward":{"24h":forward_stats([x["execution"] for x in rec_eff],market,e,24),"168h":forward_stats([x["execution"] for x in rec_eff],market,e,168)},"exposure_occupancy":occupancy,"half_state_episodes":episode_stats(half,market,s),"turnover_attributed_to_daily_changes":attributed,"boundary_turnover":boundary,"turnover_reconstructed":total}

def decomposition(a,p):
    s,e=OOS; delta=p["candidate"][s:e]-p["b1"][s:e]
    market=float((delta*a["candidate"]["market"][s:e]).sum()); fee=float(a["candidate"]["fees"][s:e].sum()-a["b1"]["fees"][s:e].sum()); obs=float((a["candidate"]["net"][s:e]-a["b1"]["net"][s:e]).sum())
    if not math.isclose(obs,market-fee,abs_tol=1e-12): raise ValueError("decomposition")
    return {"arithmetic_net_delta":obs,"exposure_market_return_delta":market,"incremental_fees":fee,"candidate_only_full_exposure_equivalent_hours":float(np.maximum(delta,0).sum()),"b1_only_full_exposure_equivalent_hours":float(np.maximum(-delta,0).sum()),"candidate_only_market_return":float((np.maximum(delta,0)*a["candidate"]["market"][s:e]).sum()),"b1_only_market_return":float((np.maximum(-delta,0)*a["candidate"]["market"][s:e]).sum())}

def diagnostics(d,p,a,events,feat):
    s,e=OOS; folds=[]
    for k in range(12):
        aa=s+k*FOLD; bb=aa+FOLD; cr=float(np.prod(1+a["candidate"]["net"][aa:bb])-1); br=float(np.prod(1+a["b1"]["net"][aa:bb])-1); folds.append({"fold":k+1,"candidate":cr,"b1":br,"delta":cr-br})
    years=d.index[:-1].year; yc={}
    for y in sorted(set(years[s:e])):
        z=years[s:e]==y; cr=float(np.prod(1+a["candidate"]["net"][s:e][z])-1); br=float(np.prod(1+a["b1"]["net"][s:e][z])-1); yc[str(y)]={"candidate":cr,"b1":br,"delta":cr-br}
    bal=feat["balance"]
    return {"training_state_diagnostics":sample_diag(events,a,p,TRAIN),"oos_state_diagnostics":sample_diag(events,a,p,OOS),"candidate_vs_b1":decomposition(a,p),"fold_comparison_vs_b1":folds,"folds_improved_vs_b1":sum(x["delta"]>0 for x in folds),"year_comparison_vs_b1":yc,"years_improved_vs_b1":sum(x["delta"]>0 for x in yc.values()),"balance_distribution":{"training":{"mean":float(np.mean(bal[TRAIN[0]:TRAIN[1]])),"std":float(np.std(bal[TRAIN[0]:TRAIN[1]],ddof=1)),"negative_share":float(np.mean(bal[TRAIN[0]:TRAIN[1]]<0))},"development_oos":{"mean":float(np.mean(bal[OOS[0]:OOS[1]])),"std":float(np.std(bal[OOS[0]:OOS[1]],ddof=1)),"negative_share":float(np.mean(bal[OOS[0]:OOS[1]]<0))}},"identity_checks":{"allowed_exposure_states":True,"fee":True,"decomposition":True,"turnover_attribution":True}}

def protocol(issue=691):
    return {"family_id":"directional-movement-trend-quality-risk-state-1h-v1","issue":issue,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","bar":"1H","canonical_fee_one_way":FEE,"candidate_count":1,"parameter_grid_count":0,"trend_horizon_hours":W,"directional_movement_smoother_hours":DM_W,"state_means_hours":168,"sources":{m:{"artifact_id":ART[m],"sha256":HASH[m]} for m in HASH},"observations":N,"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"fold_hours":FOLD,"fold_count":12,"bootstrap":{"kind":"paired non-circular moving blocks","block_hours":BLOCK,"resamples":R,"seed":SEED},"hard_boundary":{"own_history_only":True,"cross_sectional":False,"pairs_spreads":False,"market_neutral":False,"leverage":False,"synthetic_data":False,"credentials":False,"orders":False}}

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
    res={"protocol":protocol(),"markets":markets,"bilateral_accepted":ok,"verdict":"accept_directional_movement_trend_quality_risk_state_family" if ok else "reject_exact_directional_movement_trend_quality_risk_state_family","repaired_discrepancy":"The initial diagnostic classified any positive-trend onset that also satisfied the recovery inequality as a recovery transition. Terminal evidence counts effective risk and recovery transitions only when the corresponding state-machine action actually changes an already-positive trend exposure, separates unconditional from eligible trigger frequencies, and attributes turnover at next-open execution. No signal, exposure, fee, return, benchmark, bootstrap result, gate or verdict changed.","remaining_blocker":"Directional-movement deterioration separates lower-quality from higher-quality exposure, especially in ETH, but the lower-quality state still carries positive unconditional trend return. Recurrent half-sizing therefore removes positive carry and adds turnover; BTC risk transitions are followed by positive short-horizon continuation, while neither market achieves breadth or dependence-aware superiority.","next_experiment":"One own-history-only trend-onset participation-decay architecture: enter the unchanged 2,160H positive trend immediately, then permit a single irreversible exit only when the latest 168H positive directional-movement sum falls below one half of its maximum since onset while the completed close remains below the onset close; no re-entry until a new onset, one candidate, no fitted threshold, grid, exogenous input or market-specific rule."}
    text=json.dumps(nat(res),indent=2,sort_keys=True,allow_nan=False)+"\n"; (z.out/"result.json").write_text(text); (z.out/"protocol.json").write_text(json.dumps(nat(protocol()),indent=2,sort_keys=True)+"\n"); print(text)
if __name__=="__main__": main()
