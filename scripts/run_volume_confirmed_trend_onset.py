# ruff: noqa
# fmt: off
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
FEE,ANN,TW,IW,PREFIX,FOLD=.0005,8760.,2160,168,43441,2160
TRAIN,OOS,FULL=(2880,17520),(17520,43440),(2880,43440)
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
ART={"BTC-USDT":8704977298,"ETH-USDT":8704978112}
def load(p:Path,m:str)->pd.DataFrame:
 if hashlib.sha256(p.read_bytes()).hexdigest()!=HASH[m]: raise ValueError(f"{m} hash")
 d=pd.read_csv(p,nrows=PREFIX); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
 ok=len(d)==PREFIX and t.equals(pd.date_range(t[0],periods=len(t),freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all() and (d.high>=d.low).all()
 if not ok: raise ValueError(f"{m} source")
 d.index=t; return d
def feats(d:pd.DataFrame)->dict[int,tuple[bool,float,float,float]]:
 c=np.log(d.close.to_numpy(float)); v=np.log1p(d.volume_quote.to_numpy(float)); out={}; z=np.arange(7,dtype=float); z-=z.mean(); den=float(z@z)
 for t in range(TW,len(d)-1):
  if d.index[t].hour: continue
  r=float(c[t]-c[t-IW]); a=float(r-(c[t-IW]-c[t-2*IW])); med=np.median(v[t-IW+1:t+1].reshape(7,24),axis=1); s=float(z@(med-med.mean())/den)
  if not all(map(math.isfinite,(r,a,s))): raise ValueError("feature")
  out[t]=(bool(c[t]>c[t-TW]),r,a,s)
 return out
def positions(d:pd.DataFrame,f:dict[int,tuple[bool,float,float,float]])->tuple[dict[str,np.ndarray],list[dict[str,object]]]:
 c=d.close.to_numpy(float); n=len(d); p={k:np.zeros(n-1) for k in ("candidate","b0","b1")}; q=b0=b1=0.; prev=None; left=0; onset=-1; current=None; hold=None; events=[]
 for t in range(TW,n-1):
  b0=float(c[t]>c[t-TW])
  if d.index[t].hour==0:
   base,r,a,s=f[t]; b1=float(base)
   if prev is not None and base and not prev:
    onset+=1; current=onset; left=7; events.append({"t":t,"entered":False,"offset":None})
   elif not base: left=0; current=None
   if q==0 and base and left>0:
    off=7-left
    if r>0 and a>0 and s>0:
     if current is None: raise ValueError("entry without onset")
     q=1.; hold=t+IW; events[current]["entered"]=True; events[current]["offset"]=off; left=0; current=None
    else:
     left-=1
     if left==0: current=None
   elif q==1:
    if hold is None: raise ValueError("hold")
    if t>=hold and not base: q=0.; hold=None
   prev=base
  j=t+1
  if j<n-1: p["candidate"][j],p["b0"][j],p["b1"][j]=q,b0,b1
 for k in ("candidate","b1"):
  ch=np.flatnonzero(np.r_[p[k][0]!=0,np.diff(p[k])!=0])
  if any(j<=0 or d.index[int(j)-1].hour!=0 for j in ch): raise ValueError(f"{k} timing")
 return p,events
def pack(d:pd.DataFrame,p:np.ndarray)->dict[str,np.ndarray]:
 o=d.open.to_numpy(float); mk=o[1:]/o[:-1]-1; tr=np.r_[abs(p[0]),abs(np.diff(p))]; gr=p*mk; fe=FEE*tr; ne=gr-fe
 if not np.array_equal(ne,p*mk-.0005*tr): raise ValueError("fee")
 return {"market":mk,"gross":gr,"turn":tr,"fees":fe,"net":ne}
def sh(x:np.ndarray)->float|None:
 s=float(np.std(x,ddof=1)); return None if s<=0 else float(math.sqrt(ANN)*np.mean(x)/s)
def metrics(a:dict[str,np.ndarray],p:np.ndarray,span:tuple[int,int])->dict[str,float|int|None]:
 i,j=span; x=a["net"][i:j]; z=p[i:j]; w=np.cumprod(1+x); path=np.r_[1.,w]; tv=float(a["turn"][i:j].sum()); prev=np.r_[p[i-1] if i else 0.,z[:-1]]
 return {"net_return":float(w[-1]-1),"sharpe":sh(x),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":tv,"fees":float(a["fees"][i:j].sum()),"edge_per_turnover_bps":float(x.sum()/tv*10000) if tv else None,"exposure":float(z.mean()),"long_entries":int(((z==1)&(prev==0)).sum())}
def breadth(net:np.ndarray,ts:pd.DatetimeIndex)->dict[str,object]:
 folds=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in folds if x>0]; lab=ts[:-1].year; years={}
 for y in sorted(set(lab[OOS[0]:OOS[1]])):
  mask=lab[OOS[0]:OOS[1]]==y; years[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][mask])-1)
 return {"profitable_folds":int(sum(x>0 for x in folds)),"profitable_years":int(sum(x>0 for x in years.values())),"positive_fold_concentration":max(pos)/sum(pos) if pos else None,"year_returns":years}
