from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION = 365
MOMENTUM_LOOKBACK = 90
REVERSAL_LOOKBACK = 5
TREND_WEIGHT = 0.70
VOLATILITY_LOOKBACK = 30
TARGET_VOLATILITY = 0.50
MAX_POSITION = 1.0
MIN_POSITION = 0.0
TRANSACTION_COST_BPS = 10.0
EXPECTED_OBSERVATIONS = 2340
BLOCK_LENGTH = 20
RESAMPLES = 2000
CONFIDENCE = 0.95
EVALUATION_START = pd.Timestamp('2020-01-11T00:00:00Z')
EVALUATION_END = pd.Timestamp('2026-06-07T00:00:00Z')
SOURCE_WORKFLOW_RUN_ID = 29922259536
SOURCE_ARTIFACT_ID = 8530429665
SOURCE_ARTIFACT_NAME = 'quant-research-source-1027-attempt-1'
SOURCE_ARTIFACT_SHA256 = 'da7ab1b69654f50d0da42e2898a69780269e797bcc808dfdaf1f4e04ae9b64df'
SOURCE_HEAD_COMMIT = 'd2249852a0236398bd540b0e9960009ada7e6940'
SOURCE_BASE_COMMIT = '1302c649cf87a7eaf04cbd442a33573cd939e2b4'
MARKETS = {
    'BTC-USDT': {
        'seed': 202607225,
        'snapshot_sha256': 'b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb',
        'returns_sha256': '539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73',
        'report_sha256': 'e003da1dbedb57b87f8a596fd480f175c5d316fc7e9059ce8edfbe2c954fa88c',
    },
    'ETH-USDT': {
        'seed': 202607226,
        'snapshot_sha256': '78f3bf81d3983e6c894066a1c298fbf14ae06a5eff9ca7326554b0a8933c0df5',
        'returns_sha256': '027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6',
        'report_sha256': 'bb30925eb8351218db08f28a63d32ab32a702fac7008297e90f8f7c3cf329f05',
    },
}
SIGNATURE = (
    'adaptive-selection-risk-vs-fixed-base-v1|markets=BTC-USDT,ETH-USDT|'
    'source=immutable-OKX-1Dutc-snapshots-and-persisted-net-rolling-oos-returns|'
    'adaptive=repository-730-selection-90-test-27-grid|'
    'fixed-base=momentum90-reversal5-trend0.70-vol30-targetvol0.50-long-cash|'
    'execution=one-bar-delay-10bps-continuous-position|'
    'evaluation=2020-01-11..2026-06-07-2340-bars|'
    'metrics=adaptive-minus-fixed-max-drawdown,calmar|'
    'max-drawdown-delta=adaptive-negative-drawdown-minus-fixed-negative-drawdown|'
    'resampling=paired-noncircular-moving-block-bootstrap-20|resamples=2000|confidence=0.95|'
    'pass=both-metric-lower-bounds-positive-in-both-markets|candidate_count=1'
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def explicit_daily_utc_index(values: pd.Series, *, label: str) -> pd.DatetimeIndex:
    parsed: list[pd.Timestamp] = []
    for value in values:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f'{label} timestamps must contain explicit timezone information')
        parsed.append(timestamp)
    index = pd.DatetimeIndex(pd.to_datetime(parsed, utc=True))
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f'{label} timestamps must be unique and strictly increasing')
    if len(index) > 1 and not bool(((index[1:] - index[:-1]) == pd.Timedelta(days=1)).all()):
        raise ValueError(f'{label} timestamps must have exact daily cadence')
    return index


