# ruff: noqa
# fmt: off
"""Reproduce issue #697 from immutable public OKX 1H CSV artifacts."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd
FEE=5e-4; ANN=8760.; W=2160; H=168; N=43441; FOLD=2160
TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); R=5000; SEED=20260730
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}

def load(path,market):
 raw=Path(path).read_bytes(); observed=hashlib.sha256(raw).hexdigest()
 if observed!=HASH[market]: raise ValueError(f"{market} hash {observed}")
 d=pd.read_csv(path,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
 ok=len(d)==N and t.equals(pd.date_range(t[0],periods=N,freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all() and (d.high>=d[["open","close"]].max(axis=1)).all() and (d.low<=d[["open","close"]].min(axis=1)).all()
 if not ok: raise ValueError(f"{market} invalid source")
 d.index=t; return d

def features(d):
 o,h,l,c=(d[k].to_numpy(float) for k in ("open","high","low","close")); r=h-l
 u=np.divide(h-np.maximum(o,c),r,out=np.zeros_like(r),where=r>0); q=np.divide(np.minimum(o,c)-l,r,out=np.zeros_like(r),where=r>0)
 u=np.clip(u,0,1); q=np.clip(q,0,1); u168=pd.Series(u,index=d.index).rolling(H,min_periods=H).sum().to_numpy(); q168=pd.Series(q,index=d.index).rolling(H,min_periods=H).sum().to_numpy(); ret=np.full(len(d),np.nan); ret[H:]=np.log(c[H:]/c[:-H]); return u168,q168,ret

def positions(d):
 n=len(d); c=d.close.to_numpy(float); u,q,r=features(d); p={k:np.zeros(n-1) for k in ("candidate","b0","b1")}; events=[]
 cand=b1=prev=0.; rid=0; used=active=False; trigger_t=resume_t=None
 for t in range(W,n-1):
  base=float(c[t]>c[t-W])
  if t+1<n-1: p["b0"][t+1]=base
  if d.index[t].hour==0:
   before=cand; action="carry"; trigger=False
   if not(np.isfinite(u[t]) and np.isfinite(q[t]) and np.isfinite(r[t])): raise ValueError("nonfinite feature")
   if base<=0:
    action="base_exit_during_pause" if active else ("base_exit" if before>0 else "remain_cash"); cand=0.; used=active=False; trigger_t=resume_t=None
   elif prev<=0:
    rid+=1; cand=1.; used=active=False; trigger_t=resume_t=None; action="new_trend_entry"
   elif active:
    if t<resume_t: cand=0.; action="pause_cash"
    elif t==resume_t:
     if t-trigger_t!=H: raise ValueError("pause length")
     cand=1.; active=False; action="automatic_resume"
    else: raise ValueError("missed resume")
   else:
    trigger=bool((not used) and cand>0 and u[t]>q[t] and r[t]<0)
    if trigger: cand=0.; used=active=True; trigger_t=t; resume_t=t+H; action="upper_wick_pause_start"
    else: cand=1.; action="remain_long_after_pause" if used else "remain_long"
   b1=base; events.append({"decision":t,"execution":t+1,"timestamp":d.index[t].isoformat(),"regime_id":rid if base else None,"base":base,"previous_base":prev,"upper168":float(u[t]),"lower168":float(q[t]),"ret168":float(r[t]),"trigger":trigger,"action":action,"before":before,"after":cand,"change":abs(cand-before)>1e-15}); prev=base
  if t+1<n-1: p["candidate"][t+1]=cand; p["b1"][t+1]=b1
 return p,events

def pack(d,p):
 o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; fee=FEE*turn; net=p*market-fee
 if not np.array_equal(net,p*market-FEE*turn): raise ValueError("fee identity")
 return {"market":market,"turn":turn,"fees":fee,"net":net}

def sharpe(x):
 s=float(np.std(x,ddof=1)); return None if s<=0 or not np.isfinite(s) else float(math.sqrt(ANN)*np.mean(x)/s)

def metric(a,p,span):
 s,e=span; n=a["net"][s:e]; wealth=np.cumprod(1+n); path=np.r_[1.,wealth]; to=float(a["turn"][s:e].sum())
 return {"net_return":float(wealth[-1]-1),"sharpe":sharpe(n),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":to,"fees":float(a["fees"][s:e].sum()),"edge_per_turnover_bps":float(n.sum()/to*1e4) if to else None}

def breadth(net,t):
 folds=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; years=t[:-1].year; yr={}
 for y in sorted(set(years[OOS[0]:OOS[1]])):
  z=years[OOS[0]:OOS[1]]==y; yr[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][z])-1)
 return {"fold_returns":folds,"profitable_folds":sum(x>0 for x in folds),"year_returns":yr,"profitable_years":sum(x>0 for x in yr.values())}

def boot(c,b):
 c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(SEED); md=np.empty(R); sd=np.empty(R); off=np.arange(H); nb=math.ceil(n/H)
 for k in range(0,R,100):
  ix=(rng.integers(0,n-H+1,size=(100,nb))[:,:,None]+off).reshape(100,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cv=cs.std(1,ddof=1); bv=bs.std(1,ddof=1)
  md[k:k+100]=ANN*(cm-bm); sd[k:k+100]=np.divide(math.sqrt(ANN)*cm,cv,out=np.zeros(100),where=cv>0)-np.divide(math.sqrt(ANN)*bm,bv,out=np.zeros(100),where=bv>0)
 return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sharpe(c) or 0)-(sharpe(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}

def diagnostics(p,a,events,span):
 s,e=span; es=[x for x in events if s<=x["execution"]<e]; starts=[x for x in es if x["action"]=="upper_wick_pause_start"]; rows=[]; market=a["candidate"]["market"]
 for ev in starts:
  i=ev["execution"]; j=i
  while j<e and p["b1"][j]>p["candidate"][j]: j+=1
  rows.append({"regime_id":ev["regime_id"],"trigger_timestamp":ev["timestamp"],"hours_cash_vs_b1":j-i,"market_return_omitted":float(market[i:j].sum()),"upper168":ev["upper168"],"lower168":ev["lower168"],"ret168":ev["ret168"]})
 delta=p["candidate"][s:e]-p["b1"][s:e]; m=float((delta*market[s:e]).sum()); fee=float(a["candidate"]["fees"][s:e].sum()-a["b1"]["fees"][s:e].sum()); observed=float((a["candidate"]["net"][s:e]-a["b1"]["net"][s:e]).sum())
 if not math.isclose(observed,m-fee,abs_tol=1e-12): raise ValueError("decomposition")
 return {"pause_starts":len(starts),"automatic_resumes":sum(x["action"]=="automatic_resume" for x in es),"base_exits_during_pause":sum(x["action"]=="base_exit_during_pause" for x in es),"pause_events":rows,"b1_only_hours":int(np.sum(delta<0)),"b1_only_market_return":float((np.maximum(-delta,0)*market[s:e]).sum()),"incremental_fees":fee,"arithmetic_net_delta":observed}

def run(d):
 p,events=positions(d); a={k:pack(d,v) for k,v in p.items()}; metrics={k:{"training":metric(a[k],p[k],TRAIN),"oos":metric(a[k],p[k],OOS),"full":metric(a[k],p[k],FULL)} for k in p}; bc=breadth(a["candidate"]["net"],d.index); bb=breadth(a["b1"]["net"],d.index); residual=sharpe(a["candidate"]["net"][OOS[0]:OOS[1]]-a["b1"]["net"][OOS[0]:OOS[1]]); bt=boot(a["candidate"]["net"],a["b1"]["net"]); diag={"training":diagnostics(p,a,events,TRAIN),"oos":diagnostics(p,a,events,OOS),"full":diagnostics(p,a,events,FULL)}; c=metrics["candidate"]; b=metrics["b1"]
 gates={"candidate_oos_positive":c["oos"]["net_return"]>0,"candidate_full_positive":c["full"]["net_return"]>0,"oos_net_not_below_b1":c["oos"]["net_return"]>=b["oos"]["net_return"],"oos_sharpe_not_below_b1":c["oos"]["sharpe"]>=b["oos"]["sharpe"],"oos_drawdown_not_worse_b1":c["oos"]["max_drawdown"]>=b["oos"]["max_drawdown"],"oos_turnover_not_above_b1":c["oos"]["turnover"]<=b["oos"]["turnover"],"oos_edge_per_turn_not_below_b1":c["oos"]["edge_per_turnover_bps"]>=b["oos"]["edge_per_turnover_bps"],"profitable_folds_at_least_7":bc["profitable_folds"]>=7,"profitable_years_at_least_3":bc["profitable_years"]>=3,"residual_sharpe_positive":residual is not None and residual>0,"mean_delta_lower_95_positive":bt["annualized_mean_delta"]["lower_95"]>0,"sharpe_delta_lower_95_positive":bt["sharpe_delta"]["lower_95"]>0}
 return {"metrics":metrics,"breadth":{"candidate":bc,"b1":bb,"residual_sharpe_vs_b1":residual},"bootstrap":bt,"diagnostics":diag,"acceptance_gates":gates,"accepted":all(gates.values())}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--btc",required=True); ap.add_argument("--eth",required=True); ap.add_argument("--output",required=True); z=ap.parse_args(); result={"family_id":"bounded-upper-wick-rejection-pause-1h-v1","issue":697,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","candidate_count":1,"parameter_grid_count":0,"fee_one_way":FEE,"markets":{}}
 for m,p in (("BTC-USDT",z.btc),("ETH-USDT",z.eth)): result["markets"][m]=run(load(p,m))
 result["accepted"]=all(x["accepted"] for x in result["markets"].values()); result["verdict"]="accept_exact_bounded_upper_wick_rejection_pause_family" if result["accepted"] else "reject_exact_bounded_upper_wick_rejection_pause_family"; text=json.dumps(result,sort_keys=True,indent=2)+"\n"; Path(z.output).write_text(text); print(result["verdict"])
if __name__=="__main__": main()
