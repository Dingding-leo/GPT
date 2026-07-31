#!/usr/bin/env python3
# ruff: noqa
# fmt: off
"""Reproduce beta-sign-soft-exit-sleeve-1h-v1 on frozen real OKX 1H data."""
import argparse,csv,hashlib,json,math
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np

FEE=.0005; Y=8760; LB=2160; H=168; N=43441; R=5000; SEED=20260731
S={'training':(2880,17520),'development_oos':(17520,43440),'full':(2880,43440)}
E={
'SOL-USDT':('321c1180674db5c577357f636a3e8caacb6052953e0007f77fc4947c00c1c744',43994,8781469963,'082b96bdd3bdec5f80b7fd68949ae588a77ddd392d733528790400bc725b699a'),
'XRP-USDT':('16de43751adf14d1274ff5656506f62c2dd5250a0029a11059b419de7d354cdb',43994,8781477440,'05b884d52cfe7aeaef3bfe116e6875cf1cbe70a486600993cece57fa9dc7316c')}
def h(b): return hashlib.sha256(b).hexdigest()
def ts(x): return datetime.fromisoformat(x.replace('Z','+00:00')).astimezone(timezone.utc)
def load(path,inst):
 b=path.read_bytes(); ex,rows,aid,ah=E[inst]
 assert h(b)==ex and len(b.splitlines())==rows+1
 pref=b''.join(b.splitlines(keepends=True)[:N+1])
 with path.open(newline='',encoding='utf-8') as f: z=list(csv.DictReader(f))
 t=[ts(x['timestamp']) for x in z]; assert t[0]==datetime(2021,7,24,tzinfo=timezone.utc)
 assert all(v-u==timedelta(hours=1) for u,v in zip(t[:-1],t[1:],strict=True)) and len(set(t))==len(t)
 for c in ('open','high','low','close'):
  v=np.array([float(x[c]) for x in z]); assert np.all(np.isfinite(v)&(v>0))
 assert all(x['confirm']=='1' for x in z)
 return {'inst':inst,'name':path.name,'sha':ex,'prefix_sha':h(pref),'artifact_id':aid,'artifact_sha':ah,'t':t,'o':np.array([float(x['open']) for x in z]),'c':np.array([float(x['close']) for x in z])}
def build(d,n):
 o=d['o'][:n]; c=d['c'][:n]; t=d['t'][:n]; ret=o[1:]/o[:-1]-1
 base=np.zeros(n,dtype=np.int8); base[LB:]=(c[LB:]>c[:-LB]).astype(np.int8)
 daily=np.array([x.hour==0 for x in t]); di=np.flatnonzero(daily&(np.arange(n)>=LB))
 ep=[]; prev=None
 for q in di:
  b=int(base[q])
  if prev==1 and b==0:
   f=di[(di>q)&(di<=min(q+H,n-1))]; rr=f[base[f]==1]
   if len(rr): u=int(rr[0]); term='recross'; complete=True
   elif q+H<n: u=int(q+H); term='expiry'; complete=True
   else: u=None; term='open'; complete=False
   target=None if not complete else .5*float(ret[q+1:u+1].sum())+(FEE if term=='recross' else 0)
   ep.append({'exit':int(q),'u':u,'term':term,'complete':complete,'target':target})
  prev=b
 for e in ep:
  p=[x for x in ep if x['complete'] and x['u']<e['exit']]
  w=sum(x['target']>0 for x in p); e.update(n=len(p),wins=w,x=.5*(w+1)/(len(p)+2))
 em={e['exit']:e for e in ep}
 def pol(kind):
  x=np.zeros(n-1); cur=0.; active=None
  for i in range(n-1):
   q=i-1
   if q>=LB:
    if kind=='b0': cur=float(base[q])
    elif kind=='b1':
     if daily[q]: cur=float(base[q])
    elif daily[q]:
     if base[q]==1: cur=1.; active=None
     elif q in em: active=em[q]; cur=active['x']
     elif active is not None and active['u'] is not None and q>=active['u']: cur=0.; active=None
   x[i]=cur
  f=FEE*np.abs(x-np.r_[0.,x[:-1]]); return {'x':x,'f':f,'r':x*ret-f}
 return ret,ep,{'candidate':pol('candidate'),'daily_b1':pol('b1'),'hourly_b0':pol('b0')}