def target_position(prices: pd.Series) -> pd.Series:
    log_returns = np.log(prices).diff()
    trend_mean = log_returns.rolling(MOMENTUM_LOOKBACK, min_periods=MOMENTUM_LOOKBACK).mean()
    trend_std = log_returns.rolling(MOMENTUM_LOOKBACK, min_periods=MOMENTUM_LOOKBACK).std(ddof=0)
    trend_score = trend_mean / trend_std.replace(0.0, np.nan) * math.sqrt(MOMENTUM_LOOKBACK)
    recent_return = log_returns.rolling(REVERSAL_LOOKBACK, min_periods=REVERSAL_LOOKBACK).sum()
    risk_scale = log_returns.rolling(
        VOLATILITY_LOOKBACK, min_periods=VOLATILITY_LOOKBACK
    ).std(ddof=0)
    reversal_score = -recent_return / (
        risk_scale.replace(0.0, np.nan) * math.sqrt(REVERSAL_LOOKBACK)
    )
    ensemble = (TREND_WEIGHT * trend_score + (1.0 - TREND_WEIGHT) * reversal_score).clip(
        -4.0, 4.0
    )
    directional = pd.Series(np.tanh(ensemble.to_numpy()), index=ensemble.index)
    realized_volatility = risk_scale * math.sqrt(ANNUALIZATION)
    volatility_scalar = (TARGET_VOLATILITY / realized_volatility.replace(0.0, np.nan)).clip(
        lower=0.0, upper=MAX_POSITION
    )
    return (
        (directional * volatility_scalar)
        .clip(MIN_POSITION, MAX_POSITION)
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .rename('target_position')
    )


def build_fixed_base_frame(prices: pd.Series) -> pd.DataFrame:
    target = target_position(prices)
    position = target.shift(1).fillna(0.0).rename('position')
    asset_return = prices.pct_change().fillna(0.0).rename('asset_return')
    turnover = position.diff().abs().fillna(position.abs()).rename('turnover')
    trading_cost = (turnover * TRANSACTION_COST_BPS / 10_000.0).rename('trading_cost')
    strategy_return = (position * asset_return - trading_cost).rename('strategy_return')
    nav = (1.0 + strategy_return).cumprod().rename('nav')
    return pd.concat([position, turnover, trading_cost, strategy_return, nav], axis=1)


