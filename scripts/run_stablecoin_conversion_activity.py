from __future__ import annotations
import hashlib,json,math,os
from pathlib import Path
import numpy as np
import pandas as pd
from stablecoin_conversion_source import acquire,canon,sha,TRAIN_END

FAMILY='causal-lagged-stablecoin-conversion-activity-opportunity-1h-v1'
REJECT='reject_causal_lagged_stablecoin_conversion_activity_opportunity_information_premise_1h_v1'
SOURCE_REJECT='reject_causal_lagged_stablecoin_conversion_activity_source_contract_1h_v1'
SUPPORT='support_causal_lagged_stablecoin_conversion_activity_for_separate_candidate_predeclaration_1h_v1'
TARGETS=('BTCUSDT','ETHUSDT'); EXOG='USDCUSDT'; TRAIN_START=2208; OOS_START=10800; OOS_END=23760; SOURCE_END=24144
DRAWS=5000; BLOCK=7; SEEDS={'BTCUSDT':202608092101,'ETHUSDT':202608092102}; OUT=Path('reports/research/stablecoin-conversion-activity-1h-v1')

def rho(x,y):
 a=pd.Series(x).rank(method='average').to_numpy(float); b=pd.Series(y).rank(method='average').to_numpy(float)
 return float(np.corrcoef(a,b)[0,1]) if np.std(a)>0 and np.std(b)>0 else float('nan')
def slope(x,y):
 z=(x-np.mean(x))/np.std(x); return float(np.dot(z-np.mean(z),y-np.mean(y))/np.dot(z-np.mean(z),z-np.mean(z)))
def terc(x,y):
 o=np.argsort(x,kind='mergesort'); k=len(o)//3; return float(np.mean(y[o[-k:]])-np.mean(y[o[:k]])),k
def triple(x,y):
 t,k=terc(x,y); return {'rho':rho(x,y),'slope':slope(x,y),'tercile':t,'outer_count':int(k)}
def mbb(x,n,a,seed):
 rng=np.random.default_rng(seed); starts=np.arange(0,len(x)-BLOCK+1); need=math.ceil(len(x)/BLOCK); d={k:[] for k in ('net_rho','net_slope','adverse_rho','adverse_slope')}
 for _ in range(DRAWS):
  idx=np.concatenate([np.arange(s,s+BLOCK) for s in rng.choice(starts,size=need,replace=True)])[:len(x)]
  xx,nn,aa=x[idx],n[idx],a[idx]; d['net_rho'].append(rho(xx,nn)); d['net_slope'].append(slope(xx,nn)); d['adverse_rho'].append(rho(xx,aa)); d['adverse_slope'].append(slope(xx,aa))
 return {k:[float(np.quantile(v,.025)),float(np.quantile(v,.975))] for k,v in d.items()}
def opportunities(target,exo):
 c=target.close.to_numpy(float); o=target.open.to_numpy(float); v=exo.quote_volume.to_numpy(float); rows=[]
 for t in range(TRAIN_START,TRAIN_END,24):
  if t+25>=TRAIN_END or c[t-25]<=c[t-2185]: continue
  recent=v[t-192:t-24]; base=v[t-912:t-192]
  if len(recent)!=168 or len(base)!=720 or np.mean(recent)<=0 or np.mean(base)<=0: continue
  f=float(np.log(np.mean(recent)/np.mean(base))); entry=o[t]; net=float(o[t+24]/entry-1-.001); adv=float(np.min(o[t:t+25]/entry-1)); de=o[t+1]; dnet=float(o[t+25]/de-1-.001); dadv=float(np.min(o[t+1:t+26]/de-1))
  rows.append({'t':t,'timestamp':str(target.index[t]),'feature':f,'margin':float(c[t-25]/c[t-2185]-1),'net':net,'adverse':adv,'delay_net':dnet,'delay_adverse':dadv})
 return pd.DataFrame(rows)
