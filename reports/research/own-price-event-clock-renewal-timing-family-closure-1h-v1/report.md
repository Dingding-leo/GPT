# Own-price event-clock and renewal-timing family closure

## Verdict

```text
close_causal_own_price_event_clock_renewal_timing_family_1h_v1
```

This completed-evidence audit introduced **zero** candidates, parameters, market data, target returns or OOS observations. It binds four preregistered same-instrument causal 1H architecture groups and applies the nine frozen family gates at exactly the repository's 5-bps one-way standard whenever executable economics existed.

## Closure matrix

| Group | Representation | Economic access | Bilateral result | Highest-value failure |
|---|---|---:|---|---|
| A | Trailing-high renewal drought and irreversible half downgrade | Yes | Rejected | Downgrade outlived the warning and removed profitable post-renewal carry |
| B | Renewal-conditioned 168H half bridge after E2160 exit | Yes | Rejected | BTC harmed; ETH benefit concentrated in two events with non-strict lower bounds |
| C | Log age of uninterrupted positive E2160 state | Training diagnostic only | Rejected | Adequate support but weak, non-transportable rank information |
| D | Volatility-normalized first-passage sign consensus | Blocked before returns | Rejected | Disagreements concentrated by quarter/direction; OOS remained sealed |

## Executable economics

| Group / market | Candidate OOS net | Sharpe | Benchmark OOS net | Sharpe | Turnover | Edge/turnover | Fold breadth | Dependence lower bound |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A BTC | +57.16% | 0.832 | +119.68% | 0.954 | 45 | 114.97 bp | 5/12 | Mean -33.18%; Sharpe -0.424 |
| A ETH | +32.52% | 0.495 | +74.52% | 0.646 | 30 | 127.39 bp | 6/12 | Mean -40.56%; Sharpe -0.492 |
| B BTC | +111.75% | 0.912 | +119.68% | 0.954 | 42 | 219.97 bp | 5/12 | Mean -5.32%; Sharpe -0.168 |
| B ETH | +78.91% | 0.664 | +74.52% | 0.646 | 28 | 312.75 bp | 6/12 | Mean 0.00%; Sharpe 0.000 |

Group B's ETH point estimate is not family support: it did not replicate in BTC, occurred in only two bridge events and both strict lower-bound gates failed.

## Information and transport

Group C had 246 BTC and 272 ETH active anchors, broad state IQRs and 5,000/5,000 valid dependence draws, but every correlation lower bound crossed zero and fold/year breadth failed. Group D had active, balanced event states, yet ADA's largest disagreement quarter was 47.89%, while DOT had a missing disagreement quarter, 80.77% one-direction concentration and 60.26% concentration in one quarter.

## Frozen gate result

All nine architecture-level gates pass. Every leave-one-group-out audit retains at least one information-support failure and at least one economic or transport failure. No completed group achieved bilateral promotion or bilateral strictly positive dependence-aware lower bounds.

## Disposition

- Correction permitted: `false`
- Canonical policy changed: `false`
- Observation epoch restarted: `false`
- Paper trading authorised: `false`
- Live trading authorised: `false`

The direct renewal/event-clock rescue surface is closed. Continue the immutable BTC/ETH E2160 prospective shadow; any future architecture must add materially orthogonal causal information and be frozen before target-return access.