def boot(c:np.ndarray,b:np.ndarray)->dict[str,object]:
 c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(20260730); md=np.empty(5000); sd=np.empty(5000); ne=np.empty(5000,bool); off=np.arange(168); blocks=math.ceil(n/168)
 for q in range(0,5000,100):
  z=min(5000,q+100); starts=rng.integers(0,n-167,size=(z-q,blocks)); ix=(starts[:,:,None]+off).reshape(z-q,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cstd=cs.std(1,ddof=1); bstd=bs.std(1,ddof=1); md[q:z]=ANN*(cm-bm); sd[q:z]=np.divide(math.sqrt(ANN)*cm,cstd,out=np.zeros(z-q),where=cstd>0)-np.divide(math.sqrt(ANN)*bm,bstd,out=np.zeros(z-q),where=bstd>0); ne[q:z]=np.all(cs==bs,axis=1)
 return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sh(c) or 0)-(sh(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))},"no_selector_effect_resample_rate":float(ne.mean()),"block_hours":168,"resamples":5000,"seed":20260730}
def fdiag(f:dict[int,tuple[bool,float,float,float]],span:tuple[int,int])->dict[str,float]:
 z=[v for t,v in f.items() if span[0]<=t<span[1]]; base=np.array([x[0] for x in z]); r=np.array([x[1] for x in z]); a=np.array([x[2] for x in z]); s=np.array([x[3] for x in z]); joint=base&(r>0)&(a>0)&(s>0)
 return {"joint_confirmation_rate":float(joint.mean()),"positive_volume_slope_rate":float((s>0).mean())}
def onset(events:list[dict[str,object]],span:tuple[int,int])->dict[str,float|int|None]:
 z=[x for x in events if span[0]<=int(x["t"])<span[1]]; e=[x for x in z if x["entered"]]; offs=[int(x["offset"]) for x in e]
 return {"base_regime_onsets":len(z),"qualified_onsets":len(e),"missed_onsets":len(z)-len(e),"qualification_rate":len(e)/len(z) if z else None,"median_entry_delay_hours":float(np.median(offs)*24) if offs else None,"max_entry_delay_hours":max(offs)*24 if offs else None}
def diff(p:dict[str,np.ndarray],a:dict[str,dict[str,np.ndarray]])->dict[str,object]:
 s,e=OOS; c=p["candidate"][s:e]; b=p["b1"][s:e]; mk=a["candidate"]["market"][s:e]; co=(c==1)&(b==0); bo=(c==0)&(b==1); fee=float(a["candidate"]["fees"][s:e].sum()-a["b1"]["fees"][s:e].sum()); rec=float(mk[co].sum()-mk[bo].sum()-fee); obs=float(a["candidate"]["net"][s:e].sum()-a["b1"]["net"][s:e].sum())
 if not math.isclose(rec,obs,abs_tol=1e-12): raise ValueError("decomposition")
 cn=a["candidate"]["net"][s:e]; bn=a["b1"]["net"][s:e]; effect=improved=0
 for k in range(12):
  i,j=k*FOLD,(k+1)*FOLD; effect+=not np.array_equal(cn[i:j],bn[i:j]); improved+=float(cn[i:j].sum()-bn[i:j].sum())>0
 return {"candidate_only_hours":int(co.sum()),"candidate_only_market_arithmetic_return":float(mk[co].sum()),"b1_only_hours":int(bo.sum()),"b1_only_market_arithmetic_return":float(mk[bo].sum()),"incremental_fee_cost_vs_b1":fee,"observed_candidate_minus_b1_arithmetic_net":obs,"reconstructed_candidate_minus_b1_arithmetic_net":rec,"decomposition_identity_passes":True,"selector_effect_folds":int(effect),"improved_arithmetic_net_folds_vs_b1":int(improved)}
