# ruff: noqa
# fmt: off
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
FEE,ANN,TW,PW,PREFIX,FOLD,Q=.0005,8760.,2160,720,43441,2160,.60
TRAIN,OOS,FULL=(2880,17520),(17520,43440),(2880,43440)
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
ART={"BTC-USDT":8704977298,"ETH-USDT":8704978112}
def load(p:Path,m:str)->pd.DataFrame:
 if hashlib.sha256(p.read_bytes()).hexdigest()!=HASH[m]: raise ValueError(f"{m} hash")
 d=pd.read_csv(p,nrows=PREFIX); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
 ok=len(d)==PREFIX and t.equals(pd.date_range(t[0],periods=len(t),freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all() and (d.high>=d.low).all()
 if not ok: raise ValueError(f"{m} source")
 d.index=t; return d
def feats(d:pd.DataFrame)->dict[int,float]:
 lc=np.log(d.close.to_numpy(float)); lv=np.log1p(d.volume_quote.to_numpy(float)); out={}
 for t in range(TW,len(d)-1):
  if d.index[t].hour: continue
  r=np.diff(lc[t-PW:t+1]); v=lv[t-PW+1:t+1]; c=float(np.median(v)); mad=float(np.median(abs(v-c))); s=1.4826*mad
  if not math.isfinite(s) or s<=0: raise ValueError("MAD")
  w=np.exp(np.clip((v-c)/s,-3.,3.)); q=float(np.sum(np.sign(r)*w)/np.sum(w))
  if not math.isfinite(q) or not -1<=q<=1: raise ValueError("feature")
  out[t]=q
 return out
def pos(d:pd.DataFrame,f:dict[int,float],th:float)->dict[str,np.ndarray]:
 c=d.close.to_numpy(float); n=len(d); out={k:np.zeros(n-1) for k in ("candidate","b0","b1")}; q=b0=b1=0.
 for t in range(TW,n-1):
  b0=float(c[t]>c[t-TW])
  if d.index[t].hour==0:
   b1=b0
   if q==0: q=float(b0==1 and f[t]>=th)
   elif b0==0: q=0.
  j=t+1
  if j<n-1: out["candidate"][j],out["b0"][j],out["b1"][j]=q,b0,b1
 for k in ("candidate","b1"):
  ch=np.flatnonzero(np.r_[out[k][0]!=0,np.diff(out[k])!=0])
  if any(j<=0 or d.index[int(j)-1].hour!=0 for j in ch): raise ValueError(f"{k} timing")
 return out
def pack(d:pd.DataFrame,p:np.ndarray)->dict[str,np.ndarray]:
 o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),abs(np.diff(p))]; gross=p*market; fees=FEE*turn; net=gross-fees
 if not np.array_equal(net,p*market-.0005*turn): raise ValueError("fee")
 return {"net":net,"fees":fees,"turn":turn,"gross":gross,"market":market}
def sh(x:np.ndarray)->float|None:
 s=float(np.std(x,ddof=1)); return None if s<=0 else float(math.sqrt(ANN)*np.mean(x)/s)
def metrics(a:dict[str,np.ndarray],p:np.ndarray,span:tuple[int,int])->dict[str,float|int|None]:
 i,j=span; x=a["net"][i:j]; z=p[i:j]; w=np.cumprod(1+x); path=np.r_[1.,w]; tv=float(a["turn"][i:j].sum()); prev=np.r_[p[i-1] if i else 0.,z[:-1]]
 return {"net_return":float(w[-1]-1),"arithmetic_net_sum":float(x.sum()),"gross_sum":float(a["gross"][i:j].sum()),"sharpe":sh(x),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":tv,"fees":float(a["fees"][i:j].sum()),"edge_per_turnover_bps":float(x.sum()/tv*10000) if tv else None,"exposure":float(z.mean()),"long_entries":int(((z==1)&(prev==0)).sum()),"position_changes":int((a["turn"][i:j]>0).sum())}
def breadth(net:np.ndarray,ts:pd.DatetimeIndex)->dict[str,object]:
 folds=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; positive=[x for x in folds if x>0]; labels=ts[:-1].year; years={}
 for y in sorted(set(labels[OOS[0]:OOS[1]])):
  mask=labels[OOS[0]:OOS[1]]==y; years[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][mask])-1)
 return {"fold_returns":folds,"profitable_folds":int(sum(x>0 for x in folds)),"year_returns":years,"profitable_years":int(sum(x>0 for x in years.values())),"positive_fold_concentration":max(positive)/sum(positive) if positive else None}
