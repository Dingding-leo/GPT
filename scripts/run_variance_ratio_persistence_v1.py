#!/usr/bin/env python3
"""Reproduce issue #595's frozen variance-ratio persistence verdict."""
from __future__ import annotations

import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=0.0005; ANN=8760.0; TRAIN=2880; OOS=17520; STOP=43440; FOLD=2160
DIR=168; W=2160; Q=24; HOLD=168; BLOCK=168; NBOOT=5000; SEED=20260729
MAIN="5a0fcc97d1a882f8223656c51f5bb8055f534e38"
SOURCES={
 "BTC-USDT":{"artifact_id":8704977298,"zip_sha256":"22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c","csv_sha256":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9"},
 "ETH-USDT":{"artifact_id":8704978112,"zip_sha256":"e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3","csv_sha256":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"},
}


def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 return h.hexdigest()


def sharpe(x:np.ndarray):
 s=float(np.std(x,ddof=1))
 return float(np.mean(x)/s*math.sqrt(ANN)) if s>0 else None


def metrics(net,gross,turn,pos):
 eq=np.cumprod(1+net); path=np.r_[1.0,eq]; dd=path/np.maximum.accumulate(path)-1
 t=float(turn.sum())
 return {"net_total_return":float(eq[-1]-1),"sharpe":sharpe(net),"max_drawdown":float(dd.min()),"turnover":t,"fee_sum":t*FEE,"net_edge_per_turnover_bps":float(net.sum()/t*1e4) if t else None,"average_exposure":float(pos.mean())}


def residual(a,b): return sharpe(a-b)


def vr24(r):
 s=pd.Series(r); den=s.rolling(W,min_periods=W).var(ddof=1)*Q
 qsum=s.rolling(Q,min_periods=Q).sum(); num=qsum.rolling(W-Q+1,min_periods=W-Q+1).var(ddof=1)
 a=num.to_numpy(float); b=den.to_numpy(float); out=np.full(len(r),np.nan); ok=np.isfinite(a)&np.isfinite(b)&(b>0); out[ok]=a[ok]/b[ok]; return out


def bootstrap(a,b):
 n=len(a); count=math.ceil(n/BLOCK); lengths=np.full(count,BLOCK,dtype=int); lengths[-1]=n-BLOCK*(count-1); rng=np.random.default_rng(SEED)
 def pref(x): return np.r_[0.,np.cumsum(x)],np.r_[0.,np.cumsum(x*x)]
 pa,pa2=pref(a); pb,pb2=pref(b); md=np.empty(NBOOT); sd=np.empty(NBOOT)
 for k in range(NBOOT):
  starts=np.array([rng.integers(0,n-L+1) for L in lengths]); sa=float(np.sum(pa[starts+lengths]-pa[starts])); sb=float(np.sum(pb[starts+lengths]-pb[starts])); sa2=float(np.sum(pa2[starts+lengths]-pa2[starts])); sb2=float(np.sum(pb2[starts+lengths]-pb2[starts])); ma=sa/n; mb=sb/n; va=max(0.,(sa2-n*ma*ma)/(n-1)); vb=max(0.,(sb2-n*mb*mb)/(n-1)); ha=ma/math.sqrt(va)*math.sqrt(ANN) if va>0 else 0.; hb=mb/math.sqrt(vb)*math.sqrt(ANN) if vb>0 else 0.; md[k]=(ma-mb)*ANN; sd[k]=ha-hb
 return {"annualized_mean_delta_lower_95":float(np.quantile(md,.025)),"sharpe_delta_lower_95":float(np.quantile(sd,.025))}


def evaluate(inst,zip_path,csv_path):
 src=SOURCES[inst]
 if sha(zip_path)!=src["zip_sha256"] or sha(csv_path)!=src["csv_sha256"]: raise ValueError(f"hash mismatch: {inst}")
 df=pd.read_csv(csv_path); ts=pd.DatetimeIndex(pd.to_datetime(df.timestamp,utc=True)); px=df[["open","high","low","close"]].to_numpy(float)
 if len(df)!=43941 or not (df.confirm==1).all() or ts.has_duplicates or not ts.is_monotonic_increasing or not np.all(np.diff(ts.view("int64"))==3600_000_000_000) or not np.isfinite(px).all() or not (px>0).all(): raise ValueError(f"invalid grid: {inst}")
 close=df.close.to_numpy(float); opening=df.open.to_numpy(float); lc=np.log(close); r=np.r_[np.nan,np.diff(lc)]; direction=np.full(len(df),np.nan); direction[DIR:]=lc[DIR:]-lc[:-DIR]; trend=np.full(len(df),np.nan); trend[W:]=lc[W:]-lc[:-W]; vr=vr24(r)
 daily=(np.arange(len(df))>=TRAIN)&(np.arange(len(df))<OOS)&(ts.hour==0)&np.isfinite(vr); train_vr=vr[daily]; entry=float(np.quantile(train_vr,.6)); exit=float(np.quantile(train_vr,.4))
 payoff=opening[2:STOP+2]/opening[1:STOP+1]-1; cand=np.zeros(STOP); d0=np.zeros(STOP); b0=np.zeros(STOP); b1=np.zeros(STOP); cs=ds=b1s=0.; ce=de=None
 for i in range(STOP):
  if i>=W: b0[i]=float(trend[i]>0)
  if ts[i].hour==0:
   if i>=W: b1s=float(trend[i]>0)
   if i>=TRAIN:
    if not (math.isfinite(direction[i]) and math.isfinite(vr[i])): raise ValueError(f"bad feature {inst} {i}")
    if cs==0 and direction[i]>0 and vr[i]>entry: cs=1.; ce=i
    elif cs==1 and i-ce>=HOLD and (direction[i]<=0 or vr[i]<exit): cs=0.; ce=None
    if ds==0 and direction[i]>0: ds=1.; de=i
    elif ds==1 and i-de>=HOLD and direction[i]<=0: ds=0.; de=None
  cand[i]=cs; d0[i]=ds; b1[i]=b1s
 def path(p):
  prior=np.r_[0.,p[:-1]]; turn=np.abs(p-prior); gross=p*payoff; return {"position":p,"turn":turn,"gross":gross,"net":gross-FEE*turn}
 paths={"candidate":path(cand),"d0":path(d0),"b0":path(b0),"b1":path(b1)}
 def slice_metric(name,a,b):
  q=paths[name]; return metrics(q["net"][a:b],q["gross"][a:b],q["turn"][a:b],q["position"][a:b])
 train=slice_metric("candidate",TRAIN,OOS); full=slice_metric("candidate",TRAIN,STOP); oos={k:slice_metric(k,OOS,STOP) for k in paths}
 oc=paths["candidate"]["net"][OOS:STOP]; od=paths["d0"]["net"][OOS:STOP]; ots=ts[OOS:STOP]; folds=[float(np.prod(1+oc[j:j+FOLD])-1) for j in range(0,len(oc),FOLD)]; years={str(y):float(np.prod(1+oc[np.asarray(ots.year)==y])-1) for y in sorted(set(ots.year))}; pos=[max(0.,x) for x in folds]; conc=max(pos)/sum(pos) if sum(pos)>0 else None
 prior=np.r_[0.,cand[:-1]]; entries=np.flatnonzero((cand==1)&(prior==0)); exits=np.flatnonzero((cand==0)&(prior==1)); oentries=entries[(entries>=OOS)&(entries<STOP)]; holds=[]
 for e in entries:
  x=exits[exits>e]
  if len(x) and e<STOP and x[0]>OOS: holds.append(int(x[0]-e))
 unc=bootstrap(oc,od); gates={"positive_net_return":oos["candidate"]["net_total_return"]>0,"positive_sharpe":oos["candidate"]["sharpe"] is not None and oos["candidate"]["sharpe"]>0,"positive_edge_per_turnover":oos["candidate"]["net_edge_per_turnover_bps"] is not None and oos["candidate"]["net_edge_per_turnover_bps"]>0,"profitable_folds_at_least_7_of_12":sum(x>0 for x in folds)>=7,"profitable_year_segments_at_least_3":sum(x>0 for x in years.values())>=3,"positive_fold_concentration_at_most_50pct":conc is not None and conc<=.5,"long_entries_at_least_5":len(oentries)>=5,"sharpe_exceeds_d0":oos["candidate"]["sharpe"]>oos["d0"]["sharpe"],"edge_per_turnover_exceeds_d0":oos["candidate"]["net_edge_per_turnover_bps"]>oos["d0"]["net_edge_per_turnover_bps"],"positive_residual_sharpe_vs_d0":residual(oc,od)>0,"positive_residual_sharpe_vs_b0":residual(oc,paths["b0"]["net"][OOS:STOP])>0,"bootstrap_mean_delta_lower_bound_positive":unc["annualized_mean_delta_lower_95"]>0,"bootstrap_sharpe_delta_lower_bound_positive":unc["sharpe_delta_lower_95"]>0}
 return {"instrument":inst,"thresholds":{"entry_vr":entry,"exit_vr":exit,"training_daily_vr_observations":int(len(train_vr))},"train_candidate":train,"oos_candidate":oos["candidate"],"oos_d0":oos["d0"],"oos_b0":oos["b0"],"oos_b1":oos["b1"],"residual_sharpe_vs_d0":residual(oc,od),"residual_sharpe_vs_b0":residual(oc,paths["b0"]["net"][OOS:STOP]),"full_candidate":full,"breadth":{"profitable_folds":sum(x>0 for x in folds),"fold_count":len(folds),"positive_fold_return_concentration":conc,"profitable_years":sum(x>0 for x in years.values()),"year_count":len(years),"year_returns":years},"position":{"long_entries_oos":int(len(oentries)),"median_completed_holding_hours":float(np.median(holds)),"mean_completed_holding_hours":float(np.mean(holds)),"max_completed_holding_hours":max(holds)},"uncertainty_vs_d0":unc,"acceptance_gates":gates,"accepted":all(gates.values())}


def main():
 p=argparse.ArgumentParser(); p.add_argument("--btc-zip",type=Path,required=True); p.add_argument("--btc-csv",type=Path,required=True); p.add_argument("--eth-zip",type=Path,required=True); p.add_argument("--eth-csv",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args(); markets=[evaluate("BTC-USDT",a.btc_zip,a.btc_csv),evaluate("ETH-USDT",a.eth_zip,a.eth_csv)]
 out={"schema_version":1,"family_id":"variance-ratio-persistence-state-1h-v1","issue":595,"main":MAIN,"bar":"1H","candidate_count":1,"fee_bps_one_way":5.0,"execution":"completed confirmed bar t; target at open[t+1]; payoff open[t+1] to open[t+2]","sample":{"train_hours":14640,"oos_hours":25920,"folds":12,"fold_hours":2160,"unscored_suffix":True},"bootstrap":{"method":"paired_non_circular_moving_block","block_hours":168,"resamples":5000,"seed":SEED},"sources":SOURCES,"markets":markets,"untouched_oos_consumed":False,"paper_or_live_authorized":False,"rescue_tuning_authorized":False,"verdict":"accept_for_shadow_observation_only" if all(m["accepted"] for m in markets) else "reject_exact_variance_ratio_persistence_family"}
 a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n"); print(json.dumps({"output":str(a.output),"sha256":sha(a.output),"verdict":out["verdict"]},indent=2))
if __name__=="__main__": main()
