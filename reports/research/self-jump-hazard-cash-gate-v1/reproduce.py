from __future__ import annotations

import argparse, hashlib, json, math
from pathlib import Path
from statistics import NormalDist
import numpy as np
import pandas as pd

H,L,F,N,B,SEED=8760.,2160,.0005,5000,168,20260728
D0,D1=pd.Timestamp('2023-07-24T00:00:00Z'),pd.Timestamp('2026-07-07T23:00:00Z')
Z=NormalDist().inv_cdf(.01)


def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''): h.update(c)
 return h.hexdigest()


def verify(root:Path)->None:
 for line in (root/'artifact-manifest.sha256').read_text().splitlines():
  d,r=line.split('  ',1); assert sha(root/r)==d,r


def sr(x:np.ndarray)->float:
 s=np.std(x,ddof=1); return float(np.mean(x)/s*math.sqrt(H)) if s>0 else 0.


def dd(x:np.ndarray)->float:
 nav=np.cumprod(1+x); return float(np.min(nav/np.maximum.accumulate(nav)-1))


def metrics(r,t,p):
 years=len(r)/H; ann=float(np.mean(r)*H); turn=float(np.sum(t)/years); gross=r+F*t
 return {'return':float(np.prod(1+r)-1),'gross_return':float(np.prod(1+gross)-1),
  'sharpe':sr(r),'max_drawdown':dd(r),'turnover':turn,'fee_sum':float(F*np.sum(t)),
  'edge_bps':float(ann/turn*1e4),'time_in_market':float(np.mean(p)),'adjustments':int(np.count_nonzero(t))}


def feature(df:pd.DataFrame)->pd.DataFrame:
 r=np.log(df.close.astype(float)).diff(); prod=r.abs()*r.shift().abs()
 sig=np.sqrt((math.pi/2)*prod.shift().rolling(23,min_periods=23).mean())
 lv=np.log(df.volume_quote_alt.astype(float).where(df.volume_quote_alt.astype(float)>0))
 med=lv.shift().rolling(720,min_periods=720).median()
 valid=r.notna()&sig.notna()&med.notna()&lv.notna()&(sig>0)
 jump=valid&(r<Z*sig)&(lv>med)
 p11=np.full(len(df),np.nan); p01=np.full(len(df),np.nan); gate=np.zeros(len(df),bool)
 n11=n10=n01=n00=0; pv=False; pj=False; va=valid.to_numpy(bool); ja=jump.to_numpy(bool)
 for i in range(len(df)):
  if va[i] and pv:
   c=bool(ja[i])
   if pj and c:n11+=1
   elif pj:n10+=1
   elif c:n01+=1
   else:n00+=1
  p11[i]=(n11+.5)/(n11+n10+1); p01[i]=(n01+.5)/(n01+n00+1)
  gate[i]=bool(va[i] and ja[i] and p11[i]>p01[i])
  if va[i]:pv,pj=True,bool(ja[i])
  else:pv=False
 return pd.DataFrame({'jump':jump,'gate':gate,'p11':p11,'p01':p01},index=df.index)


def paths(df:pd.DataFrame,ft:pd.DataFrame):
 base=(df.close/df.close.shift(L)-1>0).astype(float); cand=base.where(~ft.gate,0.)
 op=df.open.shift(-1)/df.open-1; out={}
 ids=(df.index>=D0)&(df.index<=D1)
 for k,target in {'J0':base,'J1':cand}.items():
  p=target.shift().loc[ids].to_numpy(float); prev=np.r_[0.,p[:-1]]; t=np.abs(p-prev)
  r=p*op.loc[ids].to_numpy(float)-F*t; out[k]=(r,t,p)
 return out,ft.loc[ids],op.loc[ids].to_numpy(float)


def bix(rng):
 z=[]
 for f in range(12):
  base=f*2160; z.append(np.array([base])); q=[]
  while sum(map(len,q))<2159:
   s=int(rng.integers(1,2160-B+1));q.append(base+np.arange(s,s+B))
  z.append(np.concatenate(q)[:2159])
 return np.concatenate(z)


def holm(ps):
 items=sorted(ps.items(),key=lambda x:x[1]);out={};run=0.;m=len(items)
 for i,(k,p) in enumerate(items):run=max(run,min(1.,(m-i)*p));out[k]=run
 return out


def main():
 ap=argparse.ArgumentParser();ap.add_argument('--btc',type=Path,required=True);ap.add_argument('--eth',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
 allp={};res={'family':'self-jump-hazard-cash-gate-v1','markets':{},'bootstrap':{}}
 for m,root in {'BTC-USDT':a.btc,'ETH-USDT':a.eth}.items():
  verify(root);p=next((root/'snapshot').glob('*.csv'));df=pd.read_csv(p,parse_dates=['timestamp']).set_index('timestamp')
  assert len(df)==43930 and df.index.is_unique and (df.confirm==1).all() and (df.index.to_series().diff().dropna()==pd.Timedelta(hours=1)).all()
  ft=feature(df);ps,fe,op=paths(df,ft);allp[m]=ps
  pos_gate=ps['J1'][2]<ps['J0'][2]
  res['markets'][m]={'J0':metrics(*ps['J0']),'J1':metrics(*ps['J1']),
   'gate_decisions':int(fe.gate.sum()),'gated_position_hours':int(pos_gate.sum()),
   'removed_hour_mean_open_return':float(op[pos_gate].mean()),'residual_sharpe':sr(ps['J1'][0]-ps['J0'][0])}
 obs={};draw={}
 for m,ps in allp.items():
  obs[m+'_sharpe']=sr(ps['J1'][0])-sr(ps['J0'][0])
  obs[m+'_edge']=metrics(*ps['J1'])['edge_bps']-metrics(*ps['J0'])['edge_bps']
  draw[m+'_sharpe']=[];draw[m+'_edge']=[]
 rng=np.random.default_rng(SEED)
 for _ in range(N):
  ix=bix(rng)
  for m,ps in allp.items():
   draw[m+'_sharpe'].append(sr(ps['J1'][0][ix])-sr(ps['J0'][0][ix]))
   e=[]
   for k in ['J0','J1']:
    r,t,_=ps[k];ann=np.mean(r[ix])*H;turn=np.mean(t[ix])*H;e.append(ann/turn*1e4)
   draw[m+'_edge'].append(e[1]-e[0])
 raw={};stats={}
 for k,v in draw.items():
  x=np.asarray(v);o=obs[k];err=x-o;p=float((1+np.sum(err>=o))/(N+1));raw[k]=p
  stats[k]={'observed':o,'lower95':float(o-np.quantile(err,.95)),'raw_p':p}
 adj=holm(raw)
 for k,p in adj.items():stats[k]['holm_p']=p
 res['bootstrap']={'n':N,'block':B,'seed':SEED,'endpoints':stats};res['verdict']='rejected_exact_family_cooldown'
 payload=(json.dumps(res,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode();a.out.write_bytes(payload);print(hashlib.sha256(payload).hexdigest())

if __name__=='__main__':main()
