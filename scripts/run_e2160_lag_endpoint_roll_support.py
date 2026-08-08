from __future__ import annotations

import hashlib, json, math, os
from pathlib import Path
import numpy as np
import pandas as pd
from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY="causal-own-price-e2160-lag-endpoint-roll-support-opportunity-1h-v1"
START="2023-04-01T00:00:00Z"; END="2025-12-31T23:00:00Z"
N=24144; TRAIN0=2208; TRAIN1=10800; OOS1=23760
H=2160; ROLL=24; FEE=.001; DRAWS=5000; BLK=7; SEED=20260808
TARGETS=("DOGE-USDT","TRX-USDT")
OUT=Path("reports/research/e2160-lag-endpoint-roll-support-1h-v1")
REJECT="reject_causal_own_price_e2160_lag_endpoint_roll_support_information_premise_1h_v1"
SUPPORT="support_causal_own_price_e2160_lag_endpoint_roll_support_for_separate_candidate_preregistration_1h_v1"

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def csv_bytes(df:pd.DataFrame)->bytes:
    return df.reset_index(names="timestamp").to_csv(index=False,date_format="%Y-%m-%dT%H:%M:%S.%fZ",float_format="%.12g",lineterminator="\n").encode()
def fetch(inst:str):
    return fetch_okx_one_hour_candles(inst_id=inst,start=START,end=END,limit=100,pause_seconds=.08,timeout=20.,safety_pages=64)

def acquire(inst:str):
    a,b=fetch(inst),fetch(inst)
    x,y=a.candles.copy(),b.candles.copy()
    x.columns=[str(c).lower() for c in x.columns]; y.columns=[str(c).lower() for c in y.columns]
    grid=pd.date_range(START,END,freq="h")
    if len(x)!=N or len(y)!=N or not x.index.equals(grid) or not y.index.equals(grid): raise ValueError(f"{inst}: frozen grid")
    if not x.equals(y): raise ValueError(f"{inst}: repeat mismatch")
    p=x[["open","high","low","close"]].to_numpy(float)
    if not np.isfinite(p).all() or not (p>0).all(): raise ValueError(f"{inst}: invalid prices")
    if not (x["high"]>=x[["open","close","low"]].max(axis=1)).all() or not (x["low"]<=x[["open","close","high"]].min(axis=1)).all(): raise ValueError(f"{inst}: OHLC")
    if a.metadata.get("instrument_id")!=inst or a.metadata.get("bar")!="1H" or a.metadata.get("missing_intervals") not in (0,None): raise ValueError(f"{inst}: identity")
    h=sha(csv_bytes(x)); hr=sha(csv_bytes(y))
    meta=str(a.metadata.get("normalized_csv_sha256"))
    if h!=hr or h!=meta: raise ValueError(f"{inst}: normalized hash")
    return x,{"rows":len(x),"source_sha256":h,"training_prefix_sha256":sha(csv_bytes(x.iloc[:TRAIN1])),"start":str(x.index[0]),"end":str(x.index[-1])}

def anchors(): return [t for t in range(TRAIN0,TRAIN1,24) if t+25<TRAIN1]

def opportunities(df:pd.DataFrame)->pd.DataFrame:
    c=df.close.to_numpy(float); o=df.open.to_numpy(float); lo=df.low.to_numpy(float); rows=[]
    for t in anchors():
        u=t-1; old=u-H; roll=old+ROLL
        if roll>u or old<0: raise ValueError("lag arithmetic")
        cur,d0,d1=float(c[u]),float(c[old]),float(c[roll])
        margin=math.log(cur/d0); feature=-math.log(d1/d0)
        if margin<=0: continue
        ident=abs(math.log(cur/d1)-(margin+feature))
        s=7.25
        scale=max(abs(math.log(cur*s/(d0*s))-margin),abs(-math.log(d1*s/(d0*s))-feature))
        entry=float(o[t])
        rows.append({"t":t,"feature":feature,"margin":margin,
          "net":math.log(float(o[t+24])/entry)-FEE,
          "adverse":float(np.min(np.log(lo[t:t+25]/entry)-FEE)),
          "delay_net":math.log(float(o[t+25])/float(o[t+1]))-FEE,
          "delay_adverse":float(np.min(np.log(lo[t+1:t+26]/float(o[t+1]))-FEE)),
          "u":u,"old":old,"roll":roll,"identity_error":ident,"scale_error":scale})
    return pd.DataFrame(rows)

