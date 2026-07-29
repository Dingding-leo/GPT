# ruff: noqa
# fmt: off
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
FEE=.0005; ANN=8760.; W=2160; SW=168; BH=24; BC=7; N=43441; FOLD=2160; TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); SEED=20260730; EPS=1e-30; ISSUE=658
HASH={'BTC-USDT':'92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9','ETH-USDT':'2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726'}; ART={'BTC-USDT':8704977298,'ETH-USDT':8704978112}
def load(p,m):
 raw=p.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=HASH[m]: raise ValueError(f'{m} hash mismatch')
 d=pd.read_csv(p,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[['open','high','low','close','volume_quote']].to_numpy(float)
 ok=len(d)==N and t.equals(pd.date_range(t[0],periods=len(t),freq='1h',tz='UTC')) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all() and (d.high>=d.low).all()
 if not ok: raise ValueError(f'{m} source validation failed')
 d.index=t; return d
def features(b):
 c=b.close.to_numpy(float); v=b.volume_quote.to_numpy(float); r=np.zeros(len(b)); r[1:]=np.diff(np.log(c)); h=np.abs(r)/(1+v); s=np.full(len(b),np.nan); q=np.full(len(b),np.nan); z=np.full(len(b),np.nan); ii,jj=np.triu_indices(BC,k=1); dd=(jj-ii).astype(float)
 for t in range(SW-1,len(b)):
  bm=np.median(h[t-SW+1:t+1].reshape(BC,BH),axis=1); lb=np.log(bm+EPS); s[t]=np.median(bm); q[t]=np.median((lb[jj]-lb[ii])/dd); z[t]=bm[-1]
 return {'hourly':h,'stress':s,'slope':q,'latest':z}
def calibrate(b,f):
 rows=[t for t in range(*TRAIN) if b.index[t].hour==0 and np.isfinite(f['stress'][t])]; x=f['stress'][rows]; th=float(np.median(x)); state=(x>th)&(f['slope'][rows]<0)&(f['latest'][rows]<x)
 return th,{'support':len(rows),'stress_median_threshold':th,'stress_min':float(x.min()),'stress_median':float(np.median(x)),'stress_max':float(x.max()),'stress_above_threshold_rate':float(np.mean(x>th)),'recovery_state_rate':float(np.mean(state)),'first_t':rows[0],'last_t':rows[-1],'threshold_source':'BTC-USDT exogenous training daily decisions only'}
def featdiag(b,f,th):
 out={'stress_median_threshold':th}
 for lab,sp in (('training',TRAIN),('development_oos',OOS)):
  rows=[t for t in range(*sp) if b.index[t].hour==0]; x=f['stress'][rows]; sl=f['slope'][rows]; latest=f['latest'][rows]; state=(x>th)&(sl<0)&(latest<x)
  out[lab]={'daily_decisions':len(rows),'stress_mean':float(x.mean()),'stress_median':float(np.median(x)),'stress_q10':float(np.quantile(x,.1)),'stress_q90':float(np.quantile(x,.9)),'stress_above_threshold_rate':float(np.mean(x>th)),'negative_recovery_slope_rate':float(np.mean(sl<0)),'latest_below_level_rate':float(np.mean(latest<x)),'recovery_state_rate':float(np.mean(state))}
 out['oos_minus_training_recovery_state_drift']=out['development_oos']['recovery_state_rate']-out['training']['recovery_state_rate']; return out
def scalediag(b,f,th):
 c=b.close.to_numpy(float); v=b.volume_quote.to_numpy(float); ar=np.zeros(len(b)); ar[1:]=np.abs(np.diff(np.log(c))); out={}
 for lab,sp in (('training',TRAIN),('development_oos',OOS)):
  s,e=sp; rows=[t for t in range(s,e) if b.index[t].hour==0]; out[lab]={'quote_volume_median':float(np.median(v[s:e])),'absolute_log_return_median':float(np.median(ar[s:e])),'hourly_stress_median':float(np.median(f['hourly'][s:e])),'weekly_stress_median':float(np.median(f['stress'][rows])),'daily_stress_above_training_threshold_count':int(np.sum(f['stress'][rows]>th)),'daily_decisions':len(rows)}
 tr=out['training']; oo=out['development_oos']; out['oos_to_training_ratios']={k:oo[k]/tr[k] for k in ('quote_volume_median','absolute_log_return_median','hourly_stress_median','weekly_stress_median')}; rows=[t for t in range(*OOS) if b.index[t].hour==0 and f['stress'][t]>th]; out['development_oos_threshold_exceedances']=[{'t':t,'timestamp':b.index[t].isoformat(),'stress_level':float(f['stress'][t]),'recovery_slope':float(f['slope'][t]),'latest_block_stress':float(f['latest'][t]),'latest_below_level':bool(f['latest'][t]<f['stress'][t])} for t in rows]; return out
def positions(d,f,th):
 c=d.close.to_numpy(float); n=len(d); out={k:np.zeros(n-1) for k in ('candidate','b0','b1')}; cand=b0=b1=0.; rec=[]
 for t in range(W,n-1):
  b0=float(c[t]>c[t-W])
  if d.index[t].hour==0:
   base=bool(c[t]>c[t-W]); level=float(f['stress'][t]); slope=float(f['slope'][t]); latest=float(f['latest'][t]); state=bool(level>th and slope<0 and latest<level); before=cand
   if cand and not base: cand=0.
   elif not cand and base and state: cand=1.
   b1=float(base); rec.append({'t':t,'base_positive':base,'recovery_state':state})
  j=t+1
  if j<n-1: out['candidate'][j]=cand; out['b0'][j]=b0; out['b1'][j]=b1
 if np.any(out['candidate']-out['b1']>1e-15): raise ValueError('candidate must be subset of B1')
 for k in ('candidate','b1'):
  z=np.flatnonzero(np.r_[out[k][0]!=0,np.diff(out[k])!=0])
  if any(i<=0 or d.index[int(i)-1].hour!=0 for i in z): raise ValueError(f'{k} timing')
 return out,rec
def pack(d,p):
 o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; gross=p*market; fees=FEE*turn; net=gross-fees
 if not np.array_equal(net,p*market-FEE*turn): raise ValueError('fee identity')
 return {'market':market,'turn':turn,'fees':fees,'net':net}
def shp(x):
 s=float(np.std(x,ddof=1)); return None if s<=0 else float(math.sqrt(ANN)*np.mean(x)/s)
def metric(a,p,sp):
 s,e=sp; n=a['net'][s:e]; x=p[s:e]; wealth=np.cumprod(1+n); path=np.r_[1.,wealth]; turn=float(a['turn'][s:e].sum()); prev=np.r_[p[s-1] if s else 0.,x[:-1]]; ex=n[x>0]; neg=(ex<0).astype(int); longest=cur=0
 for v in neg: cur=cur+1 if v else 0; longest=max(longest,cur)
 return {'net_return':float(wealth[-1]-1),'arithmetic_net_return':float(n.sum()),'sharpe':shp(n),'max_drawdown':float(np.min(path/np.maximum.accumulate(path)-1)),'turnover':turn,'exposure_change_count':int((np.abs(x-prev)>1e-15).sum()),'fees':float(a['fees'][s:e].sum()),'edge_per_turnover_bps':float(n.sum()/turn*1e4) if turn else None,'mean_exposure':float(x.mean()),'exposed_hours':int((x>0).sum()),'loss_hour_rate_when_exposed':float(np.mean(ex<0)) if len(ex) else None,'longest_exposed_loss_cluster_hours':int(longest)}
def breadth(n,t):
 f=[float(np.prod(1+n[OOS[0]+k*FOLD:OOS[0]+(k+1)*FOLD])-1) for k in range(12)]; pos=[x for x in f if x>0]; yrs=t[:-1].year; y={}
 for yr in sorted(set(yrs[OOS[0]:OOS[1]])):
  z=yrs[OOS[0]:OOS[1]]==yr; y[str(yr)]=float(np.prod(1+n[OOS[0]:OOS[1]][z])-1)
 return {'fold_returns':f,'profitable_folds':sum(x>0 for x in f),'year_returns':y,'profitable_years':sum(x>0 for x in y.values()),'positive_fold_concentration':max(pos)/sum(pos) if pos else None}
def boot(c,b):
 c=c[OOS[0]:OOS[1]]; b=b[OOS[0]:OOS[1]]; n=len(c); rng=np.random.default_rng(SEED); md=np.empty(5000); sd=np.empty(5000); off=np.arange(168); blocks=math.ceil(n/168)
 for q in range(0,5000,100):
  e=q+100; st=rng.integers(0,n-167,size=(100,blocks)); ix=(st[:,:,None]+off).reshape(100,-1)[:,:n]; cs=c[ix]; bs=b[ix]; cm=cs.mean(1); bm=bs.mean(1); cstd=cs.std(1,ddof=1); bstd=bs.std(1,ddof=1); md[q:e]=ANN*(cm-bm); sd[q:e]=np.divide(math.sqrt(ANN)*cm,cstd,out=np.zeros(100),where=cstd>0)-np.divide(math.sqrt(ANN)*bm,bstd,out=np.zeros(100),where=bstd>0)
 return {'annualized_mean_delta':{'point':float(ANN*np.mean(c-b)),'lower_95':float(np.quantile(md,.025)),'upper_95':float(np.quantile(md,.975))},'sharpe_delta':{'point':float((shp(c) or 0)-(shp(b) or 0)),'lower_95':float(np.quantile(sd,.025)),'upper_95':float(np.quantile(sd,.975))},'block_hours':168,'resamples':5000,'seed':SEED}
def seldiag(rec,pos,a):
 s,e=OOS; c=pos['candidate'][s:e]; b=pos['b1'][s:e]; m=a['candidate']['market'][s:e]; om=b>c+1e-15; extra=c>b+1e-15
 if extra.any(): raise ValueError('candidate-only exposure')
 save=float(a['b1']['fees'][s:e].sum()-a['candidate']['fees'][s:e].sum()); omitted=float(m[om].sum()); obs=float(a['candidate']['net'][s:e].sum()-a['b1']['net'][s:e].sum()); recon=-omitted+save
 if not math.isclose(obs,recon,abs_tol=1e-12): raise ValueError('decomposition')
 regimes=[]; i=s
 while i<e:
  if pos['b1'][i]<=0: i+=1; continue
  st=i
  while i<e and pos['b1'][i]>0: i+=1
  en=i; hit=np.flatnonzero(pos['candidate'][st:en]>0); delay=int(hit[0]) if len(hit) else None; regimes.append({'entered':len(hit)>0,'delay':delay,'market':float(m[st-s:en-s].sum())})
 cn=a['candidate']['net'][s:e]; bn=a['b1']['net'][s:e]; improved=sum(float(cn[k*FOLD:(k+1)*FOLD].sum()-bn[k*FOLD:(k+1)*FOLD].sum())>0 for k in range(12)); entered=[r for r in regimes if r['entered']]; positive=[r for r in rec if s<=r['t']<e and r['base_positive']]
 return {'oos_exposure_decomposition':{'candidate_only_hours':int(extra.sum()),'b1_only_hours':int(om.sum()),'b1_only_market_arithmetic_return':omitted,'fee_saving_vs_b1':save,'observed_candidate_minus_b1_arithmetic_net':obs,'reconstructed_candidate_minus_b1_arithmetic_net':recon,'identity_passes':True},'oos_positive_base_feature':{'positive_base_decisions':len(positive),'recovery_state_rate':float(np.mean([r['recovery_state'] for r in positive]))},'oos_regimes':{'b1_positive_regimes':len(regimes),'candidate_entered_regimes':len(entered),'never_entered_regimes':len(regimes)-len(entered),'entry_delay_hours':[r['delay'] for r in entered],'median_entry_delay_hours':float(np.median([r['delay'] for r in entered])) if entered else None,'entered_regime_market_arithmetic_return':float(sum(r['market'] for r in entered)),'entered_profitable_regimes':sum(r['market']>0 for r in entered),'entered_omitted_prefix_market_return':0.,'never_entered_regime_market_arithmetic_return':float(sum(r['market'] for r in regimes if not r['entered'])),'never_entered_profitable_regimes':sum(r['market']>0 for r in regimes if not r['entered']),'selector_effect_folds':sum(np.any(om[k*FOLD:(k+1)*FOLD]) for k in range(12)),'improved_arithmetic_net_folds_vs_b1':improved}}
def checks(r):
 c=r['metrics']['development_oos']['candidate']; b=r['metrics']['development_oos']['b1']; f=r['metrics']['full_scored']['candidate']; br=r['breadth']; u=r['uncertainty']; rs=r['residual_sharpe']['vs_b1']; con=br['positive_fold_concentration']; cs=c['sharpe']; ce=c['edge_per_turnover_bps']
 return {'positive_oos_net':c['net_return']>0,'positive_oos_sharpe':cs is not None and cs>0,'net_at_least_b1':c['net_return']>=b['net_return'],'sharpe_at_least_b1':cs is not None and b['sharpe'] is not None and cs>=b['sharpe'],'drawdown_no_worse_b1':c['max_drawdown']>=b['max_drawdown'],'turnover_no_greater_b1':c['turnover']<=b['turnover'],'edge_per_turnover_at_least_b1':ce is not None and b['edge_per_turnover_bps'] is not None and ce>=b['edge_per_turnover_bps'],'profitable_folds_at_least_7':br['profitable_folds']>=7,'profitable_years_at_least_3':br['profitable_years']>=3,'positive_residual_sharpe_b1':rs is not None and rs>0,'mean_delta_lower_95_positive':u['annualized_mean_delta']['lower_95']>0,'sharpe_delta_lower_95_positive':u['sharpe_delta']['lower_95']>0,'positive_fold_concentration_at_most_half':con is not None and con<=.5,'positive_full_scored_net':f['net_return']>0}
def run(d,m,f,th,fd):
 pos,rec=positions(d,f,th); a={k:pack(d,v) for k,v in pos.items()}; spans={'training':TRAIN,'development_oos':OOS,'full_scored':FULL}; mets={lab:{k:metric(a[k],pos[k],sp) for k in a} for lab,sp in spans.items()}; co=a['candidate']['net'][OOS[0]:OOS[1]]; b0=a['b0']['net'][OOS[0]:OOS[1]]; b1=a['b1']['net'][OOS[0]:OOS[1]]; r={'source':{'artifact_id':ART[m],'csv_sha256':HASH[m],'observations_in_source':43941,'parsed_prefix_bars':N,'start_timestamp':d.index[0].isoformat(),'parsed_end_timestamp':d.index[-1].isoformat()},'exogenous_source':{'market':'BTC-USDT','artifact_id':ART['BTC-USDT'],'csv_sha256':HASH['BTC-USDT'],'lagged_only':True},'feature_definition':{'hourly_stress':'abs(log(close_t/close_t-1))/(1+quote_volume_t)','window_hours':SW,'blocks':BC,'block_hours':BH,'stress_level':'median of seven 24H block medians','recovery_slope':'Sen median pairwise slope of log(block_median+1e-30) vs block index','recovery_state':'stress>S50 and recovery_slope<0 and latest_block_stress<stress'},'common_btc_feature_diagnostics':fd,'metrics':mets,'breadth':breadth(a['candidate']['net'],d.index),'residual_sharpe':{'vs_b0':shp(co-b0),'vs_b1':shp(co-b1)},'uncertainty':boot(a['candidate']['net'],a['b1']['net']),'selector_diagnostics':seldiag(rec,pos,a)}; r['acceptance_checks']=checks(r); r['market_accepts']=all(r['acceptance_checks'].values()); return r
def compact(r):
 fields=('net_return','arithmetic_net_return','sharpe','max_drawdown','turnover','fees','edge_per_turnover_bps','mean_exposure','exposure_change_count','exposed_hours','loss_hour_rate_when_exposed','longest_exposed_loss_cluster_hours'); slim=lambda z:{k:z[k] for k in fields}
 return {'source':r['source'],'exogenous_source':r['exogenous_source'],'feature_definition':r['feature_definition'],'common_btc_feature_diagnostics':r['common_btc_feature_diagnostics'],'metrics':{'training':{k:slim(r['metrics']['training'][k]) for k in ('candidate','b1')},'development_oos':{k:slim(r['metrics']['development_oos'][k]) for k in ('candidate','b0','b1')},'full_scored':{k:slim(r['metrics']['full_scored'][k]) for k in ('candidate','b1')}},'breadth':r['breadth'],'residual_sharpe':r['residual_sharpe'],'uncertainty':r['uncertainty'],'selector_diagnostics':r['selector_diagnostics'],'acceptance_checks':r['acceptance_checks'],'market_accepts':r['market_accepts']}
def main():
 p=argparse.ArgumentParser(); p.add_argument('--btc-csv',type=Path,required=True); p.add_argument('--eth-csv',type=Path,required=True); p.add_argument('--output',type=Path,required=True); x=p.parse_args(); btc=load(x.btc_csv,'BTC-USDT'); eth=load(x.eth_csv,'ETH-USDT')
 if not btc.index.equals(eth.index): raise ValueError('timestamp grids differ')
 f=features(btc); th,cal=calibrate(btc,f); fd=featdiag(btc,f,th); sd=scalediag(btc,f,th); full={'BTC-USDT':run(btc,'BTC-USDT',f,th,fd),'ETH-USDT':run(eth,'ETH-USDT',f,th,fd)}; ok=all(v['market_accepts'] for v in full.values()); out={'family_id':'lagged-btc-liquidity-stress-recovery-entry-1h-v1','issue':ISSUE,'candidate_count':1,'parameter_grid_count':0,'bar':'1H','canonical_fee_one_way':FEE,'research_parent':'5a0fcc97d1a882f8223656c51f5bb8055f534e38','sample':{'warmup':[0,2880],'training':list(TRAIN),'development_oos':list(OOS),'full_scored':list(FULL),'parsed_prefix_bars':N,'later_suffix_unread':True},'common_btc_training_calibration':cal,'common_btc_stress_scale_diagnostics':sd,'markets':{m:compact(v) for m,v in full.items()},'verdict':'nominate_lagged_btc_liquidity_stress_recovery_entry_for_g1' if ok else 'reject_exact_lagged_btc_liquidity_stress_recovery_entry_family','paper_or_live_authorized':False,'repaired_discrepancy':'The first complete execution exposed a fail-closed scorecard defect: an inactive candidate has undefined Sharpe and edge per turnover, but the acceptance comparator attempted numeric ordering and raised TypeError. The gates were repaired to treat undefined candidate statistics as failed, and the complete frozen experiment was rerun. No feature, threshold, position, fee, return, benchmark, uncertainty specification, or economic verdict changed.'}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(out,sort_keys=True,separators=(',',':'),default=lambda o:o.item() if isinstance(o,np.generic) else str(o))+'\n')
if __name__=='__main__': main()
