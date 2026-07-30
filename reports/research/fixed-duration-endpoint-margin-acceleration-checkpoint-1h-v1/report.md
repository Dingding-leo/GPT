# Fixed-duration endpoint-margin acceleration checkpoint — terminal report

```text
family          fixed-duration-endpoint-margin-acceleration-checkpoint-1h-v1
candidate count 1
parameter grid  0
checkpoint      exactly 168H
fee             exactly 5 bps one way
verdict         reject_exact_fixed_duration_endpoint_margin_acceleration_checkpoint_family
```

## Frozen strategy

At each completed daily `00:00 UTC` decision, each instrument independently computed:

```text
m_t = log(close_t / close_(t-2160H))
latest_change    = m_t - m_(t-168H)
preceding_change = m_(t-168H) - m_(t-336H)
```

Every newly positive 2,160H endpoint trend entered at full exposure. During an already-positive regime, the first decision with both changes negative and `latest_change < preceding_change` reduced exposure from `1.0` to `0.5` at the next hourly open. The checkpoint lasted exactly 168 realizable open-to-open hours unless a non-positive base decision forced cash earlier. At exact expiry, exposure automatically returned to `1.0` when the base trend remained positive. No second checkpoint was allowed in the same positive regime.

The rule had no fitted threshold, no parameter grid, no exogenous input, and no market-specific treatment.

## Immutable data and evaluation

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT 1H candles, evaluated independently.
- Exact-head successful canonical workflow run `30567744552`; BTC artifact `8769605568`, ETH artifact `8769619607`.
- First 43,441 confirmed contiguous rows only; training `[2,880,17,520)`, development OOS `[17,520,43,440)`, full `[2,880,43,440)`.
- Twelve contiguous 2,160H OOS folds and four calendar years.
- 5,000 paired non-circular 168H moving-block resamples, seed `20260731`.
- Completed-bar decisions, next-open execution, and exactly 5 bps per absolute exposure change.
- Future-suffix invariance and independent hourly/daily benchmark reconstructions passed.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -37.33% | -0.739 | -53.05% | 29.0 | 1.45% | -132.95 bps |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.0 | 1.40% | -159.81 bps |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.0 | 6.90% | -32.09 bps |
| ETH-USDT | Candidate | -36.66% | -0.498 | -56.08% | 25.0 | 1.25% | -130.84 bps |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.0 | 1.15% | -168.77 bps |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.0 | 4.40% | -56.53 bps |

The bounded checkpoint improved training return, Sharpe, and drawdown in both markets. It also added turnover, and every training policy remained negative.

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | **+121.13%** | **0.975** | **-22.68%** | 50.0 | 2.50% | 191.23 bps |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | **45.0** | 2.25% | **212.75 bps** |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.0 | 10.15% | 45.31 bps |
| ETH-USDT | Candidate | +59.93% | 0.583 | **-46.31%** | 34.0 | 1.70% | 220.69 bps |
| ETH-USDT | B1 | **+74.52%** | **0.646** | -47.77% | **30.0** | 1.50% | **283.58 bps** |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.0 | 6.95% | 58.31 bps |

BTC improved compounded return by 1.45 percentage points, Sharpe by `0.021`, and drawdown by 3.87 points. The point estimate did not survive efficiency gates: five completed restorations added 5.0 turnover units and 25 bps of fees, reducing edge per turnover by 21.52 bps.

ETH improved drawdown by 1.46 points but lost 14.59 points of compounded return, reduced Sharpe by `0.063`, added four turnover units, and reduced edge per turnover by 62.89 bps.

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | **+38.58%** | **0.380** | **-53.05%** | 79.0 | 3.95% | **72.23 bps** |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | **73.0** | 3.65% | 69.85 bps |
| ETH-USDT | Candidate | +1.29% | 0.217 | **-56.08%** | 59.0 | 2.95% | 71.74 bps |
| ETH-USDT | B1 | **+3.68%** | **0.233** | -56.95% | **53.0** | 2.65% | **87.28 bps** |

BTC's full-sample sequencing improved aggregate return, Sharpe, drawdown, and edge per turnover, but the preregistered decision was based on bilateral development-OOS gates. ETH remained positive full-sample but underperformed B1 on return, Sharpe, turnover, and efficiency.

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 2/12; 1/4 | 34.86% | -0.010 | [-4.99%, +4.16%] | [-0.126, +0.144] |
| ETH-USDT | 6/12 | 2/4 | 2/12; 1/4 | 23.06% | -0.623 | [-8.32%, +3.45%] | [-0.171, +0.079] |