def max_drawdown(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    peaks = np.maximum.accumulate(nav)
    return float(np.min(nav / peaks - 1.0))


def cagr(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    growth = float(np.prod(1.0 + values))
    years = len(values) / ANNUALIZATION
    return growth ** (1.0 / years) - 1.0 if growth > 0.0 else -1.0


def calmar(returns: np.ndarray) -> float:
    drawdown = max_drawdown(returns)
    return cagr(returns) / abs(drawdown) if drawdown < 0.0 else 0.0


def moving_block_indices(
    observations: int, *, block_length: int, rng: np.random.Generator
) -> np.ndarray:
    if isinstance(observations, bool) or not isinstance(observations, int) or observations < 2:
        raise ValueError('observations must be an integer of at least two')
    if isinstance(block_length, bool) or not isinstance(block_length, int):
        raise ValueError('block_length must be an integer')
    if not 2 <= block_length <= observations:
        raise ValueError('block_length must be between two and observations')
    block_count = math.ceil(observations / block_length)
    starts = rng.integers(0, observations - block_length + 1, size=block_count)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observations]


def paired_bootstrap_comparison(
    adaptive_returns: np.ndarray,
    fixed_returns: np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, Any]:
    adaptive = np.asarray(adaptive_returns, dtype=float)
    fixed = np.asarray(fixed_returns, dtype=float)
    if adaptive.ndim != 1 or fixed.ndim != 1 or len(adaptive) != len(fixed):
        raise ValueError('paired returns must be one-dimensional with equal length')
    if len(adaptive) < 20 or not np.isfinite(adaptive).all() or not np.isfinite(fixed).all():
        raise ValueError('paired returns must contain at least 20 finite observations')
    if (adaptive <= -1.0).any() or (fixed <= -1.0).any():
        raise ValueError('paired returns must be greater than -100%')
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 100:
        raise ValueError('resamples must be an integer of at least 100')
    if not 0.0 < confidence < 1.0:
        raise ValueError('confidence must be in (0, 1)')
    rng = np.random.default_rng(seed)
    drawdown_deltas = np.empty(resamples, dtype=float)
    calmar_deltas = np.empty(resamples, dtype=float)
    for sample_index in range(resamples):
        indices = moving_block_indices(len(adaptive), block_length=block_length, rng=rng)
        sampled_adaptive = adaptive[indices]
        sampled_fixed = fixed[indices]
        drawdown_deltas[sample_index] = max_drawdown(sampled_adaptive) - max_drawdown(
            sampled_fixed
        )
        calmar_deltas[sample_index] = calmar(sampled_adaptive) - calmar(sampled_fixed)
    alpha = 1.0 - confidence
    drawdown_interval = np.quantile(drawdown_deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    calmar_interval = np.quantile(calmar_deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    point_drawdown_delta = max_drawdown(adaptive) - max_drawdown(fixed)
    point_calmar_delta = calmar(adaptive) - calmar(fixed)
    passes = bool(drawdown_interval[0] > 0.0 and calmar_interval[0] > 0.0)
    return {
        'observations': len(adaptive),
        'adaptive_max_drawdown': max_drawdown(adaptive),
        'fixed_max_drawdown': max_drawdown(fixed),
        'max_drawdown_delta': point_drawdown_delta,
        'max_drawdown_delta_interval': [float(value) for value in drawdown_interval],
        'probability_max_drawdown_delta_positive': float(np.mean(drawdown_deltas > 0.0)),
        'adaptive_cagr': cagr(adaptive),
        'fixed_cagr': cagr(fixed),
        'adaptive_calmar': calmar(adaptive),
        'fixed_calmar': calmar(fixed),
        'calmar_delta': point_calmar_delta,
        'calmar_delta_interval': [float(value) for value in calmar_interval],
        'probability_calmar_delta_positive': float(np.mean(calmar_deltas > 0.0)),
        'passes': passes,
    }


def load_market_inputs(artifact_dir: Path, market: str) -> tuple[pd.Series, pd.DataFrame]:
    evidence = MARKETS[market]
    market_dir = artifact_dir / market
    snapshot_path = market_dir / 'snapshot' / f'okx-{market}-1Dutc.csv'
    report_path = market_dir / 'walk_forward.json'
    returns_path = market_dir / 'walk_forward_returns.csv'
    for path, expected in {
        snapshot_path: evidence['snapshot_sha256'],
        report_path: evidence['report_sha256'],
        returns_path: evidence['returns_sha256'],
    }.items():
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f'{path.name} hash mismatch: expected {expected}, actual {actual}')
    snapshot = pd.read_csv(snapshot_path)
    snapshot_index = explicit_daily_utc_index(snapshot['timestamp'], label='snapshot')
    closes = pd.to_numeric(snapshot['close'], errors='raise').to_numpy(dtype=float)
    confirms = pd.to_numeric(snapshot['confirm'], errors='raise').to_numpy(dtype=float)
    if not np.isfinite(closes).all() or (closes <= 0.0).any() or not np.equal(confirms, 1.0).all():
        raise ValueError('snapshot must contain positive closes and only confirmed rows')
    prices = pd.Series(closes, index=snapshot_index, name='close')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    settings = report.get('settings')
    if not isinstance(settings, dict) or settings.get('candidate_count') != 27:
        raise ValueError('walk-forward candidate count changed')
    base = settings.get('base_config')
    if not isinstance(base, dict):
        raise ValueError('walk-forward base configuration must be a mapping')
    expected_base = {
        'annualization': ANNUALIZATION,
        'momentum_lookback': MOMENTUM_LOOKBACK,
        'reversal_lookback': REVERSAL_LOOKBACK,
        'trend_weight': TREND_WEIGHT,
        'reversal_weight': 1.0 - TREND_WEIGHT,
        'volatility_lookback': VOLATILITY_LOOKBACK,
        'target_volatility': TARGET_VOLATILITY,
        'max_abs_position': MAX_POSITION,
        'min_position': MIN_POSITION,
        'transaction_cost_bps': TRANSACTION_COST_BPS,
    }
    for key, expected in expected_base.items():
        actual = base.get(key)
        if isinstance(expected, float):
            matches = isinstance(actual, (int, float)) and math.isclose(
                float(actual), expected, rel_tol=0.0, abs_tol=1e-12
            )
        else:
            matches = actual == expected
        if not matches:
            raise ValueError(f'walk-forward base configuration {key} changed')
    persisted = pd.read_csv(returns_path)
    persisted.index = explicit_daily_utc_index(persisted['timestamp'], label='return')
    if len(persisted) != EXPECTED_OBSERVATIONS:
        raise ValueError('walk-forward return observation count changed')
    if persisted.index[0] != EVALUATION_START or persisted.index[-1] != EVALUATION_END:
        raise ValueError('walk-forward evaluation boundary changed')
    strategy_returns = pd.to_numeric(persisted['strategy_return'], errors='raise').to_numpy(
        dtype=float
    )
    persisted_nav = pd.to_numeric(persisted['nav'], errors='raise').to_numpy(dtype=float)
    recomputed_nav = np.cumprod(1.0 + strategy_returns)
    if not np.allclose(recomputed_nav, persisted_nav, rtol=0.0, atol=5e-14):
        raise ValueError('persisted adaptive NAV does not match compounded strategy returns')
    return prices, persisted


def build_result(artifact_dir: Path) -> dict[str, Any]:
    market_results: dict[str, Any] = {}
    for market, evidence in MARKETS.items():
        prices, persisted = load_market_inputs(artifact_dir, market)
        fixed = build_fixed_base_frame(prices).loc[EVALUATION_START:EVALUATION_END]
        if len(fixed) != EXPECTED_OBSERVATIONS or not fixed.index.equals(persisted.index):
            raise ValueError(f'{market} fixed base path does not match the evaluation window')
        adaptive_returns = pd.to_numeric(
            persisted['strategy_return'], errors='raise'
        ).to_numpy(dtype=float)
        fixed_returns = fixed['strategy_return'].to_numpy(dtype=float)
        market_results[market] = paired_bootstrap_comparison(
            adaptive_returns,
            fixed_returns,
            block_length=BLOCK_LENGTH,
            resamples=RESAMPLES,
            confidence=CONFIDENCE,
            seed=int(evidence['seed']),
        )
    passes = all(bool(result['passes']) for result in market_results.values())
    return {
        'hypothesis': (
            "The repository's adaptive rolling parameter selection improves both maximum "
            'drawdown and Calmar versus its fixed base configuration in BTC-USDT and ETH-USDT.'
        ),
        'canonical_signature': SIGNATURE,
        'candidate_accounting': {
            'searched': 1,
            'passed': int(passes),
            'rejected': int(not passes),
        },
        'verdict': 'supported' if passes else 'rejected',
        'failure_reason': (
            None
            if passes
            else (
                'At least one market or risk metric has a non-positive 95% paired '
                'moving-block-bootstrap lower bound.'
            )
        ),
        'method': {
            'adaptive_process': (
                'repository rolling 730-bar selection / 90-bar test over 27 candidates'
            ),
            'fixed_base_configuration': {
                'momentum_lookback': MOMENTUM_LOOKBACK,
                'reversal_lookback': REVERSAL_LOOKBACK,
                'trend_weight': TREND_WEIGHT,
                'reversal_weight': 1.0 - TREND_WEIGHT,
                'volatility_lookback': VOLATILITY_LOOKBACK,
                'target_volatility': TARGET_VOLATILITY,
                'min_position': MIN_POSITION,
                'max_abs_position': MAX_POSITION,
            },
            'annualization': ANNUALIZATION,
            'transaction_cost_bps': TRANSACTION_COST_BPS,
            'execution_delay_bars': 1,
            'max_drawdown_delta_definition': (
                'adaptive negative max drawdown minus fixed negative max drawdown; '
                'positive is better'
            ),
            'block_length': BLOCK_LENGTH,
            'resamples': RESAMPLES,
            'confidence': CONFIDENCE,
            'development_markets': True,
        },
        'provenance': {
            'provider': 'OKX',
            'market_type': 'spot',
            'timeframe': '1Dutc',
            'source_workflow_run_id': SOURCE_WORKFLOW_RUN_ID,
            'source_artifact_id': SOURCE_ARTIFACT_ID,
            'source_artifact_name': SOURCE_ARTIFACT_NAME,
            'source_artifact_sha256': SOURCE_ARTIFACT_SHA256,
            'source_head_commit': SOURCE_HEAD_COMMIT,
            'source_base_commit': SOURCE_BASE_COMMIT,
            'oos_observations_per_market': EXPECTED_OBSERVATIONS,
            'oos_start': EVALUATION_START.isoformat(),
            'oos_end': EVALUATION_END.isoformat(),
            'markets': MARKETS,
        },
        'markets': market_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Compare adaptive and fixed-base drawdown and Calmar evidence.'
    )
    parser.add_argument('--artifact-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n',
        encoding='utf-8',
    )
    print(f"verdict={result['verdict']}")
    for market, market_result in result['markets'].items():
        print(f"{market}_max_drawdown_delta={market_result['max_drawdown_delta']:.6f}")
        print(f"{market}_calmar_delta={market_result['calmar_delta']:.6f}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
