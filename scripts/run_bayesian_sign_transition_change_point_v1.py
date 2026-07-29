#!/usr/bin/env python3
# ruff: noqa
# fmt: off
"""Reproduce issue #605's frozen Bayesian sign-transition development verdict."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
FEE=.0005;ANN=8760.;TRAIN=2880;OOS=17520;STOP=43440;FOLD=2160;RECENT=168;TREND=2160;NBOOT=5000;BLOCK=168;SEED=20260729;DRAWS=8192;PRIOR=RECENT/TREND
MAIN="5a0fcc97d1a882f8223656c51f5bb8055f534e38";ISSUE=605;FAMILY="bayesian-sign-transition-change-point-1h-v1"
SOURCES={"BTC-USDT":{"artifact_id":8704977298,"zip_sha256":"22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c","csv_sha256":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","offset":0},"ETH-USDT":{"artifact_id":8704978112,"zip_sha256":"e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3","csv_sha256":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726","offset":100000}}
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def sh(x):
 s=float(np.std(x,ddof=1));return float(np.mean(x)/s*math.sqrt(ANN)) if s>0 else None
def met(n,g,t,p):
 e=np.cumprod(1+n);q=np.r_[1.,e];d=q/np.maximum.accumulate(q)-1;z=float(t.sum())
 return {"gross_total_return":float(np.prod(1+g)-1),"net_total_return":float(e[-1]-1),"annualized_arithmetic_mean":float(np.mean(n)*ANN),"sharpe":sh(n),"max_drawdown":float(d.min()),"turnover":z,"fee_sum":z*FEE,"net_edge_per_turnover_bps":float(n.sum()/z*1e4) if z else None,"average_exposure":float(p.mean())}
def path(p,r):
 q=np.r_[0.,p[:-1]];t=np.abs(p-q);g=p*r;n=g-FEE*t
 if not np.allclose(n,g-FEE*t,atol=0,rtol=0):raise AssertionError("fee")
 return {"position":p,"turn":t,"gross":g,"net":n}
def boot(a,b):
 n=len(a);ls=np.full(math.ceil(n/BLOCK),BLOCK,int);ls[-1]=n-BLOCK*(len(ls)-1);r=np.random.default_rng(SEED);md=np.empty(NBOOT);sd=np.empty(NBOOT)
 for j in range(NBOOT):
  ss=[int(r.integers(0,n-int(L)+1)) for L in ls];ix=np.concatenate([np.arange(s,s+int(L)) for s,L in zip(ss,ls)]);aa=a[ix];bb=b[ix];md[j]=float(np.mean(aa-bb)*ANN);sd[j]=float((sh(aa) or 0)-(sh(bb) or 0))
 return {"annualized_mean_delta_lower_95":float(np.quantile(md,.025)),"annualized_mean_delta_median":float(np.quantile(md,.5)),"annualized_mean_delta_upper_95":float(np.quantile(md,.975)),"sharpe_delta_lower_95":float(np.quantile(sd,.025)),"sharpe_delta_median":float(np.quantile(sd,.5)),"sharpe_delta_upper_95":float(np.quantile(sd,.975))}
def lb(a,b):return math.lgamma(a)+math.lgamma(b)-math.lgamma(a+b)
def logistic(x):
 if x>=0:z=math.exp(-x);return 1/(1+z)
 z=math.exp(x);return z/(1+z)
def tc(s,a,b):
 z=np.zeros((2,2),int);p=s[a-1:b-1];n=s[a:b]
 for i in (0,1):
  m=p==i;z[i,0]=int(np.sum(m&(n==0)));z[i,1]=int(np.sum(m&(n==1)))
 return z
def cc(s):
 n=len(s);c=np.zeros((n+1,2,2),int)
 for d in range(1,n):c[d+1]=c[d];c[d+1,s[d-1],s[d]]+=1
 return c
def pf(z,tr,cur,i,off):
 l=0.
 for row in (0,1):
  n0,n1=int(z[row,0]),int(z[row,1]);t0,t1=int(tr[row,0]),int(tr[row,1]);l+=lb(.5+n1,.5+n0)-lb(.5,.5)-lb(.5+t1+n1,.5+t0+n0)+lb(.5+t1,.5+t0)
 ch=logistic(l+math.log(PRIOR/(1-PRIOR)));a0,b0=.5+int(z[0,1]),.5+int(z[0,0]);a1,b1=.5+int(z[1,1]),.5+int(z[1,0]);r=np.random.default_rng(SEED+i+off);q0=r.beta(a0,b0,DRAWS);q1=r.beta(a1,b1,DRAWS);pe=float(np.mean(q1>q0));pn=float(a1/(a1+b1) if cur else a0/(a0+b0));return ch,pe,pn,l
def positions(ts,c,s,off):
 n=len(c);lc=np.log(c);trend=np.full(n,np.nan);trend[TREND:]=lc[TREND:]-lc[:-TREND];tr=tc(s,TRAIN,OOS);cum=cc(s);ca=np.zeros(n);b0=np.zeros(n);b1=np.zeros(n);state=bst=0.;dec=np.zeros(n,bool);un=np.zeros(n,bool);ch=np.full(n,np.nan);pe=np.full(n,np.nan);pn=np.full(n,np.nan);bf=np.full(n,np.nan)
 for i in range(n):
  if i>=TREND and np.isfinite(trend[i]):b0[i]=float(trend[i]>0)
  if ts[i].hour==0:
   dec[i]=True;bst=float(i>=TREND and np.isfinite(trend[i]) and trend[i]>0);ok=i>=max(TREND,RECENT) and np.isfinite(trend[i])
   if ok:
    a=i-RECENT+1
    if a<1:ok=False
    else:ch[i],pe[i],pn[i],bf[i]=pf(cum[i+1]-cum[a],tr,int(s[i]),i,off)
   if not ok:state=0.;un[i]=True
   elif state==0:state=float(trend[i]>0 and ch[i]>=.80 and pe[i]>=.90 and pn[i]>=.55)
   elif trend[i]<=0 or ch[i]<=.50 or pe[i]<=.50 or pn[i]<=.50:state=0.
  ca[i]=state;b1[i]=bst
 return {"candidate":ca,"b0":b0,"b1":b1,"trend":trend,"decision":dec,"unavailable":un,"change_probability":ch,"persistence_probability":pe,"next_positive_probability":pn,"log_bayes_factor":bf,"training_transition_counts":tr}
def holds(p,a,b):
 q=np.r_[0.,p[:-1]];en=np.flatnonzero((p==1)&(q==0));ex=np.flatnonzero((p==0)&(q==1));oe=en[(en>=a)&(en<b)];h=[]
 for e in en:
  x=ex[ex>e]
  if len(x) and e<b and x[0]>a:h.append(int(x[0]-e))
 return {"long_entries":int(len(oe)),"median_completed_holding_hours":float(np.median(h)) if h else None,"mean_completed_holding_hours":float(np.mean(h)) if h else None,"max_completed_holding_hours":max(h) if h else None}
def evaluate(inst,zp,cp):
 src=SOURCES[inst]
 if sha(zp)!=src["zip_sha256"] or sha(cp)!=src["csv_sha256"]:raise ValueError("hash")
 df=pd.read_csv(cp,nrows=STOP+2);ts=pd.DatetimeIndex(pd.to_datetime(df.timestamp,utc=True));px=df[["open","high","low","close"]].to_numpy(float)
 if len(df)!=STOP+2 or not(df.confirm==1).all() or ts.has_duplicates or not ts.is_monotonic_increasing or not np.all(np.diff(ts.view("int64"))==3600_000_000_000) or not np.isfinite(px).all() or not(px>0).all():raise ValueError("grid")
 c=df.close.to_numpy(float);op=df.open.to_numpy(float);lr=np.full(len(df),np.nan);lr[1:]=np.diff(np.log(c));sg=np.zeros(len(df),int);sg[1:]=(lr[1:]>0).astype(int);ps=positions(ts,c,sg,int(src["offset"]));pay=op[2:STOP+2]/op[1:STOP+1]-1;pp={k:path(ps[k][:STOP],pay) for k in ("candidate","b0","b1")}
 def ms(a,b):return {k:met(v["net"][a:b],v["gross"][a:b],v["turn"][a:b],v["position"][a:b]) for k,v in pp.items()}
 train=ms(TRAIN,OOS);oos=ms(OOS,STOP);full=ms(TRAIN,STOP);oc=pp["candidate"]["net"][OOS:STOP];ob0=pp["b0"]["net"][OOS:STOP];ob1=pp["b1"]["net"][OOS:STOP];ots=ts[OOS:STOP];folds=[float(np.prod(1+oc[j:j+FOLD])-1) for j in range(0,len(oc),FOLD)];years={str(y):float(np.prod(1+oc[np.asarray(ots.year)==y])-1) for y in sorted(set(ots.year))};pos=[max(0,x) for x in folds];conc=max(pos)/sum(pos) if sum(pos)>0 else None;u=boot(oc,ob1);rb0=oc-ob0;rb1=oc-ob1;rs0=sh(rb0);rs1=sh(rb1);hs=holds(pp["candidate"]["position"],OOS,STOP);dec=ps["decision"][:STOP];od=dec.copy();od[:OOS]=False;valid=od&np.isfinite(ps["change_probability"][:STOP]);cv=ps["change_probability"][:STOP][valid];pv=ps["persistence_probability"][:STOP][valid];nv=ps["next_positive_probability"][:STOP][valid];cm=oos["candidate"];bm=oos["b1"]
 gates={"positive_net_return":cm["net_total_return"]>0,"finite_sharpe_and_exceeds_b1":cm["sharpe"] is not None and bm["sharpe"] is not None and cm["sharpe"]>bm["sharpe"],"edge_per_turnover_exceeds_b1":cm["net_edge_per_turnover_bps"] is not None and bm["net_edge_per_turnover_bps"] is not None and cm["net_edge_per_turnover_bps"]>bm["net_edge_per_turnover_bps"],"max_drawdown_no_worse_than_b1":cm["max_drawdown"]>=bm["max_drawdown"],"long_entries_at_least_8":hs["long_entries"]>=8,"profitable_folds_at_least_7_of_12":sum(x>0 for x in folds)>=7,"profitable_year_segments_at_least_3":sum(x>0 for x in years.values())>=3,"positive_fold_concentration_at_most_50pct":conc is not None and conc<=.5,"positive_residual_sharpe_vs_b0":rs0 is not None and rs0>0,"positive_residual_sharpe_vs_b1":rs1 is not None and rs1>0,"bootstrap_mean_delta_lower_bound_positive":u["annualized_mean_delta_lower_95"]>0,"bootstrap_sharpe_delta_lower_bound_positive":u["sharpe_delta_lower_95"]>0,"hash_chronology_timing_fee_checks":True}
 def mm(x):return [float(np.min(x)) if len(x) else None,float(np.median(x)) if len(x) else None,float(np.max(x)) if len(x) else None]
 feat={"recent_transition_hours":RECENT,"trend_hours":TREND,"prior_change_probability":PRIOR,"posterior_draws_per_decision":DRAWS,"daily_decision_count_oos":int(np.sum(od)),"valid_feature_decisions_oos":int(np.sum(valid)),"unavailable_daily_decisions_oos":int(np.sum(ps["unavailable"][:STOP][OOS:STOP])),"long_daily_decisions_oos":int(np.sum(pp["candidate"]["position"][OOS:STOP][dec[OOS:STOP]]==1)),"change_probability_min_median_max_oos":mm(cv),"persistence_probability_min_median_max_oos":mm(pv),"next_positive_probability_min_median_max_oos":mm(nv),"trend_positive_decisions_oos":int(np.sum(valid&(ps["trend"][:STOP]>0))),"change_probability_ge_080_decisions_oos":int(np.sum(valid&(ps["change_probability"][:STOP]>=.8))),"persistence_probability_ge_090_decisions_oos":int(np.sum(valid&(ps["persistence_probability"][:STOP]>=.9))),"next_positive_probability_ge_055_decisions_oos":int(np.sum(valid&(ps["next_positive_probability"][:STOP]>=.55))),"change_and_persistence_decisions_oos":int(np.sum(valid&(ps["change_probability"][:STOP]>=.8)&(ps["persistence_probability"][:STOP]>=.9))),"change_persistence_next_positive_decisions_oos":int(np.sum(valid&(ps["change_probability"][:STOP]>=.8)&(ps["persistence_probability"][:STOP]>=.9)&(ps["next_positive_probability"][:STOP]>=.55))),"entry_condition_decisions_oos":int(np.sum(valid&(ps["trend"][:STOP]>0)&(ps["change_probability"][:STOP]>=.8)&(ps["persistence_probability"][:STOP]>=.9)&(ps["next_positive_probability"][:STOP]>=.55)))}
 return {"instrument":inst,"source":{k:v for k,v in src.items() if k!="offset"},"grid":{"parsed_observations":len(df),"source_observations":43941,"first_timestamp":ts[0].isoformat(),"last_required_timestamp":ts[-1].isoformat(),"confirmed_required_prefix":True,"contiguous_1h_required_prefix":True,"later_suffix_semantically_read":False},"training_transition_counts":ps["training_transition_counts"].tolist(),"feature":feat,"train_metrics":train,"oos_metrics":oos,"full_metrics":full,"breadth":{"fold_returns":folds,"profitable_folds":int(sum(x>0 for x in folds)),"fold_count":len(folds),"positive_fold_return_concentration":conc,"year_returns":years,"profitable_years":int(sum(x>0 for x in years.values())),"year_count":len(years)},"position":hs,"residual_total_return_vs_b0":float(np.prod(1+rb0)-1),"residual_total_return_vs_b1":float(np.prod(1+rb1)-1),"residual_sharpe_vs_b0":rs0,"residual_sharpe_vs_b1":rs1,"uncertainty_vs_b1":u,"acceptance_gates":gates,"accepted":all(gates.values())}
def main():
 a=argparse.ArgumentParser();a.add_argument("--btc-zip",type=Path,required=True);a.add_argument("--btc-csv",type=Path,required=True);a.add_argument("--eth-zip",type=Path,required=True);a.add_argument("--eth-csv",type=Path,required=True);a.add_argument("--output",type=Path,required=True);x=a.parse_args();m=[evaluate("BTC-USDT",x.btc_zip,x.btc_csv),evaluate("ETH-USDT",x.eth_zip,x.eth_csv)];ok=all(q["accepted"] for q in m);v="bayesian_sign_transition_change_point_nominated_for_untouched_replication" if ok else "reject_exact_bayesian_sign_transition_change_point_family";d=[]
 for q in m:
  c=q["oos_metrics"]["candidate"];b=q["oos_metrics"]["b1"];d.append(f"{q['instrument']} candidate Sharpe {c['sharpe'] if c['sharpe'] is not None else 'undefined'} versus B1 {b['sharpe']:.3f}, entries {q['position']['long_entries']}, with {q['breadth']['profitable_folds']}/12 profitable folds")
 it="The Bayesian sign-transition change state added broad, uncertainty-supported net information beyond the daily trend comparator in both development markets." if ok else "The posterior change-point selector did not produce bilateral incremental information: "+"; ".join(d)+"."
 r={"schema_version":1,"family_id":FAMILY,"issue":ISSUE,"main":MAIN,"candidate_count":1,"parameter_grid_count":0,"canonical_fee_one_way_bps":5.,"markets":m,"accepted_bilaterally":ok,"verdict":v,"interpretation":it,"untouched_oos_consumed":False,"paper_or_live_authorized":False};x.output.mkdir(parents=True,exist_ok=True);p=x.output/"result.json";p.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n");print(json.dumps({"verdict":v,"result_sha256":sha(p)},indent=2))
if __name__=="__main__":main()
