# ruff: noqa
# fmt: off
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
FEE = 0.0005
ANNUALIZATION = 8760.0
TREND_HOURS = 2160
RECENT_HOURS = 168
VOL_HOURS = 720
PREFIX_BARS = 43441
FOLD_HOURS = 2160
TRAIN = (2880, 17520)
OOS = (17520, 43440)
FULL = (2880, 43440)
MARKETS = ('BTC-USDT', 'ETH-USDT')
HASHES = {'BTC-USDT': '92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9', 'ETH-USDT': '2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726'}
ARTIFACTS = {'BTC-USDT': 8704977298, 'ETH-USDT': 8704978112}
FEATURES = ('margin', 'recent_return', 'volume_slope')

def load(path: Path, market: str) -> pd.DataFrame:
    observed_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed_hash != HASHES[market]:
        raise ValueError(f'{market} hash mismatch: {observed_hash}')
    data = pd.read_csv(path, nrows=PREFIX_BARS)
    timestamps = pd.DatetimeIndex(pd.to_datetime(data['timestamp'], utc=True))
    numeric = data[['open', 'high', 'low', 'close', 'volume_quote']].to_numpy(float)
    expected = pd.date_range(timestamps[0], periods=len(timestamps), freq='1h', tz='UTC')
    valid = len(data) == PREFIX_BARS and timestamps.equals(expected) and timestamps.is_unique and (data['confirm'] == 1).all() and np.isfinite(numeric).all() and (numeric[:, :4] > 0).all() and (numeric[:, 4] >= 0).all() and (data['high'] >= data['low']).all()
    if not valid:
        raise ValueError(f'{market} source validation failed')
    data.index = timestamps
    return data

def mad(values: np.ndarray) -> float:
    med = float(np.median(values))
    return float(np.median(np.abs(values - med)))

def onset_feature(data: pd.DataFrame, t: int) -> np.ndarray:
    log_close = np.log(data['close'].to_numpy(float))
    log_volume = np.log1p(data['volume_quote'].to_numpy(float))
    hourly_returns = np.diff(log_close[t - VOL_HOURS:t + 1])
    sigma = max(1.4826 * mad(hourly_returns), 1e-12)
    margin = float((log_close[t] - log_close[t - TREND_HOURS]) / (sigma * math.sqrt(TREND_HOURS)))
    recent = float((log_close[t] - log_close[t - RECENT_HOURS]) / (sigma * math.sqrt(RECENT_HOURS)))
    blocks = np.median(log_volume[t - RECENT_HOURS + 1:t + 1].reshape(7, 24), axis=1)
    x = np.arange(7, dtype=float)
    x -= x.mean()
    raw_slope = float(x @ (blocks - blocks.mean()) / (x @ x))
    volume_slope = raw_slope / max(1.4826 * mad(blocks), 1e-12)
    feature = np.array([margin, recent, volume_slope], dtype=float)
    if not np.isfinite(feature).all():
        raise ValueError('non-finite onset feature')
    return feature

def build_daily_records(data: pd.DataFrame) -> list[dict[str, Any]]:
    close = data['close'].to_numpy(float)
    daily = [t for t in range(TREND_HOURS, len(data) - 1) if data.index[t].hour == 0]
    base = {t: bool(close[t] > close[t - TREND_HOURS]) for t in daily}
    records: list[dict[str, Any]] = []
    previous: bool | None = None
    for t in daily:
        state = base[t]
        if previous is not None and state and (not previous):
            future = [base.get(t + 24 * k) for k in range(1, 8)]
            label = None if any((x is None for x in future)) else bool(all(future))
            records.append({'t': t, 'feature': onset_feature(data, t), 'label': label})
        previous = state
    return records