def checks(r:dict[str,object])->dict[str,bool]:
 c=r["metrics"]["development_oos"]["candidate"]; b=r["metrics"]["development_oos"]["b1"]; full=r["metrics"]["full_scored"]["candidate"]; br=r["breadth"]; u=r["uncertainty"]
 return {"positive_oos_net":c["net_return"]>0,"positive_oos_sharpe":c["sharpe"]>0,"net_at_least_b1":c["net_return"]>=b["net_return"],"sharpe_at_least_b1":c["sharpe"]>=b["sharpe"],"drawdown_no_worse_b1":c["max_drawdown"]>=b["max_drawdown"],"turnover_no_greater_b1":c["turnover"]<=b["turnover"],"edge_per_turnover_at_least_b1":c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],"profitable_folds_at_least_7":br["profitable_folds"]>=7,"profitable_years_at_least_3":br["profitable_years"]>=3,"positive_residual_sharpe_b1":r["residual_sharpe"]["vs_b1"]>0,"mean_delta_lower_95_positive":u["annualized_mean_delta"]["lower_95"]>0,"sharpe_delta_lower_95_positive":u["sharpe_delta"]["lower_95"]>0,"positive_fold_concentration_at_most_half":br["positive_fold_concentration"]<=.5,"positive_full_scored_net":full["net_return"]>0}
def run(path:Path,m:str)->dict[str,object]:
 d=load(path,m); f=feats(d); p,ev=positions(d,f); a={k:pack(d,v) for k,v in p.items()}; ms={lab:{k:metrics(a[k],p[k],sp) for k in a} for lab,sp in {"training":TRAIN,"development_oos":OOS,"full_scored":FULL}.items()}; c=a["candidate"]["net"][OOS[0]:OOS[1]]; b0=a["b0"]["net"][OOS[0]:OOS[1]]; b1=a["b1"]["net"][OOS[0]:OOS[1]]
 r={"source":{"artifact_id":ART[m],"csv_sha256":HASH[m],"observations_in_source":43941,"parsed_prefix_bars":PREFIX},"metrics":ms,"breadth":breadth(a["candidate"]["net"],d.index),"residual_sharpe":{"vs_b0":sh(c-b0),"vs_b1":sh(c-b1)},"uncertainty":boot(a["candidate"]["net"],a["b1"]["net"]),"feature_drift":{"training_joint_confirmation_rate":fdiag(f,TRAIN)["joint_confirmation_rate"],"oos_joint_confirmation_rate":fdiag(f,OOS)["joint_confirmation_rate"],"training_positive_volume_slope_rate":fdiag(f,TRAIN)["positive_volume_slope_rate"],"oos_positive_volume_slope_rate":fdiag(f,OOS)["positive_volume_slope_rate"]},"onset_oos":onset(ev,OOS),"selector_discrepancy_vs_b1":diff(p,a)}; r["acceptance_checks"]=checks(r); r["market_accepts"]=bool(all(r["acceptance_checks"].values())); return r
def main()->None:
 ap=argparse.ArgumentParser(); ap.add_argument("--btc-csv",type=Path,required=True); ap.add_argument("--eth-csv",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); x=ap.parse_args(); markets={"BTC-USDT":run(x.btc_csv,"BTC-USDT"),"ETH-USDT":run(x.eth_csv,"ETH-USDT")}; ok=all(v["market_accepts"] for v in markets.values()); result={"family_id":"volume-confirmed-trend-onset-impulse-1h-v1","issue":645,"candidate_count":1,"parameter_grid_count":0,"bar":"1H","canonical_fee_one_way":FEE,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","sample":{"warmup":[0,2880],"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"parsed_prefix_bars":PREFIX,"later_suffix_unread":True},"markets":markets,"verdict":"nominate_volume_confirmed_trend_onset_impulse_for_g1" if ok else "reject_exact_volume_confirmed_trend_onset_impulse_family","paper_or_live_authorized":False}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
if __name__=="__main__": main()
