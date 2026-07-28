from __future__ import annotations
import argparse, json, math, hashlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import numpy as np
import pandas as pd

parser=argparse.ArgumentParser(description='Audit the frozen funding/basis feature artifact')
parser.add_argument('--artifact-dir', required=True, type=Path)
parser.add_argument('--artifact-zip', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args=parser.parse_args()
ART=args.artifact_dir
HOUR_MS=3_600_000
FEE=0.0005
YEAR_HOURS=8760.0
WARMUP_EVENTS=30
WARMUP_HOURS=240
FOLD_HOURS=14*24

manifest=json.load(open(ART/'source-manifest.json'))
result=json.load(open(ART/'result-summary.json'))

records=[]
for r in manifest['records']:
    data=json.load(open(ART/r['relative_path']))
    records.append((r,data))

def rows_for(path_sub, inst_id):
    out=[]
    for r,d in records:
        u=urlparse(r['url'])
        q=parse_qs(u.query)
        if path_sub in u.path and q.get('instId',[''])[0]==inst_id:
            out.extend(d.get('data',[]))
    return out

def funding_frame(swap_id):
    rows=rows_for('/public/funding-rate-history',swap_id)
    unique={}
    for row in rows:
        ts=int(row['fundingTime'])
        item={'funding_time_ms':ts,'realized_rate':float(row['realizedRate']),
              'formula_type':str(row.get('formulaType','')),'method':str(row.get('method',''))}
        assert ts not in unique or unique[ts]==item
        unique[ts]=item
    return pd.DataFrame(unique.values()).sort_values('funding_time_ms').reset_index(drop=True)

def candle_frame(path_sub, inst_id, expected_width):
    rows=rows_for(path_sub,inst_id)
    unique={}
    for row in rows:
        assert len(row)==expected_width,(path_sub,inst_id,len(row))
        if str(row[-1])!='1': continue
        ts=int(row[0]); item=(float(row[1]),float(row[4]))
        assert ts not in unique or unique[ts]==item
        unique[ts]=item
    frame=pd.DataFrame([{'open_time_ms':t,'open':v[0],'close':v[1]} for t,v in unique.items()]).sort_values('open_time_ms').reset_index(drop=True)
    dif=np.diff(frame.open_time_ms.to_numpy(np.int64)); assert (dif==HOUR_MS).all()
    return frame

def weighted_median(values,weights,times):
    order=np.lexsort((times,values)); values=values[order]; weights=weights[order]
    idx=int(np.searchsorted(np.cumsum(weights),weights.sum()/2.0,side='left'))
    return float(values[min(idx,len(values)-1)])

def robust_z(history,field,current):
    values=np.array([x[field] for x in history],float)
    weights=np.array([x['interval'] for x in history],float)
    times=np.array([x['time'] for x in history],np.int64)
    med=weighted_median(values,weights,times)
    mad=weighted_median(np.abs(values-med),weights,times)
    if not math.isfinite(mad) or mad<=0:return None
    return float(np.clip((current-med)/mad,-6,6))

def build_events(funding,mark,index):
    mark_by_close={int(r.open_time_ms)+HOUR_MS:float(r.close) for r in mark.itertuples()}
    index_by_close={int(r.open_time_ms)+HOUR_MS:float(r.close) for r in index.itertuples()}
    basis={t:math.log(m/index_by_close[t]) for t,m in mark_by_close.items() if t in index_by_close}
    out=[]; previous_time=None; previous_regime=None; episode=-1; history=[]
    for row in funding.itertuples(index=False):
        t=int(row.funding_time_ms); regime=(str(row.formula_type),str(row.method))
        if regime!=previous_regime:
            episode+=1; history=[]; previous_regime=regime
        interval=None if previous_time is None else (t-previous_time)/HOUR_MS
        previous_time=t; interval_ok=interval in {1.,2.,4.,6.,8.}
        cb=basis.get(t); pb=basis.get(t-24*HOUR_MS)
        recovery=None if cb is None or pb is None else cb-pb
        funding8=None if not interval_ok else float(row.realized_rate)*8/float(interval)
        components_ok=interval_ok and all(regime) and funding8 is not None and cb is not None and recovery is not None
        warm=len(history)>=WARMUP_EVENTS and sum(x['interval'] for x in history)>=WARMUP_HOURS
        zf=zb=zr=None
        if components_ok and warm:
            zf=robust_z(history,'funding',float(funding8)); zb=robust_z(history,'basis',float(cb)); zr=robust_z(history,'recovery',float(recovery))
        usable=components_ok and warm and None not in (zf,zb,zr)
        f0=f1=0.
        if usable and funding8<0: f0=max(0.,math.tanh(-zf))
        if usable and funding8<0 and cb<0 and recovery>0:
            f1=max(0.,math.tanh(min(-zf,-zb,zr)))
        out.append({'funding_time_ms':t,'interval_hours':interval,'episode':episode,
                    'funding_8h_equivalent':funding8,'basis_log_close':cb,'basis_recovery_24h':recovery,
                    'z_funding':zf,'z_basis':zb,'z_recovery':zr,'usable':usable,'target_f0':f0,'target_f1':f1})
        if components_ok:
            history.append({'time':float(t),'interval':float(interval),'funding':float(funding8),'basis':float(cb),'recovery':float(recovery)})
    return pd.DataFrame(out)

def build_hourly(events,spot):
    frame=spot[['open_time_ms','open','close']].copy()
    frame['execution_open_time_ms']=frame['open_time_ms']
    frame['close_time_ms']=frame['open_time_ms']+HOUR_MS
    frame=frame.set_index('close_time_ms')
    event_times=set(events.funding_time_ms.astype(int));actions={}
    for row in events.itertuples(index=False):
        t=int(row.funding_time_ms);actions[t+HOUR_MS]=(float(row.target_f0),float(row.target_f1),'event',t)
        if row.interval_hours in {1.,2.,4.,6.,8.}:
            deadline=t+int(float(row.interval_hours)*HOUR_MS)
            if deadline not in event_times:actions[deadline+HOUR_MS]=(0.,0.,'expiry',t)
    cf0=cf1=0.;tf0=[];tf1=[];reasons=[];source_event=[];current_event=None
    for row in frame.itertuples():
        execution_time=int(row.execution_open_time_ms)
        if execution_time in actions:cf0,cf1,reason,current_event=actions[execution_time]
        else:reason='carry'
        tf0.append(cf0);tf1.append(cf1);reasons.append(reason);source_event.append(current_event)
    frame['target_f0']=tf0;frame['target_f1']=tf1;frame['action_reason']=reasons;frame['source_event_ms']=source_event
    frame['spot_return']=frame['open'].shift(-1)/frame['open']-1.0
    frame['prior_close_to_execution_open_gap']=frame['open']/frame['close'].shift(1)-1.0
    for p in ['f0','f1']:
        frame[f'position_{p}']=frame[f'target_{p}']
        to=frame[f'position_{p}'].diff().abs();to.iloc[0]=abs(float(frame[f'position_{p}'].iloc[0]));frame[f'turnover_{p}']=to
        frame[f'gross_return_{p}']=frame[f'position_{p}']*frame.spot_return
        frame[f'net_return_{p}']=frame[f'gross_return_{p}']-FEE*to
    trend=(frame['close'].shift(1)/frame['close'].shift(2161)-1>0).astype(float);frame['position_trend']=trend
    to=frame.position_trend.diff().abs();to.iloc[0]=abs(float(frame.position_trend.iloc[0]));frame['turnover_trend']=to
    frame['net_return_trend']=frame.position_trend*frame.spot_return-FEE*to
    return frame.reset_index()

def sharpe(x):
    x=np.asarray(x,float);sd=np.std(x,ddof=1)
    return None if len(x)<2 or sd<=0 else float(np.mean(x)/sd*math.sqrt(YEAR_HOURS))

def total(x):return float(np.prod(1+np.asarray(x,float))-1)

def metric(frame,p,fold_ids):
    r=frame[f'net_return_{p}'].to_numpy(float);to=frame[f'turnover_{p}'].to_numpy(float)
    annual_mean=float(r.mean()*YEAR_HOURS); annual_to=float(to.mean()*YEAR_HOURS)
    fr=[total(r[fold_ids==i]) for i in sorted(set(fold_ids))];pos=[x for x in fr if x>0]
    return {'return':total(r),'sharpe':sharpe(r),'turnover':annual_to,'edge':None if annual_to<=0 else annual_mean/annual_to*1e4,
            'fold_returns':fr,'profitable_folds':sum(x>0 for x in fr),'concentration':None if not pos else max(pos)/sum(pos)}

markets={}
first_usable={};last_available={};full={};evs={}
for market,swap,mark_id,index_id,spot_id in [
    ('BTC-USDT','BTC-USDT-SWAP','BTC-USDT-SWAP','BTC-USDT','BTC-USDT'),
    ('ETH-USDT','ETH-USDT-SWAP','ETH-USDT-SWAP','ETH-USDT','ETH-USDT')]:
    funding=funding_frame(swap); mark=candle_frame('/market/history-mark-price-candles',mark_id,6); index=candle_frame('/market/history-index-candles',index_id,6); spot=candle_frame('/market/history-candles',spot_id,9)
    events=build_events(funding,mark,index); hourly=build_hourly(events,spot)
    usable=events[events.usable]; first_usable[market]=int(usable.funding_time_ms.min())+2*HOUR_MS
    last_available[market]=min(int(hourly.close_time_ms.max()),int(funding.funding_time_ms.max())+8*HOUR_MS)
    full[market]=hourly;evs[market]=events
common_start=max(first_usable.values());common_end=min(last_available.values());folds=int(((common_end-common_start)//HOUR_MS+1)//FOLD_HOURS);eval_end=common_start+folds*FOLD_HOURS*HOUR_MS-HOUR_MS

out={'artifact_digest':hashlib.sha256(args.artifact_zip.read_bytes()).hexdigest(),
     'source_result_sha256':hashlib.sha256(open(ART/'result-summary.json','rb').read()).hexdigest(),
     'source_generated_from_commit':result['generated_from_commit'],'sample':{'start_ms':common_start,'end_ms':eval_end,'hours_per_market':folds*FOLD_HOURS,'folds':folds},'markets':{}}
for market,frame0 in full.items():
    frame=frame0[(frame0.close_time_ms>=common_start)&(frame0.close_time_ms<=eval_end)].copy().reset_index(drop=True)
    ids=np.repeat(np.arange(folds),FOLD_HOURS)
    m0=metric(frame,'f0',ids);m1=metric(frame,'f1',ids)
    pub=result['metrics'][market]
    parity={
      'f0_return_abs_error':abs(m0['return']-pub['f0']['net_total_return']),
      'f1_return_abs_error':abs(m1['return']-pub['f1']['net_total_return']),
      'f0_sharpe_abs_error':abs(m0['sharpe']-pub['f0']['sharpe']),
      'f1_sharpe_abs_error':abs(m1['sharpe']-pub['f1']['sharpe']),
      'f0_turnover_abs_error':abs(m0['turnover']-pub['f0']['annualized_turnover']),
      'f1_turnover_abs_error':abs(m1['turnover']-pub['f1']['annualized_turnover']),
    }
    diff_pos=(frame.position_f0-frame.position_f1).to_numpy(float)
    assert np.min(diff_pos)>=-1e-12
    removed=diff_pos>1e-12; retained=frame.position_f1.to_numpy(float)>1e-12
    gross_delta=(frame.gross_return_f1-frame.gross_return_f0).to_numpy(float)
    fee_delta=(-FEE*(frame.turnover_f1-frame.turnover_f0)).to_numpy(float)
    net_delta=(frame.net_return_f1-frame.net_return_f0).to_numpy(float)
    event_rows=[]
    for eid,g in frame.dropna(subset=['source_event_ms']).groupby('source_event_ms',sort=True):
        event_rows.append({'event_ms':int(eid),'hours':int(len(g)),'f0_net':float(g.net_return_f0.sum()),'f1_net':float(g.net_return_f1.sum()),
                           'f0_gross':float(g.gross_return_f0.sum()),'f1_gross':float(g.gross_return_f1.sum()),
                           'f1_minus_f0_net':float((g.net_return_f1-g.net_return_f0).sum()),
                           'f1_active_hours':int((g.position_f1>0).sum()),'f0_active_hours':int((g.position_f0>0).sum())})
    active_f1=[x for x in event_rows if x['f1_active_hours']>0]
    pos_f1=[x['f1_net'] for x in active_f1 if x['f1_net']>0]
    delta_pos=[x['f1_minus_f0_net'] for x in event_rows if x['f1_minus_f0_net']>0]
    evt=evs[market]
    f0ev=evt[evt.target_f0>0];f1ev=evt[evt.target_f1>0]
    out['markets'][market]={
      'published_parity':parity,
      'f0':m0,'f1':m1,
      'corrected_deterministic_screens':{
        'profitable_fold_ratio_at_least_half':m1['profitable_folds']*2>=folds,
        'positive_fold_concentration_at_most_half':m1['concentration'] is not None and m1['concentration']<=0.5,
      },
      'feature_occupancy':{'usable_events':int(evt.usable.sum()),'f0_positive_events':int(len(f0ev)),'f1_positive_events':int(len(f1ev)),
                           'f1_share_of_f0_positive_events':float(len(f1ev)/len(f0ev)) if len(f0ev) else None,
                           'hours_f0_exposure_exceeds_f1':int(removed.sum()),'hours_f1_active':int(retained.sum())},
      'incremental_feature_attribution':{
        'f1_minus_f0_net_total_return_pp':(m1['return']-m0['return'])*100,
        'f1_minus_f0_sharpe':m1['sharpe']-m0['sharpe'],
        'f1_minus_f0_edge_bps':m1['edge']-m0['edge'],
        'annualized_gross_mean_delta_pp':float(gross_delta.mean()*YEAR_HOURS*100),
        'annualized_fee_saving_contribution_pp':float(fee_delta.mean()*YEAR_HOURS*100),
        'annualized_net_mean_delta_pp':float(net_delta.mean()*YEAR_HOURS*100),
        'removed_exposure_unweighted_spot_mean_bps':float(frame.loc[removed,'spot_return'].mean()*1e4) if removed.any() else None,
        'retained_f1_exposure_unweighted_spot_mean_bps':float(frame.loc[retained,'spot_return'].mean()*1e4) if retained.any() else None,
        'folds_f1_beats_f0_compounded':int(sum(a>b for a,b in zip(m1['fold_returns'],m0['fold_returns']))),
        'positive_incremental_event_concentration':None if not delta_pos else max(delta_pos)/sum(delta_pos),
      },
      'event_concentration':{'f1_active_event_windows':len(active_f1),'f1_positive_event_windows':sum(x['f1_net']>0 for x in active_f1),
                             'f1_positive_event_pnl_concentration':None if not pos_f1 else max(pos_f1)/sum(pos_f1),
                             'event_windows':event_rows},
    }

all_screens=[]
for market,d in out['markets'].items():
    pubscr=result['markets'][market]['deterministic_screens']
    all_screens += list(pubscr.values()) + list(d['corrected_deterministic_screens'].values())
stat_pass=result['statistical_pass']
out['methodological_repair']={'defect':'published short-window runner omitted the predeclared profitable-fold and positive-fold-concentration qualification screens from deterministic_failures',
                              'point_metrics_changed':False,'family_verdict_changed':False,
                              'corrected_all_deterministic_screens_pass':all(all_screens),'statistical_pass':stat_pass}
out['verdict']='rejected_by_predeclared_short_window_diagnostic_after_missing_breadth_and_concentration_gates_restored'
out['candidate_count']=2;out['new_candidate_count']=0;out['oos_consumed']=False;out['untouched_evidence_consumed']=False

p=args.output
p.write_text(json.dumps(out,sort_keys=True,separators=(',',':'),allow_nan=False))
print(json.dumps({k:v for k,v in out.items() if k!='markets'},indent=2))
for market,d in out['markets'].items():
 print('\n',market)
 print(json.dumps({k:v for k,v in d.items() if k!='event_concentration'},indent=2))
 print('event conc summary', {k:v for k,v in d['event_concentration'].items() if k!='event_windows'})
print('sha256',hashlib.sha256(p.read_bytes()).hexdigest())
