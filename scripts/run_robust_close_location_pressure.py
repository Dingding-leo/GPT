# ruff: noqa
# fmt: off
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

FEE=.0005; ANN=8760.; W=2160; PW=720; BLOCK=24; NB=30; N=43441; FOLD=2160
TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); MKTS=('BTC-USDT','ETH-USDT')
HASH={'BTC-USDT':'92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9','ETH-USDT':'2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726'}
ART={'BTC-USDT':8704977298,'ETH-USDT':8704978112}; ISSUE=655; SEED=20260730


def load(p,m):
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=HASH[m]: raise ValueError(f'{m} hash mismatch')
    d=pd.read_csv(p,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[['open','high','low','close','volume_quote']].to_numpy(float)
    ok=len(d)==N and t.equals(pd.date_range(t[0],periods=len(t),freq='1h',tz='UTC')) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all() and (d.high>=d.low).all()
    if not ok: raise ValueError(f'{m} source validation failed')
    d.index=t; return d


def pressure_series(d):
    h=d.high.to_numpy(float); l=d.low.to_numpy(float); c=d.close.to_numpy(float)
    r=h-l; clv=np.divide(2*c-h-l,r,out=np.zeros_like(c),where=r>0)
    if np.nanmax(np.abs(clv))>1+1e-10: raise ValueError('CLV outside [-1,1]')
    p=np.full(len(d),np.nan)
    for t in range(PW-1,len(d)):
        blocks=clv[t-PW+1:t+1].reshape(NB,BLOCK)
        p[t]=float(np.median(np.median(blocks,axis=1)))
    return clv,p


def threshold(d,p):
    c=d.close.to_numpy(float); vals=[]; rows=[]
    for t in range(max(W,TRAIN[0]),TRAIN[1]):
        if d.index[t].hour==0 and c[t]>c[t-W]:
            vals.append(float(p[t])); rows.append(t)
    if not vals or not np.isfinite(vals).all(): raise ValueError('invalid training pressure support')
    q=float(np.quantile(np.array(vals),.60))
    return q,{'support':len(vals),'threshold_q60':q,'min':float(np.min(vals)),'median':float(np.median(vals)),'max':float(np.max(vals)),'exceedance_rate':float(np.mean(np.array(vals)>q)),'first_t':int(rows[0]),'last_t':int(rows[-1])}


def positions(d,p,q60):
    c=d.close.to_numpy(float); n=len(d); out={k:np.zeros(n-1) for k in ('candidate','b0','b1')}; cand=b0=b1=0.; rec=[]
    for t in range(W,n-1):
        b0=float(c[t]>c[t-W])
        if d.index[t].hour==0:
            base=bool(c[t]>c[t-W]); before=cand
            if cand and not base: cand=0.
            elif (not cand) and base and p[t]>q60: cand=1.
            b1=float(base)
            rec.append({'t':t,'timestamp':d.index[t].isoformat(),'base_positive':base,'pressure':float(p[t]),'above_threshold':bool(p[t]>q60),'candidate_before':float(before),'candidate_target':float(cand),'b1_target':float(b1)})
        j=t+1
        if j<n-1: out['candidate'][j]=cand; out['b0'][j]=b0; out['b1'][j]=b1
    if np.any(out['candidate']-out['b1']>1e-15): raise ValueError('candidate must be subset of B1')
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
    exposed=n[x>0]; neg=(exposed<0).astype(int); longest=cur=0
    for v in neg:
        cur=cur+1 if v else 0; longest=max(longest,cur)
    return {'net_return':float(wealth[-1]-1),'arithmetic_net_return':float(n.sum()),'sharpe':shp(n),'max_drawdown':float(np.min(path/np.maximum.accumulate(path)-1)),'turnover':turn,'exposure_change_count':int((np.abs(x-prev)>1e-15).sum()),'fees':float(a['fees'][s:e].sum()),'edge_per_turnover_bps':float(n.sum()/turn*1e4) if turn else None,'mean_exposure':float(x.mean()),'exposed_hours':int((x>0).sum()),'loss_hour_rate_when_exposed':float(np.mean(exposed<0)) if len(exposed) else None,'longest_exposed_loss_cluster_hours':int(longest)}


def breadth(n,t):
    f=[float(np.prod(1+n[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in f if x>0]; yrs=t[:-1].year; y={}
    for yr in sorted(set(yrs[OOS[0]:OOS[1]])):
        z=yrs[OOS[0]:OOS[1]]==yr; y[str(yr)]=float(np.prod(1+n[OOS[0]:OOS[1]][z])-1)
    return {'fold_returns':f,'profitable_folds':sum(x>0 for x in f),'year_returns':y,'profitable_years':sum(x>0 for x in y.values()),'positive_fold_concentration':max(pos)/sum(pos) if pos else None}


def boot(c,b):
    c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(SEED); md=np.empty(5000); sd=np.empty(5000); off=np.arange(168); blocks=math.ceil(n/168)
    for q in range(0,5000,100):
        e=q+100; st=rng.integers(0,n-167,size=(100,blocks)); ix=(st[:,:,None]+off).reshape(100,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cstd=cs.std(1,ddof=1); bstd=bs.std(1,ddof=1)
        md[q:e]=ANN*(cm-bm); sd[q:e]=np.divide(math.sqrt(ANN)*cm,cstd,out=np.zeros(100),where=cstd>0)-np.divide(math.sqrt(ANN)*bm,bstd,out=np.zeros(100),where=bstd>0)
    return {'annualized_mean_delta':{'point':float(ANN*np.mean(c-b)),'lower_95':float(np.quantile(md,.025)),'upper_95':float(np.quantile(md,.975))},'sharpe_delta':{'point':float((shp(c) or 0)-(shp(b) or 0)),'lower_95':float(np.quantile(sd,.025)),'upper_95':float(np.quantile(sd,.975))},'block_hours':168,'resamples':5000,'seed':SEED}


def selector_diag(rec,pos,a,q60):
    out={'threshold_q60':q60}
    for lab,span in (('training',TRAIN),('development_oos',OOS)):
        rows=[r for r in rec if span[0]<=r['t']<span[1] and r['base_positive']]
        vals=np.array([r['pressure'] for r in rows],float)
        out[lab]={'positive_base_decisions':len(rows),'pressure_mean':float(vals.mean()),'pressure_median':float(np.median(vals)),'pressure_q10':float(np.quantile(vals,.1)),'pressure_q90':float(np.quantile(vals,.9)),'threshold_exceedance_rate':float(np.mean(vals>q60))}
    out['oos_minus_training_exceedance_drift']=out['development_oos']['threshold_exceedance_rate']-out['training']['threshold_exceedance_rate']
    s,e=OOS; c=pos['candidate'][s:e]; b=pos['b1'][s:e]; m=a['candidate']['market'][s:e]; omitted=(b>c+1e-15); extra=(c>b+1e-15)
    if extra.any(): raise ValueError('candidate-only exposure present')
    fee_saving=float(a['b1']['fees'][s:e].sum()-a['candidate']['fees'][s:e].sum()); omitted_market=float(m[omitted].sum()); observed=float(a['candidate']['net'][s:e].sum()-a['b1']['net'][s:e].sum()); reconstructed=-omitted_market+fee_saving
    if not math.isclose(observed,reconstructed,abs_tol=1e-12): raise ValueError('selector decomposition')
    # B1 positive regimes and candidate delays.
    bfull=pos['b1']; cfull=pos['candidate']; regimes=[]; i=s
    while i<e:
        if bfull[i]<=0: i+=1; continue
        start=i
        while i<e and bfull[i]>0: i+=1
        end=i
        hits=np.flatnonzero(cfull[start:end]>0)
        if len(hits):
            delay=int(hits[0]); entered=True
        else:
            delay=None; entered=False
        regimes.append({'start':start,'end':end,'hours':end-start,'entered':entered,'delay_hours':delay,'market_arithmetic_return':float(m[start-s:end-s].sum()),'omitted_prefix_market_return':float(m[start-s:start-s+(delay if delay is not None else end-start)].sum())})
    cn=a['candidate']['net'][s:e]; bn=a['b1']['net'][s:e]; improved=[]
    for k in range(12): improved.append(float(cn[k*FOLD:(k+1)*FOLD].sum()-bn[k*FOLD:(k+1)*FOLD].sum())>0)
    out['oos_exposure_decomposition']={'candidate_only_hours':int(extra.sum()),'b1_only_hours':int(omitted.sum()),'b1_only_market_arithmetic_return':omitted_market,'fee_saving_vs_b1':fee_saving,'observed_candidate_minus_b1_arithmetic_net':observed,'reconstructed_candidate_minus_b1_arithmetic_net':reconstructed,'identity_passes':True}
    entered=[r for r in regimes if r['entered']]; never=[r for r in regimes if not r['entered']]
    out['oos_regimes']={'b1_positive_regimes':len(regimes),'candidate_entered_regimes':len(entered),'never_entered_regimes':len(never),'entry_delay_hours':[r['delay_hours'] for r in entered],'median_entry_delay_hours':float(np.median([r['delay_hours'] for r in entered])) if entered else None,'entered_regime_market_arithmetic_return':float(sum(r['market_arithmetic_return'] for r in entered)),'entered_profitable_regimes':sum(r['market_arithmetic_return']>0 for r in entered),'entered_omitted_prefix_market_return':float(sum(r['omitted_prefix_market_return'] for r in entered)),'never_entered_regime_market_arithmetic_return':float(sum(r['market_arithmetic_return'] for r in never)),'never_entered_profitable_regimes':sum(r['market_arithmetic_return']>0 for r in never),'selector_effect_folds':sum(np.any(omitted[k*FOLD:(k+1)*FOLD]) for k in range(12)),'improved_arithmetic_net_folds_vs_b1':sum(improved)}
    return out


def checks(r):
    c=r['metrics']['development_oos']['candidate']; b=r['metrics']['development_oos']['b1']; f=r['metrics']['full_scored']['candidate']; br=r['breadth']; u=r['uncertainty']; rs=r['residual_sharpe']['vs_b1']; con=br['positive_fold_concentration']
    return {'positive_oos_net':c['net_return']>0,'positive_oos_sharpe':c['sharpe'] is not None and c['sharpe']>0,'net_at_least_b1':c['net_return']>=b['net_return'],'sharpe_at_least_b1':c['sharpe']>=b['sharpe'],'drawdown_no_worse_b1':c['max_drawdown']>=b['max_drawdown'],'turnover_no_greater_b1':c['turnover']<=b['turnover'],'edge_per_turnover_at_least_b1':c['edge_per_turnover_bps']>=b['edge_per_turnover_bps'],'profitable_folds_at_least_7':br['profitable_folds']>=7,'profitable_years_at_least_3':br['profitable_years']>=3,'positive_residual_sharpe_b1':rs is not None and rs>0,'mean_delta_lower_95_positive':u['annualized_mean_delta']['lower_95']>0,'sharpe_delta_lower_95_positive':u['sharpe_delta']['lower_95']>0,'positive_fold_concentration_at_most_half':con is not None and con<=.5,'positive_full_scored_net':f['net_return']>0}


def run(d,m):
    clv,p=pressure_series(d); q60,cal=threshold(d,p); pos,rec=positions(d,p,q60); a={k:pack(d,v) for k,v in pos.items()}; spans={'training':TRAIN,'development_oos':OOS,'full_scored':FULL}; mets={lab:{k:metric(a[k],pos[k],sp) for k in a} for lab,sp in spans.items()}; co=a['candidate']['net'][OOS[0]:OOS[1]]; b0=a['b0']['net'][OOS[0]:OOS[1]]; b1=a['b1']['net'][OOS[0]:OOS[1]]
    r={'source':{'artifact_id':ART[m],'csv_sha256':HASH[m],'observations_in_source':43941,'parsed_prefix_bars':N,'start_timestamp':d.index[0].isoformat(),'parsed_end_timestamp':d.index[-1].isoformat()},'training_calibration':cal,'feature_definition':{'hourly_clv':'(2*close-high-low)/(high-low), zero if high==low','window_hours':PW,'blocks':NB,'block_hours':BLOCK,'aggregate':'median of 30 within-block medians'},'metrics':mets,'breadth':breadth(a['candidate']['net'],d.index),'residual_sharpe':{'vs_b0':shp(co-b0),'vs_b1':shp(co-b1)},'uncertainty':boot(a['candidate']['net'],a['b1']['net']),'selector_diagnostics':selector_diag(rec,pos,a,q60)}
    r['acceptance_checks']=checks(r); r['market_accepts']=all(r['acceptance_checks'].values()); return r



def compact_market(r):
    fields=('net_return','arithmetic_net_return','sharpe','max_drawdown','turnover','fees','edge_per_turnover_bps','mean_exposure','exposure_change_count','exposed_hours','loss_hour_rate_when_exposed','longest_exposed_loss_cluster_hours')
    def slim(z): return {k:z[k] for k in fields}
    return {
        'source':r['source'],
        'training_calibration':r['training_calibration'],
        'feature_definition':r['feature_definition'],
        'metrics':{
            'training':{k:slim(r['metrics']['training'][k]) for k in ('candidate','b1')},
            'development_oos':{k:slim(r['metrics']['development_oos'][k]) for k in ('candidate','b0','b1')},
            'full_scored':{k:slim(r['metrics']['full_scored'][k]) for k in ('candidate','b1')},
        },
        'breadth':r['breadth'],
        'residual_sharpe':r['residual_sharpe'],
        'uncertainty':r['uncertainty'],
        'selector_diagnostics':r['selector_diagnostics'],
        'acceptance_checks':r['acceptance_checks'],
        'market_accepts':r['market_accepts'],
    }

def main():
    q=argparse.ArgumentParser(); q.add_argument('--btc-csv',type=Path,required=True); q.add_argument('--eth-csv',type=Path,required=True); q.add_argument('--output',type=Path,required=True); x=q.parse_args(); paths={'BTC-USDT':x.btc_csv,'ETH-USDT':x.eth_csv}; full_markets={m:run(load(paths[m],m),m) for m in MKTS}; ok=all(v['market_accepts'] for v in full_markets.values()); markets={m:compact_market(v) for m,v in full_markets.items()}
    out={'family_id':'robust-close-location-pressure-entry-1h-v1','issue':ISSUE,'candidate_count':1,'parameter_grid_count':0,'bar':'1H','canonical_fee_one_way':FEE,'research_parent':'5a0fcc97d1a882f8223656c51f5bb8055f534e38','sample':{'warmup':[0,2880],'training':list(TRAIN),'development_oos':list(OOS),'full_scored':list(FULL),'parsed_prefix_bars':N,'later_suffix_unread':True},'markets':markets,'verdict':'nominate_robust_close_location_pressure_entry_for_g1' if ok else 'reject_exact_robust_close_location_pressure_entry_family','paper_or_live_authorized':False,'repaired_discrepancy':'Initial serialization failed on NumPy integer scalars in diagnostics. Native-scalar JSON conversion was added and the full experiment was rerun twice byte-identically; no strategy or metric changed.'}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(out,sort_keys=True,separators=(',',':'),default=lambda o:o.item() if isinstance(o,np.generic) else str(o))+'\n')

if __name__=='__main__': main()
