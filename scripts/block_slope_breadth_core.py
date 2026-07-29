# ruff: noqa: E501
# fmt: off
from __future__ import annotations
import hashlib, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE, ANN = 0.0005, 8760.0
TRAIN, OOS, FULL = (2880, 17520), (17520, 43440), (2880, 43440)
WINDOW, BLOCK_HOURS, BLOCK_COUNT, FOLD, PREFIX = 2160, 180, 12, 2160, 43441
HASH = {"BTC-USDT":"92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9","ETH-USDT":"2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726"}
ART = {"BTC-USDT":8704977298,"ETH-USDT":8704978112}
ART_HASH = {"BTC-USDT":"22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c","ETH-USDT":"e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3"}

def load(path: Path, market: str) -> pd.DataFrame:
    if hashlib.sha256(path.read_bytes()).hexdigest() != HASH[market]: raise ValueError(f"{market} hash")
    d = pd.read_csv(path, nrows=PREFIX); t = pd.DatetimeIndex(pd.to_datetime(d.timestamp, utc=True)); x=d[["open","high","low","close"]].to_numpy(float)
    ok=len(d)==PREFIX and t.equals(pd.date_range(t[0],periods=len(t),freq="1h",tz="UTC")) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x>0).all() and (d.high>=d.low).all()
    if not ok: raise ValueError(f"{market} invalid source")
    d.index=t; return d

def features(d: pd.DataFrame) -> dict[int,tuple[float,int,tuple[float,...]]]:
    lp=np.log(d.close.to_numpy(float)); offsets=np.arange(0,WINDOW+1,BLOCK_HOURS); out={}
    if len(offsets)!=13 or offsets[-1]!=WINDOW: raise ValueError("block layout")
    for t in range(WINDOW,len(d)-1):
        if d.index[t].hour: continue
        slopes=np.diff(lp[t-WINDOW+offsets])/BLOCK_HOURS
        out[t]=(float(np.median(slopes)),int(np.sum(slopes>0)),tuple(float(v) for v in slopes))
    return out

def boundaries(f: dict[int,tuple[float,int,tuple[float,...]]]) -> dict[str,int|float|bool]:
    vals=[(m,b) for t,(m,b,_) in f.items() if TRAIN[0]<=t<TRAIN[1]]; b=np.array([x[1] for x in vals],int); m=np.array([x[0] for x in vals])
    entry=int(np.quantile(b,.70,method="higher")); exit_=int(np.quantile(b,.30,method="lower"))
    if entry<=exit_: raise ValueError("non-hysteretic boundaries")
    return {"daily_decisions":len(vals),"entry_breadth_q70_higher":entry,"exit_breadth_q30_lower":exit_,"training_breadth_mean":float(b.mean()),"training_breadth_median":float(np.median(b)),"training_positive_median_rate":float(np.mean(m>0)),"performance_used_for_boundary_selection":False}

def positions(d: pd.DataFrame,f:dict[int,tuple[float,int,tuple[float,...]]],entry:int,exit_:int)->dict[str,np.ndarray]:
    c=d.close.to_numpy(float); n=len(d); out={k:np.zeros(n-1) for k in ("candidate","b0","b1")}; q=b0=b1=0.0
    for t in range(WINDOW,n-1):
        b0=float(c[t]>c[t-WINDOW])
        if d.index[t].hour==0:
            median,breadth,_=f[t]; old=q
            if q==0 and median>0 and breadth>=entry: q=1.0
            elif q==1 and median<0 and breadth<=exit_: q=0.0
            b1=b0
            if old!=q and not ((q==1 and median>0 and breadth>=entry) or (q==0 and median<0 and breadth<=exit_)): raise ValueError("transition")
        j=t+1
        if j<n-1: out["candidate"][j],out["b0"][j],out["b1"][j]=q,b0,b1
    ch=np.flatnonzero(np.r_[out["candidate"][0]!=0,np.diff(out["candidate"])!=0])
    if any(j<=0 or d.index[int(j)-1].hour!=0 for j in ch): raise ValueError("timing")
    return out

def pack(d:pd.DataFrame,p:np.ndarray)->tuple[np.ndarray,...]:
    o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; gross=p*market; fees=FEE*turn; net=gross-fees
    if not np.array_equal(net,p*market-.0005*turn): raise ValueError("fee")
    return net,fees,turn,gross,market

def sharpe(x:np.ndarray)->float|None:
    s=float(np.std(x,ddof=1)); return None if s<=0 else float(math.sqrt(ANN)*np.mean(x)/s)

def metrics(a:tuple[np.ndarray,...],p:np.ndarray,span:tuple[int,int])->dict[str,float|int|None]:
    net,fees,turn,gross,_=a; i,j=span; x=net[i:j]; z=p[i:j]; wealth=np.cumprod(1+x); path=np.r_[1.,wealth]; tv=float(turn[i:j].sum()); prev=np.r_[p[i-1] if i else 0.,z[:-1]]
    return {"net_return":float(wealth[-1]-1),"arithmetic_net_sum":float(x.sum()),"gross_sum":float(gross[i:j].sum()),"sharpe":sharpe(x),"max_drawdown":float(np.min(path/np.maximum.accumulate(path)-1)),"turnover":tv,"fees":float(fees[i:j].sum()),"edge_per_turnover_bps":float(x.sum()/tv*10000) if tv else None,"exposure":float(z.mean()),"long_entries":int(((z==1)&(prev==0)).sum()),"position_changes":int((turn[i:j]>0).sum())}

def breadth(net:np.ndarray,ts:pd.DatetimeIndex)->dict[str,object]:
    folds=[float(np.prod(1+net[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in folds if x>0]; labels=ts[:-1].year; years={}
    for y in sorted(set(labels[OOS[0]:OOS[1]])):
        mask=labels[OOS[0]:OOS[1]]==y; years[str(y)]=float(np.prod(1+net[OOS[0]:OOS[1]][mask])-1)
    return {"fold_returns":folds,"profitable_folds":sum(x>0 for x in folds),"year_returns":years,"profitable_years":sum(x>0 for x in years.values()),"positive_fold_concentration":max(pos)/sum(pos) if pos else None}

def bootstrap(candidate:np.ndarray,b1:np.ndarray)->dict[str,object]:
    c=candidate[OOS[0]:OOS[1]]; b=b1[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(20260730); md=np.empty(5000); sd=np.empty(5000); offsets=np.arange(168); blocks=math.ceil(n/168)
    for a in range(0,5000,100):
        z=min(5000,a+100); starts=rng.integers(0,n-167,size=(z-a,blocks)); ix=(starts[:,:,None]+offsets).reshape(z-a,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cstd=cs.std(1,ddof=1); bstd=bs.std(1,ddof=1); md[a:z]=ANN*(cm-bm); sd[a:z]=np.divide(math.sqrt(ANN)*cm,cstd,out=np.zeros(z-a),where=cstd>0)-np.divide(math.sqrt(ANN)*bm,bstd,out=np.zeros(z-a),where=bstd>0)
    return {"annualized_mean_delta":{"point":float(ANN*np.mean(c-b)),"lower_95":float(np.quantile(md,.025)),"upper_95":float(np.quantile(md,.975))},"sharpe_delta":{"point":float((sharpe(c) or 0)-(sharpe(b) or 0)),"lower_95":float(np.quantile(sd,.025)),"upper_95":float(np.quantile(sd,.975))},"block_hours":168,"resamples":5000,"seed":20260730}