def rho(x,y):
    return float(pd.Series(np.asarray(x,float)).rank(method="average").corr(pd.Series(np.asarray(y,float)).rank(method="average")))
def slope(x,y):
    x=np.asarray(x,float); y=np.asarray(y,float); s=float(x.std(ddof=0))
    return float("nan") if not np.isfinite(s) or s<=0 else float(np.mean(((x-x.mean())/s)*(y-y.mean())))
def tercile(x,y):
    x=np.asarray(x,float); y=np.asarray(y,float); k=len(x)//3; ix=np.argsort(x,kind="mergesort")
    return float("nan") if k==0 else float(y[ix[-k:]].mean()-y[ix[:k]].mean())
def stat(x,y): return rho(x,y),slope(x,y)

def boot(x,n,a):
    x=np.asarray(x,float); n=np.asarray(n,float); a=np.asarray(a,float); m=len(x); rng=np.random.default_rng(SEED); z=np.empty((DRAWS,4))
    for d in range(DRAWS):
        ix=[]
        while len(ix)<m:
            s=int(rng.integers(0,m-BLK+1)); ix.extend(range(s,s+BLK))
        j=np.asarray(ix[:m],int); z[d]=(*stat(x[j],n[j]),*stat(x[j],a[j]))
    return {k:[float(np.quantile(z[:,i],.025)),float(np.quantile(z[:,i],.975))] for i,k in enumerate(("net_rho","net_slope","adverse_rho","adverse_slope"))}

def folds(q):
    q=q.sort_values("t").reset_index(drop=True); out=[]
    for i,j in enumerate(np.array_split(np.arange(len(q)),4),1):
        p=q.iloc[j]; x=p.feature.to_numpy(float)
        out.append({"fold":i,"n":len(p),"net_slope":slope(x,p.net),"adverse_slope":slope(x,p.adverse)})
    pos=[f["net_slope"] for f in out if np.isfinite(f["net_slope"]) and f["net_slope"]>0]
    conc=float("inf") if not pos else max(pos)/sum(pos)
    return out,float(conc)

def stratum(q):
    med=float(q.margin.median()); out={"median":med}
    for name,p in (("lower",q[q.margin<=med]),("upper",q[q.margin>med])):
        out[name]={"n":len(p),"net_tercile":tercile(p.feature,p.net),"adverse_tercile":tercile(p.feature,p.adverse)}
    return out

