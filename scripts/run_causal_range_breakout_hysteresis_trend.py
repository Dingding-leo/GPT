from __future__ import annotations

import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE, ANN = 0.0005, 8760.0
TRAIN, OOS, FULL = (2880,17520), (17520,43440), (2880,43440)
ENTRY, EXIT, FOLD, PREFIX = 2160, 720, 2160, 43441
HASH = {"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
ART = {"BTC-USDT":8704977298,"ETH-USDT":8704978112}

def load(p:Path,n:str)->pd.DataFrame:
    if hashlib.sha256(p.read_bytes()).hexdigest()!=HASH[n]: raise ValueError(f"{n} hash")
    d=pd.read_csv(p,nrows=PREFIX); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[["open","high","low","close"]].to_numpy(float)
    ok=len(d)==PREFIX and t.equals(pd.date_range(t[0],periods=len(t),freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x>0).all() and (d.high>=d.low).all()
    if not ok: raise ValueError(f"{n} invalid")
    d.index=t; return d

def positions(d:pd.DataFrame)->dict[str,np.ndarray]:
    c,h,l=d.close.to_numpy(float),d.high.to_numpy(float),d.low.to_numpy(float); n=len(d); out={k:np.zeros(n-1) for k in ("candidate","b0","b1")}; q=b0=b1=0.
    for t in range(ENTRY,n-1):
        b0=float(c[t]>c[t-ENTRY])
        if d.index[t].hour==0:
            en=float(np.max(h[t-ENTRY:t])); ex=float(np.min(l[t-EXIT:t])); old=q
            if q==0 and c[t]>en:q=1.
            elif q==1 and c[t]<ex:q=0.
            b1=b0
            if old!=q and not ((q==1 and c[t]>en) or (q==0 and c[t]<ex)): raise ValueError("transition")
        j=t+1
        if j<n-1: out["candidate"][j],out["b0"][j],out["b1"][j]=q,b0,b1
    ch=np.flatnonzero(np.r_[out["candidate"][0]!=0,np.diff(out["candidate"])!=0])
    if any(j<=0 or d.index[int(j)-1].hour!=0 for j in ch): raise ValueError("timing")
    return out

def pack(d:pd.DataFrame,p:np.ndarray):
    o=d.open.to_numpy(float); m=o[1:]/o[:-1]-1; tr=np.r_[abs(p[0]),np.abs(np.diff(p))]; g=p*m; f=FEE*tr; return g-f,f,tr,g,m

def shp(x):
    s=float(np.std(x,ddof=1)); return None if s<=0 else float(math.sqrt(ANN)*np.mean(x)/s)

def met(a,p,span):
    n,f,tr,g,_=a; i,j=span; x=n[i:j]; z=p[i:j]; w=np.cumprod(1+x); path=np.r_[1.,w]; tv=float(tr[i:j].sum()); prior=np.r_[p[i-1] if i else 0,z[:-1]]
    return {"net_return":float(w[-1]-1),"arithmetic_net_sum":float(x.sum()),"gross_sum":float(g[i:j].sum()),"sharpe":shp(x),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":tv,"fees":float(f[i:j].sum()),"edge_per_turnover_bps":float(x.sum()/tv*1e4) if tv else None,"exposure":float(z.mean()),"long_entries":int(((z==1)&(prior==0)).sum()),"position_changes":int((tr[i:j]>0).sum())}

def breadth(n,ts):
    fs=[float(np.prod(1+n[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in fs if x>0]; y={}; lab=ts[:-1].year
    for yr in sorted(set(lab[OOS[0]:OOS[1]])):
        m=lab[OOS[0]:OOS[1]]==yr; y[str(yr)]=float(np.prod(1+n[OOS[0]:OOS[1]][m])-1)
    return {"fold_returns":fs,"profitable_folds":sum(x>0 for x in fs),"year_returns":y,"profitable_years":sum(x>0 for x in y.values()),"positive_fold_concentration":max(pos)/sum(pos) if pos else None}

def boot(c,b):
    c,b=c[OOS[0]:OOS[1]],b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(20260729); md=np.empty(5000); sd=np.empty(5000); off=np.arange(168)
    for i in range(5000):
        st=rng.integers(0,n-167,size=math.ceil(n/168)); ix=(st[:,None]+off).ravel()[:n]; cr,br=c[ix],b[ix]; md[i]=ANN*np.mean(cr-br); sd[i]=(shp(cr) or 0)-(shp(br) or 0)
    return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((shp(c) or 0)-(shp(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))},"block_hours":168,"resamples":5000,"seed":20260729}

def episodes(pos,net,ts):
    a,z=OOS; p=pos[a:z]; x=net[a:z]; bd=np.r_[0,np.flatnonzero(np.diff(p)!=0)+1,len(p)]; ep=[]
    for s,e in zip(bd[:-1],bd[1:]):
        if p[s]==1: ep.append({"start":str(ts[a+s]),"stop":str(ts[a+e]),"hours":int(e-s),"net_return":float(np.prod(1+x[s:e])-1)})
    r=[e["net_return"] for e in ep]; return {"overlapping_oos_episodes":len(ep),"episodes":ep,"median_duration_hours":float(np.median([e["hours"] for e in ep])) if ep else None,"profitable_episode_ratio":float(np.mean(np.array(r)>0)) if ep else None,"worst_episode_return":min(r) if ep else None}

def diag(d,pos,pk):
    a,z=OOS; c,b=pos["candidate"][a:z],pos["b1"][a:z]; m=pk["candidate"][4][a:z]; co=(c==1)&(b==0); bo=(c==0)&(b==1); daily_tr=np.array([t for t in range(*TRAIN) if d.index[t].hour==0]); daily_o=np.array([t for t in range(*OOS) if d.index[t].hour==0]); cp=pos["candidate"]
    def trans(ix):
        x=cp[ix+1]; old=np.r_[cp[ix[0]],x[:-1]]; return int(((x==1)&(old==0)).sum()),int(((x==0)&(old==1)).sum())
    def worst(h):
        n=pk["candidate"][0][a:z]; return float(min(np.prod(1+n[i:i+h])-1 for i in range(len(n)-h+1)))
    te,tx=trans(daily_tr); oe,ox=trans(daily_o)
    return {"candidate_only_hours":int(co.sum()),"candidate_only_market_gross_sum":float(m[co].sum()),"b1_only_hours":int(bo.sum()),"b1_only_market_gross_sum":float(m[bo].sum()),"training_daily_decisions":len(daily_tr),"training_entries":te,"training_exits":tx,"oos_daily_decisions":len(daily_o),"oos_entries":oe,"oos_exits":ox,"worst_rolling_168h_candidate_return":worst(168),"worst_rolling_720h_candidate_return":worst(720),"episodes":episodes(cp,pk["candidate"][0],d.index)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--btc-csv",type=Path,required=True); ap.add_argument("--eth-csv",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); q=ap.parse_args(); frames={"BTC-USDT":load(q.btc_csv,"BTC-USDT"),"ETH-USDT":load(q.eth_csv,"ETH-USDT")}; R={"family_id":"causal-range-breakout-hysteresis-trend-1h-v1","issue":630,"candidate_count":1,"parameter_grid_count":0,"canonical_fee_one_way":FEE,"sample":{"training":list(TRAIN),"development_oos":list(OOS),"full_scored":list(FULL),"fold_count":12,"fold_hours":FOLD,"parsed_prefix_bars":PREFIX,"later_suffix_unread":True},"sources":{n:{"workflow_run_id":30401519824,"artifact_id":ART[n],"csv_sha256":HASH[n],"source_total_observations":43941} for n in HASH},"markets":{}}; accepted=True
    for n,d in frames.items():
        ps=positions(d); pk={k:pack(d,v) for k,v in ps.items()}; spans=(("training",TRAIN),("development_oos",OOS),("full_scored",FULL)); mm={s:{k:met(pk[k],ps[k],sp) for k in ps} for s,sp in spans}; cn,b0,b1=pk["candidate"][0],pk["b0"][0],pk["b1"][0]; br=breadth(cn,d.index); bt=boot(cn,b1); rb0=shp(cn[OOS[0]:OOS[1]]-b0[OOS[0]:OOS[1]]); rb1=shp(cn[OOS[0]:OOS[1]]-b1[OOS[0]:OOS[1]]); c,b=mm["development_oos"]["candidate"],mm["development_oos"]["b1"]
        gates={"positive_net_return":c["net_return"]>0,"positive_sharpe":c["sharpe"] is not None and c["sharpe"]>0,"profitable_folds_at_least_7_of_12":br["profitable_folds"]>=7,"profitable_years_at_least_3":br["profitable_years"]>=3,"positive_fold_concentration_at_most_50pct":br["positive_fold_concentration"]<=.5,"max_drawdown_within_2pp_of_b1":c["max_drawdown"]>=b["max_drawdown"]-.02,"turnover_no_greater_than_b1":c["turnover"]<=b["turnover"],"positive_edge_per_turnover":c["edge_per_turnover_bps"]>0,"edge_per_turnover_no_worse_than_b1":c["edge_per_turnover_bps"]>=b["edge_per_turnover_bps"],"net_return_no_worse_than_b1":c["net_return"]>=b["net_return"],"sharpe_no_worse_than_b1":c["sharpe"]>=b["sharpe"],"positive_residual_sharpe_vs_b1":rb1 is not None and rb1>0,"bootstrap_mean_delta_lower_bound_positive":bt["annualized_mean_delta"]["lower_95"]>0,"bootstrap_sharpe_delta_lower_bound_positive":bt["sharpe_delta"]["lower_95"]>0,"source_chronology_timing_fee_checks":True}; ok=all(gates.values()); accepted &= ok; R["markets"][n]={"metrics":mm,"breadth":br,"residual_sharpe_vs_b0":rb0,"residual_sharpe_vs_b1":rb1,"bootstrap_vs_b1":bt,"diagnostics":diag(d,ps,pk),"acceptance_gates":gates,"accepted":ok}
    R["accepted"]=accepted; R["verdict"]="accept_for_g1_nomination" if accepted else "reject_exact_causal_range_breakout_hysteresis_trend_family"; q.output.parent.mkdir(parents=True,exist_ok=True); q.output.write_text(json.dumps(R,indent=2,sort_keys=True)+"\n")
if __name__=="__main__": main()