def boot(c:np.ndarray,b:np.ndarray)->dict[str,object]:
 c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(20260730); md=np.empty(5000); sd=np.empty(5000); ne=np.empty(5000,bool); off=np.arange(168); blocks=math.ceil(n/168)
 for a in range(0,5000,100):
  z=min(5000,a+100); starts=rng.integers(0,n-167,size=(z-a,blocks)); ix=(starts[:,:,None]+off).reshape(z-a,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cstd=cs.std(1,ddof=1); bstd=bs.std(1,ddof=1); md[a:z]=ANN*(cm-bm); sd[a:z]=np.divide(math.sqrt(ANN)*cm,cstd,out=np.zeros(z-a),where=cstd>0)-np.divide(math.sqrt(ANN)*bm,bstd,out=np.zeros(z-a),where=bstd>0); ne[a:z]=np.all(cs==bs,axis=1)
 return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sh(c) or 0)-(sh(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))},"no_selector_effect_resample_rate":float(ne.mean()),"block_hours":168,"resamples":5000,"seed":20260730}
def fdiag(d:pd.DataFrame,f:dict[int,float],th:float,span:tuple[int,int])->dict[str,float|int]:
 c=d.close.to_numpy(float); pairs=[(t,v) for t,v in f.items() if span[0]<=t<span[1]]; v=np.array([x for _,x in pairs]); base=np.array([c[t]>c[t-TW] for t,_ in pairs])
 return {"daily_decisions":int(len(v)),"feature_median":float(np.median(v)),"feature_mean":float(np.mean(v)),"feature_q10":float(np.quantile(v,.1)),"feature_q90":float(np.quantile(v,.9)),"threshold":th,"threshold_exceedance_rate":float(np.mean(v>=th)),"positive_slow_trend_rate":float(np.mean(base)),"entry_eligible_rate":float(np.mean(base&(v>=th))),"feature_threshold_correlation_with_base":float(np.corrcoef(v,base.astype(float))[0,1])}
def delay(p:dict[str,np.ndarray],a:dict[str,dict[str,np.ndarray]])->dict[str,object]:
 s,e=OOS; co=p["candidate"][s:e]; bo=p["b1"][s:e]; mk=a["candidate"]["market"][s:e]; cm=(co==1)&(bo==0); bm=(co==0)&(bo==1); fee=float(a["candidate"]["fees"][s:e].sum()-a["b1"]["fees"][s:e].sum()); recon=float(mk[cm].sum()-mk[bm].sum()-fee); obs=float(a["candidate"]["net"][s:e].sum()-a["b1"]["net"][s:e].sum())
 if not math.isclose(recon,obs,abs_tol=1e-12): raise ValueError("decomposition")
 prev=np.r_[p["b1"][s-1],bo[:-1]]; entries=np.flatnonzero((bo==1)&(prev==0)); delays=[]; missed=[]; never=[]
 for entry in entries:
  k=int(entry)
  while k<len(bo) and bo[k]==1 and co[k]==0: k+=1
  delays.append(k-int(entry)); missed.append(float(mk[entry:k].sum())); never.append(k>=len(bo) or bo[k]==0)
 cn=a["candidate"]["net"][s:e]; bn=a["b1"]["net"][s:e]; fd=[]; effect=improved=0
 for k in range(12):
  i,j=k*FOLD,(k+1)*FOLD; x=float(cn[i:j].sum()-bn[i:j].sum()); fd.append(x); effect+=not np.array_equal(cn[i:j],bn[i:j]); improved+=x>0
 return {"candidate_only_hours":int(cm.sum()),"candidate_only_market_arithmetic_return":float(mk[cm].sum()),"b1_only_hours":int(bm.sum()),"b1_only_market_arithmetic_return":float(mk[bm].sum()),"incremental_fee_cost_vs_b1":fee,"reconstructed_candidate_minus_b1_arithmetic_net":recon,"observed_candidate_minus_b1_arithmetic_net":obs,"decomposition_identity_passes":True,"b1_entry_regimes":int(len(entries)),"delayed_entry_regimes":int(sum(x>0 for x in delays)),"never_entered_before_b1_exit_regimes":int(sum(never)),"selector_effect_folds":int(effect),"improved_arithmetic_net_folds_vs_b1":int(improved),"fold_arithmetic_net_delta_vs_b1":fd,"entry_delay_hours":delays,"median_entry_delay_hours":float(np.median(delays)) if delays else None,"max_entry_delay_hours":int(max(delays)) if delays else None,"arithmetic_market_return_during_delays":float(sum(missed))}
