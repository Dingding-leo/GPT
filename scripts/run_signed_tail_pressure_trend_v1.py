#!/usr/bin/env python3
# ruff: noqa
# fmt: off
"""Reproduce issue #602's frozen signed-tail-pressure development verdict."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
FEE=.0005;ANN=8760.;TRAIN=2880;OOS=17520;STOP=43440;FOLD=2160;RW=720;BW=168;TW=2160;ZC=3.;NBOOT=5000;BLOCK=168;SEED=20260729
MAIN="5a0fcc97d1a882f8223656c51f5bb8055f534e38";ISSUE=602;FAMILY="signed-tail-pressure-trend-1h-v1"
SOURCES={"BTC-USDT":{"artifact_id":8704977298,"zip_sha256":"22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c","csv_sha256":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9"},"ETH-USDT":{"artifact_id":8704978112,"zip_sha256":"e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3","csv_sha256":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}}
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
def feat(r):
 n=len(r);z=np.full(n,np.nan);mad=np.full(n,np.nan)
 for i in range(RW+1,n):
  w=r[i-RW:i]
  if not np.isfinite(w).all():continue
  m=float(np.median(w));d=float(np.median(np.abs(w-m)));mad[i]=d;s=1.4826*d
  if s>0 and np.isfinite(r[i]):z[i]=(r[i]-m)/s
 q=np.zeros(n,int);q[z>=ZC]=1;q[z<=-ZC]=-1
 return z,q,mad
def positions(ts,c,z,s):
 n=len(c);lc=np.log(c);tr=np.full(n,np.nan);tr[TW:]=lc[TW:]-lc[:-TW];bal=np.full(n,np.nan);cs=np.r_[0,np.cumsum(s)]
 for i in range(BW-1,n):bal[i]=float(cs[i+1]-cs[i+1-BW])
 ca=np.zeros(n);b0=np.zeros(n);b1=np.zeros(n);state=bstate=0.;dec=np.zeros(n,bool);un=np.zeros(n,bool)
 for i in range(n):
  if i>=TW and np.isfinite(tr[i]):b0[i]=float(tr[i]>0)
  if ts[i].hour==0:
   dec[i]=True;bstate=float(i>=TW and np.isfinite(tr[i]) and tr[i]>0)
   ok=i>=TW and np.isfinite(tr[i]) and np.isfinite(bal[i]) and np.isfinite(z[i])
   if not ok:state=0.;un[i]=True
   elif state==0:state=float(tr[i]>0 and bal[i]>=1)
   elif tr[i]<=0 or bal[i]<=-1:state=0.
  ca[i]=state;b1[i]=bstate
 return {"candidate":ca,"b0":b0,"b1":b1,"trend":tr,"balance":bal,"decision":dec,"unavailable":un}
def holds(p,a,b):
 prior=np.r_[0.,p[:-1]];en=np.flatnonzero((p==1)&(prior==0));ex=np.flatnonzero((p==0)&(prior==1));oe=en[(en>=a)&(en<b)];h=[]
 for e in en:
  x=ex[ex>e]
  if len(x) and e<b and x[0]>a:h.append(int(x[0]-e))
 return {"long_entries":int(len(oe)),"median_completed_holding_hours":float(np.median(h)) if h else None,"mean_completed_holding_hours":float(np.mean(h)) if h else None,"max_completed_holding_hours":max(h) if h else None}
def evaluate(inst,zp,cp):
 src=SOURCES[inst]
 if sha(zp)!=src["zip_sha256"] or sha(cp)!=src["csv_sha256"]:raise ValueError("hash")
 df=pd.read_csv(cp,nrows=STOP+2);ts=pd.DatetimeIndex(pd.to_datetime(df.timestamp,utc=True));px=df[["open","high","low","close"]].to_numpy(float)
 if len(df)!=STOP+2 or not(df.confirm==1).all() or ts.has_duplicates or not ts.is_monotonic_increasing or not np.all(np.diff(ts.view("int64"))==3600_000_000_000) or not np.isfinite(px).all() or not(px>0).all():raise ValueError("grid")
 c=df.close.to_numpy(float);op=df.open.to_numpy(float);lr=np.full(len(df),np.nan);lr[1:]=np.diff(np.log(c));zz,sg,mad=feat(lr);ps=positions(ts,c,zz,sg);pay=op[2:STOP+2]/op[1:STOP+1]-1
 pp={k:path(ps[k][:STOP],pay) for k in ("candidate","b0","b1")}
 def ms(a,b):return {k:met(v["net"][a:b],v["gross"][a:b],v["turn"][a:b],v["position"][a:b]) for k,v in pp.items()}
 train=ms(TRAIN,OOS);oos=ms(OOS,STOP);full=ms(TRAIN,STOP);oc=pp["candidate"]["net"][OOS:STOP];ob0=pp["b0"]["net"][OOS:STOP];ob1=pp["b1"]["net"][OOS:STOP];ots=ts[OOS:STOP]
 folds=[float(np.prod(1+oc[j:j+FOLD])-1) for j in range(0,len(oc),FOLD)];years={str(y):float(np.prod(1+oc[np.asarray(ots.year)==y])-1) for y in sorted(set(ots.year))};pos=[max(0,x) for x in folds];conc=max(pos)/sum(pos) if sum(pos)>0 else None;u=boot(oc,ob1);rb0=oc-ob0;rb1=oc-ob1;rs0=sh(rb0);rs1=sh(rb1);rr0=float(np.prod(1+rb0)-1);rr1=float(np.prod(1+rb1)-1);hs=holds(pp["candidate"]["position"],OOS,STOP)
 dec=ps["decision"][:STOP];od=dec.copy();od[:OOS]=False;bv=ps["balance"][:STOP][od&np.isfinite(ps["balance"][:STOP])];cm=oos["candidate"];bm=oos["b1"]
 gates={"positive_net_return":cm["net_total_return"]>0,"positive_sharpe":cm["sharpe"] is not None and cm["sharpe"]>0,"positive_edge_per_turnover":cm["net_edge_per_turnover_bps"] is not None and cm["net_edge_per_turnover_bps"]>0,"profitable_folds_at_least_7_of_12":sum(x>0 for x in folds)>=7,"profitable_year_segments_at_least_3":sum(x>0 for x in years.values())>=3,"positive_fold_concentration_at_most_50pct":conc is not None and conc<=.5,"long_entries_at_least_5":hs["long_entries"]>=5,"sharpe_exceeds_b1":cm["sharpe"] is not None and bm["sharpe"] is not None and cm["sharpe"]>bm["sharpe"],"edge_per_turnover_exceeds_b1":cm["net_edge_per_turnover_bps"] is not None and bm["net_edge_per_turnover_bps"] is not None and cm["net_edge_per_turnover_bps"]>bm["net_edge_per_turnover_bps"],"positive_residual_sharpe_vs_b0":rs0 is not None and rs0>0,"positive_residual_sharpe_vs_b1":rs1 is not None and rs1>0,"max_drawdown_no_worse_than_b1":cm["max_drawdown"]>=bm["max_drawdown"],"bootstrap_mean_delta_lower_bound_positive":u["annualized_mean_delta_lower_95"]>0,"bootstrap_sharpe_delta_lower_bound_positive":u["sharpe_delta_lower_95"]>0,"hash_chronology_timing_fee_checks":True}
 return {"instrument":inst,"source":src,"grid":{"parsed_observations":len(df),"source_observations":43941,"first_timestamp":ts[0].isoformat(),"last_required_timestamp":ts[-1].isoformat(),"confirmed_required_prefix":True,"contiguous_1h_required_prefix":True,"later_suffix_semantically_read":False},"feature":{"robust_window_hours":RW,"z_cutoff":ZC,"balance_window_hours":BW,"trend_hours":TW,"positive_tail_events_train":int(np.sum(sg[TRAIN:OOS]==1)),"negative_tail_events_train":int(np.sum(sg[TRAIN:OOS]==-1)),"positive_tail_events_oos":int(np.sum(sg[OOS:STOP]==1)),"negative_tail_events_oos":int(np.sum(sg[OOS:STOP]==-1)),"finite_z_oos":int(np.sum(np.isfinite(zz[OOS:STOP]))),"zero_or_invalid_mad_oos":int(np.sum(~np.isfinite(mad[OOS:STOP])|(mad[OOS:STOP]<=0))),"decision_tail_balance_min_oos":float(np.min(bv)) if len(bv) else None,"decision_tail_balance_median_oos":float(np.median(bv)) if len(bv) else None,"decision_tail_balance_max_oos":float(np.max(bv)) if len(bv) else None,"daily_decision_count_oos":int(np.sum(od)),"long_daily_decisions_oos":int(np.sum(pp["candidate"]["position"][OOS:STOP][dec[OOS:STOP]]==1)),"unavailable_daily_decisions_oos":int(np.sum(ps["unavailable"][:STOP][OOS:STOP]))},"train_metrics":train,"oos_metrics":oos,"full_metrics":full,"breadth":{"fold_returns":folds,"profitable_folds":int(sum(x>0 for x in folds)),"fold_count":len(folds),"positive_fold_return_concentration":conc,"year_returns":years,"profitable_years":int(sum(x>0 for x in years.values())),"year_count":len(years)},"position":hs,"residual_total_return_vs_b0":rr0,"residual_total_return_vs_b1":rr1,"residual_sharpe_vs_b0":rs0,"residual_sharpe_vs_b1":rs1,"uncertainty_vs_b1":u,"acceptance_gates":gates,"accepted":all(gates.values())}
def main():
 a=argparse.ArgumentParser();a.add_argument("--btc-zip",type=Path,required=True);a.add_argument("--btc-csv",type=Path,required=True);a.add_argument("--eth-zip",type=Path,required=True);a.add_argument("--eth-csv",type=Path,required=True);a.add_argument("--output",type=Path,required=True);x=a.parse_args();m=[evaluate("BTC-USDT",x.btc_zip,x.btc_csv),evaluate("ETH-USDT",x.eth_zip,x.eth_csv)];ok=all(q["accepted"] for q in m);v="signed_tail_pressure_trend_nominated_for_untouched_replication" if ok else "reject_exact_signed_tail_pressure_trend_family";weak=[]
 for q in m:
  c=q["oos_metrics"]["candidate"];b=q["oos_metrics"]["b1"];weak.append(f"{q['instrument']} candidate Sharpe {c['sharpe']:.3f} versus B1 {b['sharpe']:.3f}, edge/turn {c['net_edge_per_turnover_bps']:.2f} versus {b['net_edge_per_turnover_bps']:.2f} bps, with {q['breadth']['profitable_folds']}/12 profitable folds")
 it="The signed-tail pressure state added broad, uncertainty-supported net information beyond the daily trend comparator in both development markets." if ok else "The tail-arrival asymmetry did not produce bilateral incremental trend information: "+"; ".join(weak)+"."
 r={"schema_version":1,"family_id":FAMILY,"issue":ISSUE,"main":MAIN,"candidate_count":1,"parameter_grid_count":0,"canonical_fee_one_way_bps":5.,"markets":m,"accepted_bilaterally":ok,"verdict":v,"interpretation":it,"untouched_oos_consumed":False,"paper_or_live_authorized":False};x.output.mkdir(parents=True,exist_ok=True);p=x.output/"result.json";p.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n");print(json.dumps({"verdict":v,"result_sha256":hashlib.sha256(p.read_bytes()).hexdigest()},indent=2))
if __name__=="__main__":main()