def robust_calibration(records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    centers: dict[str, list[float]] = {}
    scales: dict[str, list[float]] = {}
    training_records: dict[str, list[dict[str, Any]]] = {}
    pooled: list[dict[str, Any]] = []
    for market in MARKETS:
        usable = [record for record in records[market] if TRAIN[0] <= int(record['t']) and int(record['t']) + RECENT_HOURS < TRAIN[1]]
        if not usable:
            raise ValueError(f'{market} has no training onset records')
        matrix = np.vstack([record['feature'] for record in usable])
        center = np.median(matrix, axis=0)
        scale = np.maximum(1.4826 * np.median(np.abs(matrix - center), axis=0), 1e-12)
        centers[market] = center.tolist()
        scales[market] = scale.tolist()
        training_records[market] = []
        for record in usable:
            z = np.clip((record['feature'] - center) / scale, -3.0, 3.0)
            score = float(z.mean())
            item = {'market': market, 't': int(record['t']), 'label': int(bool(record['label'])), 'score': score, 'z': z.tolist()}
            training_records[market].append(item)
            pooled.append(item)
    favourable = [item for item in pooled if item['score'] >= 0.0]
    support_by_market = {market: sum((item['market'] == market for item in favourable)) for market in MARKETS}
    successes_by_market = {market: sum((item['label'] for item in favourable if item['market'] == market)) for market in MARKETS}
    failures_by_market = {market: support_by_market[market] - successes_by_market[market] for market in MARKETS}
    successes = sum((item['label'] for item in favourable))
    all_successes = sum((item['label'] for item in pooled))
    q10 = beta_integer_quantile(0.1, 1 + successes, 1 + len(favourable) - successes)
    unconditional_mean = (1 + all_successes) / (2 + len(pooled))
    active = len(favourable) >= 8 and all((support_by_market[market] >= 3 for market in MARKETS)) and (q10 > max(0.5, unconditional_mean))
    return {'centers': centers, 'scales': scales, 'training_records': training_records, 'pooled_training_records': len(pooled), 'pooled_training_successes': all_successes, 'unconditional_posterior_mean': unconditional_mean, 'favourable_support': len(favourable), 'favourable_support_by_market': support_by_market, 'favourable_successes_by_market': successes_by_market, 'favourable_failures_by_market': failures_by_market, 'favourable_successes': successes, 'favourable_failures': len(favourable) - successes, 'favourable_posterior_q10': q10, 'required_lower_bound': max(0.5, unconditional_mean), 'selector_active': bool(active)}

def beta_integer_cdf(x: float, a: int, b: int) -> float:
    n = a + b - 1
    return float(sum((math.comb(n, k) * x ** k * (1.0 - x) ** (n - k) for k in range(a, n + 1))))

def beta_integer_quantile(probability: float, a: int, b: int) -> float:
    low, high = (0.0, 1.0)
    for _ in range(80):
        mid = (low + high) / 2.0
        if beta_integer_cdf(mid, a, b) < probability:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0

def standardised_score(feature: np.ndarray, market: str, calibration: dict[str, Any]) -> float:
    center = np.asarray(calibration['centers'][market], dtype=float)
    scale = np.asarray(calibration['scales'][market], dtype=float)
    return float(np.clip((feature - center) / scale, -3.0, 3.0).mean())

def positions(data: pd.DataFrame, records: list[dict[str, Any]], market: str, calibration: dict[str, Any]) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    close = data['close'].to_numpy(float)
    n = len(data)
    output = {name: np.zeros(n - 1) for name in ('candidate', 'b0', 'b1')}
    onset_by_t = {int(record['t']): record for record in records}
    candidate = 0.0
    b0 = 0.0
    b1 = 0.0
    previous_daily: bool | None = None
    events: list[dict[str, Any]] = []
    for t in range(TREND_HOURS, n - 1):
        b0 = float(close[t] > close[t - TREND_HOURS])
        if data.index[t].hour == 0:
            base = bool(b0)
            is_onset = previous_daily is not None and base and (not previous_daily)
            if not base:
                candidate = 0.0
            elif is_onset:
                record = onset_by_t[t]
                score = standardised_score(record['feature'], market, calibration)
                favourable = score >= 0.0
                entered = bool(calibration['selector_active'] and favourable)
                candidate = float(entered)
                events.append({'t': t, 'score': score, 'favourable': favourable, 'entered': entered, 'strict_survival_168h': record['label'], 'label_horizon_end': t + RECENT_HOURS})
            b1 = float(base)
            previous_daily = base
        j = t + 1
        if j < n - 1:
            output['candidate'][j] = candidate
            output['b0'][j] = b0
            output['b1'][j] = b1
    for name in ('candidate', 'b1'):
        changes = np.flatnonzero(np.r_[output[name][0] != 0, np.diff(output[name]) != 0])
        if any((index <= 0 or data.index[int(index) - 1].hour != 0 for index in changes)):
            raise ValueError(f'{name} timing validation failed')
    return (output, events)

def return_pack(data: pd.DataFrame, position: np.ndarray) -> dict[str, np.ndarray]:
    opens = data['open'].to_numpy(float)
    market = opens[1:] / opens[:-1] - 1.0
    turnover = np.r_[abs(position[0]), abs(np.diff(position))]
    gross = position * market
    fees = FEE * turnover
    net = gross - fees
    if not np.array_equal(net, position * market - 0.0005 * turnover):
        raise ValueError('fee identity failed')
    return {'market': market, 'gross': gross, 'turn': turnover, 'fees': fees, 'net': net}

def sharpe(values: np.ndarray) -> float | None:
    std = float(np.std(values, ddof=1))
    if std <= 0.0:
        return None
    return float(math.sqrt(ANNUALIZATION) * np.mean(values) / std)

def metrics(arrays: dict[str, np.ndarray], position: np.ndarray, span: tuple[int, int]) -> dict[str, float | int | None]:
    start, end = span
    net = arrays['net'][start:end]
    exposure = position[start:end]
    wealth = np.cumprod(1.0 + net)
    path = np.r_[1.0, wealth]
    turnover = float(arrays['turn'][start:end].sum())
    previous = np.r_[position[start - 1] if start else 0.0, exposure[:-1]]
    return {'net_return': float(wealth[-1] - 1.0), 'sharpe': sharpe(net), 'max_drawdown': float(np.min(path / np.maximum.accumulate(path) - 1.0)), 'turnover': turnover, 'fees': float(arrays['fees'][start:end].sum()), 'edge_per_turnover_bps': float(net.sum() / turnover * 10000.0) if turnover else None, 'exposure': float(exposure.mean()), 'long_entries': int(((exposure == 1.0) & (previous == 0.0)).sum())}

def breadth(net: np.ndarray, timestamps: pd.DatetimeIndex) -> dict[str, Any]:
    fold_returns = [float(np.prod(1.0 + net[OOS[0] + k * FOLD_HOURS:OOS[0] + (k + 1) * FOLD_HOURS]) - 1.0) for k in range(12)]
    positives = [value for value in fold_returns if value > 0.0]
    years = timestamps[:-1].year
    year_returns: dict[str, float] = {}
    for year in sorted(set(years[OOS[0]:OOS[1]])):
        mask = years[OOS[0]:OOS[1]] == year
        year_returns[str(year)] = float(np.prod(1.0 + net[OOS[0]:OOS[1]][mask]) - 1.0)
    return {'fold_returns': fold_returns, 'profitable_folds': int(sum((value > 0.0 for value in fold_returns))), 'year_returns': year_returns, 'profitable_years': int(sum((value > 0.0 for value in year_returns.values()))), 'positive_fold_concentration': max(positives) / sum(positives) if positives else None}

def bootstrap(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, Any]:
    candidate = candidate[OOS[0]:OOS[1]]
    benchmark = benchmark[OOS[0]:OOS[1]]
    n = len(candidate)
    rng = np.random.default_rng(20260730)
    mean_delta = np.empty(5000)
    sharpe_delta = np.empty(5000)
    no_effect = np.empty(5000, dtype=bool)
    offsets = np.arange(168)
    blocks = math.ceil(n / 168)
    for begin in range(0, 5000, 100):
        stop = min(5000, begin + 100)
        starts = rng.integers(0, n - 167, size=(stop - begin, blocks))
        indices = (starts[:, :, None] + offsets).reshape(stop - begin, -1)[:, :n]
        candidate_samples = candidate[indices]
        benchmark_samples = benchmark[indices]
        candidate_mean = candidate_samples.mean(axis=1)
        benchmark_mean = benchmark_samples.mean(axis=1)
        candidate_std = candidate_samples.std(axis=1, ddof=1)
        benchmark_std = benchmark_samples.std(axis=1, ddof=1)
        mean_delta[begin:stop] = ANNUALIZATION * (candidate_mean - benchmark_mean)
        sharpe_delta[begin:stop] = np.divide(math.sqrt(ANNUALIZATION) * candidate_mean, candidate_std, out=np.zeros(stop - begin), where=candidate_std > 0) - np.divide(math.sqrt(ANNUALIZATION) * benchmark_mean, benchmark_std, out=np.zeros(stop - begin), where=benchmark_std > 0)
        no_effect[begin:stop] = np.all(candidate_samples == benchmark_samples, axis=1)
    candidate_sharpe = sharpe(candidate) or 0.0
    benchmark_sharpe = sharpe(benchmark) or 0.0
    return {'annualized_mean_delta': {'point': float(ANNUALIZATION * np.mean(candidate - benchmark)), 'lower_95': float(np.quantile(mean_delta, 0.025)), 'upper_95': float(np.quantile(mean_delta, 0.975))}, 'sharpe_delta': {'point': float(candidate_sharpe - benchmark_sharpe), 'lower_95': float(np.quantile(sharpe_delta, 0.025)), 'upper_95': float(np.quantile(sharpe_delta, 0.975))}, 'no_selector_effect_resample_rate': float(no_effect.mean()), 'block_hours': 168, 'resamples': 5000, 'seed': 20260730}

def event_diagnostics(events: list[dict[str, Any]], span: tuple[int, int]) -> dict[str, Any]:
    selected = [event for event in events if span[0] <= int(event['t']) < span[1]]
    labelled = [event for event in selected if event['strict_survival_168h'] is not None and int(event['label_horizon_end']) < span[1]]
    favourable = [event for event in labelled if event['favourable']]
    unfavourable = [event for event in labelled if not event['favourable']]
    def rate(items: list[dict[str, Any]]) -> float | None:
        if not items:
            return None
        return float(np.mean([bool(item['strict_survival_168h']) for item in items]))
    return {'onsets': len(selected), 'labelled_onsets': len(labelled), 'excluded_boundary_onsets': len(selected) - len(labelled), 'favourable_onsets': len(favourable), 'unfavourable_onsets': len(unfavourable), 'entered_onsets': int(sum((bool(event['entered']) for event in selected))), 'overall_strict_survival_rate': rate(labelled), 'favourable_strict_survival_rate': rate(favourable), 'unfavourable_strict_survival_rate': rate(unfavourable), 'median_score': float(np.median([event['score'] for event in selected])) if selected else None, 'favourable_rate': float(np.mean([event['favourable'] for event in selected])) if selected else None}

def selector_difference(positions_by_name: dict[str, np.ndarray], arrays: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    start, end = OOS
    candidate_position = positions_by_name['candidate'][start:end]
    b1_position = positions_by_name['b1'][start:end]
    market = arrays['candidate']['market'][start:end]
    candidate_only = (candidate_position == 1.0) & (b1_position == 0.0)
    b1_only = (candidate_position == 0.0) & (b1_position == 1.0)
    fee_delta = float(arrays['candidate']['fees'][start:end].sum() - arrays['b1']['fees'][start:end].sum())
    reconstructed = float(market[candidate_only].sum() - market[b1_only].sum() - fee_delta)
    observed = float(arrays['candidate']['net'][start:end].sum() - arrays['b1']['net'][start:end].sum())
    if not math.isclose(reconstructed, observed, abs_tol=1e-12):
        raise ValueError('selector decomposition failed')
    candidate_net = arrays['candidate']['net'][start:end]
    b1_net = arrays['b1']['net'][start:end]
    effect_folds = 0
    improved_folds = 0
    for k in range(12):
        left, right = (k * FOLD_HOURS, (k + 1) * FOLD_HOURS)
        effect_folds += not np.array_equal(candidate_net[left:right], b1_net[left:right])
        improved_folds += float(candidate_net[left:right].sum() - b1_net[left:right].sum()) > 0.0
    return {'candidate_only_hours': int(candidate_only.sum()), 'candidate_only_market_arithmetic_return': float(market[candidate_only].sum()), 'b1_only_hours': int(b1_only.sum()), 'b1_only_market_arithmetic_return': float(market[b1_only].sum()), 'incremental_fee_cost_vs_b1': fee_delta, 'observed_candidate_minus_b1_arithmetic_net': observed, 'reconstructed_candidate_minus_b1_arithmetic_net': reconstructed, 'decomposition_identity_passes': True, 'selector_effect_folds': int(effect_folds), 'improved_arithmetic_net_folds_vs_b1': int(improved_folds)}

def acceptance(result: dict[str, Any]) -> dict[str, bool]:
    candidate = result['metrics']['development_oos']['candidate']
    benchmark = result['metrics']['development_oos']['b1']
    full = result['metrics']['full_scored']['candidate']
    spread_sharpe = result['residual_sharpe']['vs_b1']
    breadth_result = result['breadth']
    uncertainty = result['uncertainty']
    concentration = breadth_result['positive_fold_concentration']
    return {'positive_oos_net': candidate['net_return'] > 0.0, 'positive_oos_sharpe': candidate['sharpe'] is not None and candidate['sharpe'] > 0.0, 'net_at_least_b1': candidate['net_return'] >= benchmark['net_return'], 'sharpe_at_least_b1': candidate['sharpe'] is not None and benchmark['sharpe'] is not None and (candidate['sharpe'] >= benchmark['sharpe']), 'drawdown_no_worse_b1': candidate['max_drawdown'] >= benchmark['max_drawdown'], 'turnover_no_greater_b1': candidate['turnover'] <= benchmark['turnover'], 'edge_per_turnover_at_least_b1': candidate['edge_per_turnover_bps'] is not None and benchmark['edge_per_turnover_bps'] is not None and (candidate['edge_per_turnover_bps'] >= benchmark['edge_per_turnover_bps']), 'profitable_folds_at_least_7': breadth_result['profitable_folds'] >= 7, 'profitable_years_at_least_3': breadth_result['profitable_years'] >= 3, 'positive_residual_sharpe_b1': spread_sharpe is not None and spread_sharpe > 0.0, 'mean_delta_lower_95_positive': uncertainty['annualized_mean_delta']['lower_95'] > 0.0, 'sharpe_delta_lower_95_positive': uncertainty['sharpe_delta']['lower_95'] > 0.0, 'positive_fold_concentration_at_most_half': concentration is not None and concentration <= 0.5, 'positive_full_scored_net': full['net_return'] > 0.0}

def run_market(data: pd.DataFrame, records: list[dict[str, Any]], market: str, calibration: dict[str, Any]) -> dict[str, Any]:
    positions_by_name, events = positions(data, records, market, calibration)
    arrays = {name: return_pack(data, position) for name, position in positions_by_name.items()}
    all_metrics = {label: {name: metrics(arrays[name], positions_by_name[name], span) for name in arrays} for label, span in {'training': TRAIN, 'development_oos': OOS, 'full_scored': FULL}.items()}
    candidate_oos = arrays['candidate']['net'][OOS[0]:OOS[1]]
    b0_oos = arrays['b0']['net'][OOS[0]:OOS[1]]
    b1_oos = arrays['b1']['net'][OOS[0]:OOS[1]]
    result: dict[str, Any] = {'source': {'artifact_id': ARTIFACTS[market], 'csv_sha256': HASHES[market], 'observations_in_source': 43941, 'parsed_prefix_bars': PREFIX_BARS}, 'metrics': all_metrics, 'breadth': breadth(arrays['candidate']['net'], data.index), 'residual_sharpe': {'vs_b0': sharpe(candidate_oos - b0_oos), 'vs_b1': sharpe(candidate_oos - b1_oos)}, 'uncertainty': bootstrap(arrays['candidate']['net'], arrays['b1']['net']), 'event_diagnostics': {'training': event_diagnostics(events, TRAIN), 'development_oos': event_diagnostics(events, OOS)}, 'selector_discrepancy_vs_b1': selector_difference(positions_by_name, arrays)}
    result['acceptance_checks'] = acceptance(result)
    result['market_accepts'] = bool(all(result['acceptance_checks'].values()))
    return result

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--btc-csv', type=Path, required=True)
    parser.add_argument('--eth-csv', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = {'BTC-USDT': args.btc_csv, 'ETH-USDT': args.eth_csv}
    data = {market: load(paths[market], market) for market in MARKETS}
    records = {market: build_daily_records(data[market]) for market in MARKETS}
    calibration = robust_calibration(records)
    markets = {market: run_market(data[market], records[market], market, calibration) for market in MARKETS}
    accepted = all((result['market_accepts'] for result in markets.values()))
    result = {'family_id': 'pooled-bayesian-trend-survival-onset-1h-v1', 'issue': 648, 'candidate_count': 1, 'parameter_grid_count': 0, 'bar': '1H', 'canonical_fee_one_way': FEE, 'research_parent': '5a0fcc97d1a882f8223656c51f5bb8055f534e38', 'sample': {'warmup': [0, 2880], 'training': list(TRAIN), 'development_oos': list(OOS), 'full_scored': list(FULL), 'parsed_prefix_bars': PREFIX_BARS, 'later_suffix_unread': True}, 'calibration': calibration, 'markets': markets, 'verdict': 'nominate_pooled_bayesian_trend_survival_onset_for_g1' if accepted else 'reject_exact_pooled_bayesian_trend_survival_onset_family', 'paper_or_live_authorized': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
if __name__ == '__main__':
    main()
