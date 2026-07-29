# ruff: noqa
# fmt: off
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd
FEE,ANN,WINDOW,BLOCK,PREFIX,FOLD=.0005,8760.,2160,180,43441,2160
TRAIN,OOS,FULL=(2880,17520),(17520,43440),(2880,43440)
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
def load(p:Path,m:str)->pd.DataFrame:
 if hashlib.sha256(p.read_bytes()).hexdigest()!=HASH[m]: raise ValueError(f"{m} hash")
 d=pd.read_csv(p,nrows=PREFIX); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[["open","high","low","close"]].to_numpy(float)
 ok=len(d)==PREFIX and t.equals(pd.date_range(t[0],periods=len(t),freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x>0).all() and (d.high>=d.low).all()
 if not ok: raise ValueError(f"{m} source")
 d.index=t; return d
def features(d:pd.DataFrame)->dict[int,tuple[float,float,float,float]]:
 lp=np.log(d.close.to_numpy(float)); x=np.arange(WINDOW+1,dtype=float); xc=x-x.mean(); den=float(xc@xc); off=np.arange(0,WINDOW+1,BLOCK); out={}
 for t in range(WINDOW,len(d)-1):
  if d.index[t].hour: continue
  w=lp[t-WINDOW:t+1]; e=float((w[-1]-w[0])/WINDOW); o=float(xc@(w-w.mean())/den); b=float(np.median(np.diff(w[off])/BLOCK)); out[t]=(e,o,b,float(np.median([e,o,b])))
 return out
def positions(d:pd.DataFrame,f:dict[int,tuple[float,float,float,float]])->dict[str,np.ndarray]:
 c=d.close.to_numpy(float); n=len(d); out={k:np.zeros(n-1) for k in ("candidate","b0","b1")}; q=b0=b1=0.
 for t in range(WINDOW,n-1):
  b0=float(c[t]>c[t-WINDOW])
  if d.index[t].hour==0: q=float(f[t][3]>0); b1=b0
  j=t+1
  if j<n-1: out["candidate"][j],out["b0"][j],out["b1"][j]=q,b0,b1
 for k in ("candidate","b1"):
  ch=np.flatnonzero(np.r_[out[k][0]!=0,np.diff(out[k])!=0])
  if any(j<=0 or d.index[int(j)-1].hour!=0 for j in ch): raise ValueError(f"{k} timing")
 return out
def pack(d:pd.DataFrame,p:np.ndarray)->dict[str,np.ndarray]:
 o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; gross=p*market; fees=FEE*turn; net=gross-fees
 if not np.array_equal(net,p*market-.0005*turn): raise ValueError("fee")
 return {"net":net,"fees":fees,"turn":turn,"gross":gross,"market":market}
def sh(x:np.ndarray)->float|None:
 s=float(np.std(x,ddof=1)); return None if s<=0 else float(math.sqrt(ANN)*np.mean(x)/s)
def metrics(a:dict[str,np.ndarray],p:np.ndarray,span:tuple[int,int])->dict[str,float|int|None]:
 i,j=span; x=a["net"][i:j]; z=p[i:j]; w=np.cumprod(1+x); path=np.r_[1.,w]; tv=float(a["turn"][i:j].sum()); prev=np.r_[p[i-1] if i else 0.,z[:-1]]
 return {"net_return":float(w[-1]-1),"arithmetic_net_sum":float(x.sum()),"gross_sum":float(a["gross"][i:j].sum()),"sharpe":sh(x),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":tv,"fees":float(a["fees"][i:j].sum()),"edge_per_turnover_bps":float(x.sum()/tv*10000) if tv else None,"exposure":float(z.mean()),"long_entries":int(((z==1)&(prev==0)).sum()),"position_changes":int((a["turn"][i:j]>0).sum())}
def breadth(net:np.ndarray,ts:pd.DatetimeIndex)->dict[str,object]:
 folds=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in folds if x>0]; labels=ts[:-1].year; years={}
 for y in sorted(set(labels[OOS[0]:OOS[1]])):
  mask=labels[OOS[0]:OOS[1]]==y; years[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][mask])-1)
 return {"fold_returns":folds,"profitable_folds":sum(x>0 for x in folds),"year_returns":years,"profitable_years":sum(x>0 for x in years.values()),"positive_fold_concentration":max(pos)/sum(pos) if pos else None}
