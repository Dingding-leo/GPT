# ruff: noqa
# fmt: off
"""Reproduce issue #679 from immutable public OKX 1H candles."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=5e-4; ANN=8760.; W=2160; VOL_W=720; MAD_SCALE=1.4826; N=43441; FOLD=2160
TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); SEED=20260730; BLOCK=168; RESAMPLES=5000
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
ART={"BTC-USDT":8704977298,"ETH-USDT":8704978112}


def native(x):
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,)): return float(x)
    if isinstance(x,np.ndarray): return x.tolist()
    if isinstance(x,dict): return {str(k):native(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [native(v) for v in x]
    return x


def load(path:Path,m:str)->pd.DataFrame:
    raw=path.read_bytes(); got=hashlib.sha256(raw).hexdigest()
    if got!=HASH[m]: raise ValueError(f"{m} hash {got}")
    d=pd.read_csv(path,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True))
    x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
    ok=(len(d)==N and t.equals(pd.date_range(t[0],periods=N,freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all())
    if not ok: raise ValueError(f"{m} invalid source")
    d.index=t; return d


def robust_scale(logret:np.ndarray,t:int):
    z=logret[t-VOL_W+1:t+1]
    if len(z)!=VOL_W or not np.isfinite(z).all(): raise ValueError("invalid robust window")
    med=float(np.median(z)); sigma=float(MAD_SCALE*np.median(np.abs(z-med))); budget=float(math.sqrt(VOL_W)*sigma)
    return med,sigma,budget


def positions(d:pd.DataFrame):
    n=len(d); close=d.close.to_numpy(float); logret=np.empty(n); logret[0]=np.nan; logret[1:]=np.log(close[1:]/close[:-1])
    p={k:np.zeros(n-1) for k in ("candidate","b0","b1")}
    c=b0=b1=0.; prev_daily_base=False; onset=None; onset_close=None; peak_close=None; locked=False
    rows=[]; regimes=[]; active=None
    for t in range(W,n-1):
        base=bool(close[t]>close[t-W]); b0=float(base)
        if d.index[t].hour==0:
            prev_c=c; event="hold"; onset_flag=base and not prev_daily_base
            med=sigma=budget=regime_ret=adverse=ratio=None; failed=False
            if not base:
                if active is not None:
                    active["end_decision"]=t; active["base_exit"]=True; regimes.append(active); active=None
                c=0.; onset=None; onset_close=None; peak_close=None; locked=False; event="base_exit" if prev_c>0 else "base_nonpositive"
            elif onset_flag:
                if active is not None: raise ValueError("overlapping regime")
                onset=t; onset_close=float(close[t]); peak_close=float(close[t]); locked=False; c=1.; event="onset_entry"
                med,sigma,budget=robust_scale(logret,t); regime_ret=0.; adverse=0.; ratio=0. if budget>0 else None
                active={"onset_decision":t,"onset_execution":t+1,"onset_close":onset_close,"peak_close_max":peak_close,"loss_budget_exit_decision":None,"loss_budget_exit_execution":None,"base_exit":False,"end_decision":None}
            else:
                if onset is None or active is None or onset_close is None or peak_close is None: raise ValueError("positive regime missing onset")
                peak_close=max(peak_close,float(close[t])); active["peak_close_max"]=peak_close
                med,sigma,budget=robust_scale(logret,t); regime_ret=float(math.log(close[t]/onset_close)); adverse=float(math.log(peak_close/close[t])); ratio=float(adverse/budget) if budget>0 else (math.inf if adverse>0 else 0.)
                failed=bool(adverse>budget and regime_ret<=0)
                if locked:
                    c=0.; event="locked_out"
                elif failed:
                    c=0.; locked=True; event="loss_budget_exit"
                    active.update({"loss_budget_exit_decision":t,"loss_budget_exit_execution":t+1,"exit_age_hours":t-onset,"exit_close":float(close[t]),"exit_peak_close":peak_close,"exit_regime_return":regime_ret,"exit_adverse_excursion":adverse,"exit_median_return":med,"exit_robust_sigma":sigma,"exit_loss_budget":budget,"exit_adverse_budget_ratio":ratio})
                else:
                    c=1.; event="hold_long"
            b1=float(base)
            rows.append({"decision":t,"execution":t+1,"base":base,"prev_daily_base":prev_daily_base,"onset":onset_flag,"onset_decision":onset,"age_hours":None if onset is None else t-onset,"onset_close":onset_close,"peak_close":peak_close,"current_close":float(close[t]),"median_return":med,"robust_sigma":sigma,"loss_budget":budget,"regime_return":regime_ret,"adverse_excursion":adverse,"adverse_budget_ratio":ratio,"failed":failed,"locked_before":bool(locked and event=="locked_out"),"locked_after":locked,"prev_candidate":prev_c,"candidate":c,"b1":b1,"event":event})
            prev_daily_base=base
        if t+1<n-1:
            p["candidate"][t+1]=c; p["b0"][t+1]=b0; p["b1"][t+1]=b1
    if active is not None:
        active["end_decision"]=n-1; active["base_exit"]=False; regimes.append(active)
    if np.any(p["candidate"]>p["b1"]+1e-15): raise ValueError("candidate exceeds B1")
    return p,rows,regimes


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
    c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(SEED); md=np.empty(RESAMPLES); sd=np.empty(RESAMPLES); off=np.arange(BLOCK); blocks=math.ceil(n/BLOCK)
    for q in range(0,RESAMPLES,100):
        idx=(rng.integers(0,n-BLOCK+1,size=(100,blocks))[:,:,None]+off).reshape(100,-1)[:,:n]; cs=c[idx]; bs=b[idx]; cm=cs.mean(1); bm=bs.mean(1); cv=cs.std(1,ddof=1); bv=bs.std(1,ddof=1)
        md[q:q+100]=ANN*(cm-bm); sd[q:q+100]=np.divide(math.sqrt(ANN)*cm,cv,out=np.zeros(100),where=cv>0)-np.divide(math.sqrt(ANN)*bm,bv,out=np.zeros(100),where=bv>0)
    return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((shp(c) or 0)-(shp(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}


def span_overlap(start,stop,span): return max(start,span[0]),min(stop,span[1])


def quantiles(vals):
    a=np.asarray(vals,float)
    return None if len(a)==0 else {"count":int(len(a)),"min":float(np.min(a)),"q10":float(np.quantile(a,.1)),"median":float(np.median(a)),"q90":float(np.quantile(a,.9)),"max":float(np.max(a)),"mean":float(np.mean(a))}


def state_summary(rows,span):
    s,e=span; rr=[r for r in rows if s<=r["execution"]<e and r["base"]]
    unlocked=[r for r in rr if not r["locked_before"]]
    complete=[r for r in rr if r["loss_budget"] is not None and r["adverse_excursion"] is not None]
    eligible=[r for r in complete if not r["locked_before"]]
    joint_all=sum(bool(r["failed"]) for r in complete); joint_eligible=sum(bool(r["failed"]) for r in eligible)
    return {
        "positive_base_decisions":len(rr),"unlocked_positive_base_decisions":len(unlocked),"locked_positive_base_decisions":len(rr)-len(unlocked),"complete_feature_decisions":len(complete),"eligible_feature_decisions":len(eligible),
        "adverse_exceeds_budget_all":sum(bool(r["adverse_excursion"]>r["loss_budget"]) for r in complete),
        "adverse_exceeds_budget_eligible":sum(bool(r["adverse_excursion"]>r["loss_budget"]) for r in eligible),
        "regime_nonpositive_all":sum(bool(r["regime_return"]<=0) for r in complete),
        "regime_nonpositive_eligible":sum(bool(r["regime_return"]<=0) for r in eligible),
        "joint_condition_all":joint_all,
        "joint_condition_eligible":joint_eligible,
        "joint_condition_repeated_while_locked":joint_all-joint_eligible,
        "loss_budget":quantiles([r["loss_budget"] for r in eligible]),
        "adverse_excursion":quantiles([r["adverse_excursion"] for r in eligible]),
        "adverse_budget_ratio":quantiles([r["adverse_budget_ratio"] for r in eligible if r["adverse_budget_ratio"] is not None and np.isfinite(r["adverse_budget_ratio"])]),
        "regime_return":quantiles([r["regime_return"] for r in eligible]),
    }


def diagnostics(d,rows,regimes,p,a):
    s,e=OOS; c=p["candidate"][s:e]; b=p["b1"][s:e]; m=a["candidate"]["market"][s:e]
    fee=float(a["candidate"]["fees"][s:e].sum()-a["b1"]["fees"][s:e].sum()); exposure=float(((c-b)*m).sum()); observed=float((a["candidate"]["net"][s:e]-a["b1"]["net"][s:e]).sum())
    if not math.isclose(observed,exposure-fee,abs_tol=1e-12): raise ValueError("decomposition")
    candidate_only=np.maximum(c-b,0); b1_only=np.maximum(b-c,0)
    if candidate_only.sum()!=0: raise ValueError("unexpected candidate-only exposure")
    exit_rows=[r for r in rows if r["event"]=="loss_budget_exit"]
    def fwd_stats(h):
        vals=[]
        for r in exit_rows:
            x=r["execution"]
            if s<=x<e and x+h<=e: vals.append(float(np.prod(1+a["candidate"]["market"][x:x+h])-1))
        return dict(events=len(vals),mean=float(np.mean(vals)) if vals else None,positive_rate=float(np.mean(np.array(vals)>0)) if vals else None,values=vals)
    regime_stats=[]; outcomes={"improved":0,"tied":0,"worse":0}; failed_outcomes={"improved":0,"tied":0,"worse":0}; started=0
    for rg in regimes:
        start=rg["onset_execution"]; stop=min(rg["end_decision"]+1,len(p["candidate"])); os,oe=span_overlap(start,stop,OOS)
        if oe<=os: continue
        started_in_oos=OOS[0]<=rg["onset_decision"]<OOS[1]; started+=int(started_in_oos)
        cand=float(a["candidate"]["net"][os:oe].sum()); base=float(a["b1"]["net"][os:oe].sum()); delta=cand-base
        outcome="tied" if math.isclose(delta,0.0,abs_tol=1e-15) else ("improved" if delta>0 else "worse"); outcomes[outcome]+=1
        lock_start=rg["loss_budget_exit_execution"] if rg["loss_budget_exit_execution"] is not None else stop; ls,le=span_overlap(lock_start,stop,OOS); lock_hours=max(0,le-ls)
        failed_in_oos=rg["loss_budget_exit_execution"] is not None and OOS[0]<=rg["loss_budget_exit_execution"]<OOS[1]
        if failed_in_oos: failed_outcomes[outcome]+=1
        regime_stats.append({**rg,"started_in_oos":started_in_oos,"loss_budget_exit_in_oos":failed_in_oos,"oos_overlap_hours":oe-os,"candidate_arithmetic_net":cand,"b1_arithmetic_net":base,"arithmetic_net_delta":delta,"outcome":outcome,"lockout_hours_oos":lock_hours,"lockout_market_return_oos":float(a["candidate"]["market"][ls:le].sum()) if lock_hours else 0.0})
    failed_oos=[r for r in exit_rows if s<=r["execution"]<e]
    event_counts={}
    for r in rows:
        if s<=r["execution"]<e: event_counts[r["event"]]=event_counts.get(r["event"],0)+1
    lockmask=np.zeros(len(p["candidate"]))
    for rg in regimes:
        if rg["loss_budget_exit_execution"] is not None:
            stop=min(rg["end_decision"]+1,len(lockmask)); lockmask[rg["loss_budget_exit_execution"]:stop]=1
    actual=np.maximum(p["b1"]-p["candidate"],0)
    if not np.array_equal(lockmask,actual): raise ValueError("lockout attribution")
    transitions={}; pp=p["candidate"]
    for i in range(1,len(pp)):
        if pp[i]!=pp[i-1]:
            key=f"{pp[i-1]:g}->{pp[i]:g}"; transitions[key]=transitions.get(key,0.0)+abs(pp[i]-pp[i-1])
    exit_fields=("decision","execution","age_hours","onset_close","peak_close","current_close","regime_return","adverse_excursion","median_return","robust_sigma","loss_budget","adverse_budget_ratio")
    affected=[x for x in regime_stats if x["loss_budget_exit_in_oos"]]
    return dict(oos_loss_budget_exits=len(failed_oos),loss_budget_exit_records=[{k:r[k] for k in exit_fields} for r in failed_oos],forward_after_exit_24h=fwd_stats(24),forward_after_exit_168h=fwd_stats(168),oos_event_counts=event_counts,oos_affected_regimes=affected,oos_regimes_overlapping=len(regime_stats),oos_regimes_started=started,oos_regime_outcomes_vs_b1=outcomes,oos_exit_regime_outcomes_vs_b1=failed_outcomes,b1_only_exposure_hours=float(b1_only.sum()),candidate_only_exposure_hours=float(candidate_only.sum()),b1_only_market_return=float((b1_only*m).sum()),candidate_only_market_return=float((candidate_only*m).sum()),exposure_delta_market_arithmetic_return=exposure,incremental_fees_candidate_minus_b1=fee,observed_arithmetic_net_delta=observed,candidate_transition_turnover=transitions,state_summary_training=state_summary(rows,TRAIN),state_summary_oos=state_summary(rows,OOS),lockout_attribution_identity_passes=True,decomposition_identity_passes=True)


def run(d,m):
    p,rows,regimes=positions(d); a={k:packed(d,v) for k,v in p.items()}
    mm={name:{k:metrics(a[k],p[k],span) for k in p} for name,span in (("training",TRAIN),("development_oos",OOS),("full_scored",FULL))}
    br=breadth(a["candidate"]["net"],d.index); u=bootstrap(a["candidate"]["net"],a["b1"]["net"]); rs=shp(a["candidate"]["net"][OOS[0]:OOS[1]]-a["b1"]["net"][OOS[0]:OOS[1]])
    c=mm["development_oos"]["candidate"]; b=mm["development_oos"]["b1"]
    gates=dict(positive_oos_net=c["net_return"]>0,positive_oos_sharpe=c["sharpe"] is not None and c["sharpe"]>0,net_at_least_b1=c["net_return"]>=b["net_return"],sharpe_at_least_b1=c["sharpe"] is not None and c["sharpe"]>=b["sharpe"],drawdown_no_worse_b1=c["max_drawdown"]>=b["max_drawdown"],turnover_no_greater_b1=c["turnover"]<=b["turnover"],edge_per_turnover_at_least_b1=c["edge_per_turnover_bps"] is not None and c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],profitable_folds_at_least_7=br["profitable_folds"]>=7,profitable_years_at_least_3=br["profitable_years"]>=3,positive_residual_sharpe=rs is not None and rs>0,positive_mean_delta_lower_95=u["annualized_mean_delta"]["lower_95"]>0,positive_sharpe_delta_lower_95=u["sharpe_delta"]["lower_95"]>0,positive_fold_concentration_at_most_half=br["positive_fold_concentration"] is not None and br["positive_fold_concentration"]<=.5,positive_full_scored_net=mm["full_scored"]["candidate"]["net_return"]>0)
    return dict(market=m,source_artifact=ART[m],source_sha256=HASH[m],metrics=mm,breadth=br,residual_sharpe_vs_b1=rs,uncertainty=u,gates=gates,accepted=all(gates.values()),diagnostics=diagnostics(d,rows,regimes,p,a))


def protocol():
    return {"family_id":"trend-onset-loss-budget-exit-1h-v1","issue":679,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","bar":"1H","canonical_fee_one_way":FEE,"candidate_count":1,"parameter_grid_count":0,"sources":{m:{"artifact_id":ART[m],"csv_sha256":HASH[m],"provider":"OKX public confirmed SPOT"} for m in HASH},"sample":{"parsed_prefix_bars":N,"warmup":[0,2880],"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"folds":12,"fold_hours":FOLD,"later_suffix_unread":True},"feature":{"base":"close_t > close_(t-2160)","onset":"first positive daily base decision after a non-positive daily base decision","peak_close":"highest completed daily decision close since onset","hourly_log_return":"log(close_i/close_(i-1))","robust_sigma":"1.4826 * median absolute deviation of trailing 720 completed hourly log returns","loss_budget":"sqrt(720) * robust_sigma","regime_return":"log(close_t/onset_close)","adverse_excursion":"log(peak_close_t/close_t)","failed":"adverse_excursion > loss_budget and regime_return <= 0"},"policy":{"decision_cadence":"daily completed 00:00 UTC","execution":"next hourly open","entry":"immediate at every new positive base-trend onset","loss_budget_exit":"first failed state, with no grace period","reentry":"only after a later distinct onset following non-positive base","base_exit":"immediate cash when base non-positive","exposure_states":[0,1],"fees":"5 bps per absolute exposure change"},"uncertainty":{"resamples":RESAMPLES,"block_hours":BLOCK,"paired_non_circular":True,"seed":SEED}}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--btc",type=Path,required=True); ap.add_argument("--eth",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); z=ap.parse_args(); z.out.mkdir(parents=True,exist_ok=True)
    markets={"BTC-USDT":run(load(z.btc,"BTC-USDT"),"BTC-USDT"),"ETH-USDT":run(load(z.eth,"ETH-USDT"),"ETH-USDT")}; accepted=all(v["accepted"] for v in markets.values())
    result={"protocol":protocol(),"markets":markets,"bilateral_accepted":accepted,"verdict":"accept_trend_onset_loss_budget_exit_family" if accepted else "reject_exact_trend_onset_loss_budget_exit_family","repaired_discrepancy":"The first diagnostic counted the joint loss-budget condition on every positive-trend decision, including mechanically repeated observations after the strategy had already exited and become locked. The terminal diagnostic separates unlocked eligible decisions, first actionable exits, and repeated post-lock conditions. No signal, position, fee, return, benchmark, uncertainty result, acceptance gate or verdict changed.","remaining_blocker":"volatility-scaled adverse excursion identifies short-horizon weakness but an irreversible same-regime lockout still removes profitable ETH recovery; BTC remains promising in aggregate but lacks fold breadth and uncertainty-supported superiority.","next_experiment":"Preregister one own-history-only bounded recovery re-entry architecture: retain immediate onset entry and the same frozen loss-budget exit, but permit at most one same-regime re-entry only after the completed daily close is back above the onset close and the latest 168H return is positive; after re-entry, hold until the base-trend exit. One candidate, no grid and no market-specific rule."}
    result=native(result); text=json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n"; (z.out/"result.json").write_text(text); (z.out/"protocol.json").write_text(json.dumps(native(protocol()),indent=2,sort_keys=True)+"\n"); print(text)

if __name__=="__main__": main()