def eval_target(symbol,target,exo):
 f=opportunities(target,exo); x=f.feature.to_numpy(float); n=f.net.to_numpy(float); a=f.adverse.to_numpy(float); dn=f.delay_net.to_numpy(float); da=f.delay_adverse.to_numpy(float)
 point={'net':triple(x,n),'adverse':triple(x,a)}; delay={'net':triple(x,dn),'adverse':triple(x,da)}; boot=mbb(x,n,a,SEEDS[symbol]); folds=[]
 for i,idx in enumerate(np.array_split(np.arange(len(f)),4),1):
  q=f.iloc[idx]; folds.append({'fold':i,'rows':len(q),'net_slope':slope(q.feature.to_numpy(float),q.net.to_numpy(float)),'adverse_slope':slope(q.feature.to_numpy(float),q.adverse.to_numpy(float))})
 negnet=[abs(z['net_slope']) for z in folds if z['net_slope']<0]; concentration=max(negnet)/sum(negnet) if negnet else None; med=float(f.margin.median()); strata={}
 for name,mask in {'lower_or_equal':f.margin<=med,'upper':f.margin>med}.items():
  q=f.loc[mask]; strata[name]={'rows':len(q),'net_tercile':terc(q.feature.to_numpy(float),q.net.to_numpy(float))[0],'adverse_tercile':terc(q.feature.to_numpy(float),q.adverse.to_numpy(float))[0]}
 failures=[]; distinct=int(f.feature.nunique()); iqr=float(f.feature.quantile(.75)-f.feature.quantile(.25)); outer=len(f)//3
 if len(f)<180: failures.append('opportunities<180')
 if distinct<100 or iqr<=0 or outer<50: failures.append('feature_support')
 for endpoint in ('net','adverse'):
  if not all(point[endpoint][k]<0 for k in ('rho','slope','tercile')): failures.append(f'{endpoint}_sign')
 if not all(boot[k][1]<0 for k in boot): failures.append('dependence_upper_bound')
 if sum(z['net_slope']<0 for z in folds)<3: failures.append('net_fold_breadth')
 if sum(z['adverse_slope']<0 for z in folds)<3: failures.append('adverse_fold_breadth')
 if concentration is None or concentration>.60: failures.append('net_fold_concentration')
 if not all(z['net_tercile']<0 and z['adverse_tercile']<0 for z in strata.values()): failures.append('margin_strata')
 for endpoint in ('net','adverse'):
  if not all(delay[endpoint][k]<0 for k in ('rho','slope','tercile')): failures.append('delay_transport'); break
 scale=np.log(np.mean((exo.quote_volume.to_numpy(float)*7.25)[TRAIN_START-192:TRAIN_START-24])/np.mean((exo.quote_volume.to_numpy(float)*7.25)[TRAIN_START-912:TRAIN_START-192])); scale0=np.log(np.mean(exo.quote_volume.to_numpy(float)[TRAIN_START-192:TRAIN_START-24])/np.mean(exo.quote_volume.to_numpy(float)[TRAIN_START-912:TRAIN_START-192]))
 structural=bool(abs(scale-scale0)<1e-12)
 if not structural: failures.append('structural_invariance')
 return {'opportunities':len(f),'feature_distinct':distinct,'feature_iqr':iqr,'outer_tercile_count':outer,'point':point,'bootstrap_95pct':boot,'folds':folds,'negative_net_folds':sum(z['net_slope']<0 for z in folds),'negative_adverse_folds':sum(z['adverse_slope']<0 for z in folds),'negative_net_fold_concentration':concentration,'margin_strata':strata,'delay':delay,'structural_passed':structural,'failure_reasons':sorted(set(failures)),'pass':not failures,'_frame':f}
def strategy_nulls(): return {k:None for k in ('train_return','train_sharpe','oos_return','oos_sharpe','full_return','full_sharpe','benchmark_comparison','turnover','modeled_fee_drag','max_drawdown','edge_per_turnover','fold_year_strategy_breadth','strategy_uncertainty')}
def emit(p):
 OUT.mkdir(parents=True,exist_ok=True); e=OUT/'evidence.json'; r=OUT/'report.md'; m=OUT/'manifest.json'; e.write_text(json.dumps(p,indent=2,sort_keys=True)+'\n'); lines=['# Stablecoin conversion-activity 1H',f"\n- family: `{FAMILY}`",f"- head: `{p['code_head']}`",f"- source pass: `{p['source_contract_passed']}`",f"- candidate/grid: `0/0`",f"- OOS accessed: `{p['sealed_oos_accessed']}`",f"- verdict: `{p['verdict']}`",'','## Training information']
 for s,z in p.get('targets',{}).items(): lines += ['',f'### {s}',f"- opportunities: `{z['opportunities']}`",f"- net rho/slope/tercile: `{z['point']['net']['rho']:+.6f}` / `{z['point']['net']['slope']:+.6f}` / `{z['point']['net']['tercile']*10000:+.2f} bp`",f"- adverse rho/slope/tercile: `{z['point']['adverse']['rho']:+.6f}` / `{z['point']['adverse']['slope']:+.6f}` / `{z['point']['adverse']['tercile']*10000:+.2f} bp`",f"- negative folds net/adverse: `{z['negative_net_folds']}/4` / `{z['negative_adverse_folds']}/4`",f"- failures: `{json.dumps(z['failure_reasons'])}`"]
 r.write_text('\n'.join(lines)+'\n'); eb=e.read_bytes(); rb=r.read_bytes(); m.write_text(json.dumps({'family_id':FAMILY,'code_head':p['code_head'],'evidence_sha256':sha(eb),'report_sha256':sha(rb)},indent=2,sort_keys=True)+'\n')
