# ruff: noqa
# fmt: off
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
FEE=.0005; ANN=8760.; W=2160; VH=720; VS=math.sqrt(3.); BAND=.10; N=43441; FOLD=2160; TRAIN=(2880,17520); OOS=(17520,43440); FULL=(2880,43440); SEED=20260730; ISSUE=664
HASH={'BTC-USDT':'92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9','ETH-USDT':'2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726'}; ART={'BTC-USDT':8704977298,'ETH-USDT':8704978112}
def load(p,m):
 raw=p.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=HASH[m]: raise ValueError(f'{m} hash mismatch')
 d=pd.read_csv(p,nrows=N); t=pd.DatetimeIndex(pd.to_datetime(d.timestamp,utc=True)); x=d[['open','high','low','close','volume_quote']].to_numpy(float)
 ok=len(d)==N and t.equals(pd.date_range(t[0],periods=len(t),freq='1h',tz='UTC')) and t.is_unique and (d.confirm==1).all() and np.isfinite(x).all() and (x[:,:4]>0).all() and (x[:,4]>=0).all() and (d.high>=d.low).all()
 if not ok: raise ValueError(f'{m} source validation failed')
 d.index=t; return d
def features(d):
 c=d.close.to_numpy(float); n=len(d); r=np.zeros(n); r[1:]=np.diff(np.log(c)); sq=r*r; cs=np.r_[0.,np.cumsum(sq)]; rv=np.full(n,np.nan); idx=np.arange(VH,n); rv[idx]=np.sqrt(cs[idx+1]-cs[idx+1-VH]); margin=np.full(n,np.nan); margin[W:]=np.log(c[W:]/c[:-W]); scaled=VS*rv; raw=np.zeros(n); valid=(margin>0)&np.isfinite(scaled)&(scaled>0); raw[valid]=np.clip(margin[valid]/scaled[valid],0.,1.)
 return {'returns':r,'rv720':rv,'scaled_2160_vol':scaled,'slow_margin':margin,'raw_target':raw}
def positions(d,f):
 n=len(d); out={k:np.zeros(n-1) for k in ('candidate','b0','b1')}; cand=b0=b1=0.; rec=[]
 for t in range(W,n-1):
  base=bool(f['slow_margin'][t]>0); b0=float(base)
  if d.index[t].hour==0:
   prev=cand; raw=float(f['raw_target'][t]); accepted=False; suppressed=False; reason='none'
   if not base:
    cand=0.; accepted=abs(prev)>0; reason='immediate_base_exit' if accepted else 'cash_base_nonpositive'
   elif abs(raw-prev)>=BAND:
    cand=raw; accepted=True; reason='band_update'
   else:
    suppressed=abs(raw-prev)>0; reason='band_suppressed' if suppressed else 'unchanged'
   b1=float(base); rec.append({'t':t,'timestamp':d.index[t].isoformat(),'base_positive':base,'margin':float(f['slow_margin'][t]),'rv720':float(f['rv720'][t]),'scaled_2160_vol':float(f['scaled_2160_vol'][t]),'raw_target':raw,'previous_target':float(prev),'target':float(cand),'accepted':accepted,'suppressed':suppressed,'reason':reason,'intended_delta':float(abs(raw-prev))})
  j=t+1
  if j<n-1: out['candidate'][j]=cand; out['b0'][j]=b0; out['b1'][j]=b1
 if np.any(out['candidate']<-1e-15) or np.any(out['candidate']>1+1e-15): raise ValueError('candidate bounds')
 if np.any(out['candidate']-out['b1']>1e-15): raise ValueError('candidate must not exceed B1')
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
 return {'net_return':float(wealth[-1]-1),'arithmetic_net_return':float(n.sum()),'sharpe':shp(n),'max_drawdown':float(np.min(path/np.maximum.accumulate(path)-1)),'turnover':turn,'exposure_change_count':int((np.abs(x-prev)>1e-15).sum()),'fees':float(a['fees'][s:e].sum()),'edge_per_turnover_bps':float(n.sum()/turn*1e4) if turn else None,'mean_exposure':float(x.mean()),'exposed_hours':int((x>0).sum()),'loss_hour_rate_when_exposed':float(np.mean(ex<0)) if len(ex) else None,'longest_exposed_loss_cluster_hours':int(longest),'exposure_quantiles':{str(q):float(np.quantile(x,q)) for q in (0,.1,.25,.5,.75,.9,1)}}
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
def decision_diag(rec,sp):
 rr=[r for r in rec if sp[0]<=r['t']<sp[1]]; raw=np.array([r['raw_target'] for r in rr]); tar=np.array([r['target'] for r in rr]); acc=[r for r in rr if r['accepted']]; sup=[r for r in rr if r['suppressed']]
 return {'daily_decisions':len(rr),'positive_base_decisions':sum(r['base_positive'] for r in rr),'raw_target_quantiles':{str(q):float(np.quantile(raw,q)) for q in (0,.1,.25,.5,.75,.9,1)},'banded_target_quantiles':{str(q):float(np.quantile(tar,q)) for q in (0,.1,.25,.5,.75,.9,1)},'mean_raw_target':float(raw.mean()),'mean_banded_target':float(tar.mean()),'accepted_changes':len(acc),'accepted_absolute_target_change':float(sum(abs(r['target']-r['previous_target']) for r in acc)),'suppressed_changes':len(sup),'suppressed_intended_absolute_change':float(sum(r['intended_delta'] for r in sup)),'suppressed_median_intended_change':float(np.median([r['intended_delta'] for r in sup])) if sup else None,'immediate_base_exits':sum(r['reason']=='immediate_base_exit' for r in rr),'band_updates':sum(r['reason']=='band_update' for r in rr)}
