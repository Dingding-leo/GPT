# ruff: noqa
# fmt: off
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
FEE=.0005; ANN=8760.; W=2160; VH=168; MINAGE=24; MAXAGE=168; K=3.; WICK=.5; SUPPORT=20; N=43441; FOLD=2160; TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); SEED=20260730; ISSUE=661
HASH={'BTC-USDT':'92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9','ETH-USDT':'2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726'}; ART={'BTC-USDT':8704977298,'ETH-USDT':8704978112}
def load(p,m):
 raw=p.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=HASH[m]: raise ValueError(f'{m} hash mismatch')
 d=pd.read_csv(p,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[['open','high','low','close','volume_quote']].to_numpy(float)
 ok=len(d)==N and t.equals(pd.date_range(t[0],periods=len(t),freq='1h',tz='UTC')) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all() and (d.high>=d.low).all()
 if not ok: raise ValueError(f'{m} source validation failed')
 d.index=t; return d
def feat(b):
 o=b.open.to_numpy(float); h=b.high.to_numpy(float); l=b.low.to_numpy(float); c=b.close.to_numpy(float); n=len(b); r=np.zeros(n); r[1:]=np.diff(np.log(c)); s=np.full(n,np.nan)
 for u in range(VH+1,n):
  x=r[u-VH:u]; md=np.median(x); s[u]=1.4826*np.median(np.abs(x-md))
 wick=np.divide(np.minimum(o,c)-l,h-l,out=np.zeros(n),where=h>l); shock=(s>0)&(r<=-K*s); absorb=shock&(wick>=WICK); ai=np.flatnonzero(absorb); state=np.zeros(n,bool); ei=np.full(n,-1,int); age=np.full(n,-1,int); found=np.zeros(n,bool); pos=np.zeros(n,bool); nll=np.zeros(n,bool)
 for t in range(n):
  if b.index[t].hour: continue
  z=ai[(ai>=t-MAXAGE)&(ai<=t-MINAGE)]
  if not len(z): continue
  u=int(z[-1]); found[t]=True; ei[t]=u; age[t]=t-u; pos[t]=np.log(c[t]/c[u])>0; nll[t]=np.min(l[u+1:t+1])>=l[u]; state[t]=pos[t] and nll[t]
 return {'shock':shock,'absorb':absorb,'state':state,'event':ei,'age':age,'found':found,'positive':pos,'no_lower_low':nll}
def rows(b,sp): return [t for t in range(*sp) if b.index[t].hour==0]
def calibrate(b,f):
 rr=rows(b,TRAIN); support=int(np.sum(f['state'][rr])); return {'eligible_daily_training_decisions':len(rr),'absorption_state_support':support,'minimum_support_required':SUPPORT,'selector_enabled':support>=SUPPORT,'support_uses_target_performance':False}
def fdiag(b,f,en):
 out={'selector_enabled':en}
 for lab,sp in (('training',TRAIN),('development_oos',OOS)):
  s,e=sp; rr=rows(b,sp); sh=np.flatnonzero(f['shock'][s:e])+s; ab=np.flatnonzero(f['absorb'][s:e])+s; ev=f['event'][rr]; allu=sorted({int(x) for x in ev if x>=0}); sr=[t for t in rr if f['state'][t]]; cnt={}
  for t in sr: cnt[int(f['event'][t])]=cnt.get(int(f['event'][t]),0)+1
  out[lab]={'daily_decisions':len(rr),'robust_shock_hours':len(sh),'absorptive_shock_hours':len(ab),'absorptive_share_of_robust_shocks':len(ab)/len(sh) if len(sh) else None,'daily_decisions_with_eligible_absorptive_event':int(np.sum(f['found'][rr])),'daily_decisions_with_positive_response':int(np.sum(f['positive'][rr])),'daily_decisions_with_no_lower_low':int(np.sum(f['no_lower_low'][rr])),'absorption_state_decisions':len(sr),'absorption_state_rate':len(sr)/len(rr),'unique_absorptive_events_referenced':len(allu),'unique_absorptive_events_supporting_state':len(cnt),'largest_state_event_decision_count':max(cnt.values()) if cnt else 0,'largest_state_event_decision_concentration':max(cnt.values())/len(sr) if sr else None,'median_state_event_age_hours':float(np.median([f['age'][t] for t in sr])) if sr else None}
 out['oos_minus_training_state_rate']=out['development_oos']['absorption_state_rate']-out['training']['absorption_state_rate']; out['oos_to_training_state_rate_ratio']=out['development_oos']['absorption_state_rate']/out['training']['absorption_state_rate'] if out['training']['absorption_state_rate'] else None; return out
def positions(d,f,en):
 c=d.close.to_numpy(float); n=len(d); out={k:np.zeros(n-1) for k in ('candidate','b0','b1')}; cand=b0=b1=0.; rec=[]
 for t in range(W,n-1):
  b0=float(c[t]>c[t-W])
  if d.index[t].hour==0:
   base=bool(c[t]>c[t-W]); st=bool(f['state'][t])
   if cand and not base: cand=0.
   elif not cand and en and base and st: cand=1.
   b1=float(base); rec.append({'t':t,'base_positive':base,'absorption_state':st})
  j=t+1
  if j<n-1: out['candidate'][j]=cand; out['b0'][j]=b0; out['b1'][j]=b1
 if np.any(out['candidate']-out['b1']>1e-15): raise ValueError('candidate must be subset of B1')
 for k in ('candidate','b1'):
  z=np.flatnonzero(np.r_[out[k][0]!=0,np.diff(out[k])!=0])
  if any(i<=0 or d.index[int(i)-1].hour!=0 for i in z): raise ValueError(f'{k} timing')
 return out,rec
def pack(d,p):
 o=d.open.to_numpy(float); market=o[1:]/o[:-1]-1; turn=np.r_[abs(p[0]),np.abs(np.diff(p))]; fees=FEE*turn; net=p*market-fees
 if not np.array_equal(net,p*market-FEE*turn): raise ValueError('fee identity')
 return {'market':market,'turn':turn,'fees':fees,'net':net}
def shp(x):
 s=float(np.std(x,ddof=1)); return None if s<=0 else float(math.sqrt(ANN)*np.mean(x)/s)
def metric(a,p,sp):
 s,e=sp; n=a['net'][s:e]; x=p[s:e]; wealth=np.cumprod(1+n); path=np.r_[1.,wealth]; turn=float(a['turn'][s:e].sum()); prev=np.r_[p[s-1] if s else 0.,x[:-1]]; ex=n[x>0]; longest=cur=0
 for v in ex<0: cur=cur+1 if v else 0; longest=max(longest,cur)
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
  en=i; hit=np.flatnonzero(pos['candidate'][st:en]>0); regimes.append({'entered':len(hit)>0,'delay':int(hit[0]) if len(hit) else None,'market':float(m[st-s:en-s].sum())})
 cn=a['candidate']['net'][s:e]; bn=a['b1']['net'][s:e]; improved=sum(float(cn[k*FOLD:(k+1)*FOLD].sum()-bn[k*FOLD:(k+1)*FOLD].sum())>0 for k in range(12)); entered=[r for r in regimes if r['entered']]; positive=[r for r in rec if s<=r['t']<e and r['base_positive']]
 return {'oos_exposure_decomposition':{'candidate_only_hours':int(extra.sum()),'b1_only_hours':int(om.sum()),'b1_only_market_arithmetic_return':omitted,'fee_saving_vs_b1':save,'observed_candidate_minus_b1_arithmetic_net':obs,'reconstructed_candidate_minus_b1_arithmetic_net':recon,'identity_passes':True},'oos_positive_base_feature':{'positive_base_decisions':len(positive),'absorption_state_rate':float(np.mean([r['absorption_state'] for r in positive]))},'oos_regimes':{'b1_positive_regimes':len(regimes),'candidate_entered_regimes':len(entered),'never_entered_regimes':len(regimes)-len(entered),'entry_delay_hours':[r['delay'] for r in entered],'median_entry_delay_hours':float(np.median([r['delay'] for r in entered])) if entered else None,'entered_regime_market_arithmetic_return':float(sum(r['market'] for r in entered)),'entered_profitable_regimes':sum(r['market']>0 for r in entered),'never_entered_regime_market_arithmetic_return':float(sum(r['market'] for r in regimes if not r['entered'])),'never_entered_profitable_regimes':sum(r['market']>0 for r in regimes if not r['entered']),'selector_effect_folds':sum(np.any(om[k*FOLD:(k+1)*FOLD]) for k in range(12)),'improved_arithmetic_net_folds_vs_b1':improved}}
def checks(r):
 c=r['metrics']['development_oos']['candidate']; b=r['metrics']['development_oos']['b1']; f=r['metrics']['full_scored']['candidate']; br=r['breadth']; u=r['uncertainty']; rs=r['residual_sharpe']['vs_b1']; con=br['positive_fold_concentration']; cs=c['sharpe']; ce=c['edge_per_turnover_bps']
 return {'positive_oos_net':c['net_return']>0,'positive_oos_sharpe':cs is not None and cs>0,'net_at_least_b1':c['net_return']>=b['net_return'],'sharpe_at_least_b1':cs is not None and b['sharpe'] is not None and cs>=b['sharpe'],'drawdown_no_worse_b1':c['max_drawdown']>=b['max_drawdown'],'turnover_no_greater_b1':c['turnover']<=b['turnover'],'edge_per_turnover_at_least_b1':ce is not None and b['edge_per_turnover_bps'] is not None and ce>=b['edge_per_turnover_bps'],'profitable_folds_at_least_7':br['profitable_folds']>=7,'profitable_years_at_least_3':br['profitable_years']>=3,'positive_residual_sharpe_b1':rs is not None and rs>0,'mean_delta_lower_95_positive':u['annualized_mean_delta']['lower_95']>0,'sharpe_delta_lower_95_positive':u['sharpe_delta']['lower_95']>0,'positive_fold_concentration_at_most_half':con is not None and con<=.5,'positive_full_scored_net':f['net_return']>0}
def run(d,m,f,cal,fd):
 pos,rec=positions(d,f,cal['selector_enabled']); a={k:pack(d,v) for k,v in pos.items()}; spans={'training':TRAIN,'development_oos':OOS,'full_scored':FULL}; mets={lab:{k:metric(a[k],pos[k],sp) for k in a} for lab,sp in spans.items()}; co=a['candidate']['net'][OOS[0]:OOS[1]]; b0=a['b0']['net'][OOS[0]:OOS[1]]; b1=a['b1']['net'][OOS[0]:OOS[1]]; r={'source':{'artifact_id':ART[m],'csv_sha256':HASH[m],'observations_in_source':43941,'parsed_prefix_bars':N,'start_timestamp':d.index[0].isoformat(),'parsed_end_timestamp':d.index[-1].isoformat()},'exogenous_source':{'market':'BTC-USDT','artifact_id':ART['BTC-USDT'],'csv_sha256':HASH['BTC-USDT'],'lagged_only':True},'feature_definition':{'volatility':'1.4826*MAD of preceding 168 completed BTC hourly log returns','robust_shock':'BTC hourly log return <= -3.0*preceding robust volatility','lower_wick':'(min(open,close)-low)/(high-low), zero for zero range','absorptive_shock':'robust_shock and lower_wick>=0.50','event_age_hours':[MINAGE,MAXAGE],'absorption_state':'most recent eligible absorptive shock, BTC close_t>shock close and no post-shock lower low','minimum_training_support':SUPPORT},'common_btc_training_calibration':cal,'common_btc_feature_diagnostics':fd,'metrics':mets,'breadth':breadth(a['candidate']['net'],d.index),'residual_sharpe':{'vs_b0':shp(co-b0),'vs_b1':shp(co-b1)},'uncertainty':boot(a['candidate']['net'],a['b1']['net']),'selector_diagnostics':seldiag(rec,pos,a)}; r['acceptance_checks']=checks(r); r['market_accepts']=all(r['acceptance_checks'].values()); return r
def compact(r):
 fields=('net_return','arithmetic_net_return','sharpe','max_drawdown','turnover','fees','edge_per_turnover_bps','mean_exposure','exposure_change_count','exposed_hours','loss_hour_rate_when_exposed','longest_exposed_loss_cluster_hours'); slim=lambda z:{k:z[k] for k in fields}
 return {'source':r['source'],'exogenous_source':r['exogenous_source'],'feature_definition':r['feature_definition'],'common_btc_training_calibration':r['common_btc_training_calibration'],'common_btc_feature_diagnostics':r['common_btc_feature_diagnostics'],'metrics':{'training':{k:slim(r['metrics']['training'][k]) for k in ('candidate','b1')},'development_oos':{k:slim(r['metrics']['development_oos'][k]) for k in ('candidate','b0','b1')},'full_scored':{k:slim(r['metrics']['full_scored'][k]) for k in ('candidate','b1')}},'breadth':r['breadth'],'residual_sharpe':r['residual_sharpe'],'uncertainty':r['uncertainty'],'selector_diagnostics':r['selector_diagnostics'],'acceptance_checks':r['acceptance_checks'],'market_accepts':r['market_accepts']}
def main():
 p=argparse.ArgumentParser(); p.add_argument('--btc-csv',type=Path,required=True); p.add_argument('--eth-csv',type=Path,required=True); p.add_argument('--output',type=Path,required=True); x=p.parse_args(); btc=load(x.btc_csv,'BTC-USDT'); eth=load(x.eth_csv,'ETH-USDT')
 if not btc.index.equals(eth.index): raise ValueError('timestamp grids differ')
 f=feat(btc); cal=calibrate(btc,f); fd=fdiag(btc,f,cal['selector_enabled']); full={'BTC-USDT':run(btc,'BTC-USDT',f,cal,fd),'ETH-USDT':run(eth,'ETH-USDT',f,cal,fd)}; ok=all(v['market_accepts'] for v in full.values()); out={'family_id':'lagged-btc-downside-shock-absorption-entry-1h-v1','issue':ISSUE,'candidate_count':1,'parameter_grid_count':0,'bar':'1H','canonical_fee_one_way':FEE,'research_parent':'5a0fcc97d1a882f8223656c51f5bb8055f534e38','sample':{'warmup':[0,2880],'training':list(TRAIN),'development_oos':list(OOS),'full_scored':list(FULL),'parsed_prefix_bars':N,'later_suffix_unread':True},'common_btc_training_calibration':cal,'common_btc_feature_diagnostics':fd,'markets':{m:compact(v) for m,v in full.items()},'verdict':'nominate_lagged_btc_downside_shock_absorption_entry_for_g1' if ok else 'reject_exact_lagged_btc_downside_shock_absorption_entry_family','paper_or_live_authorized':False,'repaired_discrepancy':"The initial diagnostic counted daily absorption-state decisions but did not distinguish repeated daily decisions generated by the same shock event. The terminal diagnostic now records unique state-supporting events and maximum event concentration. Training's six state decisions all came from one BTC shock. No feature, support rule, activation decision, position, return, fee, benchmark, uncertainty gate, or verdict changed."}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(out,sort_keys=True,separators=(',',':'),default=lambda o:o.item() if isinstance(o,np.generic) else str(o))+'\n')
if __name__=='__main__': main()