def met(p,a,b):
 r=p['r'][a:b]; x=p['x'][a:b]; f=p['f'][a:b]; sd=r.std(ddof=1); eq=np.cumprod(1+r); peak=np.maximum.accumulate(np.r_[1.,eq])[1:]; to=f.sum()/FEE; ar=r.sum()
 sh=None if (not np.isfinite(sd) or sd==0) else float(math.sqrt(Y)*r.mean()/sd); edge=None if to==0 else float(ar/to*1e4)
 return {'net':float(np.prod(1+r)-1),'arithmetic':float(ar),'sharpe':sh,'max_drawdown':float((eq/peak-1).min()),'turnover':float(to),'fees':float(f.sum()),'mean_exposure':float(x.mean()),'exposure_hours':int(np.count_nonzero(x)),'edge_per_turnover_bps':edge}
def boot(v,starts):
 n=len(v); k=starts.shape[1]; rem=n-(k-1)*H; cs=np.r_[0.,np.cumsum(v)]; c2=np.r_[0.,np.cumsum(v*v)]; a=starts[:,:-1]; sm=(cs[a+H]-cs[a]).sum(1); sq=(c2[a+H]-c2[a]).sum(1); z=starts[:,-1]; sm+=cs[z+rem]-cs[z]; sq+=c2[z+rem]-c2[z]; mean=sm/n; sd=np.sqrt(np.maximum((sq-sm*sm/n)/(n-1),0)); return mean,math.sqrt(Y)*mean/sd