def bucket_diag(pos,a):
 s,e=OOS; p=pos['candidate'][s:e]; n=a['candidate']['net'][s:e]; m=a['candidate']['market'][s:e]; fees=a['candidate']['fees'][s:e]; bins=[('zero',p==0),('[0,0.25)',(p>0)&(p<.25)),('[0.25,0.50)',(p>=.25)&(p<.5)),('[0.50,0.75)',(p>=.5)&(p<.75)),('[0.75,1)',(p>=.75)&(p<1)),('one',p==1)]
 return {lab:{'hours':int(z.sum()),'mean_exposure':float(p[z].mean()) if z.any() else None,'market_arithmetic_return':float((p[z]*m[z]).sum()),'fees':float(fees[z].sum()),'net_arithmetic_return':float(n[z].sum())} for lab,z in bins}
def transition_diag(rec,sp):
 rr=[r for r in rec if sp[0]<=r['t']<sp[1] and r['accepted']]; out={}
 for lab,test in (('increase',lambda r:r['target']>r['previous_target']),('decrease',lambda r:r['target']<r['previous_target']),('band_update',lambda r:r['reason']=='band_update'),('immediate_base_exit',lambda r:r['reason']=='immediate_base_exit')):
  z=[r for r in rr if test(r)]; turn=float(sum(abs(r['target']-r['previous_target']) for r in z)); out[lab]={'count':len(z),'turnover':turn,'fees':FEE*turn,'median_change':float(np.median([abs(r['target']-r['previous_target']) for r in z])) if z else None}
 if not math.isclose(out['increase']['turnover']+out['decrease']['turnover'],out['band_update']['turnover']+out['immediate_base_exit']['turnover'],abs_tol=1e-12): raise ValueError('transition turnover attribution')
 return out
def selector_diag(rec,pos,a):
 s,e=OOS; c=pos['candidate'][s:e]; b=pos['b1'][s:e]; m=a['candidate']['market'][s:e]; more=c>b+1e-15; less=b>c+1e-15; cand_mkt=float((c*m).sum()); b1_mkt=float((b*m).sum()); fee_delta=float(a['candidate']['fees'][s:e].sum()-a['b1']['fees'][s:e].sum()); obs=float(a['candidate']['net'][s:e].sum()-a['b1']['net'][s:e].sum()); exposure_delta_market=float(((c-b)*m).sum()); recon=exposure_delta_market-fee_delta
 if not math.isclose(obs,recon,abs_tol=1e-12): raise ValueError('decomposition')
 cn=a['candidate']['net'][s:e]; bn=a['b1']['net'][s:e]; trans=transition_diag(rec,OOS)
 if not math.isclose(trans['increase']['turnover']+trans['decrease']['turnover'],a['candidate']['turn'][s:e].sum(),abs_tol=1e-12): raise ValueError('transition turnover reconstruction')
 return {'oos_exposure_decomposition':{'candidate_more_hours':int(more.sum()),'candidate_more_exposure_hours':float(np.maximum(c-b,0).sum()),'candidate_less_hours':int(less.sum()),'candidate_less_exposure_hours':float(np.maximum(b-c,0).sum()),'candidate_market_arithmetic_return':cand_mkt,'b1_market_arithmetic_return':b1_mkt,'exposure_delta_market_arithmetic_return':exposure_delta_market,'candidate_fees':float(a['candidate']['fees'][s:e].sum()),'b1_fees':float(a['b1']['fees'][s:e].sum()),'incremental_fees_candidate_minus_b1':fee_delta,'observed_candidate_minus_b1_arithmetic_net':obs,'reconstructed_candidate_minus_b1_arithmetic_net':recon,'identity_passes':True},'target_decisions':{'training':decision_diag(rec,TRAIN),'development_oos':decision_diag(rec,OOS),'full_scored':decision_diag(rec,FULL)},'oos_transition_attribution':trans,'oos_exposure_buckets':bucket_diag(pos,a),'improved_arithmetic_net_folds_vs_b1':sum(float(cn[k*FOLD:(k+1)*FOLD].sum()-bn[k*FOLD:(k+1)*FOLD].sum())>0 for k in range(12))}
