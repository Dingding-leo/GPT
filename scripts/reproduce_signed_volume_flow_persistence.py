# ruff: noqa
# fmt: off
"""Reproduce issue #685 on immutable public OKX 1H candles."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=5e-4; ANN=8760.; W=2160; FLOW=168; N=43441; FOLD=2160
TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); SEED=20260730; BLOCK=168; R=5000
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
    d=pd.read_csv(p,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
    if not(len(d)==N and t.equals(pd.date_range(t[0],periods=N,freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all()): raise ValueError(f"{m} invalid source")
    d.index=t; return d

def flow_balance(signs,vol,a,b):
    w=vol[a:b]
    den=float(w.sum())
    if b-a!=FLOW or den<=0 or not np.isfinite(w).all(): raise ValueError("bad flow block")
    return float(np.dot(w,signs[a:b])/den)

def positions(d):
    n=len(d); cl=d.close.to_numpy(float); vol=d.volume_quote.to_numpy(float); lr=np.r_[np.nan,np.log(cl[1:]/cl[:-1])]; signs=np.sign(np.nan_to_num(lr,nan=0.0))
    p={k:np.zeros(n-1) for k in ("candidate","b0","b1")}; c=b0=b1=0.; prev=False; events=[]
    for t in range(W,n-1):
        base=bool(cl[t]>cl[t-W]); b0=float(base)
        if d.index[t].hour==0:
            onset=base and not prev; ev="hold"; cur=prv=risk=recovery=None; before=c
            if not base:
                c=0.; ev="base_exit"
            elif onset:
                c=1.; ev="onset_entry"
            else:
                cur=flow_balance(signs,vol,t-FLOW+1,t+1)
                prv=flow_balance(signs,vol,t-2*FLOW+1,t-FLOW+1)
                risk=bool(cur<0 and cur<prv); recovery=bool(cur>0 and cur>prv)
                if risk: c=.5; ev="risk_trigger"
                elif recovery: c=1.; ev="recovery_trigger"
                else: ev="retain"
            b1=float(base)
            events.append({"decision":t,"execution":t+1,"base":base,"onset":onset,"flow168":cur,"flow168_prev":prv,"risk_trigger":risk,"recovery_trigger":recovery,"state_before":before,"state_after":c,"event":ev,"effective_transition":abs(c-before)>1e-15})
            prev=base
        if t+1<n-1:
            p["candidate"][t+1]=c; p["b0"][t+1]=b0; p["b1"][t+1]=b1
    if np.any(p["candidate"]>p["b1"]+1e-15): raise ValueError("containment")
    return p,events

def pack(d,p):
    o=d.open.to_numpy(float); m=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; fees=FEE*turn; net=p*m-fees
    if not np.array_equal(net,p*m-FEE*turn): raise ValueError("fee identity")
    return {"market":m,"turn":turn,"fees":fees,"net":net}

def sharpe(x):
    s=float(np.std(x,ddof=1)); return None if s<=0 or not np.isfinite(s) else float(math.sqrt(ANN)*np.mean(x)/s)

def metric(a,p,span):
    s,e=span; n=a["net"][s:e]; x=p[s:e]; w=np.cumprod(1+n); path=np.r_[1.,w]; to=float(a["turn"][s:e].sum())
    return {"net_return":float(w[-1]-1),"arithmetic_net_return":float(n.sum()),"sharpe":sharpe(n),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":to,"fees":float(a["fees"][s:e].sum()),"edge_per_turnover_bps":float(n.sum()/to*1e4) if to else None,"mean_exposure":float(x.mean()),"exposure_hours":float(x.sum())}

def breadth(net,t):
    fr=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in fr if x>0]; years=t[:-1].year; yr={}
    for y in sorted(set(years[OOS[0]:OOS[1]])):
        z=years[OOS[0]:OOS[1]]==y; yr[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][z])-1)
    return {"fold_returns":fr,"profitable_folds":sum(x>0 for x in fr),"year_returns":yr,"profitable_years":sum(x>0 for x in yr.values()),"positive_fold_concentration":max(pos)/sum(pos) if pos else None}

def boot(c,b):
    c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(SEED); md=np.empty(R); sd=np.empty(R); off=np.arange(BLOCK); nb=math.ceil(n/BLOCK)
    for q in range(0,R,100):
        ix=(rng.integers(0,n-BLOCK+1,size=(100,nb))[:,:,None]+off).reshape(100,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cv=cs.std(1,ddof=1); bv=bs.std(1,ddof=1); md[q:q+100]=ANN*(cm-bm); sd[q:q+100]=np.divide(math.sqrt(ANN)*cm,cv,out=np.zeros(100),where=cv>0)-np.divide(math.sqrt(ANN)*bm,bv,out=np.zeros(100),where=bv>0)
    return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sharpe(c) or 0)-(sharpe(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}

def decomposition(a,p):
    s,e=OOS; ld=p["candidate"][s:e]-p["b1"][s:e]; market=float((ld*a["candidate"]["market"][s:e]).sum()); fee=float(a["candidate"]["fees"][s:e].sum()-a["b1"]["fees"][s:e].sum()); obs=float((a["candidate"]["net"][s:e]-a["b1"]["net"][s:e]).sum())
    if not math.isclose(obs,market-fee,abs_tol=1e-12): raise ValueError("decomposition")
    return {"arithmetic_net_delta":obs,"exposure_market_return_delta":market,"incremental_fees":fee,"candidate_only_hours":float(np.maximum(ld,0).sum()),"b1_only_full_exposure_equivalent_hours":float(np.maximum(-ld,0).sum()),"market_return_removed":float((np.maximum(-ld,0)*a["candidate"]["market"][s:e]).sum())}

def _forward_stats(indices,market,e,h):
    vals=[]
    for j in indices:
        if j+h<=e: vals.append(float(market[j:j+h].sum()))
    return {"horizon_hours":h,"count":len(vals),"mean":float(np.mean(vals)) if vals else None,"median":float(np.median(vals)) if vals else None,"positive_share":float(np.mean(np.array(vals)>0)) if vals else None}

def _episodes(mask,market,s,e):
    x=np.asarray(mask,bool); starts=np.flatnonzero(x & ~np.r_[False,x[:-1]]); ends=np.flatnonzero(x & ~np.r_[x[1:],False])+1; out=[]
    for aa,bb in zip(starts,ends):
        out.append({"start":int(s+aa),"end":int(s+bb),"hours":int(bb-aa),"market_return":float(market[s+aa:s+bb].sum())})
    hours=sum(z["hours"] for z in out); absret=sum(abs(z["market_return"]) for z in out)
    return {"count":len(out),"positive_market_return_episodes":sum(z["market_return"]>0 for z in out),"negative_market_return_episodes":sum(z["market_return"]<0 for z in out),"largest_duration_concentration":max((z["hours"] for z in out),default=0)/hours if hours else None,"largest_abs_return_concentration":max((abs(z["market_return"]) for z in out),default=0)/absret if absret else None}

def _event_sample(events,a,p,span):
    s,e=span; es=[x for x in events if s<=x["execution"]<e]; eligible=[x for x in es if x["base"] and not x["onset"]]
    risk=[x for x in eligible if bool(x["risk_trigger"])]; rec=[x for x in eligible if bool(x["recovery_trigger"])]
    er=[x for x in risk if x["effective_transition"]]; ec=[x for x in rec if x["effective_transition"]]
    rr=[x for x in risk if not x["effective_transition"]]; rc=[x for x in rec if not x["effective_transition"]]
    event_map={int(x["execution"]):x for x in es}; attr={k:0. for k in ("onset_entry","base_exit","risk_to_half","recovery_to_full","other")}
    for j in range(s,e):
        tv=float(a["candidate"]["turn"][j])
        if tv==0: continue
        x=event_map.get(j)
        if x is None: attr["other"]+=tv
        elif x["event"]=="onset_entry": attr["onset_entry"]+=tv
        elif x["event"]=="base_exit": attr["base_exit"]+=tv
        elif x["event"]=="risk_trigger": attr["risk_to_half"]+=tv
        elif x["event"]=="recovery_trigger": attr["recovery_to_full"]+=tv
        else: attr["other"]+=tv
    total=float(a["candidate"]["turn"][s:e].sum())
    if not math.isclose(sum(attr.values()),total,abs_tol=1e-12): raise ValueError("turnover attribution")
    half=p["candidate"][s:e]==.5; full=p["candidate"][s:e]==1.; b1=p["b1"][s:e]==1.; market=a["candidate"]["market"]
    def cond(mask):
        z=market[s:e][mask]
        return {"hours":int(mask.sum()),"arithmetic_market_return":float(z.sum()),"mean_hourly_return":float(z.mean()) if len(z) else None,"annualized_conditional_sharpe":sharpe(z) if len(z)>1 else None}
    return {"daily_decisions":len(es),"eligible_positive_trend_decisions":len(eligible),"raw_risk_trigger_decisions":len(risk),"raw_recovery_trigger_decisions":len(rec),"effective_risk_transitions":len(er),"effective_recovery_transitions":len(ec),"repeated_same_state_risk_triggers":len(rr),"repeated_same_state_recovery_triggers":len(rc),"raw_risk_frequency":len(risk)/len(eligible) if eligible else None,"raw_recovery_frequency":len(rec)/len(eligible) if eligible else None,"effective_transition_frequency":(len(er)+len(ec))/len(eligible) if eligible else None,"effective_risk_forward":{"24h":_forward_stats([x["execution"] for x in er],market,e,24),"168h":_forward_stats([x["execution"] for x in er],market,e,168)},"effective_recovery_forward":{"24h":_forward_stats([x["execution"] for x in ec],market,e,24),"168h":_forward_stats([x["execution"] for x in ec],market,e,168)},"exposure_states":{"half":cond(half),"full":cond(full),"cash_hours":int((p["candidate"][s:e]==0).sum()),"b1_long_hours":int(b1.sum()),"half_share_of_b1_long_hours":float(half.sum()/b1.sum()) if b1.sum() else None},"half_state_episodes":_episodes(half,market,s,e),"turnover_attribution":attr,"turnover_reconstructed":total}

def diagnostics(d,p,a,events):
    s,e=OOS; folds=[]
    for k in range(12):
        a0=s+k*FOLD; b0=a0+FOLD; cr=float(np.prod(1+a["candidate"]["net"][a0:b0])-1); br=float(np.prod(1+a["b1"]["net"][a0:b0])-1); folds.append({"fold":k+1,"candidate":cr,"b1":br,"delta":cr-br})
    years=d.index[:-1].year; yc={}
    for y in sorted(set(years[s:e])):
        z=years[s:e]==y; cr=float(np.prod(1+a["candidate"]["net"][s:e][z])-1); br=float(np.prod(1+a["b1"]["net"][s:e][z])-1); yc[str(y)]={"candidate":cr,"b1":br,"delta":cr-br}
    return {"training_state_diagnostics":_event_sample(events,a,p,TRAIN),"oos_state_diagnostics":_event_sample(events,a,p,OOS),"candidate_vs_b1":decomposition(a,p),"fold_comparison_vs_b1":folds,"folds_improved_vs_b1":sum(x["delta"]>0 for x in folds),"year_comparison_vs_b1":yc,"years_improved_vs_b1":sum(x["delta"]>0 for x in yc.values()),"identity_checks":{"position_containment":True,"fee":True,"decomposition":True,"turnover_attribution":True}}

def protocol(issue=685):
    return {"family_id":"signed-volume-flow-persistence-risk-state-1h-v1","issue":issue,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","bar":"1H","canonical_fee_one_way":FEE,"candidate_count":1,"parameter_grid_count":0,"sources":{m:{"artifact_id":ART[m],"csv_sha256":HASH[m],"provider":"OKX public confirmed SPOT"} for m in HASH},"sample":{"parsed_prefix_bars":N,"warmup":[0,2880],"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"folds":12,"fold_hours":FOLD,"later_suffix_unread":True},"feature":{"hourly_sign":"sign(log(close_i/close_(i-1)))","flow168":"sum(volume_quote_i*hourly_sign_i)/sum(volume_quote_i) over [t-167,t]","flow168_prev":"same over [t-335,t-168]","risk":"flow168<0 and flow168<flow168_prev","recovery":"flow168>0 and flow168>flow168_prev"},"policy":{"decision_cadence":"daily completed 00:00 UTC","execution":"next hourly open","base":"close_t > close_(t-2160)","onset_exposure":1.0,"risk_exposure":0.5,"recovery_exposure":1.0,"ambiguous":"retain state","base_exit":0.0,"fees":"5 bps per absolute exposure change"},"uncertainty":{"resamples":R,"block_hours":BLOCK,"paired_non_circular":True,"seed":SEED}}

def run(d,m):
    p,ev=positions(d); a={k:pack(d,v) for k,v in p.items()}; mm={name:{k:metric(a[k],p[k],span) for k in p} for name,span in (("training",TRAIN),("development_oos",OOS),("full_scored",FULL))}; br=breadth(a["candidate"]["net"],d.index); u=boot(a["candidate"]["net"],a["b1"]["net"]); rs=sharpe(a["candidate"]["net"][OOS[0]:OOS[1]]-a["b1"]["net"][OOS[0]:OOS[1]]); c=mm["development_oos"]["candidate"]; b=mm["development_oos"]["b1"]
    g={"positive_oos_net":c["net_return"]>0,"positive_oos_sharpe":c["sharpe"] is not None and c["sharpe"]>0,"net_at_least_b1":c["net_return"]>=b["net_return"],"sharpe_at_least_b1":c["sharpe"] is not None and c["sharpe"]>=b["sharpe"],"drawdown_no_worse_b1":c["max_drawdown"]>=b["max_drawdown"],"turnover_no_greater_b1":c["turnover"]<=b["turnover"],"edge_per_turnover_at_least_b1":c["edge_per_turnover_bps"] is not None and c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],"profitable_folds_at_least_7":br["profitable_folds"]>=7,"profitable_years_at_least_3":br["profitable_years"]>=3,"positive_residual_sharpe":rs is not None and rs>0,"positive_mean_delta_lower_95":u["annualized_mean_delta"]["lower_95"]>0,"positive_sharpe_delta_lower_95":u["sharpe_delta"]["lower_95"]>0,"positive_fold_concentration_at_most_half":br["positive_fold_concentration"] is not None and br["positive_fold_concentration"]<=.5,"positive_full_scored_net":mm["full_scored"]["candidate"]["net_return"]>0}
    return {"market":m,"source_artifact":ART[m],"source_sha256":HASH[m],"metrics":mm,"breadth":br,"residual_sharpe_vs_b1":rs,"uncertainty":u,"gates":g,"accepted":all(g.values()),"diagnostics":diagnostics(d,p,a,ev)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--btc",type=Path,required=True); ap.add_argument("--eth",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); z=ap.parse_args(); z.out.mkdir(parents=True,exist_ok=True)
    markets={"BTC-USDT":run(load(z.btc,"BTC-USDT"),"BTC-USDT"),"ETH-USDT":run(load(z.eth,"ETH-USDT"),"ETH-USDT")}; ok=all(v["accepted"] for v in markets.values()); res={"protocol":protocol(),"markets":markets,"bilateral_accepted":ok,"verdict":"accept_signed_volume_flow_persistence_risk_state_family" if ok else "reject_exact_signed_volume_flow_persistence_risk_state_family","repaired_discrepancy":"The first diagnostic pooled raw trigger observations with economically effective state changes. Terminal evidence separates repeated same-state triggers from actual risk/recovery transitions and exactly reconstructs turnover; no signal, position, fee, metric, gate or verdict changed.","remaining_blocker":"The flow state is not bilaterally transportable and creates excessive transitions: it removes profitable BTC carry, while ETH's compounding and drawdown improvement is not supported by arithmetic mean, fold breadth, turnover efficiency or dependence-aware lower bounds.","next_experiment":"One own-history-only four-phase daily trend ensemble: evaluate the unchanged 2,160H endpoint trend on fixed 00:00, 06:00, 12:00 and 18:00 UTC decision phases and set unlevered exposure to the fraction of positive phase states; one candidate, no fitted threshold, no grid or market-specific rule."}
    text=json.dumps(nat(res),indent=2,sort_keys=True,allow_nan=False)+"\n"; (z.out/"result.json").write_text(text); (z.out/"protocol.json").write_text(json.dumps(nat(protocol()),indent=2,sort_keys=True)+"\n"); print(text)
if __name__=="__main__": main()