def interval(v): q=np.quantile(v,[.025,.975]); return [float(q[0]),float(q[1])]
def evaluate(d,b):
 ret,ep,p=b; out={'metrics':{k:{n:met(v,*ab) for n,v in p.items()} for k,ab in S.items()}}
 a,z=S['development_oos']; folds=[]
 for i in range(12):
  u=a+i*2160; v=u+2160; c=met(p['candidate'],u,v)['net']; q=met(p['daily_b1'],u,v)['net']; folds.append({'fold':i+1,'candidate':c,'daily_b1':q,'profitable':c>0,'improved':c>q})
 pos=[x['candidate'] for x in folds if x['profitable']]; years=[]; yy=np.array([x.year for x in d['t'][:len(ret)]])
 for y in sorted(set(yy[a:z])):
  m=(yy==y)&(np.arange(len(yy))>=a)&(np.arange(len(yy))<z); c=float(np.prod(1+p['candidate']['r'][m])-1); q=float(np.prod(1+p['daily_b1']['r'][m])-1); years.append({'year':int(y),'candidate':c,'daily_b1':q,'profitable':c>0,'improved':c>q})
 residual=p['candidate']['r'][a:z]-p['daily_b1']['r'][a:z]; done=[e for e in ep if a<=e['exit']<z and e['complete'] and e['u']<z]; open_=[e for e in ep if a<=e['exit']<z and e not in done]; comp=sum(2*e['x']*e['target'] for e in done); exact=float(residual.sum())
 out['breadth']={'profitable_folds':sum(x['profitable'] for x in folds),'improved_folds':sum(x['improved'] for x in folds),'positive_fold_concentration':None if not pos else float(max(pos)/sum(pos)),'profitable_years':sum(x['profitable'] for x in years),'improved_years':sum(x['improved'] for x in years),'residual_sharpe':float(math.sqrt(Y)*residual.mean()/residual.std(ddof=1)),'folds':folds,'years':years}
 out['diagnostics']={'completed_oos_starts':len(done),'boundary_open_starts':len(open_),'wins':sum(e['target']>0 for e in done),'losses':sum(e['target']<=0 for e in done),'recrosses':sum(e['term']=='recross' for e in done),'expiries':sum(e['term']=='expiry' for e in done),'mean_sleeve_exposure':float(np.mean([e['x'] for e in done])),'completed_contribution':float(comp),'boundary_partial':float(exact-comp),'arithmetic_residual':exact,'decomposition_error':float(abs(comp+(exact-comp)-exact))}
 out['source']={'basename':d['name'],'rows':len(d['t']),'full_sha256':d['sha'],'raw_prefix_sha256':d['prefix_sha'],'artifact_id':d['artifact_id'],'artifact_sha256':d['artifact_sha'],'first':d['t'][0].isoformat().replace('+00:00','Z'),'last':d['t'][-1].isoformat().replace('+00:00','Z'),'frozen_last':d['t'][N-1].isoformat().replace('+00:00','Z'),'suffix_rows':len(d['t'])-N}
 return out
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--sol-csv',type=Path,required=True); ap.add_argument('--xrp-csv',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args(); data={'SOL-USDT':load(a.sol_csv,'SOL-USDT'),'XRP-USDT':load(a.xrp_csv,'XRP-USDT')}; pref={}; full={}
 for k,d in data.items():
  pref[k]=build(d,N); full[k]=build(d,len(d['t']))
  for p in ('candidate','daily_b1','hourly_b0'):
   for f in ('x','f','r'): assert np.array_equal(pref[k][2][p][f],full[k][2][p][f][:N-1])
 out={k:evaluate(data[k],pref[k]) for k in data}; n=S['development_oos'][1]-S['development_oos'][0]; rng=np.random.default_rng(SEED); starts=rng.integers(0,n-H+1,size=(R,math.ceil(n/H))); draws={}
 for k in data:
  p=pref[k][2]; u,v=S['development_oos']; cm,cs=boot(p['candidate']['r'][u:v],starts); bm,bs=boot(p['daily_b1']['r'][u:v],starts); md=(cm-bm)*Y; sd=cs-bs; draws[k]=(md,sd); c=out[k]['metrics']['development_oos']['candidate']; q=out[k]['metrics']['development_oos']['daily_b1']; un={'annualised_mean_delta_point':float((p['candidate']['r'][u:v].mean()-p['daily_b1']['r'][u:v].mean())*Y),'annualised_mean_delta_95pct':interval(md),'sharpe_delta_point':float(c['sharpe']-q['sharpe']),'sharpe_delta_95pct':interval(sd)}; out[k]['uncertainty']=un; br=out[k]['breadth']; out[k]['gates']={'oos_net':c['net']>0 and c['net']>=q['net'],'oos_sharpe':c['sharpe']>=q['sharpe'],'drawdown':c['max_drawdown']>=q['max_drawdown']-1e-12,'turnover':c['turnover']<=q['turnover']+1e-12,'edge_per_turnover':c['edge_per_turnover_bps']>0 and c['edge_per_turnover_bps']>=q['edge_per_turnover_bps'],'folds':br['profitable_folds']>=7,'years':br['profitable_years']>=3,'concentration':br['positive_fold_concentration']<=.5,'residual_sharpe':br['residual_sharpe']>0,'mean_ci':un['annualised_mean_delta_95pct'][0]>0,'sharpe_ci':un['sharpe_delta_95pct'][0]>0,'full_net':out[k]['metrics']['full']['candidate']['net']>0,'integrity':out[k]['diagnostics']['decomposition_error']<=1e-12}; out[k]['gates']['all']=all(out[k]['gates'].values())
 medm=np.median(np.vstack([draws[k][0] for k in data]),axis=0); meds=np.median(np.vstack([draws[k][1] for k in data]),axis=0); common={'mean_delta_point':float(np.median([out[k]['uncertainty']['annualised_mean_delta_point'] for k in data])),'mean_delta_95pct':interval(medm),'sharpe_delta_point':float(np.median([out[k]['uncertainty']['sharpe_delta_point'] for k in data])),'sharpe_delta_95pct':interval(meds),'markets_passing':sum(out[k]['gates']['all'] for k in data)}; common['bilateral_support']=common['markets_passing']==2 and common['mean_delta_95pct'][0]>0 and common['sharpe_delta_95pct'][0]>0
 payload={'schema_version':1,'family':'beta-sign-soft-exit-sleeve-1h-v1','candidate_count':1,'parameter_grid_count':0,'bar':'1H','fee_one_way':FEE,'main_parent':'5a0fcc97d1a882f8223656c51f5bb8055f534e38','source_workflow':30599723593,'source_head':'f7c069d5f6a1dfdc9e4ac00d8324f487cb1f69c3','sample':S,'uncertainty':{'resamples':R,'block_hours':H,'seed':SEED,'common_starts':True},'markets':out,'common':common,'verdict':'support_beta_sign_soft_exit_sleeve_family' if common['bilateral_support'] else 'reject_beta_sign_soft_exit_sleeve_family','repair':{'absolute_paths_removed':True,'boundary_open_attribution_added':True,'strategy_changed':False},'integrity':{'real_public_data_only':True,'confirmed_contiguous_1h':True,'future_suffix_invariance':True,'next_open':True,'exact_5bps':True}}
 payload['canonical_payload_sha256']=h((json.dumps(payload,sort_keys=True,separators=(',',':'))+'\n').encode()); a.output.write_text(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+'\n')
if __name__=='__main__': main()
