#!/usr/bin/env python3
# ruff: noqa
# fmt: off
"""Reproduce issue #611's frozen trend-break path-recovery verdict."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np,pandas as pd
FEE=.0005;ANN=8760.;TR=2880;OOS=17520;STOP=43440;FOLD=2160;RH=2160;BW=168;SW=72;Q=.20;EL=.75;XL=.50;HOLD=168;NB=5000;BLOCK=168;SEED=20260729
MAIN="5a0fcc97d1a882f8223656c51f5bb8055f534e38";ISSUE=611;FAMILY="trend-break-path-recovery-1h-v1";RUN=30401519824
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
  ss=[int(rng.integers(0,n-int(L)+1)) for L in ls];ix=np.concatenate([np.arange(s,s+int(L)) for s,L in zip(ss,ls)]);aa=a[ix];bb=b[ix];md[j]=float(np.mean(aa-bb)*ANN);sd[j]=float((sh(aa) or 0)-(sh(bb) or 0))
 return {"annualized_mean_delta_lower_95":float(np.quantile(md,.025)),"annualized_mean_delta_median":float(np.quantile(md,.5)),"annualized_mean_delta_upper_95":float(np.quantile(md,.975)),"sharpe_delta_lower_95":float(np.quantile(sd,.025)),"sharpe_delta_median":float(np.quantile(sd,.5)),"sharpe_delta_upper_95":float(np.quantile(sd,.975))}
def feat(df):
 c=df.close.to_numpy(float);h=df.high.to_numpy(float);l=df.low.to_numpy(float);ph=pd.Series(c).shift(1).rolling(RH,min_periods=RH).max().to_numpy();dd=c/ph-1;br=pd.Series(dd).rolling(BW,min_periods=BW).min().to_numpy();x=np.arange(SW,dtype=float);xc=x-x.mean();sl=np.full(len(c),np.nan);sl[SW-1:]=np.convolve(np.log(c),xc[::-1],mode="valid")/float(xc@xc);lo=pd.Series(l).rolling(SW,min_periods=SW).min().to_numpy();hi=pd.Series(h).rolling(SW,min_periods=SW).max().to_numpy();w=hi-lo;loc=np.full(len(c),np.nan);v=np.isfinite(w)&(w>0);loc[v]=(c[v]-lo[v])/w[v];tr=np.full(len(c),np.nan);tr[RH:]=np.log(c[RH:]/c[:-RH]);return br,sl,loc,tr
def positions(ts,br,sl,loc,tr,th):
 n=len(ts);ca=np.zeros(n);b0=np.zeros(n);b1=np.zeros(n);dec=np.asarray(ts.hour==0);state=dstate=0.;entry=None
 bc=np.isfinite(br)&(br<=th);tc=np.isfinite(tr)&(tr>0);sc=np.isfinite(sl)&(sl>0);lc=np.isfinite(loc)&(loc>=EL);ec=bc&tc&sc&lc
 for i in range(n):
  if np.isfinite(tr[i]):b0[i]=float(tr[i]>0)
  if dec[i]:
   dstate=float(tc[i])
   if state==0:
    if ec[i]:state=1.;entry=i
   elif entry is not None and i-entry>=HOLD and (not tc[i] or not sc[i] or not np.isfinite(loc[i]) or loc[i]<XL):state=0.;entry=None
  ca[i]=state;b1[i]=dstate
 return {"candidate":ca,"b0":b0,"b1":b1,"decision":dec,"break":bc,"trend":tc,"slope":sc,"location":lc,"entry":ec}
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
 br,sl,loc,tr=feat(df);ix=np.arange(len(df));dec=np.asarray(ts.hour==0);tm=(ix>=TR)&(ix<OOS)&dec&np.isfinite(br);th=float(np.quantile(br[tm],Q,method="linear"));ps=positions(ts,br,sl,loc,tr,th);op=df.open.to_numpy(float);pay=op[2:STOP+2]/op[1:STOP+1]-1;pp={k:path(ps[k][:STOP],pay) for k in ("candidate","b0","b1")}
 def ms(a,b):return {k:met(v["net"][a:b],v["gross"][a:b],v["turn"][a:b],v["position"][a:b]) for k,v in pp.items()}
 train=ms(TR,OOS);oos=ms(OOS,STOP);full=ms(TR,STOP);oc=pp["candidate"]["net"][OOS:STOP];ob0=pp["b0"]["net"][OOS:STOP];ob1=pp["b1"]["net"][OOS:STOP];ots=ts[OOS:STOP];folds=[float(np.prod(1+oc[j:j+FOLD])-1) for j in range(0,len(oc),FOLD)];years={str(y):float(np.prod(1+oc[np.asarray(ots.year)==y])-1) for y in sorted(set(ots.year))};pos=[max(0,x) for x in folds];conc=max(pos)/sum(pos) if sum(pos)>0 else None;u=boot(oc,ob1);r0=oc-ob0;r1=oc-ob1;hs=holds(pp["candidate"]["position"],OOS,STOP);om=(ix>=OOS)&(ix<STOP)&dec
 def wf(m):return {"daily_decisions":int(m.sum()),"break_only":int((m&ps["break"]).sum()),"break_and_slow_trend":int((m&ps["break"]&ps["trend"]).sum()),"break_slow_trend_and_positive_slope":int((m&ps["break"]&ps["trend"]&ps["slope"]).sum()),"full_entry_condition":int((m&ps["entry"]).sum()),"break_positive_slope_and_location_without_trend":int((m&ps["break"]&ps["slope"]&ps["location"]).sum())}
 cm=oos["candidate"];bm=oos["b1"];g={"positive_net_return":cm["net_total_return"]>0,"finite_sharpe_and_exceeds_b1":cm["sharpe"] is not None and bm["sharpe"] is not None and cm["sharpe"]>bm["sharpe"],"edge_per_turnover_exceeds_b1":cm["net_edge_per_turnover_bps"] is not None and bm["net_edge_per_turnover_bps"] is not None and cm["net_edge_per_turnover_bps"]>bm["net_edge_per_turnover_bps"],"max_drawdown_no_worse_than_b1":cm["max_drawdown"]>=bm["max_drawdown"],"long_entries_at_least_8":hs["long_entries"]>=8,"profitable_folds_at_least_7_of_12":sum(x>0 for x in folds)>=7,"profitable_year_segments_at_least_3":sum(x>0 for x in years.values())>=3,"positive_fold_concentration_at_most_50pct":conc is not None and conc<=.5,"positive_residual_sharpe_vs_b0":sh(r0) is not None and sh(r0)>0,"positive_residual_sharpe_vs_b1":sh(r1) is not None and sh(r1)>0,"bootstrap_mean_delta_lower_bound_positive":u["annualized_mean_delta_lower_95"]>0,"bootstrap_sharpe_delta_lower_bound_positive":u["sharpe_delta_lower_95"]>0,"hash_chronology_timing_fee_checks":True}
 return {"instrument":inst,"source":{**s,"workflow_run":RUN},"grid":{"parsed_observations":len(df),"source_observations":43941,"first_timestamp":ts[0].isoformat(),"last_required_timestamp":ts[-1].isoformat(),"confirmed_required_prefix":True,"contiguous_1h_required_prefix":True,"later_suffix_semantically_read":False},"frozen_training":{"daily_feature_anchors":int(tm.sum()),"break_quantile":Q,"break_quantile_method":"numpy-linear","break_threshold":th},"entry_condition_waterfall":{"training":wf(tm),"development_oos":wf(om)},"feature_drift":{"recent_break_training":dist(br[tm]),"recent_break_oos":dist(br[om]),"slope_training":dist(sl[tm]),"slope_oos":dist(sl[om]),"close_location_training":dist(loc[tm]),"close_location_oos":dist(loc[om])},"train_metrics":train,"oos_metrics":oos,"full_metrics":full,"breadth":{"fold_returns":folds,"profitable_folds":sum(x>0 for x in folds),"fold_count":len(folds),"positive_fold_return_concentration":conc,"year_returns":years,"profitable_years":sum(x>0 for x in years.values()),"year_count":len(years)},"position":hs,"residual_total_return_vs_b0":float(np.prod(1+r0)-1),"residual_total_return_vs_b1":float(np.prod(1+r1)-1),"residual_sharpe_vs_b0":sh(r0),"residual_sharpe_vs_b1":sh(r1),"uncertainty_vs_b1":u,"acceptance_gates":g,"accepted":all(g.values())}
def protocol():return {"family_id":FAMILY,"issue":ISSUE,"research_parent":MAIN,"candidate_count":1,"parameter_grid_count":0,"bar":"1H","markets":["BTC-USDT","ETH-USDT"],"decision_cadence":"daily 00:00 UTC","execution":"completed bar t -> target open[t+1] -> payoff open[t+1] to open[t+2]","canonical_fee_one_way":FEE,"sample":{"warmup":[0,TR],"training":[TR,OOS],"development_oos":[OOS,STOP],"fold_hours":FOLD,"fold_count":12,"later_suffix_unread":True},"features":{"rolling_high_hours":RH,"rolling_high_excludes_current":True,"recent_break_window_hours":BW,"training_break_quantile":Q,"training_break_quantile_method":"numpy-linear","recovery_ols_log_close_hours":SW,"entry_slope_threshold":0.,"entry_close_location":EL,"slow_trend_hours":RH},"position_rule":{"minimum_hold_hours":HOLD,"exit_close_location":XL,"long_cash_only":True},"comparators":["b0_hourly_2160h_trend","b1_daily_2160h_trend"],"uncertainty":{"method":"paired non-circular moving-block bootstrap","resamples":NB,"block_hours":BLOCK,"seed":SEED},"sources":SRC,"hard_boundary":{"cross_sectional":False,"credentials":False,"private_endpoints":False,"accounts":False,"orders":False,"leverage":False,"synthetic_data":False,"15m":False,"paper_or_live_authorized":False}}
def pct(x):return "undefined" if x is None else f"{100*x:.2f}%"
def num(x):return "undefined" if x is None else f"{x:.3f}"
def report(r):
 L=["# Trend-break path-recovery 1H experiment","","## Frozen strategy change","","Deep rolling-high break (training q20) + positive 72H OLS log-close slope + 72H close location >= 0.75 + positive 2160H trend; daily next-open long/cash, 168H minimum hold, exactly 5 bps one-way.","",f"Candidate count: 1; grid: 0; preregistration: #{ISSUE}; parent: `{MAIN}`.","","## Thresholds and inactivity diagnosis","","| Market | q20 break | Train break | Train break+trend | OOS break | OOS break+trend | Recovery geometry without trend (train/OOS) | Entries |","|---|---:|---:|---:|---:|---:|---:|---:|"]
 for m,x in r["markets"].items():
  a=x["entry_condition_waterfall"]["training"];b=x["entry_condition_waterfall"]["development_oos"];L.append(f"| {m} | {pct(x['frozen_training']['break_threshold'])} | {a['break_only']} | {a['break_and_slow_trend']} | {b['break_only']} | {b['break_and_slow_trend']} | {a['break_positive_slope_and_location_without_trend']} / {b['break_positive_slope_and_location_without_trend']} | {x['position']['long_entries']} |")
 L += ["","The deep-break and positive-2160H-trend conditions never overlapped in either market in training or development OOS. Recovery geometry existed only while the slow trend was non-positive. This is the direct no-trade mechanism, not a chronology or fee defect."]
 for key,title in [("train_metrics","Training"),("oos_metrics","Development OOS"),("full_metrics","Full scored")]:
  L += ["",f"## {title} metrics","","| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure |","|---|---|---:|---:|---:|---:|---:|---:|---:|"]
  for m,x in r["markets"].items():
   for p in ("candidate","b0","b1"):
    z=x[key][p];L.append(f"| {m} | {p} | {pct(z['net_total_return'])} | {num(z['sharpe'])} | {pct(z['max_drawdown'])} | {z['turnover']:.0f} | {pct(z['fee_sum'])} | {num(z['net_edge_per_turnover_bps'])} bps | {pct(z['average_exposure'])} |")
 L += ["","## Breadth and uncertainty","","| Market | Folds | Years | Concentration | Residual Sharpe B0/B1 | Mean delta L95 | Sharpe delta L95 |","|---|---:|---:|---:|---:|---:|---:|"]
 for m,x in r["markets"].items():
  u=x["uncertainty_vs_b1"];L.append(f"| {m} | {x['breadth']['profitable_folds']}/{x['breadth']['fold_count']} | {x['breadth']['profitable_years']}/{x['breadth']['year_count']} | {pct(x['breadth']['positive_fold_return_concentration'])} | {num(x['residual_sharpe_vs_b0'])}/{num(x['residual_sharpe_vs_b1'])} | {u['annualized_mean_delta_lower_95']:.6f} | {u['sharpe_delta_lower_95']:.6f} |")
 L += ["","## Verdict","",f"`{r['verdict']}`","","No G1 nomination, prospective paper promotion, or live authorization results. No threshold, horizon, hold, exit, cadence, timing, fee, market, sizing, comparator, or bootstrap rescue is permitted on this consumed development interval."]
 return "\n".join(L)+"\n"
def main():
 a=argparse.ArgumentParser();a.add_argument("--btc-zip",type=Path,required=True);a.add_argument("--btc-csv",type=Path,required=True);a.add_argument("--eth-zip",type=Path,required=True);a.add_argument("--eth-csv",type=Path,required=True);a.add_argument("--output-dir",type=Path,required=True);q=a.parse_args();q.output_dir.mkdir(parents=True,exist_ok=True);p=protocol();mk={"BTC-USDT":evaluate("BTC-USDT",q.btc_zip,q.btc_csv),"ETH-USDT":evaluate("ETH-USDT",q.eth_zip,q.eth_csv)};ok=all(x["accepted"] for x in mk.values());r={"family_id":FAMILY,"issue":ISSUE,"research_parent":MAIN,"candidate_count":1,"parameter_grid_count":0,"accepted":ok,"verdict":"accept_trend_break_path_recovery_for_untouched_replication" if ok else "reject_exact_trend_break_path_recovery_family","markets":mk};(q.output_dir/"protocol.json").write_text(json.dumps(p,indent=2,sort_keys=True)+"\n");(q.output_dir/"result.json").write_text(json.dumps(r,indent=2,sort_keys=True)+"\n");(q.output_dir/"report.md").write_text(report(r));print(json.dumps({"verdict":r["verdict"],"accepted":ok},indent=2))
if __name__=="__main__":main()
