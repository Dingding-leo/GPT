# ruff: noqa
# fmt: off
import run_slow_trend_drawdown_budget as base

def compact(r):
 fields=('net_return','arithmetic_net_return','sharpe','max_drawdown','turnover','fees','edge_per_turnover_bps','mean_exposure','exposure_change_count','exposed_hours'); slim=lambda z:{k:z[k] for k in fields}; sd=r['selector_diagnostics']
 return {'source':r['source'],'feature_definition':r['feature_definition'],'metrics':{'training':{k:slim(r['metrics']['training'][k]) for k in ('candidate','b1')},'development_oos':{k:slim(r['metrics']['development_oos'][k]) for k in ('candidate','b0','b1')},'full_scored':{k:slim(r['metrics']['full_scored'][k]) for k in ('candidate','b1')}},'breadth':r['breadth'],'residual_sharpe':r['residual_sharpe'],'uncertainty':r['uncertainty'],'selector_diagnostics':{'target_decisions':{k:sd['target_decisions'][k] for k in ('training','development_oos')},'oos_transition_attribution':sd['oos_transition_attribution'],'oos_exposure_buckets':sd['oos_exposure_buckets'],'oos_exposure_decomposition':sd['oos_exposure_decomposition'],'improved_arithmetic_net_folds_vs_b1':sd['improved_arithmetic_net_folds_vs_b1']},'acceptance_checks':r['acceptance_checks'],'market_accepts':r['market_accepts']}

base.compact=compact
if __name__=='__main__': base.main()
