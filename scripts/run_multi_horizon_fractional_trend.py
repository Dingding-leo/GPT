# ruff: noqa
# fmt: off
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=.0005; ANN=8760.; H=(720,1440,2160); W=2160; N=43441; FOLD=2160
TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); MKTS=('BTC-USDT','ETH-USDT')
HASH={'BTC-USDT':'92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9','ETH-USDT':'2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726'}
ART={'BTC-USDT':8704977298,'ETH-USDT':8704978112}; STATES=(0.,1/3,2/3,1.)

def load(p,m):
    if hashlib.sha256(p.read_bytes()).hexdigest()!=HASH[m]: raise ValueError(f'{m} hash mismatch')
    d=pd.read_csv(p,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[['open','high','low','close','volume_quote']].to_numpy(float)
    ok=len(d)==N and t.equals(pd.date_range(t[0],periods=len(t),freq='1h',tz='UTC')) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all() and (d.high>=d.low).all()
    if not ok: raise ValueError(f'{m} source validation failed')
    d.index=t; return d

def positions(d):
    c=d.close.to_numpy(float); n=len(d); out={k:np.zeros(n-1) for k in ('candidate','b0','b1')}; q=b0=b1=0.; rec=[]
    for t in range(W,n-1):
        b0=float(c[t]>c[t-W])
        if d.index[t].hour==0:
            s=tuple(int(c[t]>c[t-h]) for h in H); q=sum(s)/3; b1=float(s[-1]); rec.append({'t':t,'target':q,'signs':list(s)})
        j=t+1
        if j<n-1: out['candidate'][j]=q; out['b0'][j]=b0; out['b1'][j]=b1
    if np.max(np.min(np.abs(out['candidate'][:,None]-np.array(STATES)[None,:]),axis=1))>1e-12: raise ValueError('invalid target')
    for k in ('candidate','b1'):
        z=np.flatnonzero(np.r_[out[k][0]!=0,np.diff(out[k])!=0])
        if any(i<=0 or d.index[int(i)-1].hour!=0 for i in z): raise ValueError(f'{k} timing')
    return out,rec

def pack(d,p):
    o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; gross=p*market; fees=FEE*turn; net=gross-fees
    if not np.array_equal(net,p*market-.0005*turn): raise ValueError('fee identity')
    return {'market':market,'gross':gross,'turn':turn,'fees':fees,'net':net}

def shp(x):
    s=float(np.std(x,ddof=1)); return None if s<=0 else float(math.sqrt(ANN)*np.mean(x)/s)

def metric(a,p,span):
    s,e=span; n=a['net'][s:e]; x=p[s:e]; wealth=np.cumprod(1+n); path=np.r_[1.,wealth]; turn=float(a['turn'][s:e].sum()); prev=np.r_[p[s-1] if s else 0.,x[:-1]]
    return {'net_return':float(wealth[-1]-1),'arithmetic_net_return':float(n.sum()),'sharpe':shp(n),'max_drawdown':float(np.min(path/np.maximum.accumulate(path)-1)),'turnover':turn,'exposure_change_count':int((np.abs(x-prev)>1e-15).sum()),'fees':float(a['fees'][s:e].sum()),'edge_per_turnover_bps':float(n.sum()/turn*1e4) if turn else None,'mean_exposure':float(x.mean())}

def breadth(n,t):
    f=[float(np.prod(1+n[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in f if x>0]; yrs=t[:-1].year; y={}
    for yr in sorted(set(yrs[OOS[0]:OOS[1]])):
        z=yrs[OOS[0]:OOS[1]]==yr; y[str(yr)]=float(np.prod(1+n[OOS[0]:OOS[1]][z])-1)
    return {'fold_returns':f,'profitable_folds':sum(x>0 for x in f),'year_returns':y,'profitable_years':sum(x>0 for x in y.values()),'positive_fold_concentration':max(pos)/sum(pos) if pos else None}

def boot(c,b):
    c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(20260730); md=np.empty(5000); sd=np.empty(5000); off=np.arange(168); blocks=math.ceil(n/168)
    for q in range(0,5000,100):
        e=q+100; st=rng.integers(0,n-167,size=(100,blocks)); ix=(st[:,:,None]+off).reshape(100,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cstd=cs.std(1,ddof=1); bstd=bs.std(1,ddof=1)
        md[q:e]=ANN*(cm-bm); sd[q:e]=np.divide(math.sqrt(ANN)*cm,cstd,out=np.zeros(100),where=cstd>0)-np.divide(math.sqrt(ANN)*bm,bstd,out=np.zeros(100),where=bstd>0)
    return {'annualized_mean_delta':{'point':float(ANN*np.mean(c-b)),'lower_95':float(np.quantile(md,.025)),'upper_95':float(np.quantile(md,.975))},'sharpe_delta':{'point':float((shp(c) or 0)-(shp(b) or 0)),'lower_95':float(np.quantile(sd,.025)),'upper_95':float(np.quantile(sd,.975))},'block_hours':168,'resamples':5000,'seed':20260730}

def key(x):
    for v,k in zip(STATES,('0','1/3','2/3','1')):
        if math.isclose(x,v,abs_tol=1e-12): return k
    raise ValueError(x)

def state_diag(rec,a,p):
    z={}
    for lab,span in (('training',TRAIN),('development_oos',OOS)):
        rows=[r for r in rec if span[0]<=r['t']<span[1]]; cnt={k:0 for k in ('0','1/3','2/3','1')}
        for r in rows: cnt[key(r['target'])]+=1
        z[lab]={'decisions':len(rows),'counts':cnt,'frequencies':{k:v/len(rows) for k,v in cnt.items()}}
    z['oos_minus_training_frequency_drift']={k:z['development_oos']['frequencies'][k]-z['training']['frequencies'][k] for k in z['training']['frequencies']}
    s,e=OOS; contrib={}
    for v in STATES:
        mask=np.isclose(p[s:e],v); contrib[key(v)]={'hours':int(mask.sum()),'gross_arithmetic_return':float(a['gross'][s:e][mask].sum()),'fees':float(a['fees'][s:e][mask].sum()),'net_arithmetic_return':float(a['net'][s:e][mask].sum()),'market_arithmetic_return':float(a['market'][s:e][mask].sum())}
    z['oos_hourly_return_contribution']=contrib
    x=p[s:e]; old=np.r_[p[s-1],x[:-1]]; delta=np.abs(x-old); ch=delta>1e-15; tr={}
    for u,v,w in zip(old[ch],x[ch],delta[ch],strict=True):
        k=f'{key(float(u))}->{key(float(v))}'; item=tr.setdefault(k,{'count':0,'turnover_units':0.,'fees':0.}); item['count']+=1; item['turnover_units']+=float(w); item['fees']+=FEE*float(w)
    if not math.isclose(float(delta.sum()),float(a['turn'][s:e].sum()),abs_tol=1e-12): raise ValueError('turn attribution')
    z['oos_transition_fee_attribution']={'transition_types':dict(sorted(tr.items())),'change_count':int(ch.sum()),'total_turnover_units':float(delta.sum()),'total_fees':float(FEE*delta.sum()),'attribution_identity_passes':True}
    z['diagnostic_repair']='Fees were initially grouped by post-change target state. Exact from-to transition attribution was added; no target, return, benchmark, gate or verdict changed.'
    return z

def diff(pos,a):
    s,e=OOS; c=pos['candidate'][s:e]; b=pos['b1'][s:e]; m=a['candidate']['market'][s:e]; d=c-b; more=d>1e-15; less=d<-1e-15; fee=float(a['candidate']['fees'][s:e].sum()-a['b1']['fees'][s:e].sum()); gross=float(np.sum(d*m)); obs=float(a['candidate']['net'][s:e].sum()-a['b1']['net'][s:e].sum())
    if not math.isclose(gross-fee,obs,abs_tol=1e-12): raise ValueError('decomposition')
    cn=a['candidate']['net'][s:e]; bn=a['b1']['net'][s:e]; imp=0
    for k in range(12): imp+=float(cn[k*FOLD:(k+1)*FOLD].sum()-bn[k*FOLD:(k+1)*FOLD].sum())>0
    return {'different_exposure_hours':int((np.abs(d)>1e-15).sum()),'candidate_more_exposure_hours':int(more.sum()),'candidate_more_exposure_units':float(d[more].sum()),'candidate_more_gross_return_contribution':float(np.sum(d[more]*m[more])),'b1_more_exposure_hours':int(less.sum()),'b1_more_exposure_units':float((-d[less]).sum()),'b1_more_gross_return_contribution_to_candidate_delta':float(np.sum(d[less]*m[less])),'gross_arithmetic_delta':gross,'incremental_fee_cost_vs_b1':fee,'observed_candidate_minus_b1_arithmetic_net':obs,'reconstructed_candidate_minus_b1_arithmetic_net':gross-fee,'decomposition_identity_passes':True,'selector_effect_folds':12,'improved_arithmetic_net_folds_vs_b1':imp}

def checks(r):
    c=r['metrics']['development_oos']['candidate']; b=r['metrics']['development_oos']['b1']; f=r['metrics']['full_scored']['candidate']; br=r['breadth']; u=r['uncertainty']; rs=r['residual_sharpe']['vs_b1']; con=br['positive_fold_concentration']
    return {'positive_oos_net':c['net_return']>0,'positive_oos_sharpe':c['sharpe'] is not None and c['sharpe']>0,'net_at_least_b1':c['net_return']>=b['net_return'],'sharpe_at_least_b1':c['sharpe']>=b['sharpe'],'drawdown_no_worse_b1':c['max_drawdown']>=b['max_drawdown'],'turnover_no_greater_b1':c['turnover']<=b['turnover'],'edge_per_turnover_at_least_b1':c['edge_per_turnover_bps']>=b['edge_per_turnover_bps'],'profitable_folds_at_least_7':br['profitable_folds']>=7,'profitable_years_at_least_3':br['profitable_years']>=3,'positive_residual_sharpe_b1':rs is not None and rs>0,'mean_delta_lower_95_positive':u['annualized_mean_delta']['lower_95']>0,'sharpe_delta_lower_95_positive':u['sharpe_delta']['lower_95']>0,'positive_fold_concentration_at_most_half':con is not None and con<=.5,'positive_full_scored_net':f['net_return']>0}

def run(d,m):
    p,rec=positions(d); a={k:pack(d,v) for k,v in p.items()}; spans={'training':TRAIN,'development_oos':OOS,'full_scored':FULL}; mets={lab:{k:metric(a[k],p[k],sp) for k in a} for lab,sp in spans.items()}; co=a['candidate']['net'][OOS[0]:OOS[1]]; b0=a['b0']['net'][OOS[0]:OOS[1]]; b1=a['b1']['net'][OOS[0]:OOS[1]]
    r={'source':{'artifact_id':ART[m],'csv_sha256':HASH[m],'observations_in_source':43941,'parsed_prefix_bars':N,'start_timestamp':d.index[0].isoformat(),'parsed_end_timestamp':d.index[-1].isoformat()},'metrics':mets,'breadth':breadth(a['candidate']['net'],d.index),'residual_sharpe':{'vs_b0':shp(co-b0),'vs_b1':shp(co-b1)},'uncertainty':boot(a['candidate']['net'],a['b1']['net']),'state_diagnostics':state_diag(rec,a['candidate'],p['candidate']),'fractional_exposure_discrepancy_vs_b1':diff(p,a)}
    r['acceptance_checks']=checks(r); r['market_accepts']=all(r['acceptance_checks'].values()); return r

def main():
    q=argparse.ArgumentParser(); q.add_argument('--btc-csv',type=Path,required=True); q.add_argument('--eth-csv',type=Path,required=True); q.add_argument('--output',type=Path,required=True); x=q.parse_args(); paths={'BTC-USDT':x.btc_csv,'ETH-USDT':x.eth_csv}; markets={m:run(load(paths[m],m),m) for m in MKTS}; ok=all(v['market_accepts'] for v in markets.values())
    out={'family_id':'multi-horizon-fractional-trend-ensemble-1h-v1','issue':651,'candidate_count':1,'parameter_grid_count':0,'bar':'1H','canonical_fee_one_way':FEE,'research_parent':'5a0fcc97d1a882f8223656c51f5bb8055f534e38','sample':{'warmup':[0,2880],'training':list(TRAIN),'development_oos':list(OOS),'full_scored':list(FULL),'parsed_prefix_bars':N,'later_suffix_unread':True},'markets':markets,'verdict':'nominate_multi_horizon_fractional_trend_ensemble_for_g1' if ok else 'reject_exact_multi_horizon_fractional_trend_ensemble_family','paper_or_live_authorized':False}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
if __name__=='__main__': main()
