# ruff: noqa
# fmt: off
"""Reproduce issue #682 on immutable public OKX 1H candles."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=5e-4;ANN=8760.;W=2160;VW=720;RW=168;MAD=1.4826;N=43441;FOLD=2160
TRAIN=(2880,17520);OOS=(17520,43440);FULL=(2880,43440);SEED=20260730;BLOCK=168;R=5000
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
ART={"BTC-USDT":8704977298,"ETH-USDT":8704978112}

def nat(x):
 if isinstance(x,(np.integer,np.bool_)):return x.item()
 if isinstance(x,np.floating):return float(x)
 if isinstance(x,np.ndarray):return x.tolist()
 if isinstance(x,dict):return {str(k):nat(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [nat(v) for v in x]
 return x

def load(p,m):
 raw=Path(p).read_bytes();h=hashlib.sha256(raw).hexdigest()
 if h!=HASH[m]:raise ValueError(f"{m} hash {h}")
 d=pd.read_csv(p,nrows=N);t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True));x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
 if not(len(d)==N and t.equals(pd.date_range(t[0],periods=N,freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all()):raise ValueError(f"{m} invalid source")
 d.index=t;return d

def scale(r,t):
 z=r[t-VW+1:t+1];med=float(np.median(z));sig=float(MAD*np.median(np.abs(z-med)))
 if len(z)!=VW or not np.isfinite(z).all():raise ValueError("bad scale window")
 return med,sig,float(math.sqrt(VW)*sig)

def positions(d):
 n=len(d);cl=d.close.to_numpy(float);lr=np.r_[np.nan,np.log(cl[1:]/cl[:-1])];p={k:np.zeros(n-1) for k in("candidate","irreversible","b0","b1")}
 c=irr=b0=b1=0.;prev=False;on=None;oc=None;peak=None;phase="flat";ilock=False;events=[];regs=[];active=None
 for t in range(W,n-1):
  base=bool(cl[t]>cl[t-W]);b0=float(base)
  if d.index[t].hour==0:
   onset=base and not prev;ev=iev="hold";failed=recovery=False;med=sig=budget=rr=adv=ret168=None
   if not base:
    if active is not None:active["end"]=t;regs.append(active);active=None
    c=irr=0.;on=oc=peak=None;phase="flat";ilock=False;ev=iev="base_exit"
   elif onset:
    on=t;oc=peak=float(cl[t]);phase="pre";ilock=False;c=irr=1.;ev=iev="onset_entry";med,sig,budget=scale(lr,t);rr=adv=0.;ret168=float(math.log(cl[t]/cl[t-RW]));active={"onset":t,"onset_exec":t+1,"exit_exec":None,"re_exec":None,"end":None}
   else:
    if on is None or active is None:raise ValueError("missing onset")
    peak=max(peak,float(cl[t]));med,sig,budget=scale(lr,t);rr=float(math.log(cl[t]/oc));adv=float(math.log(peak/cl[t]));ret168=float(math.log(cl[t]/cl[t-RW]));failed=adv>budget and rr<=0;recovery=cl[t]>oc and ret168>0
    if ilock:irr=0.;iev="locked"
    elif failed:irr=0.;ilock=True;iev="loss_exit"
    else:irr=1.;iev="long"
    if phase=="pre":
     if failed:c=0.;phase="wait";ev="loss_exit";active["exit_exec"]=t+1;active["exit_decision"]=t
     else:c=1.;ev="long"
    elif phase=="wait":
     if recovery:c=1.;phase="reentered";ev="reentry";active["re_exec"]=t+1;active["re_decision"]=t
     else:c=0.;ev="wait"
    elif phase=="reentered":c=1.;ev="after_reentry"
    else:raise ValueError(phase)
   b1=float(base);events.append({"decision":t,"execution":t+1,"event":ev,"irreversible_event":iev,"onset":on,"onset_close":oc,"close":float(cl[t]),"peak":peak,"regime_return":rr,"adverse":adv,"robust_sigma":sig,"loss_budget":budget,"return_168h":ret168,"failed":failed,"recovery":recovery,"phase":phase});prev=base
  if t+1<n-1:p["candidate"][t+1]=c;p["irreversible"][t+1]=irr;p["b0"][t+1]=b0;p["b1"][t+1]=b1
 if active is not None:active["end"]=n-1;regs.append(active)
 if np.any(p["candidate"]>p["b1"]+1e-15) or np.any(p["irreversible"]>p["candidate"]+1e-15):raise ValueError("containment")
 return p,events,regs

def pack(d,p):
 o=d.open.to_numpy(float);m=o[1:]/o[:-1]-1;turn=np.r_[abs(p[0]),np.abs(np.diff(p))];fees=FEE*turn;net=p*m-fees
 if not np.array_equal(net,p*m-FEE*turn):raise ValueError("fee identity")
 return {"market":m,"turn":turn,"fees":fees,"net":net}

def sharpe(x):
 s=float(np.std(x,ddof=1));return None if s<=0 or not np.isfinite(s) else float(math.sqrt(ANN)*np.mean(x)/s)

def metric(a,p,span):
 s,e=span;n=a["net"][s:e];x=p[s:e];w=np.cumprod(1+n);path=np.r_[1.,w];to=float(a["turn"][s:e].sum())
 return {"net_return":float(w[-1]-1),"arithmetic_net_return":float(n.sum()),"sharpe":sharpe(n),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":to,"fees":float(a["fees"][s:e].sum()),"edge_per_turnover_bps":float(n.sum()/to*1e4) if to else None,"mean_exposure":float(x.mean()),"exposure_hours":float(x.sum())}

def breadth(net,t):
 fr=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)];pos=[x for x in fr if x>0];years=t[:-1].year;yr={}
 for y in sorted(set(years[OOS[0]:OOS[1]])):
  z=years[OOS[0]:OOS[1]]==y;yr[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][z])-1)
 return {"fold_returns":fr,"profitable_folds":sum(x>0 for x in fr),"year_returns":yr,"profitable_years":sum(x>0 for x in yr.values()),"positive_fold_concentration":max(pos)/sum(pos) if pos else None}

def boot(c,b):
 c=c[OOS[0]:OOS[1]];b=b[OOS[0]:OOS[1]];n=len(c);rng=np.random.default_rng(SEED);md=np.empty(R);sd=np.empty(R);off=np.arange(BLOCK);nb=math.ceil(n/BLOCK)
 for q in range(0,R,100):
  ix=(rng.integers(0,n-BLOCK+1,size=(100,nb))[:,:,None]+off).reshape(100,-1)[:,:n];cs=c[ix];bs=b[ix];cm=cs.mean(1);bm=bs.mean(1);cv=cs.std(1,ddof=1);bv=bs.std(1,ddof=1);md[q:q+100]=ANN*(cm-bm);sd[q:q+100]=np.divide(math.sqrt(ANN)*cm,cv,out=np.zeros(100),where=cv>0)-np.divide(math.sqrt(ANN)*bm,bv,out=np.zeros(100),where=bv>0)
 return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sharpe(c) or 0)-(sharpe(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}

def decomposition(a,p,left,right):
 s,e=OOS;ld=p[left][s:e]-p[right][s:e];market=float((ld*a[left]["market"][s:e]).sum());fee=float(a[left]["fees"][s:e].sum()-a[right]["fees"][s:e].sum());obs=float((a[left]["net"][s:e]-a[right]["net"][s:e]).sum())
 if not math.isclose(obs,market-fee,abs_tol=1e-12):raise ValueError("decomposition")
 return {"arithmetic_net_delta":obs,"exposure_market_return_delta":market,"incremental_fees":fee,"left_only_hours":float(np.maximum(ld,0).sum()),"right_only_hours":float(np.maximum(-ld,0).sum()),"left_only_market_return":float((np.maximum(ld,0)*a[left]["market"][s:e]).sum()),"right_only_market_return":float((np.maximum(-ld,0)*a[left]["market"][s:e]).sum())}

def diag(d,p,a,events,regs):
 s,e=OOS;ex=[x for x in events if x["event"]=="loss_exit" and s<=x["execution"]<e];re=[x for x in events if x["event"]=="reentry" and s<=x["execution"]<e];rest=np.maximum(p["candidate"]-p["irreversible"],0);om=np.maximum(p["b1"]-p["candidate"],0);rest_events=[]
 for rg in regs:
  stop=min(rg["end"]+1,len(rest));r=rg.get("re_exec")
  if r is not None:
   a0=max(r,s);b0=min(stop,e)
   if b0>a0:rest_events.append({"reentry_execution":r,"hours":b0-a0,"market_return":float(a["candidate"]["market"][a0:b0].sum())})
 total=sum(x["hours"] for x in rest_events);folds=[]
 for k in range(12):
  a0=s+k*FOLD;b0=a0+FOLD;cr=float(np.prod(1+a["candidate"]["net"][a0:b0])-1);br=float(np.prod(1+a["b1"]["net"][a0:b0])-1);folds.append({"fold":k+1,"candidate":cr,"b1":br,"delta":cr-br})
 years=d.index[:-1].year;yc={}
 for y in sorted(set(years[s:e])):
  z=years[s:e]==y;cr=float(np.prod(1+a["candidate"]["net"][s:e][z])-1);br=float(np.prod(1+a["b1"]["net"][s:e][z])-1);yc[str(y)]={"candidate":cr,"b1":br,"delta":cr-br}
 return {"oos_loss_budget_exits":len(ex),"oos_recovery_reentries":len(re),"exit_records":ex,"reentry_records":re,"candidate_vs_b1":decomposition(a,p,"candidate","b1"),"candidate_vs_irreversible":decomposition(a,p,"candidate","irreversible"),"b1_only_exposure_hours":float(om[s:e].sum()),"b1_only_market_return":float((om[s:e]*a["candidate"]["market"][s:e]).sum()),"restored_exposure_hours_vs_irreversible":float(rest[s:e].sum()),"restored_exposure_events":rest_events,"largest_reentry_event_hour_concentration":max((x["hours"] for x in rest_events),default=0)/total if total else None,"fold_comparison_vs_b1":folds,"folds_improved_vs_b1":sum(x["delta"]>0 for x in folds),"year_comparison_vs_b1":yc,"years_improved_vs_b1":sum(x["delta"]>0 for x in yc.values()),"identity_checks":{"position_containment":True,"fee":True,"decomposition":True}}

def protocol():
 return {"family_id":"bounded-recovery-reentry-loss-budget-1h-v1","issue":682,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","bar":"1H","canonical_fee_one_way":FEE,"candidate_count":1,"parameter_grid_count":0,"sources":{m:{"artifact_id":ART[m],"csv_sha256":HASH[m],"provider":"OKX public confirmed SPOT"} for m in HASH},"sample":{"parsed_prefix_bars":N,"warmup":[0,2880],"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"folds":12,"fold_hours":FOLD,"later_suffix_unread":True},"feature":{"base":"close_t > close_(t-2160)","robust_sigma":"1.4826 * MAD of trailing 720 completed hourly log returns","loss_budget":"sqrt(720) * robust_sigma","failed":"log(peak_close/current_close) > loss_budget and log(current_close/onset_close) <= 0","recovery":"current_close > onset_close and log(current_close/close_(t-168)) > 0"},"policy":{"decision_cadence":"daily completed 00:00 UTC","execution":"next hourly open","entry":"immediate at every new positive base-trend onset","loss_budget_exit":"first failed state","reentry":"at most once in same regime on first recovery state","after_reentry":"hold until base exit","exposure_states":[0,1],"fees":"5 bps per absolute exposure change"},"uncertainty":{"resamples":R,"block_hours":BLOCK,"paired_non_circular":True,"seed":SEED}}

def run(d,m):
 p,ev,regs=positions(d);a={k:pack(d,v) for k,v in p.items()};mm={name:{k:metric(a[k],p[k],span) for k in p} for name,span in(("training",TRAIN),("development_oos",OOS),("full_scored",FULL))};br=breadth(a["candidate"]["net"],d.index);u=boot(a["candidate"]["net"],a["b1"]["net"]);rs=sharpe(a["candidate"]["net"][OOS[0]:OOS[1]]-a["b1"]["net"][OOS[0]:OOS[1]]);c=mm["development_oos"]["candidate"];b=mm["development_oos"]["b1"]
 g={"positive_oos_net":c["net_return"]>0,"positive_oos_sharpe":c["sharpe"] is not None and c["sharpe"]>0,"net_at_least_b1":c["net_return"]>=b["net_return"],"sharpe_at_least_b1":c["sharpe"] is not None and c["sharpe"]>=b["sharpe"],"drawdown_no_worse_b1":c["max_drawdown"]>=b["max_drawdown"],"turnover_no_greater_b1":c["turnover"]<=b["turnover"],"edge_per_turnover_at_least_b1":c["edge_per_turnover_bps"] is not None and c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],"profitable_folds_at_least_7":br["profitable_folds"]>=7,"profitable_years_at_least_3":br["profitable_years"]>=3,"positive_residual_sharpe":rs is not None and rs>0,"positive_mean_delta_lower_95":u["annualized_mean_delta"]["lower_95"]>0,"positive_sharpe_delta_lower_95":u["sharpe_delta"]["lower_95"]>0,"positive_fold_concentration_at_most_half":br["positive_fold_concentration"] is not None and br["positive_fold_concentration"]<=.5,"positive_full_scored_net":mm["full_scored"]["candidate"]["net_return"]>0}
 return {"market":m,"source_artifact":ART[m],"source_sha256":HASH[m],"metrics":mm,"breadth":br,"residual_sharpe_vs_b1":rs,"uncertainty":u,"gates":g,"accepted":all(g.values()),"diagnostics":diag(d,p,a,ev,regs)}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--btc",type=Path,required=True);ap.add_argument("--eth",type=Path,required=True);ap.add_argument("--out",type=Path,required=True);z=ap.parse_args();z.out.mkdir(parents=True,exist_ok=True);markets={"BTC-USDT":run(load(z.btc,"BTC-USDT"),"BTC-USDT"),"ETH-USDT":run(load(z.eth,"ETH-USDT"),"ETH-USDT")};ok=all(v["accepted"] for v in markets.values());res={"protocol":protocol(),"markets":markets,"bilateral_accepted":ok,"verdict":"accept_bounded_recovery_reentry_loss_budget_family" if ok else "reject_exact_bounded_recovery_reentry_loss_budget_family","repaired_discrepancy":"Terminal evidence partitions frozen samples and attributes restored exposure event-by-event; no strategy output or verdict changed.","remaining_blocker":"All restored OOS exposure in each market came from one re-entry event; BTC was harmed, ETH remained breadth/efficiency/uncertainty deficient, and both exceeded B1 turnover.","next_experiment":"One own-history-only signed-volume-flow persistence two-state risk architecture; one candidate, no fitted threshold, no grid or market-specific rule."};text=json.dumps(nat(res),indent=2,sort_keys=True,allow_nan=False)+"\n";(z.out/"result.json").write_text(text);(z.out/"protocol.json").write_text(json.dumps(nat(protocol()),indent=2,sort_keys=True)+"\n");print(text)
if __name__=="__main__":main()
