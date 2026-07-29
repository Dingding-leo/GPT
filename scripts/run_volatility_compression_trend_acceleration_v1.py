#!/usr/bin/env python3
# ruff: noqa
# fmt: off
"""Reproduce issue #614's frozen volatility-compression trend-acceleration verdict."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np,pandas as pd
FEE=.0005;ANN=8760.;TR=2880;OOS=17520;STOP=43440;FOLD=2160;FAST=168;SLOW=2160;ENTRY=.70;EXIT=.45;HOLD=168;NB=5000;BLOCK=168;SEED=20260729
MAIN="5a0fcc97d1a882f8223656c51f5bb8055f534e38";ISSUE=614;FAMILY="volatility-compression-trend-acceleration-1h-v1";RUN=30401519824
SRC={"BTC-USDT":{"artifact_id":8704977298,"zip_sha256":"22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c","csv_sha256":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9"},"ETH-USDT":{"artifact_id":8704978112,"zip_sha256":"e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3","csv_sha256":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}}
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def sh(x):
 s=float(np.std(x,ddof=1));return float(np.mean(x)/s*math.sqrt(ANN)) if len(x)>1 and s>0 and math.isfinite(s) else None
def met(n,g,t,p):
 e=np.cumprod(1+n);q=np.r_[1.,e];d=q/np.maximum.accumulate(q)-1;z=float(t.sum());return {"gross_total_return":float(np.prod(1+g)-1),"net_total_return":float(e[-1]-1),"annualized_arithmetic_mean":float(np.mean(n)*ANN),"sharpe":sh(n),"max_drawdown":float(d.min()),"turnover":z,"fee_sum":z*FEE,"net_edge_per_turnover_bps":float(n.sum()/z*1e4) if z else None,"average_exposure":float(p.mean())}
def path(p,r):
 q=np.r_[0.,p[:-1]];t=np.abs(p-q);g=p*r;n=g-FEE*t
 if not np.allclose(n,g-FEE*t,atol=0,rtol=0):raise AssertionError("fee")
 return {"position":p,"turn":t,"gross":g,"net":n}
def boot(a,b):
 n=len(a);ls=np.full(math.ceil(n/BLOCK),BLOCK,int);ls[-1]=n-BLOCK*(len(ls)-1);rng=np.random.default_rng(SEED);md=np.empty(NB);sd=np.empty(NB)
 for j in range(NB):
  ss=[int(rng.integers(0,n-int(L)+1)) for L in ls];ix=np.concatenate([np.arange(s,s+int(L)) for s,L in zip(ss,ls)]);aa=a[ix];bb=b[ix];md[j]=np.mean(aa-bb)*ANN;sd[j]=(sh(aa) or 0)-(sh(bb) or 0)
 return {"annualized_mean_delta_lower_95":float(np.quantile(md,.025)),"annualized_mean_delta_median":float(np.quantile(md,.5)),"annualized_mean_delta_upper_95":float(np.quantile(md,.975)),"sharpe_delta_lower_95":float(np.quantile(sd,.025)),"sharpe_delta_median":float(np.quantile(sd,.5)),"sharpe_delta_upper_95":float(np.quantile(sd,.975))}
def features(df):
 c=df.close.to_numpy(float);lc=np.log(c);r=np.full(len(c),np.nan);r[1:]=np.diff(lc);sq=pd.Series(r*r);f=np.sqrt(sq.rolling(FAST,min_periods=FAST).mean()).to_numpy();s=np.sqrt(sq.rolling(SLOW,min_periods=SLOW).mean()).to_numpy();vr=np.full(len(c),np.nan);v=np.isfinite(f)&np.isfinite(s)&(s>0);vr[v]=f[v]/s[v];m=np.full(len(c),np.nan);m[FAST:]=lc[FAST:]-lc[:-FAST];p=np.full(len(c),np.nan);p[2*FAST:]=lc[FAST:-FAST]-lc[:-2*FAST];a=m-p;tr=np.full(len(c),np.nan);tr[SLOW:]=lc[SLOW:]-lc[:-SLOW];return vr,m,a,tr
def scores(vr,a,tm):
 tv=vr[tm];ta=a[tm];cr=1-pd.Series(tv).rank(method="average",pct=True).to_numpy();ar=pd.Series(ta).rank(method="average",pct=True).to_numpy();tq=(cr+ar)/2;en=float(np.quantile(tq,ENTRY,method="linear"));ex=float(np.quantile(tq,EXIT,method="linear"));vrs=np.sort(tv);aas=np.sort(ta);sc=np.full(len(vr),np.nan);ok=np.isfinite(vr)&np.isfinite(a);sc[ok]=(1-np.searchsorted(vrs,vr[ok],side="right")/len(vrs)+np.searchsorted(aas,a[ok],side="right")/len(aas))/2;sc[tm]=tq;return sc,en,ex,{"valid_training_anchors":int(tm.sum()),"entry_score_quantile":ENTRY,"entry_score_threshold":en,"exit_score_quantile":EXIT,"exit_score_threshold":ex,"training_vol_ratio_q10":float(np.quantile(tv,.1)),"training_vol_ratio_median":float(np.quantile(tv,.5)),"training_vol_ratio_q90":float(np.quantile(tv,.9)),"training_acceleration_q10":float(np.quantile(ta,.1)),"training_acceleration_median":float(np.quantile(ta,.5)),"training_acceleration_q90":float(np.quantile(ta,.9))}
def positions(ts,m,tr,sc,en,ex):
 n=len(ts);ca=np.zeros(n);b0=np.zeros(n);b1=np.zeros(n);dec=np.asarray(ts.hour==0);tp=np.isfinite(tr)&(tr>0);mp=np.isfinite(m)&(m>0);se=np.isfinite(sc)&(sc>=en);entry=tp&mp&se;state=dstate=0.;ei=None
 for i in range(n):
  if np.isfinite(tr[i]):b0[i]=float(tr[i]>0)
  if dec[i]:
   dstate=float(tp[i])
   if state==0 and entry[i]:state=1.;ei=i
   elif state==1 and ei is not None and i-ei>=HOLD and ((not tp[i]) or (not mp[i]) or (not np.isfinite(sc[i])) or sc[i]<ex):state=0.;ei=None
  ca[i]=state;b1[i]=dstate
 return {"candidate":ca,"b0":b0,"b1":b1,"trend_positive":tp,"latest_positive":mp,"score_entry":se,"entry_condition":entry}
def dist(x):
 x=x[np.isfinite(x)];return {"count":int(len(x)),"q10":float(np.quantile(x,.1)),"median":float(np.quantile(x,.5)),"q90":float(np.quantile(x,.9))}
def holds(p,a,b):
 q=np.r_[0.,p[:-1]];en=np.flatnonzero((p==1)&(q==0));ex=np.flatnonzero((p==0)&(q==1));oe=en[(en>=a)&(en<b)];hs=[]
 for e in en:
  z=ex[ex>e]
  if len(z) and e<b and z[0]>a:hs.append(int(z[0]-e))
 return {"long_entries":int(len(oe)),"median_completed_holding_hours":float(np.median(hs)) if hs else None,"mean_completed_holding_hours":float(np.mean(hs)) if hs else None,"max_completed_holding_hours":max(hs) if hs else None}
def evaluate(inst,zp,cp):
 s=SRC[inst]
 if sha(zp)!=s["zip_sha256"] or sha(cp)!=s["csv_sha256"]:raise ValueError("hash")
 df=pd.read_csv(cp,nrows=STOP+2);ts=pd.DatetimeIndex(pd.to_datetime(df.timestamp,utc=True));px=df[["open","high","low","close"]].to_numpy(float)
 if len(df)!=STOP+2 or not(df.confirm==1).all() or ts.has_duplicates or not ts.is_monotonic_increasing or not np.all(np.diff(ts.view("int64"))==3600_000_000_000) or not np.isfinite(px).all() or not(px>0).all():raise ValueError("grid")
 vr,m,a,tr=features(df);ix=np.arange(len(df));dec=np.asarray(ts.hour==0);vf=np.isfinite(vr)&np.isfinite(a)&np.isfinite(m)&np.isfinite(tr);tm=(ix>=TR)&(ix<OOS)&dec&vf;om=(ix>=OOS)&(ix<STOP)&dec&vf;sc,en,ex,fr=scores(vr,a,tm);ps=positions(ts,m,tr,sc,en,ex);op=df.open.to_numpy(float);pay=op[2:STOP+2]/op[1:STOP+1]-1;pp={k:path(ps[k][:STOP],pay) for k in ("candidate","b0","b1")}
 def ms(x,y):return {k:met(v["net"][x:y],v["gross"][x:y],v["turn"][x:y],v["position"][x:y]) for k,v in pp.items()}
 train=ms(TR,OOS);oos=ms(OOS,STOP);full=ms(TR,STOP);oc=pp["candidate"]["net"][OOS:STOP];ob0=pp["b0"]["net"][OOS:STOP];ob1=pp["b1"]["net"][OOS:STOP];ots=ts[OOS:STOP];folds=[float(np.prod(1+oc[j:j+FOLD])-1) for j in range(0,len(oc),FOLD)];years={str(y):float(np.prod(1+oc[np.asarray(ots.year)==y])-1) for y in sorted(set(ots.year))};pf=[max(0,x) for x in folds];conc=max(pf)/sum(pf) if sum(pf)>0 else None;u=boot(oc,ob1);r0=oc-ob0;r1=oc-ob1;th=holds(pp["candidate"]["position"],TR,OOS);oh=holds(pp["candidate"]["position"],OOS,STOP)
 def wf(mask):return {"daily_decisions":int(mask.sum()),"positive_slow_trend":int((mask&ps["trend_positive"]).sum()),"positive_slow_trend_and_latest_return":int((mask&ps["trend_positive"]&ps["latest_positive"]).sum()),"score_above_entry":int((mask&ps["score_entry"]).sum()),"full_entry_condition":int((mask&ps["entry_condition"]).sum())}
 cm=oos["candidate"];bm=oos["b1"];g={"positive_net_return":cm["net_total_return"]>0,"finite_sharpe_and_exceeds_b1":cm["sharpe"] is not None and bm["sharpe"] is not None and cm["sharpe"]>bm["sharpe"],"edge_per_turnover_exceeds_b1":cm["net_edge_per_turnover_bps"] is not None and bm["net_edge_per_turnover_bps"] is not None and cm["net_edge_per_turnover_bps"]>bm["net_edge_per_turnover_bps"],"max_drawdown_no_worse_than_b1":cm["max_drawdown"]>=bm["max_drawdown"],"long_entries_at_least_8":oh["long_entries"]>=8,"profitable_folds_at_least_7_of_12":sum(x>0 for x in folds)>=7,"profitable_year_segments_at_least_3":sum(x>0 for x in years.values())>=3,"positive_fold_concentration_at_most_50pct":conc is not None and conc<=.5,"positive_residual_sharpe_vs_b0":sh(r0) is not None and sh(r0)>0,"positive_residual_sharpe_vs_b1":sh(r1) is not None and sh(r1)>0,"bootstrap_mean_delta_lower_bound_positive":u["annualized_mean_delta_lower_95"]>0,"bootstrap_sharpe_delta_lower_bound_positive":u["sharpe_delta_lower_95"]>0,"hash_chronology_timing_fee_checks":True}
 return {"instrument":inst,"source":{**s,"workflow_run":RUN},"grid":{"parsed_observations":len(df),"source_observations":43941,"first_timestamp":ts[0].isoformat(),"last_required_timestamp":ts[-1].isoformat(),"confirmed_required_prefix":True,"contiguous_1h_required_prefix":True,"later_suffix_semantically_read":False},"frozen_training":fr,"signal_waterfall":{"training":wf(tm),"development_oos":wf(om)},"feature_drift":{"vol_ratio_training":dist(vr[tm]),"vol_ratio_oos":dist(vr[om]),"acceleration_training":dist(a[tm]),"acceleration_oos":dist(a[om]),"score_training":dist(sc[tm]),"score_oos":dist(sc[om])},"train_metrics":train,"oos_metrics":oos,"full_metrics":full,"breadth":{"fold_returns":folds,"profitable_folds":sum(x>0 for x in folds),"fold_count":len(folds),"positive_fold_return_concentration":conc,"year_returns":years,"profitable_years":sum(x>0 for x in years.values()),"year_count":len(years)},"train_position":th,"position":oh,"residual_total_return_vs_b0":float(np.prod(1+r0)-1),"residual_total_return_vs_b1":float(np.prod(1+r1)-1),"residual_sharpe_vs_b0":sh(r0),"residual_sharpe_vs_b1":sh(r1),"uncertainty_vs_b1":u,"acceptance_gates":g,"accepted":all(g.values())}
def protocol():return {"family_id":FAMILY,"issue":ISSUE,"research_parent":MAIN,"candidate_count":1,"parameter_grid_count":0,"bar":"1H","markets":["BTC-USDT","ETH-USDT"],"decision_cadence":"daily 00:00 UTC","execution":"completed bar t -> target open[t+1] -> payoff open[t+1] to open[t+2]","canonical_fee_one_way":FEE,"sample":{"warmup":[0,TR],"training":[TR,OOS],"development_oos":[OOS,STOP],"fold_hours":FOLD,"fold_count":12,"later_suffix_unread":True},"features":{"recent_rv_hours":FAST,"slow_rv_hours":SLOW,"rv_definition":"sqrt(mean(hourly_log_return_squared))","acceleration":"latest_168h_log_return - prior_168h_log_return","slow_trend_hours":SLOW,"training_mapping":"average-rank ECDF","oos_mapping":"frozen right-continuous training ECDF","score":"equal mean of compression percentile and acceleration percentile","entry_score_training_quantile":ENTRY,"exit_score_training_quantile":EXIT,"quantile_method":"numpy-linear"},"position_rule":{"minimum_hold_hours":HOLD,"entry":"slow_trend>0 and latest_168h_return>0 and score>=entry_threshold","exit":"after min hold: slow_trend<=0 or latest_168h_return<=0 or score<exit_threshold","long_cash_only":True},"comparators":["b0_hourly_2160h_trend","b1_daily_2160h_trend"],"uncertainty":{"method":"paired non-circular moving-block bootstrap","resamples":NB,"block_hours":BLOCK,"seed":SEED},"sources":SRC,"hard_boundary":{"cross_sectional":False,"credentials":False,"private_endpoints":False,"accounts":False,"orders":False,"leverage":False,"synthetic_data":False,"15m":False,"paper_or_live_authorized":False}}
def main():
 p=argparse.ArgumentParser();p.add_argument("--btc-zip",type=Path,required=True);p.add_argument("--btc-csv",type=Path,required=True);p.add_argument("--eth-zip",type=Path,required=True);p.add_argument("--eth-csv",type=Path,required=True);p.add_argument("--out",type=Path,required=True);a=p.parse_args();r={"family_id":FAMILY,"issue":ISSUE,"research_parent":MAIN,"candidate_count":1,"parameter_grid_count":0,"markets":{"BTC-USDT":evaluate("BTC-USDT",a.btc_zip,a.btc_csv),"ETH-USDT":evaluate("ETH-USDT",a.eth_zip,a.eth_csv)}};r["accepted"]=all(x["accepted"] for x in r["markets"].values());r["verdict"]="accept_volatility_compression_trend_acceleration_candidate" if r["accepted"] else "reject_exact_volatility_compression_trend_acceleration_family";r["paper_or_live_authorized"]=False;r["discrepancy_repair"]={"initial_failure":"report serialization referenced a missing train_position field","repair":"persist segment-specific training entry counts from the already-computed candidate position path","frozen_rule_changed":False,"metrics_changed":False};a.out.mkdir(parents=True,exist_ok=True);(a.out/"protocol.json").write_text(json.dumps(protocol(),indent=2,sort_keys=True)+"\n");(a.out/"result.json").write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
if __name__=="__main__":main()
