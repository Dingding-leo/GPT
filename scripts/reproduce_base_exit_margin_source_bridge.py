from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
FEE,ANN,TREND,LEG,BRIDGE,N,FOLD,BLOCK,RESAMPLES,SEED=5e-4,8760.,2160,24,168,43441,2160,168,5000,20260730
TRAIN,OOS,FULL=(2880,17520),(17520,43440),(2880,43440)
HASH={"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p,m):
 if sha(p)!=HASH[m]:raise ValueError("hash mismatch")
 d=pd.read_csv(p,nrows=N);t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True));x=d[["open","high","low","close","volume_quote"]].to_numpy(float)
 ok=len(d)==N and t.equals(pd.date_range(t[0],periods=N,freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all()
 if not ok:raise ValueError("source validation")
 d.index=t;return d
def positions(d):
 c=d.close.to_numpy(float);p={k:np.zeros(len(d)-1) for k in ("candidate","b1","b0")};s=b=prev=0.;active=False;expiry=None;events=[]
 for t in range(TREND,len(d)-2):
  base=float(c[t]>c[t-TREND]);p["b0"][t+1]=base
  if d.index[t].hour==0:
   cur=lag=pre=None
   if t>=TREND+LEG:
    if float(c[t-LEG]>c[t-TREND-LEG])!=prev:raise ValueError("base identity")
    pre=math.log(c[t-LEG]/c[t-TREND-LEG]);cur=math.log(c[t]/c[t-LEG]);lag=math.log(c[t-TREND]/c[t-TREND-LEG]);post=math.log(c[t]/c[t-TREND])
    if not math.isclose(post-pre,cur-lag,abs_tol=1e-14):raise ValueError("margin identity")
   cross=bool(not base and prev);mech=bool(cross and cur is not None and cur>=0 and lag>0);e={"t":t,"x":t+1,"ts":d.index[t].isoformat(),"cross":cross,"mech":mech,"start":False,"restore":False,"expiry":False,"direct":False,"pre":pre,"post":math.log(c[t]/c[t-TREND]),"cur":cur,"lag":lag}
   b=base
   if active:
    if base:s=1.;active=False;expiry=None;e["restore"]=True
    elif t>=expiry:
     if t!=expiry:raise ValueError("expiry skipped")
     s=0.;active=False;expiry=None;e["expiry"]=True
    else:s=.5
   elif base:s=1.
   elif cross:
    if mech:s=.5;active=True;expiry=t+BRIDGE;e["start"]=True
    else:s=0.;e["direct"]=True
   else:s=0.
   events.append(e);prev=base
  p["candidate"][t+1]=s;p["b1"][t+1]=b
 if not np.isin(p["candidate"],[0,.5,1]).all() or np.any(p["candidate"]<p["b1"]):raise ValueError("state identity")
 return p,events
def pack(d,p):
 o=d.open.to_numpy(float);m=o[1:]/o[:-1]-1;tv=np.r_[abs(p[0]),abs(np.diff(p))];f=FEE*tv;g=p*m;return {"market":m,"turnover":tv,"fees":f,"gross":g,"net":g-f}
def sh(x):
 sd=np.std(x,ddof=1);return None if not np.isfinite(sd) or sd<=0 else float(math.sqrt(ANN)*np.mean(x)/sd)
def met(a,p,span):
 i,j=span;n=a["net"][i:j];g=a["gross"][i:j];w=np.cumprod(1+n);path=np.r_[1.,w];tv=float(a["turnover"][i:j].sum())
 return {"gross_return":float(np.prod(1+g)-1),"net_return":float(w[-1]-1),"arithmetic_gross_return":float(g.sum()),"arithmetic_net_return":float(n.sum()),"sharpe":sh(n),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":tv,"fees":float(a["fees"][i:j].sum()),"edge_per_turnover_bps":float(n.sum()/tv*1e4) if tv else None,"mean_exposure":float(p[i:j].mean())}
def breadth(n,idx):
 fs=[float(np.prod(1+n[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)];pos=[x for x in fs if x>0];ys=idx[:-1].year[OOS[0]:OOS[1]];z=n[OOS[0]:OOS[1]];yr={str(y):float(np.prod(1+z[ys==y])-1) for y in sorted(set(ys))}
 return {"fold_returns":fs,"profitable_folds":sum(x>0 for x in fs),"profitable_years":sum(x>0 for x in yr.values()),"positive_fold_concentration":max(pos)/sum(pos) if pos else None,"year_returns":yr}
def boot(c,b):
 c=c[OOS[0]:OOS[1]];b=b[OOS[0]:OOS[1]];rng=np.random.default_rng(SEED);n=len(c);md=np.empty(RESAMPLES);sd=np.empty(RESAMPLES);off=np.arange(BLOCK);nb=math.ceil(n/BLOCK)
 for st in range(0,RESAMPLES,100):
  q=min(100,RESAMPLES-st);bs=rng.integers(0,n-BLOCK+1,(q,nb));ix=(bs[:,:,None]+off).reshape(q,-1)[:,:n];cc,bb=c[ix],b[ix];cm,bm=cc.mean(1),bb.mean(1);cs,ss=cc.std(1,ddof=1),bb.std(1,ddof=1);md[st:st+q]=ANN*(cm-bm);sd[st:st+q]=np.divide(math.sqrt(ANN)*cm,cs,out=np.zeros(q),where=cs>0)-np.divide(math.sqrt(ANN)*bm,ss,out=np.zeros(q),where=ss>0)
 return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sh(c) or 0)-(sh(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))}}
def fwd(m,s,h):
 e=min(s+h,len(m));return None if e-s<h else float(np.prod(1+m[s:e])-1)
def diag(p,a,ev):
 i,j=OOS;c,b=p["candidate"],p["b1"];m=a["candidate"]["market"];mask=(c[i:j]==.5)&(b[i:j]==0);fee=float(a["candidate"]["fees"][i:j].sum()-a["b1"]["fees"][i:j].sum());obs=float((a["candidate"]["net"][i:j]-a["b1"]["net"][i:j]).sum());tim=float(((c[i:j]-b[i:j])*m[i:j]).sum())
 if not math.isclose(obs,tim-fee,abs_tol=1e-12):raise ValueError("return decomposition")
 e=[x for x in ev if i<=x["x"]<j];cross=[x for x in e if x["cross"]];starts=[x for x in e if x["start"]];epis=[]
 for x in starts:
  z=next((q for q in ev if q["t"]>x["t"] and (q["restore"] or q["expiry"])),None);s=x["x"];end=min(z["x"] if z else j,j);r=m[s:end];epis.append(float(.5*r.sum()))
 def mean(rows,h):
  v=[fwd(m,x["x"],h) for x in rows];v=[x for x in v if x is not None];return float(np.mean(v)) if v else None
 mech=[x for x in cross if x["mech"]];non=[x for x in cross if not x["mech"]];bm=m[i:j][mask];ab=[abs(x) for x in epis]
 return {"exit_crossings":len(cross),"mechanical_exit_crossings":len(starts),"direct_exits":sum(x["direct"] for x in e),"bridge_restores":sum(x["restore"] for x in e),"bridge_expiries":sum(x["expiry"] for x in e),"bridge_hours":int(mask.sum()),"full_exposure_equivalent_hours_added":float(.5*mask.sum()),"bridge_full_market_return_arithmetic":float(bm.sum()),"bridge_full_market_return_compounded":float(np.prod(1+bm)-1) if len(bm) else 0.,"candidate_timing_contribution":tim,"incremental_fees":fee,"arithmetic_candidate_minus_b1":obs,"episode_breadth":{"positive_episodes":sum(x>0 for x in epis),"negative_episodes":sum(x<0 for x in epis),"largest_abs_timing_contribution_share":max(ab)/sum(ab) if ab and sum(ab)>0 else None},"mean_post_exit_compounded":{"mechanical":{"24h":mean(mech,24),"168h":mean(mech,168),"720h":mean(mech,720)},"nonmechanical":{"24h":mean(non,24),"168h":mean(non,168),"720h":mean(non,720)}}}
def market(path,name):
 d=load(path,name);p,ev=positions(d);a={k:pack(d,v) for k,v in p.items()};out={"source":{"sha256":sha(path),"rows_read":len(d),"start":d.index[0].isoformat(),"end":d.index[-1].isoformat()},"metrics":{}}
 for lab,sp in (("training",TRAIN),("development_oos",OOS),("full_scored",FULL)):out["metrics"][lab]={k:met(a[k],p[k],sp) for k in ("candidate","b1","b0")}
 out["breadth"]=breadth(a["candidate"]["net"],d.index);out["benchmark_breadth"]=breadth(a["b1"]["net"],d.index);out["benchmark_relative_breadth"]={"folds_improved_vs_b1":sum(x>y for x,y in zip(out["breadth"]["fold_returns"],out["benchmark_breadth"]["fold_returns"],strict=True)),"years_improved_vs_b1":sum(out["breadth"]["year_returns"][y]>out["benchmark_breadth"]["year_returns"][y] for y in out["breadth"]["year_returns"])};out["residual_sharpe"]=sh(a["candidate"]["net"][OOS[0]:OOS[1]]-a["b1"]["net"][OOS[0]:OOS[1]]);out["uncertainty"]=boot(a["candidate"]["net"],a["b1"]["net"]);out["diagnostic"]=diag(p,a,ev)
 c=out["metrics"]["development_oos"]["candidate"];b=out["metrics"]["development_oos"]["b1"];br=out["breadth"];u=out["uncertainty"];r=out["residual_sharpe"]
 out["acceptance_gates"]={"positive_net":c["net_return"]>0,"net_at_least_b1":c["net_return"]>=b["net_return"],"sharpe_at_least_b1":c["sharpe"]>=b["sharpe"],"drawdown_no_worse":c["max_drawdown"]>=b["max_drawdown"]-1e-12,"turnover_no_more":c["turnover"]<=b["turnover"]+1e-12,"edge_per_turnover_at_least_b1":c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],"profitable_folds":br["profitable_folds"]>=7,"profitable_years":br["profitable_years"]>=3,"fold_concentration":br["positive_fold_concentration"] is not None and br["positive_fold_concentration"]<=.5,"positive_residual_sharpe":r is not None and r>0,"mean_delta_lower_positive":u["annualized_mean_delta"]["lower_95"]>0,"sharpe_delta_lower_positive":u["sharpe_delta"]["lower_95"]>0,"positive_full_return":out["metrics"]["full_scored"]["candidate"]["net_return"]>0};out["accepted"]=all(out["acceptance_gates"].values());return out
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--btc",type=Path,required=True);ap.add_argument("--eth",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);x=ap.parse_args();r={"family_id":"base-exit-margin-source-bridge-1h-v1","issue":715,"candidate_count":1,"parameter_grid_count":0,"fee_one_way":FEE,"bar":"1H","execution":"completed daily 00:00 UTC decision -> next hourly open","sample":{"training":TRAIN,"development_oos":OOS,"full_scored":FULL,"rows":N},"bootstrap":{"resamples":RESAMPLES,"block_hours":BLOCK,"seed":SEED},"markets":{"BTC-USDT":market(x.btc,"BTC-USDT"),"ETH-USDT":market(x.eth,"ETH-USDT")}};r["accepted"]=all(v["accepted"] for v in r["markets"].values());r["verdict"]="accept_exact_base_exit_margin_source_bridge_family" if r["accepted"] else "reject_exact_base_exit_margin_source_bridge_family";x.output.parent.mkdir(parents=True,exist_ok=True);x.output.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
if __name__=="__main__":main()