def accept(r:dict[str,object])->dict[str,bool]:
 c=r["metrics"]["development_oos"]["candidate"]; b=r["metrics"]["development_oos"]["b1"]; full=r["metrics"]["full_scored"]["candidate"]; br=r["breadth"]; u=r["uncertainty"]
 return {"positive_oos_net":c["net_return"]>0,"positive_oos_sharpe":c["sharpe"] is not None and c["sharpe"]>0,"net_at_least_b1":c["net_return"]>=b["net_return"],"sharpe_at_least_b1":c["sharpe"]>=b["sharpe"],"drawdown_no_worse_b1":c["max_drawdown"]>=b["max_drawdown"],"turnover_no_greater_b1":c["turnover"]<=b["turnover"],"edge_per_turnover_at_least_b1":c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],"profitable_folds_at_least_7":br["profitable_folds"]>=7,"profitable_years_at_least_3":br["profitable_years"]>=3,"positive_residual_sharpe_b1":r["residual_sharpe"]["vs_b1"] is not None and r["residual_sharpe"]["vs_b1"]>0,"mean_delta_lower_95_positive":u["annualized_mean_delta"]["lower_95"]>0,"sharpe_delta_lower_95_positive":u["sharpe_delta"]["lower_95"]>0,"positive_fold_concentration_at_most_half":br["positive_fold_concentration"] is not None and br["positive_fold_concentration"]<=.5,"positive_full_scored_net":full["net_return"]>0}
def run(path:Path,m:str)->dict[str,object]:
 d=load(path,m); f=feats(d); vals=np.array([v for t,v in f.items() if TRAIN[0]<=t<TRAIN[1]])
 if len(vals)<500 or not np.isfinite(vals).all(): raise ValueError("training support")
 th=float(np.quantile(vals,Q)); p=pos(d,f,th); a={k:pack(d,v) for k,v in p.items()}; ms={label:{k:metrics(a[k],p[k],span) for k in a} for label,span in {"training":TRAIN,"development_oos":OOS,"full_scored":FULL}.items()}; c=a["candidate"]["net"][OOS[0]:OOS[1]]; b0=a["b0"]["net"][OOS[0]:OOS[1]]; b1=a["b1"]["net"][OOS[0]:OOS[1]]
 r={"source":{"artifact_id":ART[m],"csv_sha256":HASH[m],"observations_in_source":43941,"parsed_prefix_bars":PREFIX},"frozen_entry_threshold_q60":th,"metrics":ms,"breadth":breadth(a["candidate"]["net"],d.index),"residual_sharpe":{"vs_b0":sh(c-b0),"vs_b1":sh(c-b1)},"uncertainty":boot(a["candidate"]["net"],a["b1"]["net"]),"feature_diagnostics":{"training":fdiag(d,f,th,TRAIN),"development_oos":fdiag(d,f,th,OOS)},"selector_discrepancy_vs_b1":delay(p,a)}; r["acceptance_checks"]=accept(r); r["market_accepts"]=bool(all(r["acceptance_checks"].values())); return r
def main()->None:
 ap=argparse.ArgumentParser(); ap.add_argument("--btc-csv",type=Path,required=True); ap.add_argument("--eth-csv",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); x=ap.parse_args(); markets={"BTC-USDT":run(x.btc_csv,"BTC-USDT"),"ETH-USDT":run(x.eth_csv,"ETH-USDT")}; accepts=all(r["market_accepts"] for r in markets.values()); result={"family_id":"volume-weighted-directional-persistence-entry-1h-v1","issue":642,"candidate_count":1,"parameter_grid_count":0,"bar":"1H","canonical_fee_one_way":FEE,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","sample":{"warmup":[0,2880],"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"parsed_prefix_bars":PREFIX,"later_suffix_unread":True},"feature":{"window_hours":PW,"quote_volume_transform":"log1p","robust_scale":"1.4826*MAD within 720H","z_clip":[-3.,3.],"weights":"exp(clipped_z)","concordance":"sum(sign(log_return)*weight)/sum(weight)","entry_quantile":Q,"entry_threshold_source":"training feature distribution only","exit":"2,160H endpoint trend non-positive only"},"markets":markets,"verdict":"nominate_volume_weighted_directional_persistence_for_g1" if accepts else "reject_exact_volume_weighted_directional_persistence_entry_family","paper_or_live_authorized":False}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
if __name__=="__main__": main()