def bootstrap(c:np.ndarray,b:np.ndarray)->dict[str,object]:
 c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(20260730); md=np.empty(5000); sd=np.empty(5000); off=np.arange(168); blocks=math.ceil(n/168)
 for a in range(0,5000,100):
  z=min(5000,a+100); starts=rng.integers(0,n-167,size=(z-a,blocks)); ix=(starts[:,:,None]+off).reshape(z-a,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cstd=cs.std(1,ddof=1); bstd=bs.std(1,ddof=1); md[a:z]=ANN*(cm-bm); sd[a:z]=np.divide(math.sqrt(ANN)*cm,cstd,out=np.zeros(z-a),where=cstd>0)-np.divide(math.sqrt(ANN)*bm,bstd,out=np.zeros(z-a),where=bstd>0)
 return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sh(c) or 0)-(sh(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))},"block_hours":168,"resamples":5000,"seed":20260730}
def diag(f:dict[int,tuple[float,float,float,float]],span:tuple[int,int])->dict[str,float|int]:
 a=np.array([[e>0,o>0,b>0,q>0] for t,(e,o,b,q) in f.items() if span[0]<=t<span[1]],bool); s=a[:,:3]
 return {"daily_decisions":len(a),"all_three_sign_agreement_rate":float(np.mean((s[:,0]==s[:,1])&(s[:,1]==s[:,2]))),"endpoint_ols_disagreement_rate":float(np.mean(s[:,0]!=s[:,1])),"endpoint_block_disagreement_rate":float(np.mean(s[:,0]!=s[:,2])),"ols_block_disagreement_rate":float(np.mean(s[:,1]!=s[:,2])),"consensus_long_rate":float(a[:,3].mean()),"endpoint_long_rate":float(s[:,0].mean()),"ols_long_rate":float(s[:,1].mean()),"block_long_rate":float(s[:,2].mean())}
def run(path:Path,market:str)->dict[str,object]:
 d=load(path,market); f=features(d); p=positions(d,f); a={k:pack(d,v) for k,v in p.items()}; ms={name:{k:metrics(a[k],p[k],span) for k in a} for name,span in {"training":TRAIN,"development_oos":OOS,"full_scored":FULL}.items()}; c=a["candidate"]["net"][OOS[0]:OOS[1]]; b0=a["b0"]["net"][OOS[0]:OOS[1]]; b1=a["b1"]["net"][OOS[0]:OOS[1]]; bd=breadth(a["candidate"]["net"],d.index); bt=bootstrap(a["candidate"]["net"],a["b1"]["net"]); co=p["candidate"][OOS[0]:OOS[1]]; bo=p["b1"][OOS[0]:OOS[1]]; mk=a["candidate"]["market"][OOS[0]:OOS[1]]; cm=(co==1)&(bo==0); bm=(co==0)&(bo==1); fee=float(a["candidate"]["fees"][OOS[0]:OOS[1]].sum()-a["b1"]["fees"][OOS[0]:OOS[1]].sum()); recon=float(mk[cm].sum()-mk[bm].sum()-fee); obs=float(c.sum()-b1.sum())
 if not math.isclose(recon,obs,abs_tol=1e-12): raise ValueError("decomposition")
 return {"metrics":ms,"breadth":bd,"residual_sharpe":{"vs_b0":sh(c-b0),"vs_b1":sh(c-b1)},"uncertainty":bt,"feature_diagnostics":{"training":diag(f,TRAIN),"development_oos":diag(f,OOS)},"exposure_discrepancy_vs_b1":{"candidate_only_hours":int(cm.sum()),"candidate_only_market_arithmetic_return":float(mk[cm].sum()),"b1_only_hours":int(bm.sum()),"b1_only_market_arithmetic_return":float(mk[bm].sum()),"incremental_fee_cost_vs_b1":fee,"reconstructed_candidate_minus_b1_arithmetic_net":recon,"observed_candidate_minus_b1_arithmetic_net":obs,"decomposition_identity_passes":True}}
def main()->None:
 ap=argparse.ArgumentParser(); ap.add_argument("--btc-csv",type=Path,required=True); ap.add_argument("--eth-csv",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); x=ap.parse_args(); result={"family_id":"three-estimator-slow-trend-consensus-1h-v1","issue":639,"candidate_count":1,"parameter_grid_count":0,"bar":"1H","canonical_fee_one_way":FEE,"research_parent":"5a0fcc97d1a882f8223656c51f5bb8055f534e38","sample":{"warmup":[0,2880],"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"parsed_prefix_bars":PREFIX,"later_suffix_unread":True},"markets":{"BTC-USDT":run(x.btc_csv,"BTC-USDT"),"ETH-USDT":run(x.eth_csv,"ETH-USDT")},"verdict":"reject_exact_three_estimator_slow_trend_consensus_family","paper_or_live_authorized":False}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
if __name__=="__main__": main()