def main():
 OUT.mkdir(parents=True,exist_ok=True); sd=OUT/'source'; sd.mkdir(exist_ok=True); p={'family_id':FAMILY,'code_head':os.environ.get('RESEARCH_HEAD_SHA','unknown'),'bar':'1H','candidate_count':0,'parameter_grid_count':0,'fee_bps_one_way':5.0,'round_trip_label_bps':10.0,'fixed_targets':list(TARGETS),'fixed_exogenous':EXOG,'source_period':{'start':'2023-04-01T00:00:00Z','end':'2025-12-31T23:00:00Z','rows':24144},'training_range':[TRAIN_START,TRAIN_END],'sealed_oos_range':[OOS_START,OOS_END],'unread_suffix_range':[OOS_END,SOURCE_END],'bootstrap_draws':DRAWS,'bootstrap_block_opportunities':BLOCK,'source_contract_passed':False,'source_error':None,'sources':{},'target_returns_accessed':False,'target_oos_accessed':False,'sealed_oos_accessed':False,'unread_suffix_used_in_feature_or_label':False,'strategy_performance_accessed':False,'strategy_metrics':strategy_nulls(),'targets':{},'bilateral_training_pass':False,'canonical_mutation':False,'paper_trading_authorized':False,'live_trading_authorized':False,'verdict':SOURCE_REJECT}
 try:
  frames={}; metas={}
  for s in (*TARGETS,EXOG): frames[s],metas[s]=acquire(s,sd)
  if any(not frames[s].index.equals(frames[TARGETS[0]].index) for s in (*TARGETS,EXOG)): raise ValueError('common calendar mismatch')
  for s in (*TARGETS,EXOG):
   rf,rm=acquire(s,None); ok=rm['normalized_sha256']==metas[s]['normalized_sha256'] and rm['training_prefix_sha256']==metas[s]['training_prefix_sha256'] and rf.index.equals(frames[s].index); metas[s]['repeat_identity_passed']=ok
   if not ok: raise ValueError(f'{s}: repeat identity failed')
  p['sources']=metas; p['source_contract_passed']=True
 except Exception as e:
  p['source_error']=f'{type(e).__name__}: {e}'; emit(p); print('TERMINAL_EVIDENCE_JSON='+json.dumps({'verdict':p['verdict'],'source_error':p['source_error']},sort_keys=True)); return
 p['target_returns_accessed']=True; results={}
 for s in TARGETS:
  z=eval_target(s,frames[s].iloc[:TRAIN_END],frames[EXOG].iloc[:TRAIN_END]); prefix=z.pop('_frame'); z2=eval_target(s,frames[s],frames[EXOG]); fullprefix=z2.pop('_frame'); z['opportunity_prefix_invariance_passed']=prefix.equals(fullprefix); z['source_prefix_invariance_passed']=metas[s]['training_prefix_sha256']==sha(canon(frames[s].iloc[:TRAIN_END])) and metas[EXOG]['training_prefix_sha256']==sha(canon(frames[EXOG].iloc[:TRAIN_END]))
  if not z['opportunity_prefix_invariance_passed']: z['failure_reasons']=sorted(set(z['failure_reasons']+['opportunity_prefix_invariance'])); z['pass']=False
  if not z['source_prefix_invariance_passed']: z['failure_reasons']=sorted(set(z['failure_reasons']+['source_prefix_invariance'])); z['pass']=False
  results[s]=z
 p['targets']=results; p['bilateral_training_pass']=all(results[s]['pass'] for s in TARGETS); p['verdict']=SUPPORT if p['bilateral_training_pass'] else REJECT; emit(p)
 compact={'family_id':FAMILY,'source_contract_passed':True,'candidate_count':0,'parameter_grid_count':0,'targets':{s:{k:results[s][k] for k in ('opportunities','point','bootstrap_95pct','negative_net_folds','negative_adverse_folds','negative_net_fold_concentration','margin_strata','delay','failure_reasons','pass')} for s in TARGETS},'bilateral_training_pass':p['bilateral_training_pass'],'verdict':p['verdict']}; print('TERMINAL_EVIDENCE_JSON='+json.dumps(compact,sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
