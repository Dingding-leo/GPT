#!/usr/bin/env python3
# ruff: noqa
# fmt: off
"""Reproduce issue #608's frozen multi-horizon directional-consensus verdict."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
from statistics import NormalDist
import numpy as np
import pandas as pd
FEE=.0005;ANN=8760.;TRAIN=2880;OOS=17520;STOP=43440;FOLD=2160;HS=(24,168,720,2160);TARGET=168;MIN=56;OVER=7;HURDLE=.001;CL=.90;NBOOT=5000;BLOCK=168;SEED=20260729
MAIN="5a0fcc97d1a882f8223656c51f5bb8055f534e38";ISSUE=608;FAMILY="multi-horizon-directional-consensus-calibration-1h-v1"
SRC={"BTC-USDT":{"artifact_id":8704977298,"zip_sha256":"22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c","csv_sha256":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9"},"ETH-USDT":{"artifact_id":8704978112,"zip_sha256":"e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3","csv_sha256":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}}
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def bcf(a,b,x):
 c=1.;d=1.-(a+b)*x/(a+1.);d=1./(d if abs(d)>1e-300 else 1e-300);r=d
 for m in range(1,301):
  m2=2*m;aa=m*(b-m)*x/((a-1+m2)*(a+m2));d=1.+aa*d;d=1./(d if abs(d)>1e-300 else 1e-300);c=1.+aa/c;c=c if abs(c)>1e-300 else 1e-300;r*=d*c;aa=-(a+m)*(a+b+m)*x/((a+m2)*(a+1+m2));d=1.+aa*d;d=1./(d if abs(d)>1e-300 else 1e-300);c=1.+aa/c;c=c if abs(c)>1e-300 else 1e-300;z=d*c;r*=z
  if abs(z-1.)<3e-14:return r
 raise RuntimeError("beta")
def ib(x,a,b):
 if x<=0:return 0.
 if x>=1:return 1.
 bt=math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
 return bt*bcf(a,b,x)/a if x<(a+1)/(a+b+2) else 1-bt*bcf(b,a,1-x)/b
def tcdf(x,df):
 if x==0:return .5
 q=df/(df+x*x);t=.5*ib(q,df/2,.5);return 1-t if x>0 else t
def tppf(p,df):
 lo=0.;hi=max(1.,NormalDist().inv_cdf(p))
 while tcdf(hi,df)<p:hi*=2
 for _ in range(100):
  md=(lo+hi)/2
  if tcdf(md,df)<p:lo=md
  else:hi=md
 return (lo+hi)/2
def sh(x):
 s=float(np.std(x,ddof=1));return float(np.mean(x)/s*math.sqrt(ANN)) if s>0 else None
def met(n,g,t,p):
 e=np.cumprod(1+n);q=np.r_[1.,e];d=q/np.maximum.accumulate(q)-1;z=float(t.sum());return {"gross_total_return":float(np.prod(1+g)-1),"net_total_return":float(e[-1]-1),"annualized_arithmetic_mean":float(np.mean(n)*ANN),"sharpe":sh(n),"max_drawdown":float(d.min()),"turnover":z,"fee_sum":z*FEE,"net_edge_per_turnover_bps":float(n.sum()/z*1e4) if z else None,"average_exposure":float(p.mean())}
def path(p,r):
 q=np.r_[0.,p[:-1]];t=np.abs(p-q);g=p*r;n=g-FEE*t
 if not np.allclose(n,g-FEE*t,atol=0,rtol=0):raise AssertionError("fee")
 return {"position":p,"turn":t,"gross":g,"net":n}
def boot(a,b):
 n=len(a);ls=np.full(math.ceil(n/BLOCK),BLOCK,int);ls[-1]=n-BLOCK*(len(ls)-1);rng=np.random.default_rng(SEED);md=np.empty(NBOOT);sd=np.empty(NBOOT)
 for j in range(NBOOT):
  ss=[int(rng.integers(0,n-int(L)+1)) for L in ls];ix=np.concatenate([np.arange(s,s+int(L)) for s,L in zip(ss,ls)]);aa=a[ix];bb=b[ix];md[j]=float(np.mean(aa-bb)*ANN);sd[j]=float((sh(aa) or 0)-(sh(bb) or 0))
 return {"annualized_mean_delta_lower_95":float(np.quantile(md,.025)),"annualized_mean_delta_median":float(np.quantile(md,.5)),"annualized_mean_delta_upper_95":float(np.quantile(md,.975)),"sharpe_delta_lower_95":float(np.quantile(sd,.025)),"sharpe_delta_median":float(np.quantile(sd,.5)),"sharpe_delta_upper_95":float(np.quantile(sd,.975))}
def states(c):
 z=np.full(len(c),-1,int);v=np.zeros(len(c),int)
 for bit,h in enumerate(HS):
  p=np.zeros(len(c),bool);p[h:]=np.log(c[h:]/c[:-h])>0;v|=p.astype(int)<<bit
 z[max(HS):]=v[max(HS):];return z
def fit(ts,z,op):
 ix=np.flatnonzero((np.arange(len(z))>=TRAIN)&(np.arange(len(z))+TARGET+1<OOS)&(ts.hour==0)&(z>=0));out={}
 for s in range(16):
  q=ix[z[ix]==s];y=op[q+TARGET+1]/op[q+1]-1;n=len(y);ne=n//OVER;mu=float(np.mean(y)) if n else None;sd=float(np.std(y,ddof=1)) if n>1 else None;ok=bool(n>=MIN and ne>=MIN//OVER and sd is not None and math.isfinite(sd) and sd>0);df=ne-1 if ok else None;crit=tppf(CL,df) if ok else None;lb=mu-crit*sd/math.sqrt(ne) if ok else None
  out[s]={"state":s,"bits_24_168_720_2160":format(s,"04b")[::-1],"raw_support":int(n),"effective_support":int(ne),"posterior_degrees_of_freedom":df,"sample_mean_168h_gross":mu,"sample_std_168h_gross":sd,"posterior_lower_90":lb,"eligible":ok,"entry_qualified":bool(ok and lb>HURDLE)}
 return out
def pos(ts,c,z,cal):
 n=len(c);tr=np.full(n,np.nan);tr[2160:]=np.log(c[2160:]/c[:-2160]);ca=np.zeros(n);b0=np.zeros(n);b1=np.zeros(n);state=dstate=0.;entry=None;dec=ts.hour==0
 for i in range(n):
  if i>=2160 and np.isfinite(tr[i]):b0[i]=float(tr[i]>0)
  if dec[i]:
   dstate=float(i>=2160 and np.isfinite(tr[i]) and tr[i]>0);r=cal.get(int(z[i]))
   if state==0:
    if i>=2160 and np.isfinite(tr[i]) and tr[i]>0 and r and r["eligible"] and r["posterior_lower_90"]>HURDLE:state=1.;entry=i
   elif entry is not None and i-entry>=TARGET and (i<2160 or not np.isfinite(tr[i]) or tr[i]<=0 or not r or not r["eligible"] or r["sample_mean_168h_gross"]<=0):state=0.;entry=None
  ca[i]=state;b1[i]=dstate
 return {"candidate":ca,"b0":b0,"b1":b1,"trend":tr,"decision":dec}
def holds(p,a,b):
 q=np.r_[0.,p[:-1]];en=np.flatnonzero((p==1)&(q==0));ex=np.flatnonzero((p==0)&(q==1));oe=en[(en>=a)&(en<b)];h=[]
 for e in en:
  x=ex[ex>e]
  if len(x) and e<b and x[0]>a:h.append(int(x[0]-e))
 return {"long_entries":int(len(oe)),"median_completed_holding_hours":float(np.median(h)) if h else None,"mean_completed_holding_hours":float(np.mean(h)) if h else None,"max_completed_holding_hours":max(h) if h else None}
def evaluate(inst,zp,cp):
 src=SRC[inst]
 if sha(zp)!=src["zip_sha256"] or sha(cp)!=src["csv_sha256"]:raise ValueError("hash")
 df=pd.read_csv(cp,nrows=STOP+TARGET+2);ts=pd.DatetimeIndex(pd.to_datetime(df.timestamp,utc=True));px=df[["open","high","low","close"]].to_numpy(float)
 if len(df)!=STOP+TARGET+2 or not(df.confirm==1).all() or ts.has_duplicates or not ts.is_monotonic_increasing or not np.all(np.diff(ts.view("int64"))==3600_000_000_000) or not np.isfinite(px).all() or not(px>0).all():raise ValueError("grid")
 c=df.close.to_numpy(float);op=df.open.to_numpy(float);zs=states(c);cal=fit(ts,zs,op);ps=pos(ts,c,zs,cal);pay=op[2:STOP+2]/op[1:STOP+1]-1;pp={k:path(ps[k][:STOP],pay) for k in ("candidate","b0","b1")}
 def ms(a,b):return {k:met(v["net"][a:b],v["gross"][a:b],v["turn"][a:b],v["position"][a:b]) for k,v in pp.items()}
 train=ms(TRAIN,OOS);oos=ms(OOS,STOP);full=ms(TRAIN,STOP);oc=pp["candidate"]["net"][OOS:STOP];ob0=pp["b0"]["net"][OOS:STOP];ob1=pp["b1"]["net"][OOS:STOP];ots=ts[OOS:STOP];folds=[float(np.prod(1+oc[j:j+FOLD])-1) for j in range(0,len(oc),FOLD)];years={str(y):float(np.prod(1+oc[np.asarray(ots.year)==y])-1) for y in sorted(set(ots.year))};positive=[max(0,x) for x in folds];conc=max(positive)/sum(positive) if sum(positive)>0 else None;u=boot(oc,ob1);rb0=oc-ob0;rb1=oc-ob1;rs0=sh(rb0);rs1=sh(rb1);hs=holds(pp["candidate"]["position"],OOS,STOP)
 oi=np.flatnonzero((np.arange(len(zs))>=OOS)&(np.arange(len(zs))+TARGET+1<=STOP)&(ts.hour==0)&(zs>=0));eligible=[]
 for s,r in cal.items():
  q=oi[zs[oi]==s];y=op[q+TARGET+1]/op[q+1]-1
  if r["eligible"]:
   eligible.append({**r,"oos_occurrences":int(len(q)),"oos_realized_mean_168h_gross":float(np.mean(y)) if len(y) else None,"calibration_error_oos_minus_training":float(np.mean(y)-r["sample_mean_168h_gross"]) if len(y) else None})
 od=np.flatnonzero((np.arange(STOP)>=OOS)&ps["decision"][:STOP]);ed=sum(cal[int(zs[i])]["eligible"] for i in od);qd=sum(ps["trend"][i]>0 and cal[int(zs[i])]["entry_qualified"] for i in od);cm=oos["candidate"];bm=oos["b1"]
 gates={"positive_net_return":cm["net_total_return"]>0,"finite_sharpe_and_exceeds_b1":cm["sharpe"] is not None and cm["sharpe"]>bm["sharpe"],"edge_per_turnover_exceeds_b1":cm["net_edge_per_turnover_bps"] is not None and cm["net_edge_per_turnover_bps"]>bm["net_edge_per_turnover_bps"],"max_drawdown_no_worse_than_b1":cm["max_drawdown"]>=bm["max_drawdown"],"long_entries_at_least_8":hs["long_entries"]>=8,"profitable_folds_at_least_7_of_12":sum(x>0 for x in folds)>=7,"profitable_year_segments_at_least_3":sum(x>0 for x in years.values())>=3,"positive_fold_concentration_at_most_50pct":conc is not None and conc<=.5,"positive_residual_sharpe_vs_b0":rs0 is not None and rs0>0,"positive_residual_sharpe_vs_b1":rs1 is not None and rs1>0,"bootstrap_mean_delta_lower_bound_positive":u["annualized_mean_delta_lower_95"]>0,"bootstrap_sharpe_delta_lower_bound_positive":u["sharpe_delta_lower_95"]>0,"hash_chronology_timing_fee_checks":True}
 return {"instrument":inst,"source":src,"grid":{"parsed_observations":len(df),"source_observations":43941,"first_timestamp":ts[0].isoformat(),"last_required_timestamp":ts[-1].isoformat(),"confirmed_required_prefix":True,"contiguous_1h_required_prefix":True,"later_suffix_semantically_read":False},"signal":{"horizons_hours":list(HS),"target_hours":TARGET,"minimum_raw_support":MIN,"overlap_adjustment":OVER,"credible_level_one_sided":CL,"entry_hurdle_gross":HURDLE,"training_daily_anchor_count":sum(r["raw_support"] for r in cal.values()),"eligible_state_count":sum(r["eligible"] for r in cal.values()),"entry_qualified_state_count":sum(r["entry_qualified"] for r in cal.values()),"maximum_state_lower_bound":max(r["posterior_lower_90"] for r in cal.values() if r["posterior_lower_90"] is not None),"oos_daily_decision_count":len(od),"oos_eligible_state_decisions":int(ed),"oos_entry_condition_decisions":int(qd)},"eligible_state_calibration":eligible,"train_metrics":train,"oos_metrics":oos,"full_metrics":full,"breadth":{"fold_returns":folds,"profitable_folds":sum(x>0 for x in folds),"fold_count":len(folds),"positive_fold_return_concentration":conc,"year_returns":years,"profitable_years":sum(x>0 for x in years.values()),"year_count":len(years)},"position":hs,"residual_total_return_vs_b0":float(np.prod(1+rb0)-1),"residual_total_return_vs_b1":float(np.prod(1+rb1)-1),"residual_sharpe_vs_b0":rs0,"residual_sharpe_vs_b1":rs1,"uncertainty_vs_b1":u,"acceptance_gates":gates,"accepted":all(gates.values())}
def main():
 a=argparse.ArgumentParser();a.add_argument("--btc-zip",type=Path,required=True);a.add_argument("--btc-csv",type=Path,required=True);a.add_argument("--eth-zip",type=Path,required=True);a.add_argument("--eth-csv",type=Path,required=True);a.add_argument("--output",type=Path,required=True);x=a.parse_args();m=[evaluate("BTC-USDT",x.btc_zip,x.btc_csv),evaluate("ETH-USDT",x.eth_zip,x.eth_csv)];ok=all(q["accepted"] for q in m);v="multi_horizon_directional_consensus_nominated_for_untouched_replication" if ok else "reject_exact_multi_horizon_directional_consensus_calibration_family";r={"schema_version":1,"family_id":FAMILY,"issue":ISSUE,"main":MAIN,"candidate_count":1,"parameter_grid_count":0,"canonical_fee_one_way_bps":5.,"markets":m,"accepted_bilaterally":ok,"verdict":v,"untouched_oos_consumed":False,"paper_or_live_authorized":False};x.output.mkdir(parents=True,exist_ok=True);p=x.output/"result.json";p.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n");print(json.dumps({"verdict":v,"result_sha256":sha(p)},indent=2))
if __name__=="__main__":main()
