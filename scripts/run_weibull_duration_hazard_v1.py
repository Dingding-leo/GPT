#!/usr/bin/env python3
# ruff: noqa
# fmt: off
"""Reproduce issue #599's frozen Weibull duration-hazard verdict."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd
FEE=.0005; ANN=8760.; TRAIN=2880; OOS=17520; STOP=43440; FOLD=2160; DIR=168; W=2160; HOLD=168; H=168
MBOOT=1000; UBOOT=5000; BLOCK=168; SEED=20260729; MAIN="5a0fcc97d1a882f8223656c51f5bb8055f534e38"; ISSUE=599
FAMILY="weibull-duration-hazard-continuation-1h-v1"
SOURCES={"BTC-USDT":{"artifact_id":8704977298,"zip_sha256":"22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c","csv_sha256":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9"},"ETH-USDT":{"artifact_id":8704978112,"zip_sha256":"e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3","csv_sha256":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}}
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 return h.hexdigest()
def sh(x):
 s=float(np.std(x,ddof=1)); return float(np.mean(x)/s*math.sqrt(ANN)) if s>0 else None
def met(n,t,p):
 e=np.cumprod(1+n); q=np.r_[1.,e]; d=q/np.maximum.accumulate(q)-1; z=float(t.sum())
 return {"net_total_return":float(e[-1]-1),"sharpe":sh(n),"max_drawdown":float(d.min()),"turnover":z,"fee_sum":z*FEE,"net_edge_per_turnover_bps":float(n.sum()/z*1e4) if z else None,"average_exposure":float(p.mean())}
def eq(k,l):
 a=k*l; a-=a.max(); w=np.exp(a); return 1/k+float(l.mean())-float((w*l).sum()/w.sum())
def fit(x):
 x=np.asarray(x,float); l=np.log(x); lo,hi=.05,20.; flo,fhi=eq(lo,l),eq(hi,l)
 if len(x)<2 or not(flo>0>fhi): raise ValueError("bad Weibull fit")
 for _ in range(100):
  m=(lo+hi)/2
  if eq(m,l)>0: lo=m
  else: hi=m
 k=(lo+hi)/2; a=k*l; m=float(a.max()); lam=math.exp((m+math.log(float(np.mean(np.exp(a-m)))))/k)
 return float(k),float(lam)
def spells(z,a,b):
 out=[]; s=None
 for i in range(a,b):
  p=bool(z[i-1]) if i else False; c=bool(z[i])
  if c and not p: s=i
  elif not c and p:
   if s is not None and s>=a: out.append(i-s)
   s=None
 return np.asarray(out,float)
def ages(z):
 out=np.zeros(len(z),int); a=0
 for i,c in enumerate(z):
  if c: a=a+1 if i and z[i-1] else 1; out[i]=a
  else: a=0
 return out
def surv(a,k,l): return np.exp(np.clip(-(((a+H)/l)**k-(a/l)**k),-745,0))
def model(d):
 if len(d)<20: raise ValueError("fewer than 20 completed spells")
 k,l=fit(d); r=np.random.default_rng(SEED); pars=[]
 for _ in range(MBOOT):
  try: pars.append(fit(r.choice(d,len(d),replace=True)))
  except ValueError: pass
 if not pars: raise ValueError("no valid bootstrap fits")
 p=np.asarray(pars,float); return k,l,p
def boot(a,b):
 n=len(a); c=math.ceil(n/BLOCK); lens=np.full(c,BLOCK,int); lens[-1]=n-BLOCK*(c-1); r=np.random.default_rng(SEED); md=np.empty(UBOOT); sd=np.empty(UBOOT)
 for j in range(UBOOT):
  s=np.asarray([r.integers(0,n-L+1) for L in lens]); ix=np.concatenate([np.arange(x,x+L) for x,L in zip(s,lens)]); aa=a[ix]; bb=b[ix]; md[j]=float(np.mean(aa-bb)*ANN); sd[j]=float((sh(aa) or 0)-(sh(bb) or 0))
 return {"annualized_mean_delta_lower_95":float(np.quantile(md,.025)),"annualized_mean_delta_median":float(np.quantile(md,.5)),"sharpe_delta_lower_95":float(np.quantile(sd,.025)),"sharpe_delta_median":float(np.quantile(sd,.5))}
def path(p,r):
 prior=np.r_[0.,p[:-1]]; t=np.abs(p-prior); g=p*r; return {"position":p,"turn":t,"gross":g,"net":g-FEE*t}
def evaluate(inst,zp,cp):
 src=SOURCES[inst]
 if sha(zp)!=src["zip_sha256"] or sha(cp)!=src["csv_sha256"]: raise ValueError("hash mismatch")
 df=pd.read_csv(cp); ts=pd.DatetimeIndex(pd.to_datetime(df.timestamp,utc=True)); px=df[["open","high","low","close"]].to_numpy(float)
 if len(df)!=43941 or not(df.confirm==1).all() or ts.has_duplicates or not ts.is_monotonic_increasing or not np.all(np.diff(ts.view("int64"))==3600_000_000_000) or not np.isfinite(px).all() or not(px>0).all(): raise ValueError("invalid 1H grid")
 close=df.close.to_numpy(float); op=df.open.to_numpy(float); lc=np.log(close); dr=np.full(len(df),np.nan); dr[DIR:]=lc[DIR:]-lc[:-DIR]; tr=np.full(len(df),np.nan); tr[W:]=lc[W:]-lc[:-W]; state=np.isfinite(dr)&(dr>0); age=ages(state); dur=spells(state,TRAIN,OOS); k,l,pars=model(dur)
 ua=np.unique(age[(np.arange(len(age))<STOP)&state]); lcb={int(a):float(np.quantile(surv(int(a),pars[:,0],pars[:,1]),.1)) for a in ua}; elig=sorted(a for a in lcb if lcb[a]>.5); mx=max(lcb,key=lcb.get)
 payoff=op[2:STOP+2]/op[1:STOP+1]-1; cand=np.zeros(STOP); d0=np.zeros(STOP); b0=np.zeros(STOP); b1=np.zeros(STOP); cs=ds=b1s=0.; ce=de=None
 for i in range(STOP):
  if i>=W: b0[i]=float(tr[i]>0)
  if ts[i].hour==0:
   if i>=W: b1s=float(tr[i]>0)
   if i>=TRAIN:
    q=lcb.get(int(age[i]),0.) if state[i] else 0.
    if cs==0 and state[i] and q>.5: cs=1.; ce=i
    elif cs==1 and i-ce>=HOLD and (not state[i] or q<=.5): cs=0.; ce=None
    if ds==0 and state[i]: ds=1.; de=i
    elif ds==1 and i-de>=HOLD and not state[i]: ds=0.; de=None
  cand[i]=cs; d0[i]=ds; b1[i]=b1s
 pp={"candidate":path(cand,payoff),"d0":path(d0,payoff),"b0":path(b0,payoff),"b1":path(b1,payoff)}
 def ms(a,b): return {x:met(q["net"][a:b],q["turn"][a:b],q["position"][a:b]) for x,q in pp.items()}
 train=ms(TRAIN,OOS); oos=ms(OOS,STOP); full=ms(TRAIN,STOP); oc=pp["candidate"]["net"][OOS:STOP]; od=pp["d0"]["net"][OOS:STOP]; ob=pp["b0"]["net"][OOS:STOP]; ots=ts[OOS:STOP]
 folds=[float(np.prod(1+oc[j:j+FOLD])-1) for j in range(0,len(oc),FOLD)]; years={str(y):float(np.prod(1+oc[np.asarray(ots.year)==y])-1) for y in sorted(set(ots.year))}; pos=[max(0,x) for x in folds]; conc=max(pos)/sum(pos) if sum(pos)>0 else None
 prior=np.r_[0.,cand[:-1]]; entries=np.flatnonzero((cand==1)&(prior==0)); exits=np.flatnonzero((cand==0)&(prior==1)); oe=entries[(entries>=OOS)&(entries<STOP)]; holds=[]
 for e in entries:
  x=exits[exits>e]
  if len(x) and e<STOP and x[0]>OOS: holds.append(int(x[0]-e))
 u=boot(oc,od); rd=sh(oc-od); rb=sh(oc-ob); cm=oos["candidate"]; dm=oos["d0"]
 gates={"positive_net_return":cm["net_total_return"]>0,"positive_sharpe":cm["sharpe"] is not None and cm["sharpe"]>0,"positive_edge_per_turnover":cm["net_edge_per_turnover_bps"] is not None and cm["net_edge_per_turnover_bps"]>0,"profitable_folds_at_least_7_of_12":sum(x>0 for x in folds)>=7,"profitable_year_segments_at_least_3":sum(x>0 for x in years.values())>=3,"positive_fold_concentration_at_most_50pct":conc is not None and conc<=.5,"long_entries_at_least_5":len(oe)>=5,"sharpe_exceeds_d0":cm["sharpe"] is not None and dm["sharpe"] is not None and cm["sharpe"]>dm["sharpe"],"edge_per_turnover_exceeds_d0":cm["net_edge_per_turnover_bps"] is not None and dm["net_edge_per_turnover_bps"] is not None and cm["net_edge_per_turnover_bps"]>dm["net_edge_per_turnover_bps"],"positive_residual_sharpe_vs_d0":rd is not None and rd>0,"positive_residual_sharpe_vs_b0":rb is not None and rb>0,"bootstrap_mean_delta_lower_bound_positive":u["annualized_mean_delta_lower_95"]>0,"bootstrap_sharpe_delta_lower_bound_positive":u["sharpe_delta_lower_95"]>0}
 return {"instrument":inst,"source":src,"grid":{"observations":len(df),"first_timestamp":ts[0].isoformat(),"last_timestamp":ts[-1].isoformat(),"confirmed":True,"contiguous_1h":True},"training_model":{"completed_spell_count":len(dur),"shape":k,"scale":l,"duration_median_hours":float(np.median(dur)),"duration_mean_hours":float(np.mean(dur)),"duration_max_hours":float(np.max(dur)),"bootstrap_requested":MBOOT,"bootstrap_valid":len(pars),"survival_lcb_10pct_at_age_1":lcb.get(1),"survival_lcb_10pct_at_age_168":lcb.get(168),"survival_lcb_10pct_at_age_336":lcb.get(336),"eligible_age_min":min(elig) if elig else None,"eligible_age_max":max(elig) if elig else None,"eligible_age_count":len(elig),"max_observed_age_scored":int(max(ua)),"max_survival_lcb_scored":lcb[mx],"age_at_max_survival_lcb_scored":mx},"train_metrics":train,"oos_metrics":oos,"full_metrics":full,"residual_sharpe_vs_d0":rd,"residual_sharpe_vs_b0":rb,"breadth":{"fold_returns":folds,"profitable_folds":sum(x>0 for x in folds),"fold_count":len(folds),"positive_fold_return_concentration":conc,"year_returns":years,"profitable_years":sum(x>0 for x in years.values()),"year_count":len(years)},"position":{"long_entries_oos":len(oe),"median_completed_holding_hours":float(np.median(holds)) if holds else None,"mean_completed_holding_hours":float(np.mean(holds)) if holds else None,"max_completed_holding_hours":max(holds) if holds else None},"uncertainty_vs_d0":u,"acceptance_gates":gates,"accepted":all(gates.values())}
def protocol(): return {"schema_version":1,"issue":ISSUE,"main":MAIN,"family_id":FAMILY,"bar":"1H","candidate_count":1,"parameter_grid_count":0,"markets":["BTC-USDT","ETH-USDT"],"per_instrument_only":True,"cross_sectional_selection":False,"execution":"completed confirmed bar t; target at open[t+1]; payoff open[t+1] to open[t+2]","fee":{"component":"exchange_fee","one_way_bps":5.,"applied_to":"absolute_position_change"},"signal":{"direction_hours":DIR,"decision_hour_utc":0,"minimum_holding_hours":HOLD,"position_set":[0,1],"duration_distribution":"two_parameter_weibull_completed_training_spells","duration_fit_shape_bracket":[.05,20.],"survival_horizon_hours":H,"model_bootstraps":MBOOT,"model_bootstrap_seed":SEED,"survival_lcb_quantile":.1,"entry_exit_probability":.5},"samples":{"warmup":[0,TRAIN],"descriptive_training":[TRAIN,OOS],"development_oos":[OOS,STOP],"fold_hours":FOLD,"later_suffix_unscored":True},"comparators":{"d0":"168H direction, daily 00:00 UTC cadence, 168H minimum hold, no duration gate","b0":"2160H close-to-close trend, hourly updates","b1":"2160H close-to-close trend, daily 00:00 UTC updates"},"bootstrap":{"method":"paired_non_circular_moving_block","block_hours":BLOCK,"resamples":UBOOT,"seed":SEED},"sources":SOURCES,"untouched_oos_consumed":False,"rescue_tuning_authorized":False,"paper_or_live_authorized":False}
def report(r):
 L=["# Weibull duration-hazard continuation — frozen development result","",f"Verdict: `{r['verdict']}`","","One preregistered own-history-only causal 1H candidate was evaluated independently on BTC-USDT and ETH-USDT using exactly 5 bps one-way exchange fees.","","## Training duration models","","| Market | Spells | Shape | Scale H | Median H | LCB age1 | LCB age168 | Max scored LCB | Eligible ages |","|---|---:|---:|---:|---:|---:|---:|---:|---|"]
 for m in r["markets"]:
  x=m["training_model"]; rg=f"{x['eligible_age_min']}..{x['eligible_age_max']}" if x["eligible_age_min"] is not None else "none"; L.append(f"| {m['instrument']} | {x['completed_spell_count']} | {x['shape']:.6f} | {x['scale']:.3f} | {x['duration_median_hours']:.1f} | {x['survival_lcb_10pct_at_age_1']:.4f} | {x['survival_lcb_10pct_at_age_168']:.4f} | {x['max_survival_lcb_scored']:.4f} at {x['age_at_max_survival_lcb_scored']}H | {rg} |")
 for key,title in [("train_metrics","Descriptive training"),("oos_metrics","Development OOS"),("full_metrics","Full scored")]:
  L += ["",f"## {title}","","| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |","|---|---|---:|---:|---:|---:|---:|---:|---:|"]
  for m in r["markets"]:
   for p in ["candidate","d0","b0","b1"]:
    x=m[key][p]; ss=f"{x['sharpe']:.3f}" if x["sharpe"] is not None else "undefined"; ee=f"{x['net_edge_per_turnover_bps']:.2f} bps" if x["net_edge_per_turnover_bps"] is not None else "undefined"; L.append(f"| {m['instrument']} | {p.upper()} | {x['net_total_return']:.2%} | {ss} | {x['max_drawdown']:.2%} | {x['turnover']:.0f} | {x['fee_sum']:.2%} | {ee} | {x['average_exposure']:.2%} |")
 L += ["","## OOS breadth and uncertainty","","| Market | Entries | Profitable folds | Profitable years | Concentration | Residual S D0 | Residual S B0 | Mean L95 | Sharpe L95 |","|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
 for m in r["markets"]:
  b=m["breadth"]; u=m["uncertainty_vs_d0"]; c=f"{b['positive_fold_return_concentration']:.2%}" if b["positive_fold_return_concentration"] is not None else "undefined"; L.append(f"| {m['instrument']} | {m['position']['long_entries_oos']} | {b['profitable_folds']}/{b['fold_count']} | {b['profitable_years']}/{b['year_count']} | {c} | {m['residual_sharpe_vs_d0']:.3f} | {m['residual_sharpe_vs_b0']:.3f} | {u['annualized_mean_delta_lower_95']:.6f} | {u['sharpe_delta_lower_95']:.6f} |")
 L += ["","## Failed gates",""]
 for m in r["markets"]: L += [f"### {m['instrument']}","","Failed: "+", ".join(f"`{k}`" for k,v in m["acceptance_gates"].items() if not v),""]
 L += ["## Interpretation","","The training-fitted 10th-percentile conditional 168H survival never exceeded the frozen 0.50 majority boundary at any scored age in either market. The candidate therefore remained cash and the exact confidence rule is rejected without rescue tuning. The untouched OOS remains unread, and no paper or live trading is authorized.",""]
 return "\n".join(L)
def main():
 p=argparse.ArgumentParser(); p.add_argument("--btc-zip",type=Path,required=True); p.add_argument("--btc-csv",type=Path,required=True); p.add_argument("--eth-zip",type=Path,required=True); p.add_argument("--eth-csv",type=Path,required=True); p.add_argument("--output-dir",type=Path,required=True); a=p.parse_args(); a.output_dir.mkdir(parents=True,exist_ok=True); pr=protocol(); ms=[evaluate("BTC-USDT",a.btc_zip,a.btc_csv),evaluate("ETH-USDT",a.eth_zip,a.eth_csv)]; out={**pr,"markets":ms,"verdict":"accept_for_shadow_observation_only" if all(m["accepted"] for m in ms) else "reject_exact_weibull_duration_hazard_family"}; files={"protocol.json":json.dumps(pr,indent=2,sort_keys=True)+"\n","result.json":json.dumps(out,indent=2,sort_keys=True)+"\n","report.md":report(out)}
 for n,c in files.items(): (a.output_dir/n).write_text(c)
 print(json.dumps({"verdict":out["verdict"],**{n.replace(".","_")+"_sha256":sha(a.output_dir/n) for n in files}},indent=2))
if __name__=="__main__": main()
# fmt: on