def target_result(df,target):
    q=opportunities(df); qp=opportunities(df.iloc[:TRAIN1].copy())
    cols=["t","feature","margin","net","adverse","delay_net","delay_adverse","u","old","roll"]
    prefix=len(q)==len(qp) and q[cols].reset_index(drop=True).equals(qp[cols].reset_index(drop=True))
    if not prefix or q.empty: raise ValueError(f"{target}: prefix/empty")
    x=q.feature.to_numpy(float)
    nr,ns=stat(x,q.net); ar,ads=stat(x,q.adverse); dnr,dns=stat(x,q.delay_net); dar,das=stat(x,q.delay_adverse)
    nt,at=tercile(x,q.net),tercile(x,q.adverse); dnt,dat=tercile(x,q.delay_net),tercile(x,q.delay_adverse)
    ci=boot(x,q.net,q.adverse); fs,conc=folds(q); st=stratum(q)
    dist={"distinct":int(q.feature.nunique()),"iqr":float(q.feature.quantile(.75)-q.feature.quantile(.25)),"q25":float(q.feature.quantile(.25)),"median":float(q.feature.median()),"q75":float(q.feature.quantile(.75))}
    pn=sum(f["net_slope"]>0 for f in fs); pa=sum(f["adverse_slope"]>0 for f in fs)
    strat=all(st[z][k]>0 for z in ("lower","upper") for k in ("net_tercile","adverse_tercile"))
    structural=bool((q.u==q.t-1).all() and (q.old==q.u-H).all() and (q.roll==q.old+ROLL).all() and q.identity_error.max()<=1e-12 and q.scale_error.max()<=1e-12)
    gates={"minimum_opportunities":len(q)>=180,"feature_support":dist["distinct"]>=100 and dist["iqr"]>0,
      "positive_net_association":nr>0 and ns>0,"positive_adverse_association":ar>0 and ads>0,
      "positive_tercile_effects":nt>0 and at>0,
      "positive_bootstrap_lower_bounds":all(v[0]>0 for v in ci.values()),
      "fold_breadth":pn>=3 and pa>=3,"fold_concentration":np.isfinite(conc) and conc<=.60,
      "endpoint_margin_stratification":strat,
      "delay_transport":dnr>0 and dns>0 and dnt>0 and dar>0 and das>0 and dat>0,
      "future_suffix_invariance":prefix,"structural_identities":structural}
    stable=q.to_csv(index=False,float_format="%.12g",lineterminator="\n").encode()
    return {"opportunities":len(q),"opportunity_sha256":sha(stable),"feature_distribution":dist,
      "net_rho":nr,"net_slope":ns,"net_tercile_effect":nt,"adverse_rho":ar,"adverse_slope":ads,"adverse_tercile_effect":at,
      "bootstrap_95":ci,"folds":fs,"positive_net_folds":pn,"positive_adverse_folds":pa,"positive_net_fold_concentration":conc,
      "margin_strata":st,"delay_net_rho":dnr,"delay_net_slope":dns,"delay_net_tercile_effect":dnt,
      "delay_adverse_rho":dar,"delay_adverse_slope":das,"delay_adverse_tercile_effect":dat,
      "gates":{k:bool(v) for k,v in gates.items()},"all_training_gates_pass":bool(all(gates.values()))}

def main():
    OUT.mkdir(parents=True,exist_ok=True); sources={}; results={}
    for t in TARGETS:
        df,s=acquire(t); sources[t]=s; results[t]=target_result(df,t)
    bilateral=all(results[t]["all_training_gates_pass"] for t in TARGETS); verdict=SUPPORT if bilateral else REJECT
    payload={"family_id":FAMILY,"code_head":os.environ.get("GITHUB_SHA","local"),"base_main":"5a0fcc97d1a882f8223656c51f5bb8055f534e38",
      "targets_fixed_preperformance":list(TARGETS),"provider":"anonymous public OKX SPOT history-candles","bar":"1H","calendar":[START,END],"rows_per_target":N,
      "training":[TRAIN0,TRAIN1],"sealed_oos":[TRAIN1,OOS1],"unread_suffix":[OOS1,N],"candidate_count":0,"parameter_grid_count":0,
      "fee_bps_one_way":5.0,"round_trip_label_bps":10.0,"bootstrap_draws":DRAWS,"bootstrap_block_opportunities":BLK,"bootstrap_seed":SEED,
      "sources":sources,"targets":results,"bilateral_training_pass":bilateral,"sealed_oos_accessed":False,"canonical_mutation":False,
      "paper_trading_authorized":False,"live_trading_authorized":False,
      "strategy_metrics":{"train_return":None,"train_sharpe":None,"oos_return":None,"oos_sharpe":None,"full_return":None,"full_sharpe":None,
       "benchmark_comparison":None,"turnover":None,"fee_drag":None,"max_drawdown":None,"calendar_year_breadth":None,"edge_per_turnover":None},
      "verdict":verdict}
    raw=(json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n").encode(); (OUT/"evidence.json").write_bytes(raw)
    manifest={"code_head":payload["code_head"],"verdict":verdict,"evidence_sha256":sha(raw)}
    (OUT/"manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n")
    print(json.dumps(payload,sort_keys=True,indent=2)); print("MANIFEST",json.dumps(manifest,sort_keys=True))

if __name__=="__main__": main()