Neither market reached seven profitable folds. Both residual Sharpes were negative, and every dependence-aware lower confidence bound remained below zero. ETH also failed the three-profitable-year gate.

## Failure mechanism

### BTC-USDT — gross timing signal too small to pay for restoration

```text
OOS checkpoints                         7
Automatic restorations / base exits     5 / 2
Half-state hours                     1,080
Full-equivalent exposure removed       540.0H
Market arithmetic return in state      -0.255%
Timing contribution versus B1          +0.128%
Incremental turnover                    +5.0
Incremental fee contribution           -0.250%
Arithmetic candidate-minus-B1          -0.122%
```

The checkpoint had a weakly favourable gross arithmetic sign in BTC, but it was smaller than the mandatory restoration cost. Mean post-trigger return was `-0.15%` at 24H, `+1.08%` at 168H, and `+8.92%` at 720H. Five of seven 168H outcomes were positive. The compounded return improvement was therefore sequencing-driven rather than a robust positive residual.

The largest useful event was the May 2026 checkpoint, which halved exposure through a `-12.03%` market decline. That single loss-avoidance event offset several checkpoints that reduced positive carry, leaving no fold breadth or uncertainty support.

### ETH-USDT — the fixed window still removed strong continuation

```text
OOS checkpoints                         4
Automatic restorations / base exits     4 / 0
Half-state hours                       672
Full-equivalent exposure removed       336.0H
Market arithmetic return in state     +19.679%
Timing contribution versus B1          -9.839%
Incremental turnover                    +4.0
Incremental fee contribution           -0.200%
Arithmetic candidate-minus-B1         -10.039%
```

Two checkpoints dominated the failure:

- January 2024: the 168H window compounded `+14.63%`;
- June 2025: the 168H window compounded `+12.38%`.

Mean post-trigger returns were positive at 24H (`+1.92%`), 168H (`+4.95%`), and 720H (`+11.14%`). Bounding the state repaired the prior multi-thousand-hour lockout, but did not repair the trigger's cross-market sign.

### Diagnostic repair

The initial evidence decomposed aggregate timing and fee effects but did not prove that every reported checkpoint window exactly reconstructed the aggregate half-state result. The terminal reproducer adds per-event span-overlap returns and timing contributions, then asserts:

- summed event hours equal all half-state hours;
- summed event timing equals the aggregate position-difference timing to `1e-12`;
- automatic restorations last exactly 168 hours;
- no checkpoint exceeds 168 hours;
- candidate-minus-B1 arithmetic return equals timing plus incremental fees to `1e-12`.

The repair changed only diagnostic fields. No source, signal, position, fee, performance metric, bootstrap draw, gate, or verdict changed. Two complete terminal executions produced byte-identical files:

```text
result.json SHA-256  ba7ec6a2e9c004c00aacb8a9908b10113ebdeafba65c59100902356e489f3ead
canonical payload    d8c7b33e4d95aad000befde03eac7893e63f1e4ec13e4699ec017418e00c4dbe
```

## Verdict

```text
reject_exact_fixed_duration_endpoint_margin_acceleration_checkpoint_family
```

BTC passed OOS return, Sharpe, drawdown, profitable-year, concentration, and positive-full-sample gates. It failed turnover, edge per turnover, profitable-fold breadth, residual Sharpe, and both uncertainty gates.

ETH passed drawdown, concentration, and positive-full-sample gates. It failed return, Sharpe, turnover, edge per turnover, fold/year breadth, residual Sharpe, and both uncertainty gates.

No same-interval change to checkpoint duration, trigger, exposure fraction, cadence, fee, or market-specific treatment is authorised. There is no G1 nomination, paper promotion, or live-trading authorisation.

## Remaining blocker and next experiment

The remaining blocker is not state duration alone. Endpoint-margin acceleration has a weak, fee-insufficient short-horizon sign in BTC and the opposite sign in ETH. Any recurrent or automatically restored sizing overlay also incurs an unavoidable extra round trip when it completes.

The next strategy experiment should test one materially distinct own-history-only **trend drawdown recovery-efficiency checkpoint**: enter every positive 2,160H trend at full exposure; permit one 168H half checkpoint only when the latest 168H maximum close-to-close drawdown is larger than the preceding 168H drawdown and the latest close has recovered less than half of that latest block's drawdown from its trough. Use the same fixed candidate count, no grid, no fitted threshold, next-open execution, 5 bps, and bilateral robustness gates. This changes signal information from endpoint-margin derivatives to path-dependent drawdown/recovery structure rather than retuning the rejected trigger.