def checks(r):
 c=r['metrics']['development_oos']['candidate']; b=r['metrics']['development_oos']['b1']; f=r['metrics']['full_scored']['candidate']; br=r['breadth']; u=r['uncertainty']; rs=r['residual_sharpe']['vs_b1']; con=br['positive_fold_concentration']; cs=c['sharpe']; ce=c['edge_per_turnover_bps']
 return {'positive_oos_net':c['net_return']>0,'positive_oos_sharpe':cs is not None and cs>0,'net_at_least_b1':c['net_return']>=b['net_return'],'sharpe_at_least_b1':cs is not None and b['sharpe'] is not None and cs>=b['sharpe'],'drawdown_no_worse_b1':c['max_drawdown']>=b['max_drawdown'],'turnover_no_greater_b1':c['turnover']<=b['turnover'],'edge_per_turnover_at_least_b1':ce is not None and b['edge_per_turnover_bps'] is not None and ce>=b['edge_per_turnover_bps'],'profitable_folds_at_least_7':br['profitable_folds']>=7,'profitable_years_at_least_3':br['profitable_years']>=3,'positive_residual_sharpe_b1':rs is not None and rs>0,'mean_delta_lower_95_positive':u['annualized_mean_delta']['lower_95']>0,'sharpe_delta_lower_95_positive':u['sharpe_delta']['lower_95']>0,'positive_fold_concentration_at_most_half':con is not None and con<=.5,'positive_full_scored_net':f['net_return']>0}
def run(d,m):
 f=features(d); pos,rec=positions(d,f); a={k:pack(d,v) for k,v in pos.items()}; spans={'training':TRAIN,'development_oos':OOS,'full_scored':FULL}; mets={lab:{k:metric(a[k],pos[k],sp) for k in a} for lab,sp in spans.items()}; co=a['candidate']['net'][OOS[0]:OOS[1]]; b0=a['b0']['net'][OOS[0]:OOS[1]]; b1=a['b1']['net'][OOS[0]:OOS[1]]; r={'source':{'artifact_id':ART[m],'csv_sha256':HASH[m],'observations_in_source':43941,'parsed_prefix_bars':N,'start_timestamp':d.index[0].isoformat(),'parsed_end_timestamp':d.index[-1].isoformat()},'feature_definition':{'slow_margin':'log(close_t/close_(t-2160))','rv720':'sqrt(sum of squared 720 completed hourly log returns ending at t)','scaled_2160_vol':'sqrt(3)*rv720','raw_target':'clip(max(slow_margin,0)/scaled_2160_vol,0,1)','no_trade_band':BAND,'exit_priority':'immediate zero whenever slow_margin<=0'},'metrics':mets,'breadth':breadth(a['candidate']['net'],d.index),'residual_sharpe':{'vs_b0':shp(co-b0),'vs_b1':shp(co-b1)},'uncertainty':boot(a['candidate']['net'],a['b1']['net']),'selector_diagnostics':selector_diag(rec,pos,a)}; r['acceptance_checks']=checks(r); r['market_accepts']=all(r['acceptance_checks'].values()); return r
def compact(r): return r
def main():
 p=argparse.ArgumentParser(); p.add_argument('--btc-csv',type=Path,required=True); p.add_argument('--eth-csv',type=Path,required=True); p.add_argument('--output',type=Path,required=True); x=p.parse_args(); btc=load(x.btc_csv,'BTC-USDT'); eth=load(x.eth_csv,'ETH-USDT')
 if not btc.index.equals(eth.index): raise ValueError('timestamp grids differ')
 full={'BTC-USDT':run(btc,'BTC-USDT'),'ETH-USDT':run(eth,'ETH-USDT')}; ok=all(v['market_accepts'] for v in full.values()); out={'family_id':'slow-trend-drawdown-budget-sizing-1h-v1','issue':ISSUE,'candidate_count':1,'parameter_grid_count':0,'bar':'1H','canonical_fee_one_way':FEE,'research_parent':'5a0fcc97d1a882f8223656c51f5bb8055f534e38','sample':{'warmup':[0,2880],'training':list(TRAIN),'development_oos':list(OOS),'full_scored':list(FULL),'parsed_prefix_bars':N,'later_suffix_unread':True},'markets':{m:compact(v) for m,v in full.items()},'verdict':'nominate_slow_trend_drawdown_budget_sizing_for_g1' if ok else 'reject_exact_slow_trend_drawdown_budget_sizing_family','paper_or_live_authorized':False,'repaired_discrepancy':'The initial diagnostic attributed fees only to resulting exposure buckets. The terminal reproducer adds exact OOS transition attribution by increase/decrease and by band_update versus immediate_base_exit, and asserts exact turnover reconstruction. No signal, target, position, fee, performance metric, bootstrap result, acceptance gate, or verdict changed.'}; x.output.parent.mkdir(parents=True,exist_ok=True); x.output.write_text(json.dumps(out,sort_keys=True,separators=(',',':'),default=lambda o:o.item() if isinstance(o,np.generic) else str(o))+'\n')
if __name__=='__main__': main()
